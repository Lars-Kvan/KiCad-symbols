#!/usr/bin/env python3
"""Place manually downloaded datasheets in their KiCad library folders.

Default mode is a read-only preview.  ``--apply`` first backs up every
library that will be modified, then copies each matched PDF to the relevant
``Datasheets`` folder, updates the active symbol's Datasheet property, and
removes the original dumped copy only after all copies succeed.

Only high-confidence matches are used automatically:
  * a dumped filename matching a filename embedded in the current URL; or
  * a dumped filename containing the symbol MPN (or vice versa).
Unmatched URLs are reported and deliberately left as URLs.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import parse_qsl, unquote, urlsplit

from download_datasheets import SymbolUrl, collect_urls, escape_kicad_string, local_reference, read_library

try:
    sys.stdout.reconfigure(errors="backslashreplace")
except AttributeError:
    pass


INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def compact(value: str) -> str:
    """A comparison key for MPNs and filenames."""

    value = unquote(value).rsplit("/", 1)[-1].split("?", 1)[0].casefold()
    value = re.sub(r"\.pdfx?$", "", value)
    value = re.sub(r"\s*\(\d+\)$", "", value)
    return re.sub(r"[^a-z0-9]+", "", value)


def text_key(value: str) -> str:
    """Comparison key for PDF text; unlike a filename it may contain '/'."""

    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def url_filenames(url: str) -> set[str]:
    """Return filenames present in a URL, including nested redirect URLs."""

    found: set[str] = set()
    pending = [url]
    seen: set[str] = set()
    while pending:
        value = pending.pop()
        if value in seen:
            continue
        seen.add(value)
        parsed = urlsplit(value)
        if parsed.path:
            found.add(compact(parsed.path))
        for _, parameter in parse_qsl(parsed.query, keep_blank_values=True):
            decoded = unquote(parameter)
            if "/" in decoded or decoded.startswith(("http:", "https:")):
                pending.append(decoded)
            elif decoded:
                found.add(compact(decoded))
    return found - {""}


def is_pdf(path: Path) -> bool:
    try:
        return path.read_bytes()[:5] == b"%PDF-"
    except OSError:
        return False


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_pdf_name(mpn: str) -> str:
    name = INVALID_FILENAME.sub("_", mpn.strip()).strip(". ")
    name = re.sub(r"\s+", " ", name)
    return (name or "datasheet")[:150] + ".pdf"


@dataclass(frozen=True)
class Match:
    record: SymbolUrl
    source: Path
    method: str


def choose_source(record: SymbolUrl, sources: list[Path]) -> tuple[Path | None, str]:
    by_key: dict[str, list[Path]] = defaultdict(list)
    for path in sources:
        by_key[compact(path.name)].append(path)

    candidates: list[Path] = []
    for key in url_filenames(record.url):
        candidates.extend(by_key.get(key, []))
    method = "URL filename"

    if not candidates:
        mpn_key = compact(record.mpn)
        if len(mpn_key) >= 5:
            candidates = [
                path for path in sources
                if mpn_key in compact(path.name) or compact(path.name) in mpn_key
            ]
            method = "MPN filename"

    candidates = sorted(set(candidates), key=lambda path: ("(" in path.stem, len(path.name), path.name.casefold()))
    if not candidates:
        return None, "no matching dumped PDF"
    if len(candidates) == 1:
        return candidates[0], method

    # Browser duplicates such as "file(1).pdf" are safe if byte-identical.
    hashes = {sha256(path) for path in candidates}
    if len(hashes) == 1:
        return candidates[0], method + " (identical duplicate)"
    return None, "ambiguous dumped PDFs: " + ", ".join(path.name for path in candidates)


def unique_destination(folder: Path, preferred_name: str, source: Path) -> Path:
    candidate = folder / preferred_name
    if not candidate.exists() or sha256(candidate) == sha256(source):
        return candidate
    stem = candidate.stem
    for number in range(2, 1000):
        candidate = folder / f"{stem}_{number}.pdf"
        if not candidate.exists() or sha256(candidate) == sha256(source):
            return candidate
    raise RuntimeError(f"Could not choose a destination for {source}")


def build_plan(root: Path, dump_dir: Path) -> tuple[list[Match], dict[str, str]]:
    sources = sorted(
        path for path in dump_dir.glob("*.pdf")
        if is_pdf(path) and not path.name.casefold().startswith("missing_datasheets")
    )
    matches: list[Match] = []
    skipped: dict[str, str] = {}
    for record in collect_urls(root, False):
        source, detail = choose_source(record, sources)
        if source is None:
            skipped[record.url_key] = detail
        else:
            matches.append(Match(record, source, detail))
    return matches, skipped


def fuzzy_family(mpn: str) -> str:
    match = re.match(r"^([A-Za-z]+(?:[-_]?\d+){0,2})", mpn.strip())
    return text_key(match.group(1)) if match else text_key(mpn)


def fuzzy_additions(
    records: list[SymbolUrl], matches: list[Match], skipped: dict[str, str], dump_dir: Path,
    series_anywhere: bool,
) -> list[Match]:
    """Return high-confidence full-PDF MPN/series matches for URL records."""

    try:
        import fitz
    except ImportError:
        return []
    sources = [path for path in dump_dir.glob("*.pdf") if is_pdf(path) and not path.name.casefold().startswith("missing_datasheets")]
    text_by_source: dict[Path, str] = {}
    first_page_by_source: dict[Path, str] = {}
    for index, source in enumerate(sources, start=1):
        try:
            document = fitz.open(source)
            page_text = [page.get_text("text") for page in document]
            first_page_by_source[source] = text_key(page_text[0] if page_text else "")
            text_by_source[source] = text_key(" ".join(page_text))
            document.close()
        except Exception:
            text_by_source[source] = ""
            first_page_by_source[source] = ""
        if index % 25 == 0:
            print(f"FUZZY   scanned text from {index}/{len(sources)} PDFs")

    matched_urls = {match.record.url_key for match in matches}
    remaining = [record for record in records if record.url_key not in matched_urls]
    additions: list[Match] = []
    for record in remaining:
        mpn = text_key(record.mpn)
        candidates = [source for source, text in text_by_source.items() if len(mpn) >= 5 and mpn in text]
        if len(candidates) == 1:
            additions.append(Match(record, candidates[0], "PDF text: exact MPN"))

    matched_urls.update(match.record.url_key for match in additions)
    by_family: dict[tuple[Path, str], list[SymbolUrl]] = defaultdict(list)
    for record in remaining:
        if record.url_key not in matched_urls:
            family = fuzzy_family(record.mpn)
            if len(family) >= 5:
                by_family[(record.library_file.parent, family)].append(record)
    for (_, family), family_records in by_family.items():
        candidates = [source for source, text in text_by_source.items() if family in text]
        # By default, the series must appear on page one.  Image-based cover
        # pages need the opt-in full-document fallback below.
        if len(candidates) == 1 and (series_anywhere or family in first_page_by_source[candidates[0]]):
            additions.extend(Match(record, candidates[0], f"PDF text: unique {family} series") for record in family_records)
    return additions


def delete_invalid_pdfs(dump_dir: Path) -> int:
    """Remove only top-level .pdf files whose header proves they are not PDFs."""

    invalid = [path for path in dump_dir.glob("*.pdf") if not is_pdf(path)]
    for path in invalid:
        path.unlink()
        print(f"REMOVED {path.name} (not a PDF: missing %PDF- header)")
    return len(invalid)


def apply(root: Path, matches: list[Match]) -> tuple[int, int]:
    # One physical copy per (source URL, library folder); all symbols with the
    # same URL in that library share it.
    targets: dict[tuple[str, Path], tuple[Path, Path]] = {}
    for match in matches:
        folder = match.record.library_file.parent / "Datasheets"
        key = (match.record.url_key, folder)
        if key not in targets:
            targets[key] = (match.source, unique_destination(folder, safe_pdf_name(match.record.mpn), match.source))

    by_library: dict[Path, list[tuple[int, int, str]]] = defaultdict(list)
    for match in matches:
        _, destination = targets[(match.record.url_key, match.record.library_file.parent / "Datasheets")]
        by_library[match.record.library_file].append(
            (match.record.value_start, match.record.value_end, escape_kicad_string(local_reference(destination, root)))
        )

    # Backups are created for all affected libraries before changing any file.
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for library in sorted(by_library):
        backup = library.with_name(library.name + f".datasheet_localize_{stamp}.bak")
        shutil.copy2(library, backup)
        print(f"BACKUP  {backup.relative_to(root)}")

    copied_sources: set[Path] = set()
    for source, destination in targets.values():
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copy2(source, destination)
            copied_sources.add(source)
            print(f"COPIED  {source.name} -> {destination.relative_to(root)}")

    changed = 0
    for library, patches in by_library.items():
        # Offsets returned by collect_urls are based on unmodified CRLF text.
        text = read_library(library)
        original = text
        for start, end, replacement in sorted(patches, reverse=True):
            if text[start:end].startswith(("http://", "https://")):
                text = text[:start] + replacement + text[end:]
        if text != original:
            library.write_text(text, encoding="utf-8", newline="")
            changed += 1
            print(f"UPDATED {library.relative_to(root)}")

    # A dumped file is removed only after every required destination has been
    # copied and all symbol libraries have been written successfully.
    for source in sorted(copied_sources):
        source.unlink()
        print(f"MOVED   {source.name}")
    return changed, len(targets)


def repair_references(root: Path) -> int:
    """Finish reference updates after PDFs have already been localized."""

    groups: dict[tuple[str, Path], list[SymbolUrl]] = defaultdict(list)
    for record in collect_urls(root, False):
        groups[(record.url_key, record.library_file.parent / "Datasheets")].append(record)

    by_library: dict[Path, list[tuple[int, int, str]]] = defaultdict(list)
    for (_, folder), records in groups.items():
        candidates = [folder / safe_pdf_name(record.mpn) for record in records]
        destination = next((path for path in candidates if is_pdf(path)), None)
        if destination is None:
            continue
        for record in records:
            by_library[record.library_file].append(
                (record.value_start, record.value_end, escape_kicad_string(local_reference(destination, root)))
            )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    changed = 0
    for library, patches in sorted(by_library.items()):
        backup = library.with_name(library.name + f".datasheet_localize_repair_{stamp}.bak")
        shutil.copy2(library, backup)
        text = read_library(library)
        original = text
        for start, end, replacement in sorted(patches, reverse=True):
            if text[start:end].startswith(("http://", "https://")):
                text = text[:start] + replacement + text[end:]
        if text != original:
            with library.open("w", encoding="utf-8", newline="") as handle:
                handle.write(text)
            changed += 1
            print(f"REPAIRED {library.relative_to(root)}")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--dump-dir", type=Path, default=None, help="Folder containing manually downloaded PDFs (default: root).")
    parser.add_argument("--apply", action="store_true", help="Back up libraries, copy/move PDFs, and update Datasheet properties.")
    parser.add_argument("--delete-invalid", action="store_true", help="Delete only dumped .pdf files that do not have a PDF header, then exit.")
    parser.add_argument("--repair-references", action="store_true", help="Update URL fields where a matching localized PDF already exists, then exit.")
    parser.add_argument("--fuzzy", action="store_true", help="Also match unique embedded MPN/series text from valid dumped PDFs.")
    parser.add_argument("--series-anywhere", action="store_true", help="Allow a unique series match anywhere in a PDF, including image-based cover pages.")
    args = parser.parse_args()
    root = args.root.resolve()
    dump_dir = (args.dump_dir or root).resolve()
    if args.delete_invalid:
        print(f"Removed {delete_invalid_pdfs(dump_dir)} non-PDF response files.")
        return 0
    if args.repair_references:
        print(f"Repaired {repair_references(root)} library files.")
        return 0
    matches, skipped = build_plan(root, dump_dir)
    if args.fuzzy:
        records = collect_urls(root, False)
        additions = fuzzy_additions(records, matches, skipped, dump_dir, args.series_anywhere)
        matches.extend(additions)
        for match in additions:
            skipped.pop(match.record.url_key, None)
        print(f"FUZZY   added {len(additions)} high-confidence symbol matches.")

    urls_matched = len({match.record.url_key for match in matches})
    print(f"Matched {len(matches)} symbol references across {urls_matched} unique URLs.")
    print(f"Unmatched unique URLs: {len(skipped)}")
    for url, reason in sorted(skipped.items()):
        print(f"UNMATCHED {reason}: {url}")
    if not args.apply:
        print("Preview only. Run again with --apply to make backups, localize PDFs, and update symbols.")
        return 0

    changed, files = apply(root, matches)
    print(f"Done: updated {changed} library files and placed {files} datasheet files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
