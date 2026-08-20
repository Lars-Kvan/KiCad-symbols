#!/usr/bin/env python3
"""Download datasheet URLs from KiCad symbol libraries safely.

The default mode is a preview and makes no network requests.  Use
``--download`` to start downloading.  Use ``--update-symbols`` as well if the
Datasheet properties should be changed from URLs to local paths after a
successful download.

This tool deliberately does not bypass CAPTCHAs, rotate proxies, impersonate
browsers, or retry access-denied responses.  It uses a clear User-Agent,
follows redirects normally, throttles requests per host, caches successful
downloads, validates that responses are PDFs, and records failures for manual
review.

Examples:
    python download_datasheets.py
    python download_datasheets.py --download --limit 10
    python download_datasheets.py --download --update-symbols
"""

from __future__ import annotations

import argparse
import csv
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import random
import re
import sys
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, build_opener
from urllib.robotparser import RobotFileParser

from find_missing_datasheets import (
    PROPERTY_RE,
    SYMBOL_NAME_RE,
    decode_kicad_string,
    iter_symbol_files,
    top_level_symbol_blocks,
)


DEFAULT_USER_AGENT = "KiCad-Datasheet-Downloader/1.0"
RETRYABLE_HTTP_CODES = {408, 425, 500, 502, 503, 504}
INVALID_FILENAME_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
PRINT_LOCK = threading.Lock()


def log(message: str) -> None:
    with PRINT_LOCK:
        print(f"[{datetime.now().astimezone().strftime('%H:%M:%S')}] {message}", flush=True)


def format_duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


@dataclass(frozen=True)
class SymbolUrl:
    library_file: Path
    symbol: str
    mpn: str
    url: str
    url_key: str
    value_start: int
    value_end: int


@dataclass(frozen=True)
class DownloadResult:
    status: str
    url: str
    local_path: Path | None = None
    error: str = ""
    attempts: int = 0


def read_library(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return handle.read()
    except UnicodeDecodeError:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return handle.read()


def top_level_property_spans(block: str):
    """Yield ``(name, value, value_start, value_end)`` for direct properties."""

    depth = 0
    in_string = False
    escaped = False
    index = 0

    while index < len(block):
        character = block[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            index += 1
            continue

        if character == '"':
            in_string = True
        elif character == "(":
            if (
                depth == 1
                and block.startswith("(property", index)
                and index + 9 < len(block)
                and block[index + 9].isspace()
            ):
                match = PROPERTY_RE.match(block, index)
                if match:
                    yield (
                        decode_kicad_string(match.group(1)),
                        decode_kicad_string(match.group(2)),
                        match.start(2),
                        match.end(2),
                    )
            depth += 1
        elif character == ")":
            depth -= 1
        index += 1


def normalize_url(value: str) -> str | None:
    """Normalize an HTTP(S) URL and remove an irrelevant fragment."""

    parsed = urlsplit(value.strip())
    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return urlunsplit((scheme, parsed.netloc.casefold(), parsed.path, parsed.query, ""))


def origin_of(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme.casefold()}://{parsed.netloc.casefold()}"


def normalize_origin(value: str) -> str | None:
    value = value.strip()
    if "://" not in value:
        value = "https://" + value
    parsed = urlsplit(value)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme.casefold()}://{parsed.netloc.casefold()}"


def collect_urls(root: Path, include_archives: bool) -> list[SymbolUrl]:
    records: list[SymbolUrl] = []

    for library_file in iter_symbol_files(root, include_archives):
        text = read_library(library_file)
        for symbol_offset, block in top_level_symbol_blocks(text):
            symbol_match = SYMBOL_NAME_RE.match(block)
            if not symbol_match:
                continue

            symbol = decode_kicad_string(symbol_match.group(1))
            properties: dict[str, tuple[str, int, int]] = {}
            for name, value, value_start, value_end in top_level_property_spans(block):
                properties[name.casefold()] = (value, value_start, value_end)

            datasheet_property = properties.get("datasheet")
            if datasheet_property is None:
                continue
            datasheet, relative_start, relative_end = datasheet_property
            url = normalize_url(datasheet)
            if url is None:
                continue

            mpn = properties.get("mpn", ("", 0, 0))[0].strip()
            records.append(
                SymbolUrl(
                    library_file=library_file,
                    symbol=symbol,
                    mpn=mpn,
                    url=url,
                    url_key=url,
                    value_start=symbol_offset + relative_start,
                    value_end=symbol_offset + relative_end,
                )
            )

    return records


def safe_filename_component(value: str) -> str:
    value = value.strip()
    value = INVALID_FILENAME_CHARACTERS.sub("_", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value[:90] or "datasheet"


def target_path(record: SymbolUrl, output_dir: Path) -> Path:
    label = safe_filename_component(record.mpn or record.symbol)
    suffix = hashlib.sha256(record.url_key.encode("utf-8")).hexdigest()[:10]
    return output_dir / f"{label}__{suffix}.pdf"


def is_pdf(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            header = handle.read(1024)
    except OSError:
        return False
    return header.lstrip(b"\xef\xbb\xbf\r\n\t ").startswith(b"%PDF")


class HostRateLimiter:
    def __init__(self, delay: float, jitter: float, global_delay: float, global_jitter: float) -> None:
        self.delay = max(0.0, delay)
        self.jitter = max(0.0, jitter)
        self.global_delay = max(0.0, global_delay)
        self.global_jitter = max(0.0, global_jitter)
        self.next_allowed: dict[str, float] = {}
        self.next_global_allowed = 0.0
        self.blocked_hosts: set[str] = set()
        self.lock = threading.Lock()

    def block(self, host: str) -> None:
        with self.lock:
            self.blocked_hosts.add(host)

    def is_blocked(self, host: str) -> bool:
        with self.lock:
            return host in self.blocked_hosts

    def wait(self, host: str, purpose: str, stop_event: threading.Event | None = None) -> bool:
        if stop_event is not None and stop_event.is_set():
            return False
        with self.lock:
            now = time.monotonic()
            scheduled = max(
                now,
                self.next_allowed.get(host, 0.0),
                self.next_global_allowed,
            )
            self.next_allowed[host] = scheduled + self.delay + random.uniform(0.0, self.jitter)
            self.next_global_allowed = scheduled + self.global_delay + random.uniform(0.0, self.global_jitter)

        wait_for = scheduled - now
        if wait_for > 0:
            deadline = scheduled
            while True:
                if stop_event is not None and stop_event.is_set():
                    return False
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                next_local = datetime.fromtimestamp(time.time() + remaining).astimezone().strftime("%H:%M:%S")
                log(
                    f"[rate-limit] {purpose} for {host}: next request in "
                    f"{remaining:.0f}s (not before {next_local})"
                )
                time.sleep(min(10.0, remaining))
        return True

    def sleep_with_status(
        self,
        seconds: float,
        reason: str,
        stop_event: threading.Event | None = None,
    ) -> bool:
        deadline = time.monotonic() + seconds
        while True:
            if stop_event is not None and stop_event.is_set():
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            log(f"[backoff] {reason}: retry in {remaining:.0f}s")
            time.sleep(min(10.0, remaining))


class RobotsPolicy:
    """Fetch and cache robots.txt once per host, failing closed on errors."""

    def __init__(self, limiter: HostRateLimiter, timeout: float, user_agent: str) -> None:
        self.limiter = limiter
        self.timeout = timeout
        self.user_agent = user_agent
        self.opener = build_opener()
        self.cache: dict[str, tuple[bool, str]] = {}
        self.cache_locks: dict[str, threading.Lock] = {}
        self.cache_locks_lock = threading.Lock()

    def can_fetch(self, url: str, stop_event: threading.Event | None = None) -> tuple[bool, str]:
        parsed = urlsplit(url)
        host = parsed.netloc.casefold()
        origin = f"{parsed.scheme.casefold()}://{host}"
        with self.cache_locks_lock:
            origin_lock = self.cache_locks.setdefault(origin, threading.Lock())

        with origin_lock:
            if origin in self.cache:
                return self.cache[origin]
            if stop_event is not None and stop_event.is_set():
                return False, "run stopped after a safety block"

            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            if not self.limiter.wait(host, "robots.txt", stop_event):
                return False, "run stopped after a safety block"
            request = Request(robots_url, headers={"User-Agent": self.user_agent, "Accept": "text/plain,*/*;q=0.1"})
            try:
                log(f"[request] robots.txt: {robots_url}")
                with self.opener.open(request, timeout=self.timeout) as response:
                    content = response.read(1024 * 1024 + 1)
                    log(f"[response] robots.txt HTTP {response.getcode()} bytes={len(content)}")
                    if len(content) > 1024 * 1024:
                        decision = (False, "robots.txt is larger than 1 MiB")
                    else:
                        parser = RobotFileParser()
                        parser.set_url(robots_url)
                        parser.parse(content.decode("utf-8", errors="replace").splitlines())
                        allowed = parser.can_fetch(self.user_agent, url)
                        decision = (allowed, "disallowed by robots.txt" if not allowed else "")
            except HTTPError as error:
                if error.code == 404:
                    decision = (False, "robots.txt was not found; refusing to infer permission")
                else:
                    self.limiter.block(host)
                    decision = (False, f"robots.txt returned HTTP {error.code}")
            except (TimeoutError, URLError, OSError) as error:
                self.limiter.block(host)
                decision = (False, f"could not safely read robots.txt: {error}")

            self.cache[origin] = decision
            return decision


def retry_after_seconds(error: HTTPError) -> float | None:
    value = error.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def download_one(
    url: str,
    destination: Path,
    limiter: HostRateLimiter,
    timeout: float,
    max_bytes: int,
    max_retries: int,
    overwrite: bool,
    user_agent: str,
    robots: RobotsPolicy,
    stop_event: threading.Event | None = None,
) -> DownloadResult:
    host = urlsplit(url).netloc.casefold()
    if destination.is_file() and not overwrite:
        if is_pdf(destination):
            return DownloadResult("cached", url, destination, attempts=0)
        # An invalid previous file is replaced only after a complete valid PDF
        # has been received into the .part file below.

    if limiter.is_blocked(host):
        return DownloadResult("skipped", url, error="host was stopped after a safety block")

    can_fetch, robots_reason = robots.can_fetch(url, stop_event)
    if not can_fetch:
        return DownloadResult("skipped", url, error=robots_reason)

    destination.parent.mkdir(parents=True, exist_ok=True)
    part_path = destination.with_name(destination.name + ".part")
    opener = build_opener()

    for attempt in range(1, max_retries + 2):
        if not limiter.wait(host, "PDF", stop_event):
            return DownloadResult("skipped", url, error="run stopped after a safety block")
        request = Request(
            url,
            headers={
                "User-Agent": user_agent,
                "Accept": "application/pdf,application/octet-stream;q=0.8,*/*;q=0.1",
                "Accept-Encoding": "identity",
            },
        )
        try:
            started = time.monotonic()
            log(f"[request] PDF attempt {attempt}: {url}")
            with opener.open(request, timeout=timeout) as response:
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().casefold()
                content_length = response.headers.get("Content-Length")
                log(
                    f"[response] HTTP {response.getcode()} content-type={content_type or 'unknown'} "
                    f"content-length={content_length or 'unknown'}"
                )
                if content_length:
                    try:
                        if int(content_length) > max_bytes:
                            return DownloadResult(
                                "failed",
                                url,
                                error=f"response exceeds {max_bytes / 1024 / 1024:.1f} MiB",
                                attempts=attempt,
                            )
                    except ValueError:
                        pass

                total = 0
                next_progress = 512 * 1024
                with part_path.open("wb") as output:
                    while True:
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > max_bytes:
                            output.close()
                            part_path.unlink(missing_ok=True)
                            return DownloadResult(
                                "failed",
                                url,
                                error=f"response exceeds {max_bytes / 1024 / 1024:.1f} MiB",
                                attempts=attempt,
                            )
                        output.write(chunk)
                        if total >= next_progress:
                            log(f"[download] {urlsplit(url).netloc}: received {total / 1024 / 1024:.1f} MiB")
                            next_progress += 512 * 1024

                if content_type == "text/html" or not is_pdf(part_path):
                    part_path.unlink(missing_ok=True)
                    limiter.block(host)
                    return DownloadResult(
                        "blocked",
                        url,
                        error="response was not a PDF; stopping because it may be a bot block or landing page",
                        attempts=attempt,
                    )

                os.replace(part_path, destination)
                log(
                    f"[download] completed {total / 1024 / 1024:.1f} MiB in "
                    f"{time.monotonic() - started:.1f}s -> {destination}"
                )
                return DownloadResult("downloaded", url, destination, attempts=attempt)

        except HTTPError as error:
            if error.code in {401, 403, 429}:
                limiter.block(host)
                return DownloadResult(
                    "blocked",
                    url,
                    error=f"HTTP {error.code} {error.reason}; stopping this run for safety",
                    attempts=attempt,
                )
            if error.code not in RETRYABLE_HTTP_CODES or attempt > max_retries:
                return DownloadResult(
                    "failed",
                    url,
                    error=f"HTTP {error.code} {error.reason}",
                    attempts=attempt,
                )
            retry_after = retry_after_seconds(error)
            backoff = 30.0 * (2 ** (attempt - 1))
            if not limiter.sleep_with_status(
                min(300.0, max(backoff, retry_after or 0.0)),
                f"HTTP {error.code}",
                stop_event,
            ):
                return DownloadResult("skipped", url, error="run stopped after a safety block")
        except (TimeoutError, URLError, OSError) as error:
            if attempt > max_retries:
                return DownloadResult("failed", url, error=str(error), attempts=attempt)
            if not limiter.sleep_with_status(
                min(300.0, 15.0 * (2 ** (attempt - 1))),
                type(error).__name__,
                stop_event,
            ):
                return DownloadResult("skipped", url, error="run stopped after a safety block")
        finally:
            part_path.unlink(missing_ok=True)

    return DownloadResult("failed", url, error="download retries exhausted", attempts=max_retries + 1)


def local_reference(path: Path, root: Path) -> str:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return str(path.resolve()).replace(os.sep, "/")
    return "${PL_SYMBOL_DIR}/" + relative.as_posix()


def escape_kicad_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def update_symbols(
    records: list[SymbolUrl],
    results: dict[str, DownloadResult],
    root: Path,
) -> int:
    patches_by_file: dict[Path, list[tuple[int, int, str]]] = defaultdict(list)
    for record in records:
        result = results.get(record.url_key)
        if result is None or result.local_path is None:
            continue
        patches_by_file[record.library_file].append(
            (
                record.value_start,
                record.value_end,
                escape_kicad_string(local_reference(result.local_path, root)),
            )
        )

    changed_files = 0
    for library_file, patches in patches_by_file.items():
        text = read_library(library_file)
        original = text
        for start, end, replacement in sorted(patches, reverse=True):
            if text[start:end].startswith("http://") or text[start:end].startswith("https://"):
                text = text[:start] + replacement + text[end:]

        if text == original:
            continue

        backup = library_file.with_suffix(library_file.suffix + ".datasheet_download.bak")
        if not backup.exists():
            backup.write_bytes(library_file.read_bytes())
        with library_file.open("w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        changed_files += 1

    return changed_files


def write_manifest(
    manifest_path: Path,
    records: list[SymbolUrl],
    results: dict[str, DownloadResult],
    root: Path,
) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Status", "MPN", "Symbol", "Library", "URL", "Local file", "Error"])
        for record in records:
            result = results.get(record.url_key, DownloadResult("not_attempted", record.url_key))
            local_file = ""
            if result.local_path is not None:
                try:
                    local_file = str(result.local_path.resolve().relative_to(root.resolve()))
                except ValueError:
                    local_file = str(result.local_path)
            writer.writerow(
                [
                    result.status,
                    record.mpn,
                    record.symbol,
                    str(record.library_file.relative_to(root)),
                    record.url,
                    local_file,
                    result.error,
                ]
            )


def print_preview(records: list[SymbolUrl], limit: int | None) -> None:
    grouped: dict[str, list[SymbolUrl]] = defaultdict(list)
    for record in records:
        grouped[record.url_key].append(record)

    domains = Counter(urlsplit(url).netloc.casefold() for url in grouped)
    print(f"Found {len(records)} HTTP(S) symbol references and {len(grouped)} unique URLs.")
    print("URLs by host:")
    for host, count in domains.most_common():
        print(f"  {host}: {count}")
    shown = 0
    print("\nPreview:")
    for url, references in grouped.items():
        first = references[0]
        print(f"  {first.mpn or first.symbol} [{urlsplit(url).netloc}] {url}")
        shown += 1
        if limit is not None and shown >= limit:
            break
        if shown >= 20:
            break
    print("\nNo network requests were made. Use --download to begin.")


class BatchProgress:
    def __init__(self, total: int) -> None:
        self.total = total
        self.completed = 0
        self.started = time.monotonic()
        self.lock = threading.Lock()

    def start(self, index: int, record: SymbolUrl) -> None:
        log(
            f"[task {index}/{self.total}] START MPN={record.mpn or '(no MPN)'} "
            f"origin={origin_of(record.url)}"
        )

    def finish(self, index: int, url: str, result: DownloadResult) -> None:
        with self.lock:
            self.completed += 1
            elapsed = time.monotonic() - self.started
            average = elapsed / self.completed
            eta = average * max(0, self.total - self.completed)
            completed = self.completed
        detail = result.error or str(result.local_path or "")
        log(
            f"[task {index}/{self.total}] DONE {result.status} {url} {detail} "
            f"batch={completed}/{self.total} elapsed={format_duration(elapsed)} "
            f"estimated remaining={format_duration(eta)}"
        )

    def elapsed(self) -> float:
        return time.monotonic() - self.started


def parse_args() -> argparse.Namespace:
    script_root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=script_root, help="Symbol directory to scan.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for downloaded PDFs (default: <root>/Downloaded_Datasheets).",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="CSV manifest path (default: <root>/datasheet_download_manifest.csv when downloading).",
    )
    parser.add_argument("--download", action="store_true", help="Perform network downloads.")
    parser.add_argument(
        "--update-symbols",
        action="store_true",
        help="Replace successful HTTP Datasheet properties with local paths.",
    )
    parser.add_argument("--include-archives", action="store_true", help="Include Backups and Data folders.")
    parser.add_argument("--limit", type=int, help="Process at most this many unique URLs.")
    parser.add_argument("--delay", type=float, default=30.0, help="Minimum seconds between requests to one host.")
    parser.add_argument("--jitter", type=float, default=15.0, help="Additional random per-host delay in seconds.")
    parser.add_argument("--global-delay", type=float, default=10.0, help="Minimum seconds between any requests.")
    parser.add_argument("--global-jitter", type=float, default=5.0, help="Additional random global delay in seconds.")
    parser.add_argument("--workers", type=int, default=3, help="Maximum parallel domain workers (default: 3).")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds.")
    parser.add_argument("--max-retries", type=int, default=0, help="Retries for temporary network/server errors (default: none).")
    parser.add_argument("--max-size-mb", type=float, default=50.0, help="Maximum accepted PDF size.")
    parser.add_argument(
        "--allow-origin",
        action="append",
        default=[],
        help="Only process this exact HTTP(S) origin; repeat for multiple origins.",
    )
    parser.add_argument(
        "--max-per-origin",
        type=int,
        default=1,
        help="Maximum unique URLs per origin in one run (default: 1; 0 means unlimited).",
    )
    parser.add_argument("--overwrite", action="store_true", help="Redownload existing cached PDFs.")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT, help="User-Agent sent to servers.")
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    root = arguments.root.expanduser().resolve()
    if not root.is_dir():
        print(f"Error: symbol directory does not exist: {root}", file=sys.stderr)
        return 2
    if arguments.limit is not None and arguments.limit < 1:
        print("Error: --limit must be at least 1", file=sys.stderr)
        return 2
    if arguments.max_per_origin < 0:
        print("Error: --max-per-origin cannot be negative", file=sys.stderr)
        return 2
    if arguments.workers < 1 or arguments.workers > 8:
        print("Error: --workers must be between 1 and 8", file=sys.stderr)
        return 2
    if arguments.update_symbols and not arguments.download:
        print("Error: --update-symbols requires --download", file=sys.stderr)
        return 2

    output_dir = (arguments.output_dir or root / "Downloaded_Datasheets").expanduser()
    if not output_dir.is_absolute():
        output_dir = (Path.cwd() / output_dir).resolve()
    else:
        output_dir = output_dir.resolve()

    allowed_origins: set[str] = set()
    for value in arguments.allow_origin:
        normalized = normalize_origin(value)
        if normalized is None:
            print(f"Error: invalid --allow-origin value: {value}", file=sys.stderr)
            return 2
        allowed_origins.add(normalized)

    records = collect_urls(root, arguments.include_archives)
    unique_records: dict[str, SymbolUrl] = {}
    for record in records:
        unique_records.setdefault(record.url_key, record)
    unique_urls: list[str] = []
    origin_counts: Counter[str] = Counter()
    for url, record in unique_records.items():
        origin = origin_of(url)
        if allowed_origins and origin not in allowed_origins:
            continue
        if arguments.max_per_origin and origin_counts[origin] >= arguments.max_per_origin:
            continue
        destination = target_path(record, output_dir)
        if destination.is_file() and is_pdf(destination) and not arguments.overwrite:
            continue
        unique_urls.append(url)
        origin_counts[origin] += 1
        if arguments.limit is not None and len(unique_urls) >= arguments.limit:
            break
    selected_urls = set(unique_urls)
    records = [record for record in records if record.url_key in selected_urls]

    if not arguments.download:
        print_preview(records, len(unique_urls))
        return 0

    if not unique_urls:
        log("No uncached URLs matched the selected origins and limits.")
        return 0

    log(
        f"Preparing to process {len(unique_urls)} unique URLs with a "
        f"{arguments.workers} workers, {arguments.delay:g}s per-origin delay, "
        f"and {arguments.global_delay:g}s global delay."
    )
    limiter = HostRateLimiter(
        arguments.delay,
        arguments.jitter,
        arguments.global_delay,
        arguments.global_jitter,
    )
    robots = RobotsPolicy(limiter, max(1.0, arguments.timeout), arguments.user_agent)
    results: dict[str, DownloadResult] = {}
    stop_event = threading.Event()
    progress = BatchProgress(len(unique_urls))

    def run_task(index: int, url: str) -> tuple[str, DownloadResult]:
        record = unique_records[url]
        progress.start(index, record)
        result = download_one(
            url=url,
            destination=target_path(record, output_dir),
            limiter=limiter,
            timeout=max(1.0, arguments.timeout),
            max_bytes=max(1, int(arguments.max_size_mb * 1024 * 1024)),
            max_retries=max(0, arguments.max_retries),
            overwrite=arguments.overwrite,
            user_agent=arguments.user_agent,
            robots=robots,
            stop_event=stop_event,
        )
        if result.status == "blocked":
            stop_event.set()
            log("[safety] Server warning received; cancelling queued tasks and stopping new requests.")
        progress.finish(index, url, result)
        return url, result

    worker_count = min(arguments.workers, len(unique_urls))
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="datasheet") as executor:
        futures = {
            executor.submit(run_task, index, url): (index, url)
            for index, url in enumerate(unique_urls, start=1)
        }
        for future in as_completed(futures):
            try:
                url, result = future.result()
            except CancelledError:
                continue
            results[url] = result
            if result.status == "blocked":
                for pending in futures:
                    if pending is not future:
                        pending.cancel()

    manifest = arguments.manifest or root / "datasheet_download_manifest.csv"
    manifest = manifest.expanduser()
    if not manifest.is_absolute():
        manifest = (Path.cwd() / manifest).resolve()
    write_manifest(manifest, records, results, root)

    changed_files = 0
    if arguments.update_symbols:
        changed_files = update_symbols(records, results, root)

    counts = Counter(result.status for result in results.values())
    log(
        f"Finished: {counts.get('downloaded', 0)} downloaded, "
        f"{counts.get('cached', 0)} cached, {counts.get('skipped', 0)} skipped, "
        f"{counts.get('failed', 0)} failed, {counts.get('blocked', 0)} blocked; "
        f"total elapsed={format_duration(progress.elapsed())}"
    )
    log(f"Manifest: {manifest}")
    if arguments.update_symbols:
        log(f"Updated {changed_files} symbol library files; backups use *.datasheet_download.bak.")
    return 0 if counts.get("failed", 0) == 0 and counts.get("blocked", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
