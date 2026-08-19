from __future__ import annotations

import csv
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path


EXPECTED_EXISTING_SYMBOLS = 45
EXPECTED_EXISTING_KEYS = 42
EXPECTED_RAW_ROWS = 1054
EXPECTED_UNIQUE_PARTS = 929
EXPECTED_ELIGIBLE_ROWS = 434
EXPECTED_SELECTED = 111
EXPECTED_SKIPS = 26
EXPECTED_ADDITIONS = 85
EXPECTED_FINAL_SYMBOLS = 130

ALLOWED_PACKAGES = ("0402", "0603", "0805", "1206", "1210")
CAPACITOR_SOURCE_NAMES = tuple(f"LCSCSearchDownload({index}).csv" for index in range(22, 34))
RESISTOR_SOURCE_NAMES = ("LCSCSearchDownload.csv",) + tuple(
    f"LCSCSearchDownload({index}).csv" for index in range(1, 22)
)

REQUIRED_SOURCE_COLUMNS = {
    "LCSC Part#",
    "MPN",
    "Manufacturer",
    "Datasheet",
    "Availability",
    "Pricing($)",
    "Minimum",
    "Multiples",
    "Product Detail",
    "Package",
    "Packaging",
    "Capacitance",
    "Tolerance",
    "Voltage Rating",
    "Temperature Coefficient",
}

PROCESSED_COLUMNS = [
    "LCSC Part#",
    "MPN",
    "Manufacturer",
    "Availability",
    "Minimum",
    "Multiples",
    "Product Detail",
    "Package",
    "Packaging",
    "Capacitance",
    "Tolerance",
    "Voltage Rating",
    "Temperature Coefficient",
    "Operating Temperature",
]

NEW_REQUIRED_PROPERTIES = {
    "Reference",
    "Value",
    "Footprint",
    "Datasheet",
    "Description",
    "Manufacturer",
    "Capacitor Series",
    "Automotive Grade",
    "Technology",
    "Capacitor Class",
    "Dielectric",
    "Tolerance",
    "MPN",
    "LCSC Part #",
    "Capacitance",
    "Package",
    "Rated Voltage",
    "Operating Temperature",
    "Packaging",
    "MSL",
    "RoHS",
    "Halogen Free",
    "ki_keywords",
    "ki_fp_filters",
}

PLUS_MINUS = "\N{PLUS-MINUS SIGN}"
DEG_C = "\N{DEGREE CELSIUS}"
OPERATING_TEMPERATURE = f"-55{DEG_C}~+125{DEG_C}"
DATASHEET_LINK = (
    "${PL_SYMBOL_DIR}/PL Capacitor MLCC/Datasheets/"
    "Yageo_X7R_General_Purpose_High_Capacitance_MLCC.pdf"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def canonical_number(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def parse_capacitance(value: str) -> Decimal:
    normalized = (value or "").strip().replace("\N{MICRO SIGN}", "u")
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*([pnu])F", normalized)
    if not match:
        raise ValueError(f"Unsupported capacitance value: {value!r}")
    number_text, unit = match.groups()
    multiplier = {
        "p": Decimal("1"),
        "n": Decimal("1000"),
        "u": Decimal("1000000"),
    }[unit]
    return Decimal(number_text) * multiplier


def format_capacitance(picofarads: Decimal) -> str:
    if picofarads >= Decimal("1000000"):
        return f"{canonical_number(picofarads / Decimal('1000000'))}uF"
    if picofarads >= Decimal("1000"):
        return f"{canonical_number(picofarads / Decimal('1000'))}nF"
    return f"{canonical_number(picofarads)}pF"


def is_e6(picofarads: Decimal) -> bool:
    if picofarads <= 0:
        return False
    normalized = picofarads
    while normalized < Decimal("10"):
        normalized *= Decimal("10")
    while normalized >= Decimal("100"):
        normalized /= Decimal("10")
    return normalized in {
        Decimal("10"),
        Decimal("15"),
        Decimal("22"),
        Decimal("33"),
        Decimal("47"),
        Decimal("68"),
    }


def parse_voltage(value: str) -> Decimal:
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*(V|kV)\s*", value or "")
    if not match:
        raise ValueError(f"Unsupported voltage value: {value!r}")
    number_text, unit = match.groups()
    return Decimal(number_text) * (Decimal("1000") if unit == "kV" else Decimal("1"))


def format_voltage(volts: Decimal) -> str:
    return f"{canonical_number(volts)}V"


def parse_tolerance(value: str) -> Decimal:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)%", value or "")
    if not match:
        raise ValueError(f"Unsupported tolerance value: {value!r}")
    return Decimal(match.group(1))


def format_tolerance(percent: Decimal) -> str:
    return f"{PLUS_MINUS}{canonical_number(percent)}%"


def availability(row: dict[str, str]) -> Decimal:
    return Decimal(row["Availability"].strip())


def selected_sort_key(row: dict[str, str]) -> tuple[Decimal, Decimal, Decimal, str, str]:
    return (
        -parse_voltage(row["Voltage Rating"]),
        parse_tolerance(row["Tolerance"]),
        -availability(row),
        row["MPN"].strip(),
        row["LCSC Part#"].strip(),
    )


def symbol_name(row: dict[str, str]) -> str:
    return f"{format_capacitance(parse_capacitance(row['Capacitance']))}_{row['Package'].strip()}"


def root_close_offset(text: str) -> int:
    if not text.startswith("(kicad_symbol_lib\r\n"):
        raise ValueError("Unexpected library header or newline style")
    if not text.endswith(")\r\n"):
        raise ValueError("Library must end with a CRLF-terminated root parenthesis")
    return len(text) - 3


def parse_top_level_symbols(text: str) -> list[dict[str, object]]:
    root_close = root_close_offset(text)
    starts = [match.start() for match in re.finditer(r'(?m)^\t\(symbol "', text)]
    symbols: list[dict[str, object]] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else root_close
        block = text[start:end]
        name_match = re.match(r'\t\(symbol "([^"]+)"', block)
        if not name_match:
            raise ValueError(f"Could not parse symbol at offset {start}")
        extends_match = re.search(r'^\t\t\(extends "([^"]+)"\)', block, re.MULTILINE)
        property_pairs = re.findall(
            r'^\t\t\(property "([^"]+)" "((?:\\.|[^"])*)"', block, re.MULTILINE
        )
        if len(property_pairs) != len({name for name, _ in property_pairs}):
            raise ValueError(f"Duplicate property name in symbol {name_match.group(1)!r}")
        symbols.append(
            {
                "name": name_match.group(1),
                "extends": extends_match.group(1) if extends_match else None,
                "properties": dict(property_pairs),
                "block": block,
            }
        )
    return symbols


def parentheses_balanced(text: str) -> bool:
    depth = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0 and not in_string


def property_block(name: str, value: str, style: str = "hidden") -> str:
    escaped_value = quote(value)
    if style == "reference":
        return (
            f'\t\t(property "{name}" "{escaped_value}"\r\n'
            "\t\t\t(at 2.54 1.016 0)\r\n"
            "\t\t\t(show_name no)\r\n"
            "\t\t\t(do_not_autoplace yes)\r\n"
            "\t\t\t(effects\r\n"
            "\t\t\t\t(font\r\n"
            "\t\t\t\t\t(size 1.27 1.27)\r\n"
            "\t\t\t\t)\r\n"
            "\t\t\t\t(justify left)\r\n"
            "\t\t\t)\r\n"
            "\t\t)\r\n"
        )
    if style == "value":
        return (
            f'\t\t(property "{name}" "{escaped_value}"\r\n'
            "\t\t\t(at 2.54 -1.016 0)\r\n"
            "\t\t\t(show_name no)\r\n"
            "\t\t\t(do_not_autoplace yes)\r\n"
            "\t\t\t(effects\r\n"
            "\t\t\t\t(font\r\n"
            "\t\t\t\t\t(size 1.27 1.27)\r\n"
            "\t\t\t\t)\r\n"
            "\t\t\t\t(justify left)\r\n"
            "\t\t\t)\r\n"
            "\t\t)\r\n"
        )
    at = "0.9652 -3.81 0" if style == "footprint" else "0 0 0"
    return (
        f'\t\t(property "{name}" "{escaped_value}"\r\n'
        f"\t\t\t(at {at})\r\n"
        "\t\t\t(show_name no)\r\n"
        "\t\t\t(do_not_autoplace no)\r\n"
        "\t\t\t(hide yes)\r\n"
        "\t\t\t(effects\r\n"
        "\t\t\t\t(font\r\n"
        "\t\t\t\t\t(size 1.27 1.27)\r\n"
        "\t\t\t\t)\r\n"
        "\t\t\t)\r\n"
        "\t\t)\r\n"
    )


def build_symbol(row: dict[str, str]) -> tuple[str, str]:
    package = row["Package"].strip()
    capacitance = format_capacitance(parse_capacitance(row["Capacitance"]))
    tolerance = format_tolerance(parse_tolerance(row["Tolerance"]))
    voltage = format_voltage(parse_voltage(row["Voltage Rating"]))
    name = f"{capacitance}_{package}"
    description = (
        f"Yageo CC series X7R Class 2 MLCC, {capacitance}, {tolerance}, "
        f"{voltage}, {package}, {OPERATING_TEMPERATURE}"
    )
    properties = [
        ("Reference", "C", "reference"),
        ("Value", capacitance, "value"),
        ("Footprint", f"PL Capacitor MLCC:C{package}", "footprint"),
        ("Datasheet", DATASHEET_LINK, "hidden"),
        ("Description", description, "hidden"),
        ("Manufacturer", "YAGEO", "hidden"),
        ("Capacitor Series", "CC", "hidden"),
        ("Automotive Grade", "No", "hidden"),
        ("Technology", "MLCC", "hidden"),
        ("Capacitor Class", "Class 2", "hidden"),
        ("Dielectric", "X7R", "hidden"),
        ("Tolerance", tolerance, "hidden"),
        ("MPN", row["MPN"].strip(), "hidden"),
        ("LCSC Part #", row["LCSC Part#"].strip(), "hidden"),
        ("Capacitance", capacitance, "hidden"),
        ("Package", package, "hidden"),
        ("Rated Voltage", voltage, "hidden"),
        ("Operating Temperature", OPERATING_TEMPERATURE, "hidden"),
        ("Packaging", "Tape & Reel (TR)", "hidden"),
        ("MSL", "1", "hidden"),
        ("RoHS", "Yes", "hidden"),
        ("Halogen Free", "Yes", "hidden"),
        ("ki_keywords", "cap capacitor", "hidden"),
        ("ki_fp_filters", "C_*", "hidden"),
    ]
    block = f'\t(symbol "{quote(name)}"\r\n\t\t(extends "Capacitor_Template")\r\n'
    block += "".join(property_block(prop, value, style) for prop, value, style in properties)
    block += "\t\t(embedded_fonts no)\r\n\t)\r\n"
    return name, block


def read_sources(paths: list[Path], log) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in paths:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            fields = set(reader.fieldnames or [])
            missing = REQUIRED_SOURCE_COLUMNS - fields
            if missing:
                raise ValueError(f"{path.name} is missing columns: {sorted(missing)}")
            file_rows = []
            for row in reader:
                normalized = {column: (row.get(column) or "").strip() for column in fields}
                file_rows.append(normalized)
            rows.extend(file_rows)
            log(f"SOURCE {path.name} rows={len(file_rows)} bytes={path.stat().st_size} sha256={sha256(path)}")
    return rows


def deduplicate_parts(rows: list[dict[str, str]], log) -> list[dict[str, str]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        part = row["LCSC Part#"]
        if not part:
            raise ValueError("Source row has a blank LCSC Part#")
        grouped[part].append(row)
    unique: list[dict[str, str]] = []
    for part in sorted(grouped, key=lambda value: int(value[1:])):
        variants = grouped[part]
        chosen = sorted(variants, key=lambda row: (-availability(row), row["MPN"]))[0]
        unique.append(chosen)
        for discarded in variants:
            if discarded is not chosen:
                log(
                    f"DEDUP_DROP lcsc={part} mpn={discarded['MPN']} availability={discarded['Availability']} "
                    f"kept_availability={chosen['Availability']}"
                )
    return unique


def eligible(row: dict[str, str]) -> bool:
    try:
        return (
            row["Manufacturer"] == "YAGEO"
            and row["MPN"].startswith("CC")
            and row["Temperature Coefficient"] == "X7R"
            and row["Package"] in ALLOWED_PACKAGES
            and row["Packaging"] == "Tape & Reel (TR)"
            and Decimal("0") < parse_voltage(row["Voltage Rating"]) <= Decimal("250")
            and availability(row) >= Decimal("1000")
            and is_e6(parse_capacitance(row["Capacitance"]))
        )
    except (ValueError, ArithmeticError):
        return False


def select_preferred(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    grouped: dict[tuple[str, Decimal], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[(row["Package"], parse_capacitance(row["Capacitance"]))].append(row)
    selected = [sorted(group, key=selected_sort_key)[0] for group in grouped.values()]
    return sorted(selected, key=lambda row: (row["Package"], parse_capacitance(row["Capacitance"])))


def write_processed_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=PROCESSED_COLUMNS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in PROCESSED_COLUMNS})


def run_cli_validation(cli: Path, library: Path, symbols: list[str], output_root: Path, log) -> None:
    for index, symbol in enumerate(symbols):
        safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", symbol)
        output_dir = output_root / f"svg_{index}_{safe_name}"
        output_dir.mkdir(parents=True)
        command = [
            str(cli),
            "sym",
            "export",
            "svg",
            "--output",
            str(output_dir),
            "--symbol",
            symbol,
            str(library),
        ]
        result = subprocess.run(command, text=True, capture_output=True, timeout=120)
        log(f"CLI command: {subprocess.list2cmdline(command)}")
        log(f"CLI exit={result.returncode}")
        if result.stdout.strip():
            log(f"CLI stdout: {result.stdout.strip()}")
        if result.stderr.strip():
            log(f"CLI stderr: {result.stderr.strip()}")
        exports = list(output_dir.glob("*.svg"))
        if result.returncode != 0 or not exports or any(path.stat().st_size == 0 for path in exports):
            raise RuntimeError(f"KiCad CLI validation failed for {symbol!r}")


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    symbol_path = root / "PL Capacitor MLCC.kicad_sym"
    bak_path = root / "PL Capacitor MLCC.bak"
    old_pdf = root / "Yageo_Capacitor.pdf"
    resistor_pdf = root / "Yageo_Resistor_RC_Series.pdf"
    new_pdf = root / "Datasheets" / "Yageo_X7R_General_Purpose_High_Capacitance_MLCC.pdf"
    source_dir = root / "Data" / "LCSC" / "Source"
    processed_dir = root / "Data" / "LCSC" / "Processed"
    excluded_dir = root / "Data" / "Excluded" / "Resistor"
    merged_output = processed_dir / "LCSCSearchDownload_Yageo_CC_X7R_merged.csv"
    filtered_output = processed_dir / "LCSCSearchDownload_Yageo_CC_X7R_E6_filtered.csv"
    footprint_root = Path(r"C:\KiCad\9.0\footprints\PL Capacitor MLCC\PL Capacitor MLCC.pretty")
    cli = Path(r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe")

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    logs_dir = root / "Logs"
    backups_root = root / "Backups"
    logs_dir.mkdir(exist_ok=True)
    log_path = logs_dir / f"PL_Capacitor_MLCC_update_{run_id}.log"
    log_stream = log_path.open("w", encoding="utf-8", newline="\n")

    def log(message: str) -> None:
        timestamp = datetime.now().isoformat(timespec="seconds")
        log_stream.write(f"[{timestamp}] {message}\n")
        log_stream.flush()
        os.fsync(log_stream.fileno())

    mutation_started = False
    backup_dir: Path | None = None
    library_backup: Path | None = None
    pdf_backup: Path | None = None
    moved_files: list[tuple[Path, Path]] = []
    created_outputs: list[Path] = []
    original_library_hash = ""
    original_pdf_hash = ""
    original_bak_hash = ""
    footprint_hashes: dict[Path, str] = {}

    try:
        log("BEGIN Yageo CC X7R derived-symbol update")
        capacitor_sources = [root / name for name in CAPACITOR_SOURCE_NAMES]
        resistor_sources = [root / name for name in RESISTOR_SOURCE_NAMES]
        required_files = [symbol_path, bak_path, old_pdf, resistor_pdf, cli, *capacitor_sources, *resistor_sources]
        for required in required_files:
            if not required.is_file():
                raise FileNotFoundError(required)
        for forbidden in (new_pdf, merged_output, filtered_output):
            if forbidden.exists():
                raise FileExistsError(f"One-shot target already exists; refusing to rerun: {forbidden}")
        root_csv_names = {path.name for path in root.glob("*.csv")}
        expected_csv_names = set(CAPACITOR_SOURCE_NAMES) | set(RESISTOR_SOURCE_NAMES)
        if root_csv_names != expected_csv_names:
            raise ValueError(
                f"Unexpected root CSV set; missing={sorted(expected_csv_names-root_csv_names)} "
                f"extra={sorted(root_csv_names-expected_csv_names)}"
            )
        for package in ALLOWED_PACKAGES:
            footprint = footprint_root / f"C{package}.kicad_mod"
            if not footprint.is_file():
                raise FileNotFoundError(footprint)
            footprint_hashes[footprint] = sha256(footprint)
            log(f"FOOTPRINT {footprint} bytes={footprint.stat().st_size} sha256={footprint_hashes[footprint]}")

        original_bytes = symbol_path.read_bytes()
        if original_bytes.startswith(b"\xef\xbb\xbf"):
            raise ValueError("Library unexpectedly has a UTF-8 BOM")
        if b"\n" in original_bytes.replace(b"\r\n", b""):
            raise ValueError("Library contains non-CRLF newlines")
        original_text = original_bytes.decode("utf-8")
        original_library_hash = sha256(symbol_path)
        original_pdf_hash = sha256(old_pdf)
        original_bak_hash = sha256(bak_path)
        log(f"INPUT library={symbol_path} bytes={symbol_path.stat().st_size} sha256={original_library_hash}")
        log(f"INPUT bak={bak_path} bytes={bak_path.stat().st_size} sha256={original_bak_hash}")
        log(f"INPUT datasheet={old_pdf} bytes={old_pdf.stat().st_size} sha256={original_pdf_hash}")
        log(f"UPDATER {Path(__file__)} sha256={sha256(Path(__file__))}")

        existing_symbols = parse_top_level_symbols(original_text)
        if len(existing_symbols) != EXPECTED_EXISTING_SYMBOLS:
            raise ValueError(
                f"Expected {EXPECTED_EXISTING_SYMBOLS} existing symbols, found {len(existing_symbols)}"
            )
        existing_names = {str(symbol["name"]) for symbol in existing_symbols}
        if len(existing_names) != len(existing_symbols):
            raise ValueError("Existing library contains duplicate symbol names")
        if not {"Capacitor_Template", "Capacitor_Feed_Through_Template"}.issubset(existing_names):
            raise ValueError("Required capacitor templates are missing")

        existing_keys: dict[tuple[str, Decimal], list[str]] = defaultdict(list)
        for symbol in existing_symbols:
            if symbol["extends"] != "Capacitor_Template":
                continue
            properties = symbol["properties"]
            assert isinstance(properties, dict)
            footprint_match = re.fullmatch(
                r"PL Capacitor MLCC:C(0402|0603|0805|1206|1210)",
                str(properties.get("Footprint", "")),
            )
            if not footprint_match:
                raise ValueError(f"Ordinary capacitor has unexpected footprint: {symbol['name']}")
            capacitance = parse_capacitance(str(properties.get("Value", "")))
            existing_keys[(footprint_match.group(1), capacitance)].append(str(symbol["name"]))
        if len(existing_keys) != EXPECTED_EXISTING_KEYS:
            raise ValueError(f"Expected {EXPECTED_EXISTING_KEYS} existing capacitor keys, found {len(existing_keys)}")
        duplicate_existing = {key: names for key, names in existing_keys.items() if len(names) > 1}
        if duplicate_existing:
            raise ValueError(f"Existing ordinary capacitors contain duplicate keys: {duplicate_existing}")

        raw_rows = read_sources(capacitor_sources, log)
        if len(raw_rows) != EXPECTED_RAW_ROWS:
            raise ValueError(f"Expected {EXPECTED_RAW_ROWS} raw rows, found {len(raw_rows)}")
        unique_rows = deduplicate_parts(raw_rows, log)
        if len(unique_rows) != EXPECTED_UNIQUE_PARTS:
            raise ValueError(f"Expected {EXPECTED_UNIQUE_PARTS} unique parts, found {len(unique_rows)}")
        if len({row["MPN"] for row in unique_rows}) != EXPECTED_UNIQUE_PARTS:
            raise ValueError("Unique LCSC parts do not map one-to-one to MPNs")

        eligible_rows = [row for row in unique_rows if eligible(row)]
        if len(eligible_rows) != EXPECTED_ELIGIBLE_ROWS:
            raise ValueError(f"Expected {EXPECTED_ELIGIBLE_ROWS} eligible rows, found {len(eligible_rows)}")
        selected_rows = select_preferred(eligible_rows)
        if len(selected_rows) != EXPECTED_SELECTED:
            raise ValueError(f"Expected {EXPECTED_SELECTED} selected rows, found {len(selected_rows)}")
        selected_keys = [(row["Package"], parse_capacitance(row["Capacitance"])) for row in selected_rows]
        if len(set(selected_keys)) != len(selected_keys):
            raise ValueError("Preferred selection contains duplicate capacitance/package keys")
        for row in selected_rows:
            log(
                f"SELECT name={symbol_name(row)} mpn={row['MPN']} lcsc={row['LCSC Part#']} "
                f"capacitance={format_capacitance(parse_capacitance(row['Capacitance']))} "
                f"package={row['Package']} voltage={format_voltage(parse_voltage(row['Voltage Rating']))} "
                f"tolerance={format_tolerance(parse_tolerance(row['Tolerance']))} availability={row['Availability']}"
            )

        skipped = [
            row for row in selected_rows
            if (row["Package"], parse_capacitance(row["Capacitance"])) in existing_keys
        ]
        additions = [
            row for row in selected_rows
            if (row["Package"], parse_capacitance(row["Capacitance"])) not in existing_keys
        ]
        if len(skipped) != EXPECTED_SKIPS or len(additions) != EXPECTED_ADDITIONS:
            raise ValueError(
                f"Expected {EXPECTED_SKIPS} skips/{EXPECTED_ADDITIONS} additions, "
                f"found {len(skipped)} skips/{len(additions)} additions"
            )
        addition_names = [symbol_name(row) for row in additions]
        if len(set(addition_names)) != len(addition_names):
            raise ValueError("Generated additions contain duplicate symbol names")
        collisions = sorted(set(addition_names) & existing_names)
        if collisions:
            raise ValueError(f"Unexplained symbol-name collisions: {collisions}")

        log(
            f"PREFLIGHT counts existing={len(existing_symbols)} existing_keys={len(existing_keys)} "
            f"raw={len(raw_rows)} unique={len(unique_rows)} eligible={len(eligible_rows)} "
            f"selected={len(selected_rows)} skips={len(skipped)} additions={len(additions)}"
        )
        log(f"SELECTED_BY_PACKAGE {dict(sorted(Counter(row['Package'] for row in selected_rows).items()))}")
        log(f"ADDITIONS_BY_PACKAGE {dict(sorted(Counter(row['Package'] for row in additions).items()))}")
        for row in skipped:
            key = (row["Package"], parse_capacitance(row["Capacitance"]))
            log(
                f"SKIP name={symbol_name(row)} mpn={row['MPN']} lcsc={row['LCSC Part#']} "
                f"existing={','.join(existing_keys[key])} reason=same_capacitance_and_footprint"
            )

        generated: list[tuple[str, str, dict[str, str]]] = []
        for row in sorted(additions, key=symbol_name):
            name, block = build_symbol(row)
            generated.append((name, block, row))
            log(
                f"ADD name={name} mpn={row['MPN']} lcsc={row['LCSC Part#']} "
                f"capacitance={format_capacitance(parse_capacitance(row['Capacitance']))} "
                f"package={row['Package']} voltage={format_voltage(parse_voltage(row['Voltage Rating']))} "
                f"tolerance={format_tolerance(parse_tolerance(row['Tolerance']))}"
            )

        insertion = root_close_offset(original_text)
        candidate_text = (
            original_text[:insertion]
            + "".join(block for _, block, _ in generated)
            + original_text[insertion:]
        )
        if not parentheses_balanced(candidate_text):
            raise ValueError("Candidate library has unbalanced S-expressions")
        candidate_symbols = parse_top_level_symbols(candidate_text)
        if len(candidate_symbols) != EXPECTED_FINAL_SYMBOLS:
            raise ValueError(f"Expected {EXPECTED_FINAL_SYMBOLS} final symbols, found {len(candidate_symbols)}")
        final_names = [str(symbol["name"]) for symbol in candidate_symbols]
        if len(set(final_names)) != len(final_names):
            raise ValueError("Candidate library contains duplicate symbol names")
        for before, after in zip(existing_symbols, candidate_symbols[: len(existing_symbols)]):
            if before["name"] != after["name"] or before["block"] != after["block"]:
                raise ValueError(f"Existing symbol block changed: {before['name']}")
        if candidate_text[-3:] != original_text[-3:]:
            raise ValueError("Root closing bytes changed")
        for symbol in candidate_symbols:
            extends = symbol["extends"]
            if extends and extends not in final_names:
                raise ValueError(f"Invalid extends reference: {symbol['name']} -> {extends}")

        generated_rows = {name: row for name, _, row in generated}
        for symbol in candidate_symbols[len(existing_symbols):]:
            name = str(symbol["name"])
            if symbol["extends"] != "Capacitor_Template":
                raise ValueError(f"New symbol does not extend Capacitor_Template: {name}")
            properties = symbol["properties"]
            assert isinstance(properties, dict)
            missing = NEW_REQUIRED_PROPERTIES - set(properties)
            unexpected_height = "Height" in properties
            if missing:
                raise ValueError(f"New symbol {name} is missing properties: {sorted(missing)}")
            if unexpected_height:
                raise ValueError(f"New symbol {name} unexpectedly contains Height")
            row = generated_rows[name]
            capacitance = format_capacitance(parse_capacitance(row["Capacitance"]))
            tolerance = format_tolerance(parse_tolerance(row["Tolerance"]))
            voltage = format_voltage(parse_voltage(row["Voltage Rating"]))
            expected = {
                "Reference": "C",
                "Value": capacitance,
                "Footprint": f"PL Capacitor MLCC:C{row['Package']}",
                "Datasheet": DATASHEET_LINK,
                "Manufacturer": "YAGEO",
                "Capacitor Series": "CC",
                "Automotive Grade": "No",
                "Technology": "MLCC",
                "Capacitor Class": "Class 2",
                "Dielectric": "X7R",
                "Tolerance": tolerance,
                "MPN": row["MPN"],
                "LCSC Part #": row["LCSC Part#"],
                "Capacitance": capacitance,
                "Package": row["Package"],
                "Rated Voltage": voltage,
                "Operating Temperature": OPERATING_TEMPERATURE,
                "Packaging": "Tape & Reel (TR)",
                "MSL": "1",
                "RoHS": "Yes",
                "Halogen Free": "Yes",
                "ki_keywords": "cap capacitor",
                "ki_fp_filters": "C_*",
            }
            for property_name, expected_value in expected.items():
                if properties.get(property_name) != expected_value:
                    raise ValueError(
                        f"New symbol {name}: incorrect {property_name}: "
                        f"{properties.get(property_name)!r} != {expected_value!r}"
                    )

        with tempfile.TemporaryDirectory(prefix="pl_capacitor_stage_") as temporary:
            stage_dir = Path(temporary)
            candidate_path = stage_dir / symbol_path.name
            merged_stage = stage_dir / merged_output.name
            filtered_stage = stage_dir / filtered_output.name
            candidate_path.write_bytes(candidate_text.encode("utf-8"))
            write_processed_csv(merged_stage, unique_rows)
            write_processed_csv(filtered_stage, selected_rows)
            if "Datasheet" in PROCESSED_COLUMNS or "Pricing($)" in PROCESSED_COLUMNS:
                raise ValueError("Processed CSV schema contains forbidden supplier columns")
            with merged_stage.open("r", encoding="utf-8", newline="") as stream:
                if sum(1 for _ in csv.DictReader(stream)) != EXPECTED_UNIQUE_PARTS:
                    raise ValueError("Staged merged CSV row count mismatch")
            with filtered_stage.open("r", encoding="utf-8", newline="") as stream:
                if sum(1 for _ in csv.DictReader(stream)) != EXPECTED_SELECTED:
                    raise ValueError("Staged filtered CSV row count mismatch")
            candidate_hash = sha256(candidate_path)
            log(f"STAGED library={candidate_path} bytes={candidate_path.stat().st_size} sha256={candidate_hash}")
            log(f"STAGED merged={merged_stage} rows={EXPECTED_UNIQUE_PARTS} sha256={sha256(merged_stage)}")
            log(f"STAGED filtered={filtered_stage} rows={EXPECTED_SELECTED} sha256={sha256(filtered_stage)}")

            representatives = ["100nF_0402"]
            for package in ALLOWED_PACKAGES:
                representatives.append(next(name for name, _, row in generated if row["Package"] == package))
            run_cli_validation(cli, candidate_path, representatives, stage_dir / "preinstall_cli", log)
            log(f"PREINSTALL CLI validation passed: {', '.join(representatives)}")

            backup_dir = backups_root / run_id
            backup_dir.mkdir(parents=True, exist_ok=False)
            library_backup = backup_dir / symbol_path.name
            pdf_backup = backup_dir / old_pdf.name
            shutil.copy2(symbol_path, library_backup)
            shutil.copy2(old_pdf, pdf_backup)
            if sha256(library_backup) != original_library_hash or sha256(pdf_backup) != original_pdf_hash:
                raise RuntimeError("Backup hash verification failed")
            log(f"BACKUP verified directory={backup_dir}")

            for directory in (new_pdf.parent, source_dir, processed_dir, excluded_dir):
                directory.mkdir(parents=True, exist_ok=True)
            for source in capacitor_sources:
                destination = source_dir / source.name
                if destination.exists():
                    raise FileExistsError(destination)
            for source in [*resistor_sources, resistor_pdf]:
                destination = excluded_dir / source.name
                if destination.exists():
                    raise FileExistsError(destination)

            mutation_started = True
            old_pdf.replace(new_pdf)
            log(f"MOVE datasheet {old_pdf} -> {new_pdf} sha256={sha256(new_pdf)}")
            if sha256(new_pdf) != original_pdf_hash:
                raise RuntimeError("Renamed datasheet hash mismatch")
            for source in capacitor_sources:
                destination = source_dir / source.name
                source.replace(destination)
                moved_files.append((source, destination))
                log(f"MOVE capacitor_source {source} -> {destination}")
            for source in resistor_sources:
                destination = excluded_dir / source.name
                source.replace(destination)
                moved_files.append((source, destination))
                log(f"MOVE excluded_resistor_source {source} -> {destination}")
            resistor_pdf_destination = excluded_dir / resistor_pdf.name
            resistor_pdf.replace(resistor_pdf_destination)
            moved_files.append((resistor_pdf, resistor_pdf_destination))
            log(f"MOVE excluded_resistor_pdf {resistor_pdf} -> {resistor_pdf_destination}")

            os.replace(merged_stage, merged_output)
            created_outputs.append(merged_output)
            log(f"INSTALL processed_csv {merged_output} sha256={sha256(merged_output)}")
            os.replace(filtered_stage, filtered_output)
            created_outputs.append(filtered_output)
            log(f"INSTALL processed_csv {filtered_output} sha256={sha256(filtered_output)}")
            os.replace(candidate_path, symbol_path)
            log(f"INSTALL atomic_library_replace {symbol_path}")

            if sha256(symbol_path) != candidate_hash:
                raise RuntimeError("Installed library hash differs from validated candidate")
            installed_text = symbol_path.read_bytes().decode("utf-8")
            installed_symbols = parse_top_level_symbols(installed_text)
            if len(installed_symbols) != EXPECTED_FINAL_SYMBOLS:
                raise RuntimeError("Post-install symbol count mismatch")
            for before, after in zip(existing_symbols, installed_symbols[:len(existing_symbols)]):
                if before["block"] != after["block"]:
                    raise RuntimeError(f"Post-install original block mismatch: {before['name']}")
            if not new_pdf.is_file() or old_pdf.exists() or sha256(new_pdf) != original_pdf_hash:
                raise RuntimeError("Post-install datasheet verification failed")
            if sha256(bak_path) != original_bak_hash:
                raise RuntimeError("Existing .bak file changed")
            for footprint, original_hash in footprint_hashes.items():
                if sha256(footprint) != original_hash:
                    raise RuntimeError(f"Footprint changed: {footprint}")
            run_cli_validation(cli, symbol_path, representatives, stage_dir / "postinstall_cli", log)
            root_files = {path.name for path in root.iterdir() if path.is_file()}
            expected_root_files = {symbol_path.name, bak_path.name}
            if root_files != expected_root_files:
                raise RuntimeError(
                    f"Unexpected final root files: expected={sorted(expected_root_files)} actual={sorted(root_files)}"
                )
            log(f"FINAL library={symbol_path} bytes={symbol_path.stat().st_size} sha256={sha256(symbol_path)}")
            log(f"FINAL datasheet={new_pdf} bytes={new_pdf.stat().st_size} sha256={sha256(new_pdf)}")
            log(
                f"FINAL counts existing={EXPECTED_EXISTING_SYMBOLS} additions={EXPECTED_ADDITIONS} "
                f"skips={EXPECTED_SKIPS} symbols={len(installed_symbols)}"
            )
            log("SUCCESS update completed; rollback not required")
        return 0
    except Exception as error:
        log(f"ERROR {type(error).__name__}: {error}")
        if mutation_started:
            log("ROLLBACK started")
            rollback_errors: list[str] = []
            try:
                if library_backup and library_backup.is_file():
                    shutil.copy2(library_backup, symbol_path)
            except Exception as rollback_error:
                rollback_errors.append(f"library restore: {rollback_error}")
            try:
                if new_pdf.exists():
                    new_pdf.unlink()
                if pdf_backup and pdf_backup.is_file():
                    shutil.copy2(pdf_backup, old_pdf)
            except Exception as rollback_error:
                rollback_errors.append(f"datasheet restore: {rollback_error}")
            for source, destination in reversed(moved_files):
                try:
                    if destination.exists() and not source.exists():
                        destination.replace(source)
                except Exception as rollback_error:
                    rollback_errors.append(f"move restore {destination}: {rollback_error}")
            for output in reversed(created_outputs):
                try:
                    if output.exists():
                        output.unlink()
                except Exception as rollback_error:
                    rollback_errors.append(f"output removal {output}: {rollback_error}")
            if rollback_errors:
                log(f"ROLLBACK FAILED: {'; '.join(rollback_errors)}")
            else:
                library_ok = symbol_path.is_file() and sha256(symbol_path) == original_library_hash
                pdf_ok = old_pdf.is_file() and sha256(old_pdf) == original_pdf_hash and not new_pdf.exists()
                bak_ok = bak_path.is_file() and sha256(bak_path) == original_bak_hash
                log(f"ROLLBACK completed library_ok={library_ok} datasheet_ok={pdf_ok} bak_ok={bak_ok}")
        return 1
    finally:
        log_stream.close()
        print(log_path)


if __name__ == "__main__":
    sys.exit(main())
