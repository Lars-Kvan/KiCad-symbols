#!/usr/bin/env python3
"""Create an Excel report of KiCad symbols without a local datasheet.

The script scans active ``.kicad_sym`` files below the symbol directory.  A
datasheet is considered local when the value of the symbol's ``Datasheet``
property resolves to an existing file.  URLs and empty/sentinel values are
therefore included in the report as missing local datasheets.

The workbook is written with Python's standard library, so no third-party
Excel package is required.

Examples:
    python find_missing_datasheets.py
    python find_missing_datasheets.py --output missing.xlsx
    python find_missing_datasheets.py --root C:\\KiCad\\9.0\\symbols
"""

from __future__ import annotations

import argparse
import bisect
import html
import os
from pathlib import Path
import re
import sys
from collections import Counter
from datetime import datetime
from urllib.parse import unquote, urlparse
from zipfile import ZIP_DEFLATED, ZipFile


PROPERTY_RE = re.compile(
    r'\(property\s+"((?:\\.|[^"])*)"\s+"((?:\\.|[^"])*)"',
    re.DOTALL,
)
SYMBOL_NAME_RE = re.compile(r'^\(symbol\s+"((?:\\.|[^"])*)"')
VARIABLE_RE = re.compile(r"\$\{([^}]+)\}")

ALWAYS_EXCLUDED_DIRS = {".git", "__pycache__"}
ARCHIVE_DIRS = {"backups", "data"}
EMPTY_DATASHEET_VALUES = {"", "-", "n/a", "none", "not specified", "unspecified"}


def decode_kicad_string(value: str) -> str:
    """Decode the simple backslash escaping used by KiCad s-expressions."""

    result: list[str] = []
    escaped = False
    for character in value:
        if escaped:
            result.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        else:
            result.append(character)
    if escaped:
        result.append("\\")
    return "".join(result)


def top_level_symbol_blocks(text: str):
    """Yield ``(start_offset, block_text)`` for symbols in a library file."""

    depth = 0
    in_string = False
    escaped = False
    symbol_start: int | None = None
    index = 0

    while index < len(text):
        character = text[index]

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
                and text.startswith("(symbol", index)
                and index + 7 < len(text)
                and text[index + 7].isspace()
            ):
                symbol_start = index
            depth += 1
        elif character == ")":
            depth -= 1
            if symbol_start is not None and depth == 1:
                yield symbol_start, text[symbol_start : index + 1]
                symbol_start = None
        index += 1


def top_level_properties(block: str) -> dict[str, str]:
    """Return properties directly belonging to a symbol, not a child unit."""

    properties: dict[str, str] = {}
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
                    name = decode_kicad_string(match.group(1))
                    value = decode_kicad_string(match.group(2))
                    properties[name.casefold()] = value
            depth += 1
        elif character == ")":
            depth -= 1
        index += 1

    return properties


def line_number(line_starts: list[int], offset: int) -> int:
    return bisect.bisect_right(line_starts, offset)


def iter_symbol_files(root: Path, include_archives: bool):
    """Yield active symbol files, excluding generated/archive directories."""

    for path in sorted(root.rglob("*.kicad_sym")):
        relative_parts = {part.casefold() for part in path.relative_to(root).parts}
        if relative_parts & ALWAYS_EXCLUDED_DIRS:
            continue
        if not include_archives and relative_parts & ARCHIVE_DIRS:
            continue
        yield path


def expand_variables(value: str, root: Path) -> tuple[str, list[str]]:
    """Expand KiCad's symbol directory variable and available environment vars."""

    unresolved: list[str] = []

    def replacement(match: re.Match[str]) -> str:
        variable = match.group(1)
        if variable.casefold() == "pl_symbol_dir":
            return str(root)
        environment_value = os.environ.get(variable)
        if environment_value is None:
            unresolved.append(variable)
            return match.group(0)
        return environment_value

    return VARIABLE_RE.sub(replacement, value), unresolved


def resolve_local_datasheet(
    value: str, library_file: Path, root: Path
) -> tuple[Path | None, str, str]:
    """Resolve a Datasheet property and return ``(path, reason, checked_path)``."""

    cleaned = value.strip()
    if cleaned.casefold() in EMPTY_DATASHEET_VALUES:
        if not cleaned:
            return None, "Datasheet field is empty", ""
        return None, "Datasheet field is not specified", cleaned

    parsed_url = urlparse(cleaned)
    if parsed_url.scheme.casefold() in {"http", "https", "ftp"}:
        return None, "Datasheet field is a URL; no local file is referenced", cleaned

    if parsed_url.scheme.casefold() == "file":
        local_value = unquote(parsed_url.path)
        # file:///C:/... is represented as /C:/... by urllib on Windows.
        if os.name == "nt" and re.match(r"^/[A-Za-z]:/", local_value):
            local_value = local_value[1:]
        expanded, unresolved = expand_variables(local_value, root)
    else:
        expanded, unresolved = expand_variables(cleaned, root)

    if unresolved:
        return (
            None,
            "Unresolved environment variable(s): " + ", ".join(sorted(set(unresolved))),
            expanded,
        )

    expanded = os.path.expanduser(expanded).replace("/", os.sep)
    candidate = Path(expanded)
    if candidate.is_absolute():
        candidates = [candidate]
    else:
        candidates = [library_file.parent / candidate, root / candidate]

    for candidate_path in candidates:
        if candidate_path.is_file():
            return candidate_path.resolve(), "", str(candidate_path)

    checked = "; ".join(str(path) for path in candidates)
    return None, "Local datasheet file does not exist", checked


def scan_symbols(root: Path, include_archives: bool) -> tuple[list[dict[str, str]], dict[str, int]]:
    """Scan symbol files and return missing records plus scan statistics."""

    missing: list[dict[str, str]] = []
    stats = Counter()

    for library_file in iter_symbol_files(root, include_archives):
        stats["library_files"] += 1
        try:
            text = library_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = library_file.read_text(encoding="utf-8-sig")

        line_starts = [0]
        line_starts.extend(index + 1 for index, character in enumerate(text) if character == "\n")

        for symbol_offset, block in top_level_symbol_blocks(text):
            stats["symbols"] += 1
            symbol_match = SYMBOL_NAME_RE.match(block)
            if not symbol_match:
                continue
            symbol_name = decode_kicad_string(symbol_match.group(1))
            properties = top_level_properties(block)
            mpn = properties.get("mpn", "").strip()
            if not mpn:
                stats["symbols_without_mpn"] += 1
                continue

            stats["symbols_with_mpn"] += 1
            datasheet = properties.get("datasheet", "")
            local_path, reason, checked_path = resolve_local_datasheet(
                datasheet, library_file, root
            )
            if local_path is not None:
                stats["local_datasheets"] += 1
                continue

            stats["missing_datasheets"] += 1
            stats["reason:" + reason] += 1
            missing.append(
                {
                    "MPN": mpn,
                    "Symbol": symbol_name,
                    "Library": str(library_file.relative_to(root)),
                    "Datasheet property": datasheet,
                    "Reason": reason,
                    "Checked local path": checked_path,
                    "Source line": str(line_number(line_starts, symbol_offset)),
                }
            )

    missing.sort(key=lambda row: (row["Library"].casefold(), row["Symbol"].casefold(), row["MPN"].casefold()))
    return missing, dict(stats)


def excel_column_name(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def xml_text(value: object) -> str:
    return html.escape(str(value), quote=False)


def inline_string_cell(reference: str, value: object, style: int = 0) -> str:
    escaped = xml_text(value)
    style_attribute = f' s="{style}"' if style else ""
    return f'<c r="{reference}" t="inlineStr"{style_attribute}><is><t xml:space="preserve">{escaped}</t></is></c>'


def number_cell(reference: str, value: int, style: int = 0) -> str:
    style_attribute = f' s="{style}"' if style else ""
    return f'<c r="{reference}"{style_attribute}><v>{value}</v></c>'


def worksheet_xml(rows: list[list[object]], widths: list[float], freeze_rows: int = 1) -> str:
    last_column = excel_column_name(max(1, len(widths)))
    last_row = max(1, len(rows))
    row_xml: list[str] = []
    for row_number, row in enumerate(rows, start=1):
        cells = [
            inline_string_cell(f"{excel_column_name(column_number)}{row_number}", value, 1 if row_number == 1 else 0)
            for column_number, value in enumerate(row, start=1)
        ]
        row_xml.append(f'<row r="{row_number}">{"".join(cells)}</row>')

    columns = "".join(
        f'<col min="{index}" max="{index}" width="{width}" customWidth="1"/>'
        for index, width in enumerate(widths, start=1)
    )
    auto_filter = f'<autoFilter ref="A1:{last_column}{last_row}"/>'
    freeze = (
        f'<sheetViews><sheetView workbookViewId="0">'
        f'<pane ySplit="{freeze_rows}" topLeftCell="A{freeze_rows + 1}" activePane="bottomLeft" state="frozen"/>'
        f'<selection pane="bottomLeft" activeCell="A{freeze_rows + 1}" sqref="A{freeze_rows + 1}"/>'
        f'</sheetView></sheetViews>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"{freeze}<cols>{columns}</cols><sheetData>{''.join(row_xml)}</sheetData>{auto_filter}"
        "</worksheet>"
    )


def styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<numFmts count="0"/>'
        '<fonts count="2">'
        '<font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>'
        '</fonts>'
        '<fills count="2">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF1F4E78"/><bgColor indexed="64"/></patternFill></fill>'
        '</fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="1" borderId="0" applyFont="1" applyFill="1"/>'
        '</cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '</styleSheet>'
    )


def write_workbook(output: Path, missing: list[dict[str, str]], stats: dict[str, int], root: Path) -> None:
    columns = [
        "MPN",
        "Symbol",
        "Library",
        "Datasheet property",
        "Reason",
        "Checked local path",
        "Source line",
    ]
    missing_rows = [columns] + [[row[column] for column in columns] for row in missing]
    summary_rows: list[list[object]] = [
        ["Metric", "Value"],
        ["Generated", datetime.now().astimezone().isoformat(timespec="seconds")],
        ["Symbol directory", str(root)],
        ["Library files scanned", stats.get("library_files", 0)],
        ["Symbols scanned", stats.get("symbols", 0)],
        ["Symbols with an MPN", stats.get("symbols_with_mpn", 0)],
        ["Local datasheets found", stats.get("local_datasheets", 0)],
        ["Missing local datasheets", stats.get("missing_datasheets", 0)],
        [],
        ["Missing reason", "Count"],
    ]
    reason_counts = sorted(
        ((key.removeprefix("reason:"), value) for key, value in stats.items() if key.startswith("reason:")),
        key=lambda item: item[0].casefold(),
    )
    summary_rows.extend([[reason, count] for reason, count in reason_counts])

    output.parent.mkdir(parents=True, exist_ok=True)
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '</Types>'
    )
    root_relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Missing datasheets" sheetId="1" r:id="rId1"/>'
        '<sheet name="Summary" sheetId="2" r:id="rId2"/></sheets></workbook>'
    )
    workbook_relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '</Relationships>'
    )

    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_relationships)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_relationships)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet_xml(missing_rows, [28, 34, 42, 65, 48, 90, 12]))
        archive.writestr("xl/worksheets/sheet2.xml", worksheet_xml(summary_rows, [48, 28]))
        archive.writestr("xl/styles.xml", styles_xml())


def parse_args() -> argparse.Namespace:
    script_root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=script_root,
        help="Symbol directory to scan (default: the directory containing this script).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output .xlsx file (default: missing_datasheets.xlsx in the symbol directory).",
    )
    parser.add_argument(
        "--include-archives",
        action="store_true",
        help="Also scan .kicad_sym files below Backups and Data directories.",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    root = arguments.root.expanduser().resolve()
    output_argument = arguments.output or (root / "missing_datasheets.xlsx")
    output = output_argument.expanduser()
    if not output.is_absolute():
        output = (Path.cwd() / output).resolve()
    else:
        output = output.resolve()

    if not root.is_dir():
        print(f"Error: symbol directory does not exist: {root}", file=sys.stderr)
        return 2

    missing, stats = scan_symbols(root, arguments.include_archives)
    write_workbook(output, missing, stats, root)
    print(
        f"Wrote {len(missing)} missing-datasheet records to {output} "
        f"({stats.get('symbols', 0)} symbols scanned, "
        f"{stats.get('local_datasheets', 0)} local datasheets found)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
