from __future__ import annotations

import csv
import hashlib
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path


EXPECTED_EXISTING_SYMBOLS = 102
EXPECTED_CSV_ROWS = 683
EXPECTED_SKIPS = 24
EXPECTED_ADDITIONS = 659
EXPECTED_FINAL_SYMBOLS = 761

PACKAGE_DATA = {
    "0402": {
        "power": "62.5mW",
        "rated_voltage": "50V",
        "overload_voltage": "100V",
        "height": "0.40mm max",
    },
    "0603": {
        "power": "100mW",
        "rated_voltage": "75V",
        "overload_voltage": "150V",
        "height": "0.55mm max",
    },
    "0805": {
        "power": "125mW",
        "rated_voltage": "150V",
        "overload_voltage": "300V",
        "height": "0.60mm max",
    },
}

REQUIRED_COLUMNS = {
    "LCSC Part#",
    "MPN",
    "Manufacturer",
    "Availability",
    "Package",
    "Packaging",
    "Type",
    "Resistance",
    "Tolerance",
    "Voltage Rating",
    "Power(Watts)",
    "Temperature Coefficient",
}

NEW_REQUIRED_PROPERTIES = {
    "Reference",
    "Value",
    "Footprint",
    "Datasheet",
    "Description",
    "Manufacturer",
    "Resistor Series",
    "Automotive Grade",
    "Technology",
    "Tolerance",
    "MPN",
    "LCSC Part #",
    "Resistance",
    "Package",
    "Rated Power",
    "Rated Voltage",
    "Maximum Overload Voltage",
    "Operating Temperature",
    "Temperature Coefficient",
    "Height",
    "Packaging",
    "MSL",
    "RoHS",
    "Halogen Free",
    "ki_keywords",
    "ki_fp_filters",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def parse_resistance(value: str) -> tuple[Decimal, str, str]:
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*([kM]?)Ω\s*", value)
    if not match:
        raise ValueError(f"Unsupported resistance value: {value!r}")
    number_text, unit = match.groups()
    multiplier = {"": Decimal("1"), "k": Decimal("1000"), "M": Decimal("1000000")}[unit]
    return Decimal(number_text) * multiplier, number_text, unit


def parse_existing_resistance(value: str) -> Decimal | None:
    match = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([mMkK]?)", value or "")
    if not match:
        return None
    number_text, unit = match.groups()
    multiplier = {
        "": Decimal("1"),
        "m": Decimal("0.001"),
        "k": Decimal("1000"),
        "K": Decimal("1000"),
        "M": Decimal("1000000"),
    }[unit]
    return Decimal(number_text) * multiplier


def canonical_number(number_text: str) -> str:
    value = Decimal(number_text)
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def symbol_name(row: dict[str, str]) -> str:
    _, number_text, unit = parse_resistance(row["Resistance"])
    name_unit = {"": "R", "k": "K", "M": "M"}[unit]
    return f"{canonical_number(number_text)}{name_unit}_{row['Package']}"


def is_e96(ohms: Decimal) -> bool:
    if ohms <= 0:
        return False
    e96 = {round(100 * math.pow(10, index / 96.0)) for index in range(96)}
    decade = math.floor(math.log10(float(ohms)))
    nominal = round(float(ohms) / math.pow(10, decade) * 100)
    if nominal >= 1000:
        nominal = 100
    return nominal in e96


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
        properties = dict(
            re.findall(r'^\t\t\(property "([^"]+)" "((?:\\.|[^"])*)"', block, re.MULTILINE)
        )
        symbols.append(
            {
                "name": name_match.group(1),
                "extends": extends_match.group(1) if extends_match else None,
                "properties": properties,
                "block": block,
            }
        )
    return symbols


def package_from_existing(name: str, footprint: str) -> str | None:
    match = re.search(r":R(0402|0603|0805)$", footprint or "")
    if not match:
        match = re.search(r"_(0402|0603|0805)(?:_|$)", name)
    return match.group(1) if match else None


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
    value = quote(value)
    if style == "reference":
        return (
            f'\t\t(property "{name}" "{value}"\r\n'
            "\t\t\t(at -2.794 3.81 0)\r\n"
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
            f'\t\t(property "{name}" "{value}"\r\n'
            "\t\t\t(at -2.794 2.032 0)\r\n"
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
    if style == "footprint":
        at = "-1.778 0 90"
    else:
        at = "0 0 0"
    return (
        f'\t\t(property "{name}" "{value}"\r\n'
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


def build_symbol(row: dict[str, str], datasheet_link: str) -> tuple[str, str]:
    name = symbol_name(row)
    package = row["Package"]
    package_data = PACKAGE_DATA[package]
    resistance = row["Resistance"].strip()
    description = (
        f"Yageo RC series thick-film SMD resistor, {resistance}, ±1%, "
        f"{package_data['power']}, {package_data['rated_voltage']}, {package}, ±100ppm/℃"
    )
    properties = [
        ("Reference", "R", "reference"),
        ("Value", resistance, "value"),
        ("Footprint", f"PL Resistor SMD:R{package}", "footprint"),
        ("Datasheet", datasheet_link, "hidden"),
        ("Description", description, "hidden"),
        ("Manufacturer", "YAGEO", "hidden"),
        ("Resistor Series", "RC", "hidden"),
        ("Automotive Grade", "No", "hidden"),
        ("Technology", "Thick Film", "hidden"),
        ("Tolerance", "±1%", "hidden"),
        ("MPN", row["MPN"].strip(), "hidden"),
        ("LCSC Part #", row["LCSC Part#"].strip(), "hidden"),
        ("Resistance", resistance, "hidden"),
        ("Package", package, "hidden"),
        ("Rated Power", package_data["power"], "hidden"),
        ("Rated Voltage", package_data["rated_voltage"], "hidden"),
        ("Maximum Overload Voltage", package_data["overload_voltage"], "hidden"),
        ("Operating Temperature", "-55℃~+155℃", "hidden"),
        ("Temperature Coefficient", "±100ppm/℃", "hidden"),
        ("Height", package_data["height"], "hidden"),
        ("Packaging", "Tape & Reel (TR)", "hidden"),
        ("MSL", "1", "hidden"),
        ("RoHS", "Yes", "hidden"),
        ("Halogen Free", "Yes", "hidden"),
        ("ki_keywords", "R res resistor", "hidden"),
        ("ki_fp_filters", "R_*", "hidden"),
    ]
    block = f'\t(symbol "{quote(name)}"\r\n\t\t(extends "Resistor_Template")\r\n'
    block += "".join(property_block(prop_name, prop_value, style) for prop_name, prop_value, style in properties)
    block += "\t\t(embedded_fonts no)\r\n\t)\r\n"
    return name, block


def run_cli_validation(cli: Path, candidate: Path, symbols: list[str], stage_dir: Path, log) -> None:
    for index, symbol in enumerate(symbols):
        output_dir = stage_dir / f"svg_{index}_{symbol.replace('.', '_')}"
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
            str(candidate),
        ]
        result = subprocess.run(command, text=True, capture_output=True, timeout=120)
        log(f"CLI command: {' '.join(command)}")
        log(f"CLI exit: {result.returncode}")
        if result.stdout.strip():
            log(f"CLI stdout: {result.stdout.strip()}")
        if result.stderr.strip():
            log(f"CLI stderr: {result.stderr.strip()}")
        svgs = list(output_dir.glob("*.svg"))
        if result.returncode != 0 or not svgs or any(svg.stat().st_size == 0 for svg in svgs):
            raise RuntimeError(f"KiCad CLI validation failed for {symbol}")


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    symbol_path = root / "PL Resistor SMD.kicad_sym"
    csv_path = root / "Data" / "LCSC" / "Processed" / "LCSCSearchDownload_RC_E96_filtered.csv"
    datasheet_dir = root / "Datasheets"
    old_pdf = datasheet_dir / "Yageo_Resistor_RC_Series.pdf"
    new_pdf = datasheet_dir / "Yageo_RC_L_Series_Chip_Resistors.pdf"
    datasheet_link = "${PL_SYMBOL_DIR}/PL Resistor SMD/Datasheets/Yageo_RC_L_Series_Chip_Resistors.pdf"
    footprint_root = Path(r"C:\KiCad\9.0\footprints\PL Resistor SMD\PL Resistor SMD.pretty")
    cli = Path(r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe")

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    logs_dir = root / "Logs"
    backups_root = root / "Backups"
    logs_dir.mkdir(exist_ok=True)
    log_path = logs_dir / f"PL_Resistor_SMD_update_{run_id}.log"
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
    original_library_hash = ""
    original_pdf_hash = ""

    try:
        log("BEGIN Yageo RC derived-symbol update")
        for required in (symbol_path, csv_path, old_pdf, cli):
            if not required.is_file():
                raise FileNotFoundError(required)
        if new_pdf.exists():
            raise FileExistsError(f"Renamed datasheet target already exists: {new_pdf}")
        for package in PACKAGE_DATA:
            footprint = footprint_root / f"R{package}.kicad_mod"
            if not footprint.is_file():
                raise FileNotFoundError(footprint)
            log(f"Footprint verified: {footprint} sha256={sha256(footprint)}")

        original_bytes = symbol_path.read_bytes()
        if original_bytes.startswith(b"\xef\xbb\xbf"):
            raise ValueError("Library unexpectedly has a UTF-8 BOM")
        original_text = original_bytes.decode("utf-8")
        if "\n" in original_text.replace("\r\n", ""):
            raise ValueError("Library contains non-CRLF newlines")
        original_library_hash = sha256(symbol_path)
        original_pdf_hash = sha256(old_pdf)
        log(f"Input library: {symbol_path} bytes={symbol_path.stat().st_size} sha256={original_library_hash}")
        log(f"Input CSV: {csv_path} bytes={csv_path.stat().st_size} sha256={sha256(csv_path)}")
        log(f"Input PDF: {old_pdf} bytes={old_pdf.stat().st_size} sha256={original_pdf_hash}")

        existing_symbols = parse_top_level_symbols(original_text)
        if len(existing_symbols) != EXPECTED_EXISTING_SYMBOLS:
            raise ValueError(
                f"Expected {EXPECTED_EXISTING_SYMBOLS} existing symbols, found {len(existing_symbols)}"
            )
        existing_names = {str(symbol["name"]) for symbol in existing_symbols}
        if len(existing_names) != len(existing_symbols):
            raise ValueError("Existing library contains duplicate symbol names")
        if "Resistor_Template" not in existing_names:
            raise ValueError("Resistor_Template is missing")

        existing_keys: dict[tuple[str, Decimal], list[str]] = {}
        for symbol in existing_symbols:
            name = str(symbol["name"])
            properties = symbol["properties"]
            assert isinstance(properties, dict)
            package = package_from_existing(name, str(properties.get("Footprint", "")))
            resistance = parse_existing_resistance(str(properties.get("Value", "")))
            if package and resistance is not None:
                existing_keys.setdefault((package, resistance), []).append(name)

        with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None or not REQUIRED_COLUMNS.issubset(reader.fieldnames):
                missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
                raise ValueError(f"CSV is missing required columns: {sorted(missing)}")
            rows = list(reader)
        if len(rows) != EXPECTED_CSV_ROWS:
            raise ValueError(f"Expected {EXPECTED_CSV_ROWS} CSV rows, found {len(rows)}")

        csv_keys: set[tuple[str, Decimal]] = set()
        csv_mpns: set[str] = set()
        csv_lcsc: set[str] = set()
        candidates: list[tuple[tuple[str, Decimal], str, dict[str, str]]] = []
        for row_number, row in enumerate(rows, start=2):
            package = row["Package"].strip()
            if package not in PACKAGE_DATA:
                raise ValueError(f"Row {row_number}: unsupported package {package!r}")
            package_data = PACKAGE_DATA[package]
            checks = {
                "Manufacturer": row["Manufacturer"].strip() == "YAGEO",
                "MPN": row["MPN"].strip().startswith("RC"),
                "Tolerance": row["Tolerance"].strip() == "±1%",
                "Temperature Coefficient": row["Temperature Coefficient"].strip() == "±100ppm/℃",
                "Power": row["Power(Watts)"].strip() == package_data["power"],
                "Rated Voltage": row["Voltage Rating"].strip() == package_data["rated_voltage"],
                "Packaging": row["Packaging"].strip() == "Tape & Reel (TR)",
                "Technology": row["Type"].strip() == "Thick Film Resistor",
                "Availability": Decimal(row["Availability"].strip()) >= Decimal("1000"),
            }
            failed = [name for name, passed in checks.items() if not passed]
            if failed:
                raise ValueError(f"Row {row_number}: invariant failure: {', '.join(failed)}")
            resistance, _, _ = parse_resistance(row["Resistance"])
            if not is_e96(resistance):
                raise ValueError(f"Row {row_number}: not an E96 value: {row['Resistance']}")
            key = (package, resistance)
            if key in csv_keys:
                raise ValueError(f"Row {row_number}: duplicate CSV package/resistance key {key}")
            csv_keys.add(key)
            if row["MPN"] in csv_mpns:
                raise ValueError(f"Row {row_number}: duplicate MPN {row['MPN']}")
            csv_mpns.add(row["MPN"])
            if row["LCSC Part#"] in csv_lcsc:
                raise ValueError(f"Row {row_number}: duplicate LCSC part {row['LCSC Part#']}")
            csv_lcsc.add(row["LCSC Part#"])
            candidates.append((key, symbol_name(row), row))

        skipped = [candidate for candidate in candidates if candidate[0] in existing_keys]
        additions = [candidate for candidate in candidates if candidate[0] not in existing_keys]
        if len(skipped) != EXPECTED_SKIPS or len(additions) != EXPECTED_ADDITIONS:
            raise ValueError(
                f"Expected {EXPECTED_SKIPS} skips/{EXPECTED_ADDITIONS} additions, "
                f"found {len(skipped)} skips/{len(additions)} additions"
            )
        addition_names = [name for _, name, _ in additions]
        if len(set(addition_names)) != len(addition_names):
            raise ValueError("Generated additions contain duplicate symbol names")
        unexplained_collisions = sorted(set(addition_names) & existing_names)
        if unexplained_collisions:
            raise ValueError(f"Unexplained symbol-name collisions: {unexplained_collisions}")

        log(f"Preflight counts: existing={len(existing_symbols)} csv={len(rows)} skips={len(skipped)} additions={len(additions)}")
        log(f"Skip counts by package: {dict(sorted(Counter(key[0] for key, _, _ in skipped).items()))}")
        log(f"Addition counts by package: {dict(sorted(Counter(key[0] for key, _, _ in additions).items()))}")
        for key, name, row in skipped:
            log(
                f"SKIP name={name} mpn={row['MPN']} lcsc={row['LCSC Part#']} "
                f"resistance={row['Resistance']} package={row['Package']} "
                f"existing={','.join(existing_keys[key])} reason=same_resistance_and_footprint"
            )

        generated: list[tuple[str, str, dict[str, str]]] = []
        for _, _, row in sorted(additions, key=lambda item: item[1]):
            name, block = build_symbol(row, datasheet_link)
            generated.append((name, block, row))
            log(
                f"ADD name={name} mpn={row['MPN']} lcsc={row['LCSC Part#']} "
                f"resistance={row['Resistance']} package={row['Package']}"
            )

        insertion = root_close_offset(original_text)
        candidate_text = original_text[:insertion] + "".join(block for _, block, _ in generated) + original_text[insertion:]
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

        generated_by_name = {name: row for name, _, row in generated}
        for symbol in candidate_symbols[len(existing_symbols) :]:
            name = str(symbol["name"])
            if symbol["extends"] != "Resistor_Template":
                raise ValueError(f"New symbol does not extend Resistor_Template: {name}")
            properties = symbol["properties"]
            assert isinstance(properties, dict)
            missing = NEW_REQUIRED_PROPERTIES - set(properties)
            if missing:
                raise ValueError(f"New symbol {name} is missing properties: {sorted(missing)}")
            row = generated_by_name[name]
            package = row["Package"]
            expected = PACKAGE_DATA[package]
            exact = {
                "Manufacturer": "YAGEO",
                "Resistor Series": "RC",
                "Automotive Grade": "No",
                "Rated Power": expected["power"],
                "Rated Voltage": expected["rated_voltage"],
                "Maximum Overload Voltage": expected["overload_voltage"],
                "Datasheet": datasheet_link,
            }
            for prop_name, prop_value in exact.items():
                if properties.get(prop_name) != prop_value:
                    raise ValueError(f"New symbol {name}: incorrect {prop_name}")

        with tempfile.TemporaryDirectory(prefix="pl_resistor_stage_") as temporary:
            stage_dir = Path(temporary)
            candidate_path = stage_dir / symbol_path.name
            candidate_path.write_text(candidate_text, encoding="utf-8", newline="")
            candidate_hash = sha256(candidate_path)
            log(f"Staged candidate: {candidate_path} bytes={candidate_path.stat().st_size} sha256={candidate_hash}")
            representatives = ["0R_0201"]
            for package in PACKAGE_DATA:
                representatives.append(next(name for name, _, row in generated if row["Package"] == package))
            run_cli_validation(cli, candidate_path, representatives, stage_dir, log)
            log(f"KiCad CLI validation passed for: {', '.join(representatives)}")

            backup_dir = backups_root / run_id
            backup_dir.mkdir(parents=True, exist_ok=False)
            library_backup = backup_dir / symbol_path.name
            pdf_backup = backup_dir / old_pdf.name
            shutil.copy2(symbol_path, library_backup)
            shutil.copy2(old_pdf, pdf_backup)
            if sha256(library_backup) != original_library_hash or sha256(pdf_backup) != original_pdf_hash:
                raise RuntimeError("Backup hash verification failed")
            log(f"Backups verified: {backup_dir}")

            mutation_started = True
            old_pdf.replace(new_pdf)
            log(f"Renamed datasheet: {old_pdf} -> {new_pdf}")
            if sha256(new_pdf) != original_pdf_hash:
                raise RuntimeError("Renamed datasheet hash mismatch")
            os.replace(candidate_path, symbol_path)
            log(f"Atomically replaced symbol library: {symbol_path}")

            final_hash = sha256(symbol_path)
            if final_hash != candidate_hash:
                raise RuntimeError("Installed library hash differs from validated candidate")
            final_text = symbol_path.read_bytes().decode("utf-8")
            final_symbols = parse_top_level_symbols(final_text)
            if len(final_symbols) != EXPECTED_FINAL_SYMBOLS:
                raise RuntimeError("Post-install symbol count verification failed")
            for before, after in zip(existing_symbols, final_symbols[: len(existing_symbols)]):
                if before["block"] != after["block"]:
                    raise RuntimeError(f"Post-install existing block mismatch: {before['name']}")
            if not new_pdf.is_file() or old_pdf.exists():
                raise RuntimeError("Post-install datasheet rename verification failed")
            log(f"FINAL library bytes={symbol_path.stat().st_size} sha256={final_hash} symbols={len(final_symbols)}")
            log(f"FINAL datasheet bytes={new_pdf.stat().st_size} sha256={sha256(new_pdf)}")
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
                rollback_errors.append(f"PDF restore: {rollback_error}")
            if rollback_errors:
                log(f"ROLLBACK FAILED: {'; '.join(rollback_errors)}")
            else:
                library_ok = symbol_path.is_file() and sha256(symbol_path) == original_library_hash
                pdf_ok = old_pdf.is_file() and sha256(old_pdf) == original_pdf_hash and not new_pdf.exists()
                log(f"ROLLBACK completed library_ok={library_ok} pdf_ok={pdf_ok}")
        return 1
    finally:
        log_stream.close()
        print(log_path)


if __name__ == "__main__":
    sys.exit(main())
