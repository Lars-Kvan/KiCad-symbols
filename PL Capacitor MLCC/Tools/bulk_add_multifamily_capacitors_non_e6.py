from __future__ import annotations

import csv
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader

import bulk_add_yageo_cc_x7r_capacitors as common


EXPECTED_LIBRARY_SHA256 = "a7f8e2a43a0c656f1ec26d5d780e5b469a4c7476fbc23e6db34394ad68858ab1"
EXPECTED_EXISTING_SYMBOLS = 130
EXPECTED_EXISTING_KEYS = 127
EXPECTED_SOURCE_FILES = 35
EXPECTED_RAW_ROWS = 3354
EXPECTED_UNIQUE_PARTS = 2567
EXPECTED_ELIGIBLE_ROWS = 2376
EXPECTED_SELECTED = 372
EXPECTED_SKIPS = 121
EXPECTED_ADDITIONS = 251
EXPECTED_FINAL_SYMBOLS = 381

ALLOWED_PACKAGES = ("0402", "0603", "0805", "1206", "1210")
SUPPORTED_DIELECTRICS = {"C0G", "NP0", "C0G;NP0", "X7R"}

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

REQUIRED_SOURCE_COLUMNS = set(PROCESSED_COLUMNS) - {"Operating Temperature"} | {
    "Datasheet",
    "Pricing($)",
}

LOCAL_DATASHEETS = {
    "Capacitor datasheet.pdf": (
        "Yageo_CC_NP0_General_Purpose_16V_to_250V.pdf",
        ("General purpose Class 1, NP0", "16 V TO 250V"),
    ),
    "e147909414eb3b900a42b90481dc8914.pdf": (
        "Yageo_AC_Automotive_NP0_X7R_X7S_6.3V_to_2000V.pdf",
        ("Automotive grade NP0/X7R/X7S", "AEC-Q200"),
    ),
    "datasheet 2.pdf": (
        "Murata_GRM_GJM_GQM_General_MLCC_Catalog.pdf",
        ("Chip Multilayer Ceramic Capacitors for General", "GQM Series"),
    ),
    "Murata GCM.pdf": (
        "Murata_GCM_Automotive_C0G_MLCC_Reference.pdf",
        ("GCM1555C1H330JA16", "C0G"),
    ),
    "Datasheet kemet.pdf": (
        "KEMET_C0G_Commercial_MLCC.pdf",
        ("C0G Dielectric", "Commercial Grade"),
    ),
}

SUPPLEMENTAL_DATASHEETS = {
    "26f1ead7bc608b57806ba5c637185505.pdf": "Murata_GQM2195C2E150JB12_0805_C0G.pdf",
    "874695ec05b64e47712b911bccd14a9c.pdf": "Murata_GQM1875C2E150JB12_0603_C0G.pdf",
    "capacitor datasheet murata.pdf": "Murata_GRM1555C1H102JA01_0402_C0G.pdf",
    "Dataasheet 1.pdf": "KEMET_CBR_HiQ_C0G_RF.pdf",
    "Murata GJM.pdf": "Murata_General_MLCC_Catalog_Alternate.pdf",
    "2aafee59dab54d3907d2a47e632f9b66.pdf": "Vishay_VJ_Commodity_MLCC.pdf",
}

DOWNLOAD_DATASHEETS = {
    "Yageo_CC_High_Voltage_NP0_X7R_500V_to_3kV.pdf": (
        "https://datasheet.lcsc.com/datasheet/pdf/9a86cbae8c34c796174906a7ab23dad0.pdf",
        ("High-Voltage NP0/X7R", "500 V TO 3 KV"),
    ),
    "Yageo_CQ_HiQ_NP0_16V_to_500V.pdf": (
        "https://datasheet.lcsc.com/datasheet/pdf/d9e1f96faa5392c23fe073d37a19d097.pdf",
        ("Hi Q Series", "CQ"),
    ),
    "KEMET_C0G_Automotive_MLCC.pdf": (
        "https://datasheet.lcsc.com/datasheet/pdf/73c030c092cad88867b92e86f262076b.pdf",
        ("AEC", "automotive"),
    ),
    "KYOCERA_AVX_Surface_Mount_Ceramic_Capacitors.pdf": (
        "https://catalogs.kyocera-avx.com/surfacemount.pdf",
        ("Surface Mount Ceramic Capacitor Products", "C0G"),
    ),
}

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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def datasheet_link(filename: str) -> str:
    return f"${{PL_SYMBOL_DIR}}/PL Capacitor MLCC/Datasheets/{filename}"


def series_prefix(mpn: str) -> str:
    match = re.match(r"[A-Za-z]+", mpn)
    return match.group(0) if match else ""


def normalized_dielectric(value: str) -> str:
    return "C0G/NP0" if value == "C0G;NP0" else value


def profile_for(row: dict[str, str]) -> dict[str, str]:
    raw_manufacturer = row["Manufacturer"]
    mpn = row["MPN"]
    prefix = series_prefix(mpn)
    dielectric = normalized_dielectric(row["Temperature Coefficient"])
    voltage = common.parse_voltage(row["Voltage Rating"])
    profile: dict[str, str]

    if raw_manufacturer == "YAGEO":
        if prefix == "CC":
            if voltage > Decimal("250"):
                filename = "Yageo_CC_High_Voltage_NP0_X7R_500V_to_3kV.pdf"
            elif dielectric == "X7R":
                filename = "Yageo_X7R_General_Purpose_High_Capacitance_MLCC.pdf"
            else:
                filename = "Yageo_CC_NP0_General_Purpose_16V_to_250V.pdf"
            profile = {
                "manufacturer": "YAGEO",
                "series": "CC",
                "automotive": "No",
                "datasheet": filename,
                "msl": "1",
                "rohs": "Yes",
                "halogen": "Yes",
            }
        elif prefix == "AC":
            profile = {
                "manufacturer": "YAGEO",
                "series": "AC",
                "automotive": "Yes",
                "datasheet": "Yageo_AC_Automotive_NP0_X7R_X7S_6.3V_to_2000V.pdf",
                "msl": "1",
                "rohs": "Yes",
                "halogen": "Yes",
            }
        elif prefix == "CQ":
            profile = {
                "manufacturer": "YAGEO",
                "series": "CQ",
                "automotive": "No",
                "datasheet": "Yageo_CQ_HiQ_NP0_16V_to_500V.pdf",
                "msl": "1",
                "rohs": "Yes",
                "halogen": "Yes",
            }
        else:
            raise ValueError(f"Unsupported Yageo series for selected addition: {mpn}")
    elif raw_manufacturer == "muRata" and prefix in {"GRM", "GCM", "GJM", "GQM"}:
        automotive = prefix == "GCM"
        profile = {
            "manufacturer": "Murata",
            "series": prefix,
            "automotive": "Yes" if automotive else "No",
            "datasheet": (
                "Murata_GCM_Automotive_C0G_MLCC_Reference.pdf"
                if automotive
                else "Murata_GRM_GJM_GQM_General_MLCC_Catalog.pdf"
            ),
            "msl": "Not Specified",
            "rohs": "Yes",
            "halogen": "Not Specified",
        }
    elif raw_manufacturer == "KEMET" and prefix == "C":
        automotive = mpn.endswith("AUTO")
        profile = {
            "manufacturer": "KEMET",
            "series": "C0G Automotive" if automotive else "C0G Commercial",
            "automotive": "Yes" if automotive else "No",
            "datasheet": (
                "KEMET_C0G_Automotive_MLCC.pdf"
                if automotive
                else "KEMET_C0G_Commercial_MLCC.pdf"
            ),
            "msl": "Not Specified",
            "rohs": "Yes",
            "halogen": "Not Specified",
        }
    elif raw_manufacturer == "Kyocera AVX" and not prefix:
        profile = {
            "manufacturer": "KYOCERA AVX",
            "series": "C0G/NP0",
            "automotive": "No",
            "datasheet": "KYOCERA_AVX_Surface_Mount_Ceramic_Capacitors.pdf",
            "msl": "Not Specified",
            "rohs": "Yes",
            "halogen": "Not Specified",
        }
    else:
        raise ValueError(
            f"No approved metadata/datasheet profile for selected addition: "
            f"manufacturer={raw_manufacturer!r} mpn={mpn!r}"
        )

    profile["dielectric"] = dielectric
    profile["class"] = "Class 2" if dielectric == "X7R" else "Class 1"
    profile["key"] = f"{profile['manufacturer']}|{profile['series']}|{profile['datasheet']}"
    return profile


def build_symbol(row: dict[str, str]) -> tuple[str, str, dict[str, str]]:
    profile = profile_for(row)
    package = row["Package"]
    capacitance = common.format_capacitance(common.parse_capacitance(row["Capacitance"]))
    tolerance = common.format_tolerance(common.parse_tolerance(row["Tolerance"]))
    voltage = common.format_voltage(common.parse_voltage(row["Voltage Rating"]))
    name = f"{capacitance}_{package}"
    description = (
        f"{profile['manufacturer']} {profile['series']} series {profile['dielectric']} "
        f"{profile['class']} MLCC, {capacitance}, {tolerance}, {voltage}, {package}, "
        f"{common.OPERATING_TEMPERATURE}"
    )
    properties = [
        ("Reference", "C", "reference"),
        ("Value", capacitance, "value"),
        ("Footprint", f"PL Capacitor MLCC:C{package}", "footprint"),
        ("Datasheet", datasheet_link(profile["datasheet"]), "hidden"),
        ("Description", description, "hidden"),
        ("Manufacturer", profile["manufacturer"], "hidden"),
        ("Capacitor Series", profile["series"], "hidden"),
        ("Automotive Grade", profile["automotive"], "hidden"),
        ("Technology", "MLCC", "hidden"),
        ("Capacitor Class", profile["class"], "hidden"),
        ("Dielectric", profile["dielectric"], "hidden"),
        ("Tolerance", tolerance, "hidden"),
        ("MPN", row["MPN"], "hidden"),
        ("LCSC Part #", row["LCSC Part#"], "hidden"),
        ("Capacitance", capacitance, "hidden"),
        ("Package", package, "hidden"),
        ("Rated Voltage", voltage, "hidden"),
        ("Operating Temperature", common.OPERATING_TEMPERATURE, "hidden"),
        ("Packaging", "Tape & Reel (TR)", "hidden"),
        ("MSL", profile["msl"], "hidden"),
        ("RoHS", profile["rohs"], "hidden"),
        ("Halogen Free", profile["halogen"], "hidden"),
        ("ki_keywords", "cap capacitor", "hidden"),
        ("ki_fp_filters", "C_*", "hidden"),
    ]
    block = f'\t(symbol "{common.quote(name)}"\r\n\t\t(extends "Capacitor_Template")\r\n'
    block += "".join(common.property_block(prop, value, style) for prop, value, style in properties)
    block += "\t\t(embedded_fonts no)\r\n\t)\r\n"
    return name, block, profile


def read_sources(paths: list[Path], log) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in paths:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            fields = set(reader.fieldnames or [])
            missing = REQUIRED_SOURCE_COLUMNS - fields
            if missing:
                raise ValueError(f"{path} is missing columns: {sorted(missing)}")
            file_rows = []
            for row in reader:
                normalized = {column: (row.get(column) or "").strip() for column in fields}
                file_rows.append(normalized)
            rows.extend(file_rows)
            log(f"SOURCE {path} rows={len(file_rows)} bytes={path.stat().st_size} sha256={sha256(path)}")
    return rows


def deduplicate_parts(rows: list[dict[str, str]], log) -> list[dict[str, str]]:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[row["LCSC Part#"]].append(row)
    unique: list[dict[str, str]] = []
    for part in sorted(groups, key=lambda value: int(value[1:])):
        variants = groups[part]
        chosen = sorted(variants, key=lambda row: (-common.availability(row), row["MPN"]))[0]
        unique.append(chosen)
        for discarded in variants:
            if discarded is not chosen:
                log(
                    f"DEDUP_DROP lcsc={part} mpn={discarded['MPN']} availability={discarded['Availability']} "
                    f"kept_availability={chosen['Availability']}"
                )
    return unique


def eligibility_failures(row: dict[str, str]) -> list[str]:
    failures = []
    if row["Package"] not in ALLOWED_PACKAGES:
        failures.append("package")
    if row["Packaging"] != "Tape & Reel (TR)":
        failures.append("packaging")
    if common.availability(row) < Decimal("1000"):
        failures.append("stock")
    if row["Temperature Coefficient"] not in SUPPORTED_DIELECTRICS:
        failures.append("dielectric")
    common.parse_capacitance(row["Capacitance"])
    common.parse_voltage(row["Voltage Rating"])
    common.parse_tolerance(row["Tolerance"])
    return failures


def select_preferred(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    groups: dict[tuple[str, Decimal], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[(row["Package"], common.parse_capacitance(row["Capacitance"]))].append(row)
    selected = [sorted(group, key=common.selected_sort_key)[0] for group in groups.values()]
    return sorted(selected, key=lambda row: (row["Package"], common.parse_capacitance(row["Capacitance"])))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=PROCESSED_COLUMNS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in PROCESSED_COLUMNS})


def validate_pdf(path: Path, required_tokens: tuple[str, ...]) -> None:
    raw = path.read_bytes()
    if not raw.startswith(b"%PDF-") or len(raw) < 50000:
        raise ValueError(f"Invalid or unexpectedly small PDF: {path}")
    reader = PdfReader(path)
    if not reader.pages:
        raise ValueError(f"PDF has no pages: {path}")
    text = " ".join("\n".join((page.extract_text() or "") for page in reader.pages[:3]).split())
    missing = [
        token
        for token in required_tokens
        if " ".join(token.split()).lower() not in text.lower()
    ]
    if missing:
        raise ValueError(f"PDF {path.name} is missing expected text: {missing}")


def download_pdf(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 PL-KiCad-Library-Updater"})
    with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as stream:
        shutil.copyfileobj(response, stream)


def run_cli(cli: Path, library: Path, symbols: list[str], output_root: Path, log) -> None:
    for index, symbol in enumerate(symbols):
        safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", symbol)
        output_dir = output_root / f"svg_{index}_{safe_name}"
        output_dir.mkdir(parents=True)
        command = [
            str(cli), "sym", "export", "svg", "--output", str(output_dir),
            "--symbol", symbol, str(library),
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
            raise RuntimeError(f"KiCad CLI validation failed for {symbol}")


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    library = root / "PL Capacitor MLCC.kicad_sym"
    bak = root / "PL Capacitor MLCC.bak"
    datasheets_dir = root / "Datasheets"
    processed_dir = root / "Data" / "LCSC" / "Processed"
    source_root = root / "Data" / "LCSC" / "Source"
    supplemental_dir = root / "Data" / "Supplied_Datasheets"
    cli = Path(r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe")
    footprint_root = Path(r"C:\KiCad\9.0\footprints\PL Capacitor MLCC\PL Capacitor MLCC.pretty")

    archived_sources = [source_root / f"LCSCSearchDownload({index}).csv" for index in range(22, 34)]
    new_sources = [root / f"LCSCSearchDownload({index}).csv" for index in range(34, 48)]
    new_sources.append(root / "LCSCSearchDownload(48)(1).csv")
    new_sources.extend(root / f"LCSCSearchDownload({index}).csv" for index in range(49, 57))
    zero_source = root / "LCSCSearchDownload(48).csv"
    duplicate_cap_csvs = [root / f"LCSCSearchDownload({index}).csv" for index in range(22, 34)]
    duplicate_res_csvs = [root / "LCSCSearchDownload.csv"] + [
        root / f"LCSCSearchDownload({index}).csv" for index in range(1, 22)
    ]
    original_sources = archived_sources + new_sources

    merged_output = processed_dir / "LCSCSearchDownload_MLCC_All_Series_merged.csv"
    selected_output = processed_dir / "LCSCSearchDownload_MLCC_All_Series_selected.csv"
    additions_output = processed_dir / "LCSCSearchDownload_MLCC_All_Series_additions.csv"

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    logs_dir = root / "Logs"
    backups_root = root / "Backups"
    logs_dir.mkdir(exist_ok=True)
    log_path = logs_dir / f"PL_Capacitor_MLCC_multifamily_update_{run_id}.log"
    log_stream = log_path.open("w", encoding="utf-8", newline="\n")

    def log(message: str) -> None:
        log_stream.write(f"[{datetime.now().isoformat(timespec='seconds')}] {message}\n")
        log_stream.flush()
        os.fsync(log_stream.fileno())

    mutation_started = False
    library_backup: Path | None = None
    original_library_hash = ""
    original_bak_hash = ""
    moved_files: list[tuple[Path, Path]] = []
    created_outputs: list[Path] = []
    footprint_hashes: dict[Path, str] = {}

    try:
        log("BEGIN multi-family non-E6 capacitor update")
        if len(original_sources) != EXPECTED_SOURCE_FILES:
            raise ValueError("Internal source-file list count mismatch")
        required = [library, bak, cli, zero_source, *original_sources, *duplicate_cap_csvs, *duplicate_res_csvs]
        required.extend(root / name for name in LOCAL_DATASHEETS)
        required.extend(root / name for name in SUPPLEMENTAL_DATASHEETS)
        required.extend([root / "Yageo_Capacitor.pdf", root / "Yageo_Resistor_RC_Series.pdf"])
        for path in required:
            if not path.is_file():
                raise FileNotFoundError(path)
        if zero_source.stat().st_size != 0:
            raise ValueError(f"Expected empty failed download: {zero_source}")
        for path in (merged_output, selected_output, additions_output):
            if path.exists():
                raise FileExistsError(f"One-shot output already exists: {path}")
        for filename in [value[0] for value in LOCAL_DATASHEETS.values()] + list(DOWNLOAD_DATASHEETS):
            destination = datasheets_dir / filename
            if destination.exists():
                raise FileExistsError(f"One-shot datasheet target already exists: {destination}")

        original_library_hash = sha256(library)
        original_bak_hash = sha256(bak)
        if original_library_hash != EXPECTED_LIBRARY_SHA256:
            raise ValueError(
                f"Live library hash changed: expected={EXPECTED_LIBRARY_SHA256} actual={original_library_hash}"
            )
        original_bytes = library.read_bytes()
        if original_bytes.startswith(b"\xef\xbb\xbf") or b"\n" in original_bytes.replace(b"\r\n", b""):
            raise ValueError("Library encoding/newline invariant failed")
        original_text = original_bytes.decode("utf-8")
        log(f"INPUT library={library} bytes={library.stat().st_size} sha256={original_library_hash}")
        log(f"INPUT bak={bak} bytes={bak.stat().st_size} sha256={original_bak_hash}")
        log(f"UPDATER {Path(__file__)} sha256={sha256(Path(__file__))}")

        for package in ALLOWED_PACKAGES:
            footprint = footprint_root / f"C{package}.kicad_mod"
            if not footprint.is_file():
                raise FileNotFoundError(footprint)
            footprint_hashes[footprint] = sha256(footprint)
            log(f"FOOTPRINT {footprint} bytes={footprint.stat().st_size} sha256={footprint_hashes[footprint]}")

        for index, path in enumerate(duplicate_cap_csvs, start=22):
            archived = source_root / f"LCSCSearchDownload({index}).csv"
            if sha256(path) != sha256(archived):
                raise ValueError(f"Root capacitor repeat differs from archived source: {path}")
        excluded_resistor_dir = root / "Data" / "Excluded" / "Resistor"
        for path in duplicate_res_csvs:
            archived = excluded_resistor_dir / path.name
            if sha256(path) != sha256(archived):
                raise ValueError(f"Root resistor repeat differs from archived source: {path}")
        if sha256(root / "Yageo_Capacitor.pdf") != sha256(
            datasheets_dir / "Yageo_X7R_General_Purpose_High_Capacitance_MLCC.pdf"
        ):
            raise ValueError("Repeated Yageo X7R PDF differs from installed datasheet")
        if sha256(root / "Yageo_Resistor_RC_Series.pdf") != sha256(
            excluded_resistor_dir / "Yageo_Resistor_RC_Series.pdf"
        ):
            raise ValueError("Repeated resistor PDF differs from archived copy")

        for source_name, (_, tokens) in LOCAL_DATASHEETS.items():
            path = root / source_name
            validate_pdf(path, tokens)
            log(f"LOCAL_DATASHEET {path} bytes={path.stat().st_size} sha256={sha256(path)}")
        for source_name in SUPPLEMENTAL_DATASHEETS:
            path = root / source_name
            validate_pdf(path, ())
            log(f"SUPPLEMENTAL_DATASHEET {path} bytes={path.stat().st_size} sha256={sha256(path)}")

        existing_symbols = common.parse_top_level_symbols(original_text)
        if len(existing_symbols) != EXPECTED_EXISTING_SYMBOLS:
            raise ValueError(
                f"Expected {EXPECTED_EXISTING_SYMBOLS} symbols, found {len(existing_symbols)}"
            )
        existing_names = {str(symbol["name"]) for symbol in existing_symbols}
        if len(existing_names) != len(existing_symbols):
            raise ValueError("Existing symbol names are not unique")
        existing_keys: dict[tuple[str, Decimal], list[str]] = defaultdict(list)
        for symbol in existing_symbols:
            if symbol["extends"] != "Capacitor_Template":
                continue
            properties = symbol["properties"]
            assert isinstance(properties, dict)
            match = re.fullmatch(
                r"PL Capacitor MLCC:C(0402|0603|0805|1206|1210)",
                str(properties.get("Footprint", "")),
            )
            if not match:
                raise ValueError(f"Unexpected ordinary-capacitor footprint: {symbol['name']}")
            existing_keys[(match.group(1), common.parse_capacitance(str(properties["Value"])))].append(
                str(symbol["name"])
            )
        if len(existing_keys) != EXPECTED_EXISTING_KEYS or any(len(names) != 1 for names in existing_keys.values()):
            raise ValueError(f"Existing key invariant failed: keys={len(existing_keys)}")

        raw_rows = read_sources(original_sources, log)
        if len(raw_rows) != EXPECTED_RAW_ROWS:
            raise ValueError(f"Expected {EXPECTED_RAW_ROWS} raw rows, found {len(raw_rows)}")
        unique_rows = deduplicate_parts(raw_rows, log)
        if len(unique_rows) != EXPECTED_UNIQUE_PARTS:
            raise ValueError(f"Expected {EXPECTED_UNIQUE_PARTS} unique parts, found {len(unique_rows)}")
        if len({row["MPN"] for row in unique_rows}) != EXPECTED_UNIQUE_PARTS:
            raise ValueError("Unique LCSC parts do not map one-to-one to MPNs")

        eligible_rows = []
        exclusion_counts: Counter[str] = Counter()
        for row in unique_rows:
            failures = eligibility_failures(row)
            if failures:
                exclusion_counts.update(failures)
                log(
                    f"EXCLUDE lcsc={row['LCSC Part#']} mpn={row['MPN']} "
                    f"reasons={','.join(failures)}"
                )
            else:
                eligible_rows.append(row)
        if len(eligible_rows) != EXPECTED_ELIGIBLE_ROWS:
            raise ValueError(f"Expected {EXPECTED_ELIGIBLE_ROWS} eligible rows, found {len(eligible_rows)}")
        selected_rows = select_preferred(eligible_rows)
        if len(selected_rows) != EXPECTED_SELECTED:
            raise ValueError(f"Expected {EXPECTED_SELECTED} selections, found {len(selected_rows)}")

        skipped = []
        additions = []
        for row in selected_rows:
            key = (row["Package"], common.parse_capacitance(row["Capacitance"]))
            (skipped if key in existing_keys else additions).append(row)
        if len(skipped) != EXPECTED_SKIPS or len(additions) != EXPECTED_ADDITIONS:
            raise ValueError(
                f"Expected {EXPECTED_SKIPS} skips/{EXPECTED_ADDITIONS} additions, "
                f"found {len(skipped)} skips/{len(additions)} additions"
            )
        addition_names = [common.symbol_name(row) for row in additions]
        if len(set(addition_names)) != len(addition_names):
            raise ValueError("Generated symbol names are not unique")
        collisions = sorted(set(addition_names) & existing_names)
        if collisions:
            raise ValueError(f"Unexplained name collisions: {collisions}")

        for row in selected_rows:
            log(
                f"SELECT name={common.symbol_name(row)} manufacturer={row['Manufacturer']} "
                f"mpn={row['MPN']} lcsc={row['LCSC Part#']} capacitance={row['Capacitance']} "
                f"package={row['Package']} voltage={row['Voltage Rating']} tolerance={row['Tolerance']} "
                f"dielectric={row['Temperature Coefficient']} availability={row['Availability']}"
            )
        for row in skipped:
            key = (row["Package"], common.parse_capacitance(row["Capacitance"]))
            log(
                f"SKIP name={common.symbol_name(row)} mpn={row['MPN']} lcsc={row['LCSC Part#']} "
                f"existing={','.join(existing_keys[key])} reason=same_capacitance_and_footprint"
            )

        generated: list[tuple[str, str, dict[str, str], dict[str, str]]] = []
        for row in sorted(additions, key=common.symbol_name):
            name, block, profile = build_symbol(row)
            generated.append((name, block, row, profile))
            log(
                f"ADD name={name} manufacturer={profile['manufacturer']} series={profile['series']} "
                f"automotive={profile['automotive']} mpn={row['MPN']} lcsc={row['LCSC Part#']} "
                f"capacitance={row['Capacitance']} package={row['Package']} voltage={row['Voltage Rating']} "
                f"tolerance={row['Tolerance']} dielectric={profile['dielectric']} datasheet={profile['datasheet']}"
            )

        log(
            f"PREFLIGHT counts sources={len(original_sources)} raw={len(raw_rows)} unique={len(unique_rows)} "
            f"eligible={len(eligible_rows)} selected={len(selected_rows)} existing={len(existing_symbols)} "
            f"existing_keys={len(existing_keys)} skips={len(skipped)} additions={len(additions)}"
        )
        log(f"EXCLUSIONS {dict(sorted(exclusion_counts.items()))}")
        log(f"ADDITIONS_BY_PACKAGE {dict(sorted(Counter(row['Package'] for row in additions).items()))}")
        log(f"ADDITIONS_BY_MANUFACTURER {dict(sorted(Counter(profile['manufacturer'] for _, _, _, profile in generated).items()))}")
        log(f"ADDITIONS_BY_DIELECTRIC {dict(sorted(Counter(profile['dielectric'] for _, _, _, profile in generated).items()))}")

        insertion = common.root_close_offset(original_text)
        candidate_text = original_text[:insertion] + "".join(block for _, block, _, _ in generated) + original_text[insertion:]
        if not common.parentheses_balanced(candidate_text):
            raise ValueError("Candidate library has unbalanced S-expressions")
        candidate_symbols = common.parse_top_level_symbols(candidate_text)
        if len(candidate_symbols) != EXPECTED_FINAL_SYMBOLS:
            raise ValueError(f"Expected {EXPECTED_FINAL_SYMBOLS} final symbols, found {len(candidate_symbols)}")
        candidate_names = [str(symbol["name"]) for symbol in candidate_symbols]
        if len(set(candidate_names)) != len(candidate_names):
            raise ValueError("Candidate symbol names are not unique")
        for before, after in zip(existing_symbols, candidate_symbols[:len(existing_symbols)]):
            if before["name"] != after["name"] or before["block"] != after["block"]:
                raise ValueError(f"Existing block changed: {before['name']}")
        if candidate_text[-3:] != original_text[-3:]:
            raise ValueError("Root closing bytes changed")
        for symbol in candidate_symbols:
            if symbol["extends"] and symbol["extends"] not in candidate_names:
                raise ValueError(f"Invalid inheritance: {symbol['name']} -> {symbol['extends']}")

        generated_by_name = {name: (row, profile) for name, _, row, profile in generated}
        for symbol in candidate_symbols[len(existing_symbols):]:
            name = str(symbol["name"])
            if symbol["extends"] != "Capacitor_Template":
                raise ValueError(f"New symbol does not extend Capacitor_Template: {name}")
            properties = symbol["properties"]
            assert isinstance(properties, dict)
            missing = NEW_REQUIRED_PROPERTIES - set(properties)
            if missing or "Height" in properties:
                raise ValueError(f"New symbol property invariant failed: {name} missing={sorted(missing)}")
            row, profile = generated_by_name[name]
            cap = common.format_capacitance(common.parse_capacitance(row["Capacitance"]))
            tolerance = common.format_tolerance(common.parse_tolerance(row["Tolerance"]))
            voltage = common.format_voltage(common.parse_voltage(row["Voltage Rating"]))
            exact = {
                "Reference": "C",
                "Value": cap,
                "Footprint": f"PL Capacitor MLCC:C{row['Package']}",
                "Datasheet": datasheet_link(profile["datasheet"]),
                "Manufacturer": profile["manufacturer"],
                "Capacitor Series": profile["series"],
                "Automotive Grade": profile["automotive"],
                "Technology": "MLCC",
                "Capacitor Class": profile["class"],
                "Dielectric": profile["dielectric"],
                "Tolerance": tolerance,
                "MPN": row["MPN"],
                "LCSC Part #": row["LCSC Part#"],
                "Capacitance": cap,
                "Package": row["Package"],
                "Rated Voltage": voltage,
                "Operating Temperature": common.OPERATING_TEMPERATURE,
                "Packaging": "Tape & Reel (TR)",
                "MSL": profile["msl"],
                "RoHS": profile["rohs"],
                "Halogen Free": profile["halogen"],
            }
            for property_name, expected in exact.items():
                if properties.get(property_name) != expected:
                    raise ValueError(
                        f"New symbol {name}: {property_name}={properties.get(property_name)!r}, expected={expected!r}"
                    )

        with tempfile.TemporaryDirectory(prefix="pl_capacitor_multifamily_stage_") as temporary:
            stage = Path(temporary)
            candidate_path = stage / library.name
            merged_stage = stage / merged_output.name
            selected_stage = stage / selected_output.name
            additions_stage = stage / additions_output.name
            downloads_stage = stage / "downloaded_datasheets"
            downloads_stage.mkdir()
            candidate_path.write_bytes(candidate_text.encode("utf-8"))
            write_csv(merged_stage, unique_rows)
            write_csv(selected_stage, selected_rows)
            write_csv(additions_stage, additions)
            for path, expected_rows in (
                (merged_stage, EXPECTED_UNIQUE_PARTS),
                (selected_stage, EXPECTED_SELECTED),
                (additions_stage, EXPECTED_ADDITIONS),
            ):
                with path.open("r", encoding="utf-8", newline="") as stream:
                    reader = csv.DictReader(stream)
                    if "Datasheet" in (reader.fieldnames or []) or "Pricing($)" in (reader.fieldnames or []):
                        raise ValueError(f"Processed CSV contains forbidden columns: {path}")
                    if sum(1 for _ in reader) != expected_rows:
                        raise ValueError(f"Processed CSV row count mismatch: {path}")
                log(f"STAGED csv={path.name} rows={expected_rows} sha256={sha256(path)}")

            for filename, (url, tokens) in DOWNLOAD_DATASHEETS.items():
                path = downloads_stage / filename
                download_pdf(url, path)
                validate_pdf(path, tokens)
                log(f"DOWNLOAD url={url} file={filename} bytes={path.stat().st_size} sha256={sha256(path)}")
            candidate_hash = sha256(candidate_path)
            log(f"STAGED library={candidate_path} bytes={candidate_path.stat().st_size} sha256={candidate_hash}")

            representatives = ["100nF_0402"]
            for package in ALLOWED_PACKAGES:
                representatives.append(next(name for name, _, row, _ in generated if row["Package"] == package))
            seen_profiles = set()
            for name, _, _, profile in generated:
                if profile["key"] not in seen_profiles:
                    representatives.append(name)
                    seen_profiles.add(profile["key"])
            representatives = list(dict.fromkeys(representatives))
            run_cli(cli, candidate_path, representatives, stage / "preinstall_cli", log)
            log(f"PREINSTALL CLI validation passed symbols={','.join(representatives)}")

            backup_dir = backups_root / run_id
            backup_dir.mkdir(parents=True, exist_ok=False)
            library_backup = backup_dir / library.name
            shutil.copy2(library, library_backup)
            root_csv_backup = backup_dir / "Root_CSVs"
            root_pdf_backup = backup_dir / "Root_PDFs"
            root_csv_backup.mkdir()
            root_pdf_backup.mkdir()
            root_csvs = sorted(root.glob("*.csv"), key=lambda path: path.name)
            root_pdfs = sorted(root.glob("*.pdf"), key=lambda path: path.name)
            for source in root_csvs:
                shutil.copy2(source, root_csv_backup / source.name)
            for source in root_pdfs:
                shutil.copy2(source, root_pdf_backup / source.name)
            if sha256(library_backup) != original_library_hash:
                raise RuntimeError("Library backup hash verification failed")
            for source in [*root_csvs, *root_pdfs]:
                backup = (root_csv_backup if source.suffix.lower() == ".csv" else root_pdf_backup) / source.name
                if sha256(source) != sha256(backup):
                    raise RuntimeError(f"Backup hash mismatch: {source}")
            log(f"BACKUP verified directory={backup_dir} csvs={len(root_csvs)} pdfs={len(root_pdfs)}")

            source_batch_dir = source_root / f"Batch_{run_id}_non_E6"
            duplicate_dir = root / "Data" / "Imported_Duplicates" / run_id
            duplicate_cap_dir = duplicate_dir / "Capacitor"
            duplicate_res_dir = duplicate_dir / "Resistor"
            duplicate_pdf_dir = duplicate_dir / "PDF"
            for directory in (
                datasheets_dir, processed_dir, source_batch_dir, supplemental_dir,
                duplicate_cap_dir, duplicate_res_dir, duplicate_pdf_dir,
            ):
                directory.mkdir(parents=True, exist_ok=True)

            planned_destinations = []
            planned_destinations.extend(source_batch_dir / path.name for path in [*new_sources, zero_source])
            planned_destinations.extend(duplicate_cap_dir / path.name for path in duplicate_cap_csvs)
            planned_destinations.extend(duplicate_res_dir / path.name for path in duplicate_res_csvs)
            planned_destinations.extend(datasheets_dir / value[0] for value in LOCAL_DATASHEETS.values())
            planned_destinations.extend(supplemental_dir / value for value in SUPPLEMENTAL_DATASHEETS.values())
            planned_destinations.extend(datasheets_dir / name for name in DOWNLOAD_DATASHEETS)
            planned_destinations.extend([merged_output, selected_output, additions_output])
            if any(path.exists() for path in planned_destinations):
                raise FileExistsError("A planned transaction destination already exists")

            mutation_started = True

            def move(source: Path, destination: Path, category: str) -> None:
                source.replace(destination)
                moved_files.append((source, destination))
                log(f"MOVE category={category} source={source} destination={destination} sha256={sha256(destination)}")

            for source in [*new_sources, zero_source]:
                move(source, source_batch_dir / source.name, "new_capacitor_source")
            for source in duplicate_cap_csvs:
                move(source, duplicate_cap_dir / source.name, "repeated_capacitor_source")
            for source in duplicate_res_csvs:
                move(source, duplicate_res_dir / source.name, "repeated_resistor_source")
            move(root / "Yageo_Capacitor.pdf", duplicate_pdf_dir / "Yageo_Capacitor.pdf", "repeated_pdf")
            move(
                root / "Yageo_Resistor_RC_Series.pdf",
                duplicate_pdf_dir / "Yageo_Resistor_RC_Series.pdf",
                "repeated_pdf",
            )
            for source_name, (destination_name, _) in LOCAL_DATASHEETS.items():
                move(root / source_name, datasheets_dir / destination_name, "active_datasheet")
            for source_name, destination_name in SUPPLEMENTAL_DATASHEETS.items():
                move(root / source_name, supplemental_dir / destination_name, "supplemental_datasheet")

            for filename in DOWNLOAD_DATASHEETS:
                destination = datasheets_dir / filename
                os.replace(downloads_stage / filename, destination)
                created_outputs.append(destination)
                log(f"INSTALL downloaded_datasheet={destination} sha256={sha256(destination)}")
            for staged, destination in (
                (merged_stage, merged_output),
                (selected_stage, selected_output),
                (additions_stage, additions_output),
            ):
                os.replace(staged, destination)
                created_outputs.append(destination)
                log(f"INSTALL processed_csv={destination} sha256={sha256(destination)}")
            os.replace(candidate_path, library)
            log(f"INSTALL atomic_library_replace={library}")

            if sha256(library) != candidate_hash:
                raise RuntimeError("Installed library hash differs from staged candidate")
            final_text = library.read_bytes().decode("utf-8")
            final_symbols = common.parse_top_level_symbols(final_text)
            if len(final_symbols) != EXPECTED_FINAL_SYMBOLS:
                raise RuntimeError("Post-install symbol count mismatch")
            for before, after in zip(existing_symbols, final_symbols[:len(existing_symbols)]):
                if before["block"] != after["block"]:
                    raise RuntimeError(f"Post-install original block mismatch: {before['name']}")
            for _, _, _, profile in generated:
                path = datasheets_dir / profile["datasheet"]
                if not path.is_file():
                    raise RuntimeError(f"Referenced datasheet is missing: {path}")
            if sha256(bak) != original_bak_hash:
                raise RuntimeError("Existing .bak file changed")
            for footprint, original_hash in footprint_hashes.items():
                if sha256(footprint) != original_hash:
                    raise RuntimeError(f"Footprint changed: {footprint}")
            run_cli(cli, library, representatives, stage / "postinstall_cli", log)
            root_files = {path.name for path in root.iterdir() if path.is_file()}
            if root_files != {library.name, bak.name}:
                raise RuntimeError(f"Unexpected files remain in root: {sorted(root_files)}")
            log(f"FINAL library={library} bytes={library.stat().st_size} sha256={sha256(library)}")
            log(
                f"FINAL counts prior_symbols={EXPECTED_EXISTING_SYMBOLS} additions={EXPECTED_ADDITIONS} "
                f"skips={EXPECTED_SKIPS} symbols={len(final_symbols)}"
            )
            log("SUCCESS update completed; rollback not required")
        return 0
    except Exception as error:
        log(f"ERROR {type(error).__name__}: {error}")
        if mutation_started:
            log("ROLLBACK started")
            errors = []
            try:
                if library_backup and library_backup.is_file():
                    shutil.copy2(library_backup, library)
            except Exception as rollback_error:
                errors.append(f"library restore: {rollback_error}")
            for output in reversed(created_outputs):
                try:
                    if output.exists():
                        output.unlink()
                except Exception as rollback_error:
                    errors.append(f"remove output {output}: {rollback_error}")
            for source, destination in reversed(moved_files):
                try:
                    if destination.exists() and not source.exists():
                        destination.replace(source)
                except Exception as rollback_error:
                    errors.append(f"restore move {destination}: {rollback_error}")
            if errors:
                log(f"ROLLBACK FAILED: {'; '.join(errors)}")
            else:
                library_ok = library.is_file() and sha256(library) == original_library_hash
                bak_ok = bak.is_file() and sha256(bak) == original_bak_hash
                log(f"ROLLBACK completed library_ok={library_ok} bak_ok={bak_ok}")
        return 1
    finally:
        log_stream.close()
        print(log_path)


if __name__ == "__main__":
    sys.exit(main())
