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

from pypdf import PdfReader


DOWNLOADS = Path(r"C:\Users\larsk\Downloads")
FERRITE_ROOT = Path(r"C:\KiCad\9.0\symbols\PL Magnetics Ferrite")
ZENER_ROOT = Path(r"C:\KiCad\9.0\symbols\PL Diode Zener")
FERRITE_LIBRARY = FERRITE_ROOT / "PL Magnetics Ferrite.kicad_sym"
ZENER_LIBRARY = ZENER_ROOT / "PL Diode Zener.kicad_sym"
FERRITE_FOOTPRINT_ROOT = Path(r"C:\KiCad\9.0\footprints\PL Magnetics Ferrite\PL Magnetics Ferrite.pretty")
ZENER_FOOTPRINT_ROOT = Path(r"C:\KiCad\9.0\footprints\PL Diode Zener\PL Diode Zener.pretty")
KICAD_CLI = Path(r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe")

EXPECTED_LIBRARY_HASHES = {
    FERRITE_LIBRARY: "0932ad16713fdbfd7def886d56669b60962d45e12c10272c3c3eff2bf96f0487",
    ZENER_LIBRARY: "750d719609d7960bd74c9cc3539e95d920f49347a63825104fc87645d311291e",
}
EXPECTED_EXISTING_SYMBOLS = {"ferrite": 2, "zener": 11}
EXPECTED = {
    "ferrite": {"raw": 700, "unique": 600, "eligible": 115, "selected": 50, "skips": 0, "parts": 50, "templates": 1, "final": 53},
    "zener": {"raw": 1423, "unique": 1373, "eligible": 40, "selected": 40, "skips": 1, "parts": 39, "templates": 1, "final": 51},
}

CSV_HASHES = {
    57: "4aaa59d14d345a385c794a565d6654f1349ddf89161b93ae0753467b68d3615e",
    58: "3326d2f7fbde5d39be3f40cd86a34d44da7ed9e2022336de02d4f5b1fe890323",
    59: "21e4175f282c9ada980c4ea1414d770b9aa146c956be8df59310a3a7dfada158",
    60: "0b32bcb2de2969bc61b23b08b439cb438171ca8ae116810ad7af29158747b9d2",
    61: "fd1f4f787e1ebca1ea56f142cd86064de92a3819b5817bd094e8f56f44473a93",
    62: "e6e7b4b4ec34bc9bfbc98da7868a58099dbd7faba8081c29bccf3c9d2545114d",
    63: "cb0a458632fa3fa4619c184544a45dc2d97bc6f39aaf7591a72692398c8cad4d",
    64: "7f23563d2acc1bc47b43181aec5abd0017eb438f51a1664ac06d77660b8b7dca",
    65: "9496c3f0deabacf92e79e0e71a66b26f66333b52d098bca323034d1cb30901ab",
    66: "9496c3f0deabacf92e79e0e71a66b26f66333b52d098bca323034d1cb30901ab",
    67: "d2b3f0cb5b02c7819ecc4f26b5e5b6a3cfafdf721aebf5fa5e2f03e34607c97d",
    68: "f17df641b46aa2c33b9f0388b39c2b9e626301c49dbd186b451f72371ed25c67",
    69: "5d78d10a89a722a23aa83bba7a0aaebf77bea91cd32db216a98d9cbee6f1ea80",
    70: "090a122668e9f77b4825a7ef4da8f4d47015f238955708c5142350faa45aabdc",
    71: "ffb005da89b0c13009fafbc576bc3a9c673b44adff533ad5aad80249653a1141",
    72: "4ac1ce46cbbc3ac91f8ce2adb23efeec29849d72b241e88c65013ca79d76cab2",
    73: "c3d4793d6456d67038623690b8d5e96631407da7ce4dbe3d49465d24e7462438",
    74: "5ef98a215e445931106b8b5d7c9daaf3cbf1ba7067ad57b16e325a5b31105e42",
    75: "e8ff53eb8dee09aed1f64b3be1369c996f8b4b279807929bc3abd683941e4faa",
    76: "e8ff53eb8dee09aed1f64b3be1369c996f8b4b279807929bc3abd683941e4faa",
    77: "a62172eb8e8a7f2a6338837c4474f6d28439187726c121cf553303ce276422d5",
    78: "7b9261bb5d9a6ad8b02847d16c29e975388a97889ac9b56ee7855f054318f59e",
    79: "b44c4350762690324f72a156c2eff0d9301e56bec7a40ab962a3f71145405ef6",
}

PDF_PROFILES = {
    "f099154a6640c0e8db3f25979c3cb868": {"kind": "zener", "filename": "RplusO_BZX84C_SOT23_Zener_Diodes.pdf", "series": "BZX84C", "automotive": "No", "msl": "1", "rohs": "Yes", "halogen": "Yes", "tokens": ("BZX84C2V4 THRU BZX84C75", "SOT-23")},
    "26ade382493570f6ac7aa9df8c9e3d26": {"kind": "zener", "filename": "RplusO_MMSZ5221B_to_MMSZ5267B_SOD123_Zener_Diodes.pdf", "series": "MMSZ52xxB", "automotive": "No", "msl": "1", "rohs": "Yes", "halogen": "Yes", "tokens": ("MMSZ5221B THRU MMSZ5267B", "SOD-123")},
    "fd38dbf7891eeab523fe4c8bd002891d": {"kind": "zener", "filename": "RplusO_MMSZ5221BS_to_MMSZ5259BS_SOD323_Zener_Diodes.pdf", "series": "MMSZ52xxBS", "automotive": "No", "msl": "Not Specified", "rohs": "Yes", "halogen": "Yes", "tokens": ("MMSZ5221BS THRU MMSZ5259BS", "SOD-323")},
    "fa365b03943947af82e802e86ce28761": {"kind": "ferrite", "filename": "Murata_BLM18PG121SN1D_Third_Party_Copy.pdf", "series": "BLM18", "automotive": "No", "msl": "Not Specified", "rohs": "Not Specified", "halogen": "Not Specified", "technology": "Ferrite Bead", "tokens": ()},
    "2d503a4b167da9bb5d0eb4a3fa711314": {"kind": "ferrite", "filename": "Murata_BLM18_0603_Chip_Ferrite_Beads.pdf", "series": "BLM18", "automotive": "No", "msl": "Not Specified", "rohs": "Yes", "halogen": "Not Specified", "technology": "Ferrite Bead", "tokens": ("Chip Ferrite Bead", "BLM18")},
    "f85b01b3a1a015a5ec4a9f03876e0063": {"kind": "ferrite", "filename": "Murata_BLM15_0402_Chip_Ferrite_Beads.pdf", "series": "BLM15", "automotive": "No", "msl": "Not Specified", "rohs": "Yes", "halogen": "Not Specified", "technology": "Ferrite Bead", "tokens": ("Chip Ferrite Bead", "BLM15")},
    "1addff62e5484bf39ea4690b7cc5dd21": {"kind": "ferrite", "filename": "Murata_BLM21_0805_Chip_Ferrite_Beads.pdf", "series": "BLM21", "automotive": "No", "msl": "Not Specified", "rohs": "Yes", "halogen": "Not Specified", "technology": "Ferrite Bead", "tokens": ("Chip Ferrite Bead", "BLM21")},
    "5525eadde63874e80c8e8f485485d5a6": {"kind": "ferrite", "filename": "TDK_MPZ1608_0603_Commercial_Power_Line_Chip_Beads.pdf", "series": "MPZ1608", "automotive": "No", "msl": "Not Specified", "rohs": "Yes", "halogen": "Yes", "technology": "Ferrite Bead", "tokens": ("MPZ1608", "Chip beads")},
    "97b8fd8f95d483658715dd96ac1acb6d": {"kind": "ferrite", "filename": "TDK_MPZ2012_0805_Automotive_Power_Line_Chip_Beads.pdf", "series": "MPZ2012", "automotive": "Yes", "msl": "Not Specified", "rohs": "Yes", "halogen": "Yes", "technology": "Ferrite Bead", "tokens": ("MPZ2012", "automotive")},
    "faf431921010bd6151d84a7da591b5d1": {"kind": "ferrite", "filename": "TDK_MPZ2012_0805_Commercial_Power_Line_Chip_Beads.pdf", "series": "MPZ2012", "automotive": "No", "msl": "Not Specified", "rohs": "Yes", "halogen": "Yes", "technology": "Ferrite Bead", "tokens": ("MPZ2012", "Chip beads")},
    "b2aaeaa75f1b834be2cb67f1d33879f9": {"kind": "ferrite", "filename": "TDK_MMZ2012_0805_Automotive_Signal_Line_Chip_Beads.pdf", "series": "MMZ2012", "automotive": "Yes", "msl": "Not Specified", "rohs": "Yes", "halogen": "Yes", "technology": "Ferrite Bead", "tokens": ("MMZ2012", "AEC-Q200")},
    "8be8f6f5db2d5d7d12a82d918651c4e9": {"kind": "ferrite", "filename": "TDK_MAF1005GW_0402_Audio_Noise_Suppression_Filter.pdf", "series": "MAF1005GW", "automotive": "No", "msl": "Not Specified", "rohs": "Not Specified", "halogen": "Not Specified", "technology": "Noise Suppression Filter", "tokens": ("MAF1005GW", "Noise suppression filter")},
    "7f0426ef046fbb06a31cef2ca0797607": {"kind": "ferrite", "filename": "Bourns_MH_High_Current_Chip_Ferrite_Beads.pdf", "series": "MH", "automotive": "No", "msl": "Not Specified", "rohs": "Yes", "halogen": "Yes", "technology": "Ferrite Bead", "tokens": ("MH Series", "Ferrite Beads")},
    "c5eb2ab63e31dac1cfd52cdbf8919cc7": {"kind": "ferrite", "filename": "Murata_NFZ15SG_0402_Chip_Noise_Filter.pdf", "series": "NFZ15SG", "automotive": "No", "msl": "Not Specified", "rohs": "Yes", "halogen": "Not Specified", "technology": "Chip Noise Filter", "tokens": ("NFZ15SG", "CHIP NOISE FILTER")},
}

PDF_HASHES = {
    "f099154a6640c0e8db3f25979c3cb868": "a65683624fb8339f543bc425912e7a72a24a98329b1abe997248f4bab1b3f28f",
    "26ade382493570f6ac7aa9df8c9e3d26": "8894d63b414fbe8314e4e18e317b682da3265f03cc92ac8f6b0c39290733bcd2",
    "fd38dbf7891eeab523fe4c8bd002891d": "e7454164572e2898569fd468a48bce5e987711981cc1baadea5eae99ef9ceb64",
    "fa365b03943947af82e802e86ce28761": "a27b3aa8822c9df2f05298b36226bf8d76e1a7a5eb1af0b0a5476a37a51d6196",
    "2d503a4b167da9bb5d0eb4a3fa711314": "f2b3b23d6ae4da86504c9a7e7893101bb1edb7bca93ec37ce86eff580ff8c099",
    "f85b01b3a1a015a5ec4a9f03876e0063": "72584e2b0fad42b4fd0fc45b175151fa42acab38f373431d3f726f55317918aa",
    "1addff62e5484bf39ea4690b7cc5dd21": "651645d072b5710a8594bf47864946d4432144ef3c6437a404b0de3349ef308e",
    "5525eadde63874e80c8e8f485485d5a6": "248facf5bc65c85e0c5a74ce83ebf316bbf69a8de9ff04bc2422db49afdc680a",
    "97b8fd8f95d483658715dd96ac1acb6d": "143ae0aef04553d143fec94e5bc5d2fe6f513bbfed074774858fa6630f3cdfb4",
    "faf431921010bd6151d84a7da591b5d1": "c8b428baaacfffa1b685848153d1cfef1fb8702157b173093cd19f32d25a68bc",
    "b2aaeaa75f1b834be2cb67f1d33879f9": "5547e95740b599050736dd47180dd2758781a17a798dccedb618cd4c019b8170",
    "8be8f6f5db2d5d7d12a82d918651c4e9": "87c0b8331a838025024af130c51567bb0fb629955d283c19bc7c31406193be82",
    "7f0426ef046fbb06a31cef2ca0797607": "f3f3d6673d40c3d41ec0370d82a9d06c9844c941c2aa22bc4ac644db6aa5c9d9",
    "c5eb2ab63e31dac1cfd52cdbf8919cc7": "c977885ee2d0c6a814a9e8f343c3d515cbfb9346d1ee9f86b791352bd3af1fee",
}

FERRITE_FOOTPRINTS = {"0402": "FL0402", "0603": "FL0603", "0805": "FL0805"}
ZENER_FOOTPRINTS = {"SOT-23": "SOT-23-3", "SOD-123": "D_SOD-123", "SOD-323": "SOD-323"}

FERRITE_COLUMNS = ["LCSC Part#", "MPN", "Manufacturer", "Availability", "Minimum", "Multiples", "Product Detail", "Package", "Packaging", "Number of Lines", "Impedance @ Frequency", "Tolerance", "DC Resistance(DCR)", "Current Rating", "Operating Temperature"]
ZENER_COLUMNS = ["LCSC Part#", "MPN", "Manufacturer", "Availability", "Minimum", "Multiples", "Product Detail", "Package", "Packaging", "Diode Configuration", "Pd - Power Dissipation", "Zener Voltage(Nom)", "Reverse Leakage Current (Ir)", "Zener Voltage(Range)", "Operating Junction Temperature Range", "Impedance(Zzt)", "Impedance(Zzk)", "Tolerance"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def canonical_decimal(value: Decimal) -> str:
    result = format(value.normalize(), "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


def parse_quantity(value: str, base_unit: str) -> Decimal:
    cleaned = (value or "").strip().replace("µ", "u").replace("Ω", "ohm")
    pattern = rf"([0-9]+(?:\.[0-9]+)?)\s*([kmunp]?)\s*{re.escape(base_unit)}"
    match = re.search(pattern, cleaned, re.IGNORECASE)
    if not match:
        raise ValueError(f"Cannot parse {base_unit} quantity: {value!r}")
    multipliers = {"": Decimal(1), "k": Decimal("1e3"), "m": Decimal("1e-3"), "u": Decimal("1e-6"), "n": Decimal("1e-9"), "p": Decimal("1e-12")}
    return Decimal(match.group(1)) * multipliers[match.group(2).lower()]


def parse_percent(value: str) -> Decimal:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)%", value or "")
    if not match:
        raise ValueError(f"Cannot parse tolerance: {value!r}")
    return Decimal(match.group(1))


def pdf_hash_from_url(url: str) -> str:
    match = re.search(r"/([0-9a-f]{32})\.pdf", url or "")
    return match.group(1) if match else ""


def normalized_token(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


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
        elif character == '"':
            in_string = True
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0 and not in_string


def parse_top_level_symbols(text: str) -> list[dict[str, object]]:
    symbols: list[dict[str, object]] = []
    depth = 0
    start: int | None = None
    in_string = False
    escaped = False
    for index, character in enumerate(text):
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
            if depth == 1 and text.startswith('(symbol "', index):
                start = index
            depth += 1
        elif character == ")":
            depth -= 1
            if start is not None and depth == 1:
                block = text[start:index + 1]
                name_match = re.match(r'\(symbol "((?:\\.|[^"\\])*)"', block)
                if not name_match:
                    raise ValueError("Malformed top-level symbol")
                extends_match = re.search(r'\r\n\s*\(extends "([^"]+)"\)', block)
                properties = dict(re.findall(r'\(property "([^"]+)" "((?:\\.|[^"\\])*)"', block))
                symbols.append({"name": name_match.group(1), "extends": extends_match.group(1) if extends_match else None, "properties": properties, "block": block})
                start = None
    return symbols


def root_close_offset(text: str) -> int:
    if not text.startswith("(kicad_symbol_lib\r\n") or not text.endswith(")\r\n"):
        raise ValueError("Unexpected KiCad library framing/newlines")
    return len(text) - 3


def property_block(name: str, value: str, family: str, style: str = "hidden") -> str:
    if family == "ferrite":
        position = {"reference": "-0.635 -3.81 0", "value": "0 3.81 0", "footprint": "0 -1.778 0"}.get(style, "0 0 0")
    else:
        position = {"reference": "0 2.54 0", "value": "0 -2.54 0", "footprint": "0 0 0"}.get(style, "0 0 0")
    hidden = "" if style in {"reference", "value"} else "\t\t\t(hide yes)\r\n"
    return (
        f'\t\t(property "{quote(name)}" "{quote(value)}"\r\n'
        f"\t\t\t(at {position})\r\n"
        "\t\t\t(show_name no)\r\n"
        "\t\t\t(do_not_autoplace no)\r\n"
        f"{hidden}"
        "\t\t\t(effects\r\n"
        "\t\t\t\t(font\r\n"
        "\t\t\t\t\t(size 1.27 1.27)\r\n"
        "\t\t\t\t)\r\n"
        "\t\t\t)\r\n"
        "\t\t)\r\n"
    )


def ferrite_template() -> tuple[str, str]:
    name = "Ferrite_Bead_Template"
    properties = [
        ("Reference", "FB", "reference"), ("Value", "", "value"), ("Footprint", "", "footprint"),
        ("Datasheet", "", "hidden"), ("Description", "", "hidden"), ("Manufacturer", "", "hidden"),
        ("Ferrite Series", "", "hidden"), ("Automotive Grade", "", "hidden"), ("Technology", "", "hidden"),
        ("Tolerance", "", "hidden"), ("MPN", "", "hidden"), ("LCSC Part #", "", "hidden"),
        ("Impedance @ Frequency", "", "hidden"), ("Number of Lines", "", "hidden"), ("DCR", "", "hidden"),
        ("Rated Current", "", "hidden"), ("Package", "", "hidden"), ("Operating Temperature", "", "hidden"),
        ("Packaging", "", "hidden"), ("MSL", "", "hidden"), ("RoHS", "", "hidden"),
        ("Halogen Free", "", "hidden"), ("ki_keywords", "L ferrite bead inductor filter", "hidden"),
        ("ki_fp_filters", "FL* *Ferrite*", "hidden"),
    ]
    block = f'\t(symbol "{name}"\r\n\t\t(pin_numbers\r\n\t\t\t(hide yes)\r\n\t\t)\r\n\t\t(pin_names\r\n\t\t\t(offset 0)\r\n\t\t)\r\n\t\t(exclude_from_sim no)\r\n\t\t(in_bom yes)\r\n\t\t(on_board yes)\r\n\t\t(in_pos_files yes)\r\n\t\t(duplicate_pin_numbers_are_jumpers no)\r\n'
    block += "".join(property_block(p, v, "ferrite", s) for p, v, s in properties)
    block += (
        f'\t\t(symbol "{name}_0_1"\r\n'
        "\t\t\t(polyline\r\n\t\t\t\t(pts\r\n\t\t\t\t\t(xy -1.27 0) (xy -1.2954 0)\r\n\t\t\t\t)\r\n\t\t\t\t(stroke\r\n\t\t\t\t\t(width 0)\r\n\t\t\t\t\t(type default)\r\n\t\t\t\t)\r\n\t\t\t\t(fill\r\n\t\t\t\t\t(type none)\r\n\t\t\t\t)\r\n\t\t\t)\r\n"
        "\t\t\t(polyline\r\n\t\t\t\t(pts\r\n\t\t\t\t\t(xy -0.4064 -2.7686) (xy -2.2606 -1.7018) (xy 0.3048 2.7686) (xy 2.159 1.6764) (xy -0.4064 -2.7686)\r\n\t\t\t\t)\r\n\t\t\t\t(stroke\r\n\t\t\t\t\t(width 0)\r\n\t\t\t\t\t(type default)\r\n\t\t\t\t)\r\n\t\t\t\t(fill\r\n\t\t\t\t\t(type none)\r\n\t\t\t\t)\r\n\t\t\t)\r\n"
        "\t\t\t(polyline\r\n\t\t\t\t(pts\r\n\t\t\t\t\t(xy 1.27 0) (xy 1.2192 0)\r\n\t\t\t\t)\r\n\t\t\t\t(stroke\r\n\t\t\t\t\t(width 0)\r\n\t\t\t\t\t(type default)\r\n\t\t\t\t)\r\n\t\t\t\t(fill\r\n\t\t\t\t\t(type none)\r\n\t\t\t\t)\r\n\t\t\t)\r\n\t\t)\r\n"
        f'\t\t(symbol "{name}_1_1"\r\n'
        + pin_block("", "1", "passive", "-3.81 0 0")
        + pin_block("", "2", "passive", "3.81 0 180")
        + "\t\t)\r\n\t\t(embedded_fonts no)\r\n\t)\r\n"
    )
    return name, block


def pin_block(name: str, number: str, electrical: str, at: str, hidden: bool = False) -> str:
    hide = "\t\t\t\t(hide yes)\r\n" if hidden else ""
    return (
        f"\t\t\t(pin {electrical} line\r\n"
        f"\t\t\t\t(at {at})\r\n"
        f"\t\t\t\t(length {'0' if hidden else '2.54'})\r\n"
        f"{hide}"
        f'\t\t\t\t(name "{quote(name)}"\r\n\t\t\t\t\t(effects\r\n\t\t\t\t\t\t(font\r\n\t\t\t\t\t\t\t(size 1.27 1.27)\r\n\t\t\t\t\t\t)\r\n\t\t\t\t\t)\r\n\t\t\t\t)\r\n'
        f'\t\t\t\t(number "{number}"\r\n\t\t\t\t\t(effects\r\n\t\t\t\t\t\t(font\r\n\t\t\t\t\t\t\t(size 1.27 1.27)\r\n\t\t\t\t\t\t)\r\n\t\t\t\t\t)\r\n\t\t\t\t)\r\n'
        "\t\t\t)\r\n"
    )


def zener_sot23_template() -> tuple[str, str]:
    name = "Zener_SOT23_Template"
    properties = [
        ("Reference", "D", "reference"), ("Value", "", "value"), ("Footprint", "", "footprint"),
        ("Datasheet", "", "hidden"), ("Description", "", "hidden"), ("Manufacturer", "", "hidden"),
        ("Zener Series", "", "hidden"), ("Automotive Grade", "", "hidden"), ("Technology", "", "hidden"),
        ("Diode Configuration", "", "hidden"), ("Tolerance", "", "hidden"), ("MPN", "", "hidden"),
        ("LCSC Part #", "", "hidden"), ("Zener Voltage", "", "hidden"), ("Zener Voltage Range", "", "hidden"),
        ("Rated Power", "", "hidden"), ("Reverse Leakage Current", "", "hidden"),
        ("Zener Impedance Zzt", "", "hidden"), ("Zener Impedance Zzk", "", "hidden"),
        ("Package", "", "hidden"), ("Operating Junction Temperature", "", "hidden"),
        ("Packaging", "", "hidden"), ("MSL", "", "hidden"), ("RoHS", "", "hidden"),
        ("Halogen Free", "", "hidden"), ("ki_keywords", "diode zener", "hidden"),
        ("ki_fp_filters", "TO-???* *_Diode_* *SingleDiode* D_*", "hidden"),
    ]
    block = f'\t(symbol "{name}"\r\n\t\t(pin_numbers\r\n\t\t\t(hide yes)\r\n\t\t)\r\n\t\t(pin_names\r\n\t\t\t(offset 1.016)\r\n\t\t\t(hide yes)\r\n\t\t)\r\n\t\t(exclude_from_sim no)\r\n\t\t(in_bom yes)\r\n\t\t(on_board yes)\r\n\t\t(in_pos_files yes)\r\n\t\t(duplicate_pin_numbers_are_jumpers no)\r\n'
    block += "".join(property_block(p, v, "zener", s) for p, v, s in properties)
    block += (
        f'\t\t(symbol "{name}_0_1"\r\n'
        "\t\t\t(polyline\r\n\t\t\t\t(pts\r\n\t\t\t\t\t(xy -1.27 -1.27) (xy -1.27 1.27) (xy -0.762 1.27)\r\n\t\t\t\t)\r\n\t\t\t\t(stroke\r\n\t\t\t\t\t(width 0.254)\r\n\t\t\t\t\t(type default)\r\n\t\t\t\t)\r\n\t\t\t\t(fill\r\n\t\t\t\t\t(type none)\r\n\t\t\t\t)\r\n\t\t\t)\r\n"
        "\t\t\t(polyline\r\n\t\t\t\t(pts\r\n\t\t\t\t\t(xy 1.27 0) (xy -1.27 0)\r\n\t\t\t\t)\r\n\t\t\t\t(stroke\r\n\t\t\t\t\t(width 0)\r\n\t\t\t\t\t(type default)\r\n\t\t\t\t)\r\n\t\t\t\t(fill\r\n\t\t\t\t\t(type none)\r\n\t\t\t\t)\r\n\t\t\t)\r\n"
        "\t\t\t(polyline\r\n\t\t\t\t(pts\r\n\t\t\t\t\t(xy 1.27 -1.27) (xy 1.27 1.27) (xy -1.27 0) (xy 1.27 -1.27)\r\n\t\t\t\t)\r\n\t\t\t\t(stroke\r\n\t\t\t\t\t(width 0.254)\r\n\t\t\t\t\t(type default)\r\n\t\t\t\t)\r\n\t\t\t\t(fill\r\n\t\t\t\t\t(type none)\r\n\t\t\t\t)\r\n\t\t\t)\r\n\t\t)\r\n"
        f'\t\t(symbol "{name}_1_1"\r\n'
        + pin_block("K", "3", "passive", "-3.81 0 0")
        + pin_block("A", "1", "passive", "3.81 0 180")
        + pin_block("NC", "2", "no_connect", "0 0 0", True)
        + "\t\t)\r\n\t\t(embedded_fonts no)\r\n\t)\r\n"
    )
    return name, block


def read_rows(indices: range, required_columns: set[str], log) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for index in indices:
        path = DOWNLOADS / f"LCSCSearchDownload({index}).csv"
        if not path.is_file() or sha256(path) != CSV_HASHES[index]:
            raise ValueError(f"Source CSV missing or changed: {path}")
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            fields = set(reader.fieldnames or [])
            if missing := required_columns - fields:
                raise ValueError(f"{path.name} missing columns {sorted(missing)}")
            file_rows = []
            for row in reader:
                normalized = {field: (row.get(field) or "").strip() for field in fields}
                normalized["_source"] = path.name
                normalized["_pdf_hash"] = pdf_hash_from_url(normalized.get("Datasheet", ""))
                file_rows.append(normalized)
            rows.extend(file_rows)
        log(f"SOURCE file={path} rows={len(file_rows)} bytes={path.stat().st_size} sha256={sha256(path)}")
    return rows


def deduplicate(rows: list[dict[str, str]], pdf_text: dict[str, str], log) -> list[dict[str, str]]:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[row["LCSC Part#"]].append(row)
    unique = []
    for lcsc, variants in groups.items():
        def rank(row: dict[str, str]) -> tuple[int, int, int, str]:
            pdf_hash = row["_pdf_hash"]
            verified = pdf_hash in pdf_text and normalized_token(row["MPN"]) in pdf_text[pdf_hash]
            return (int(row["Availability"] or 0), int(verified), int(pdf_hash in pdf_text), row["_source"])
        chosen = max(variants, key=rank)
        unique.append(chosen)
        for discarded in variants:
            if discarded is not chosen:
                log(f"DEDUP_DROP lcsc={lcsc} mpn={discarded['MPN']} source={discarded['_source']} availability={discarded['Availability']} kept_source={chosen['_source']} kept_availability={chosen['Availability']}")
    return sorted(unique, key=lambda row: int(row["LCSC Part#"][1:]))


def eligible_ferrite(row: dict[str, str], pdf_text: dict[str, str]) -> list[str]:
    failures = []
    if row["Package"] not in FERRITE_FOOTPRINTS: failures.append("package")
    if row["Packaging"] != "Tape & Reel (TR)": failures.append("packaging")
    if int(row["Availability"] or 0) < 1000: failures.append("stock")
    if row["Number of Lines"] != "1": failures.append("line_count")
    pdf_hash = row["_pdf_hash"]
    if pdf_hash not in PDF_PROFILES or PDF_PROFILES[pdf_hash]["kind"] != "ferrite": failures.append("no_local_datasheet")
    elif normalized_token(row["MPN"]) not in pdf_text[pdf_hash]: failures.append("mpn_not_in_datasheet")
    try:
        parse_quantity(row["Impedance @ Frequency"].split("@")[0], "ohm")
        if "@" not in row["Impedance @ Frequency"]: raise ValueError
        if row["Tolerance"] not in {"", "-"}:
            parse_percent(row["Tolerance"])
        parse_quantity(row["DC Resistance(DCR)"], "ohm")
        parse_quantity(row["Current Rating"], "A")
    except ValueError:
        failures.append("unparseable_electrical_data")
    return failures


def zener_voltage(row: dict[str, str]) -> Decimal:
    if row["MPN"] == "MMSZ5232B":
        return Decimal("5.6")
    return parse_quantity(row["Zener Voltage(Nom)"], "V")


def eligible_zener(row: dict[str, str], pdf_text: dict[str, str]) -> list[str]:
    failures = []
    if row["Package"] not in ZENER_FOOTPRINTS: failures.append("package")
    if row["Packaging"] != "Tape & Reel (TR)": failures.append("packaging")
    if int(row["Availability"] or 0) < 1000: failures.append("stock")
    if row["Diode Configuration"] != "1 Independent": failures.append("configuration")
    pdf_hash = row["_pdf_hash"]
    if pdf_hash not in PDF_PROFILES or PDF_PROFILES[pdf_hash]["kind"] != "zener": failures.append("no_local_datasheet")
    elif normalized_token(row["MPN"]) not in pdf_text[pdf_hash]: failures.append("mpn_not_in_datasheet")
    try:
        zener_voltage(row)
        parse_quantity(row["Pd - Power Dissipation"], "W")
    except ValueError:
        failures.append("unparseable_electrical_data")
    if not re.fullmatch(r"[0-9.]+V~[0-9.]+V", row["Zener Voltage(Range)"]): failures.append("voltage_range")
    return failures


def select_ferrites(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[(row["Package"], row["Impedance @ Frequency"])].append(row)
    def rank(row: dict[str, str]) -> tuple[Decimal, Decimal, Decimal, int, str]:
        tolerance = parse_percent(row["Tolerance"]) if row["Tolerance"] not in {"", "-"} else Decimal("Infinity")
        return (-parse_quantity(row["Current Rating"], "A"), parse_quantity(row["DC Resistance(DCR)"], "ohm"), tolerance, -int(row["Availability"]), row["MPN"])
    return sorted((min(group, key=rank) for group in groups.values()), key=lambda row: (row["Package"], parse_quantity(row["Impedance @ Frequency"].split("@")[0], "ohm"), row["Impedance @ Frequency"]))


def select_zeners(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    groups: dict[tuple[str, Decimal], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[(row["Package"], zener_voltage(row))].append(row)
    def inferred_tolerance(row: dict[str, str]) -> Decimal:
        if row["Tolerance"] not in {"", "-"}: return parse_percent(row["Tolerance"])
        low, high = (Decimal(value.rstrip("V")) for value in row["Zener Voltage(Range)"].split("~"))
        return (high - low) / (Decimal(2) * zener_voltage(row)) * Decimal(100)
    def rank(row: dict[str, str]) -> tuple[Decimal, Decimal, int, str]:
        return (-parse_quantity(row["Pd - Power Dissipation"], "W"), inferred_tolerance(row), -int(row["Availability"]), row["MPN"])
    return sorted((min(group, key=rank) for group in groups.values()), key=lambda row: (row["Package"], zener_voltage(row)))


def datasheet_link(kind: str, pdf_hash: str) -> str:
    folder = "PL Magnetics Ferrite" if kind == "ferrite" else "PL Diode Zener"
    return f"${{PL_SYMBOL_DIR}}/{folder}/Datasheets/{PDF_PROFILES[pdf_hash]['filename']}"


def build_ferrite(row: dict[str, str]) -> tuple[str, str]:
    profile = PDF_PROFILES[row["_pdf_hash"]]
    name = row["MPN"]
    tolerance = row["Tolerance"] if row["Tolerance"] not in {"", "-"} else "Not Specified"
    description = f"{row['Manufacturer']} {profile['series']} series {profile['technology'].lower()}, {row['Impedance @ Frequency']}, {tolerance}, {row['Current Rating']}, {row['DC Resistance(DCR)']} DCR, {row['Package']}, {row['Operating Temperature']}"
    properties = [
        ("Reference", "FB", "reference"), ("Value", row["MPN"], "value"),
        ("Footprint", f"PL Magnetics Ferrite:{FERRITE_FOOTPRINTS[row['Package']]}", "footprint"),
        ("Datasheet", datasheet_link("ferrite", row["_pdf_hash"]), "hidden"), ("Description", description, "hidden"),
        ("Manufacturer", row["Manufacturer"], "hidden"), ("Ferrite Series", str(profile["series"]), "hidden"),
        ("Automotive Grade", str(profile["automotive"]), "hidden"), ("Technology", str(profile["technology"]), "hidden"),
        ("Tolerance", tolerance, "hidden"), ("MPN", row["MPN"], "hidden"), ("LCSC Part #", row["LCSC Part#"], "hidden"),
        ("Impedance @ Frequency", row["Impedance @ Frequency"], "hidden"), ("Number of Lines", row["Number of Lines"], "hidden"),
        ("DCR", row["DC Resistance(DCR)"], "hidden"), ("Rated Current", row["Current Rating"], "hidden"),
        ("Package", row["Package"], "hidden"), ("Operating Temperature", row["Operating Temperature"], "hidden"),
        ("Packaging", row["Packaging"], "hidden"), ("MSL", str(profile["msl"]), "hidden"),
        ("RoHS", str(profile["rohs"]), "hidden"), ("Halogen Free", str(profile["halogen"]), "hidden"),
        ("ki_keywords", "L ferrite bead inductor filter", "hidden"), ("ki_fp_filters", "FL* *Ferrite*", "hidden"),
    ]
    block = f'\t(symbol "{quote(name)}"\r\n\t\t(extends "Ferrite_Bead_Template")\r\n'
    block += "".join(property_block(p, v, "ferrite", s) for p, v, s in properties)
    block += "\t\t(embedded_fonts no)\r\n\t)\r\n"
    return name, block


def format_voltage(voltage: Decimal) -> str:
    return f"{canonical_decimal(voltage)}V"


def build_zener(row: dict[str, str]) -> tuple[str, str]:
    profile = PDF_PROFILES[row["_pdf_hash"]]
    voltage = format_voltage(zener_voltage(row))
    name = f"{voltage}_{row['MPN']}"
    template = "Zener_SOT23_Template" if row["Package"] == "SOT-23" else "Zener_Template"
    tolerance = "±5%"
    description = f"R+O {profile['series']} series silicon Zener diode, {voltage}, {tolerance}, {row['Pd - Power Dissipation']}, {row['Package']}, {row['Operating Junction Temperature Range']}"
    properties = [
        ("Reference", "D", "reference"), ("Value", voltage, "value"),
        ("Footprint", f"PL Diode Zener:{ZENER_FOOTPRINTS[row['Package']]}", "footprint"),
        ("Datasheet", datasheet_link("zener", row["_pdf_hash"]), "hidden"), ("Description", description, "hidden"),
        ("Manufacturer", "R+O", "hidden"), ("Zener Series", str(profile["series"]), "hidden"),
        ("Automotive Grade", str(profile["automotive"]), "hidden"), ("Technology", "Silicon", "hidden"),
        ("Diode Configuration", row["Diode Configuration"], "hidden"), ("Tolerance", tolerance, "hidden"),
        ("MPN", row["MPN"], "hidden"), ("LCSC Part #", row["LCSC Part#"], "hidden"),
        ("Zener Voltage", voltage, "hidden"), ("Zener Voltage Range", row["Zener Voltage(Range)"], "hidden"),
        ("Rated Power", row["Pd - Power Dissipation"], "hidden"),
        ("Reverse Leakage Current", row["Reverse Leakage Current (Ir)"], "hidden"),
        ("Zener Impedance Zzt", row["Impedance(Zzt)"], "hidden"), ("Zener Impedance Zzk", row["Impedance(Zzk)"], "hidden"),
        ("Package", row["Package"], "hidden"), ("Operating Junction Temperature", row["Operating Junction Temperature Range"], "hidden"),
        ("Packaging", row["Packaging"], "hidden"), ("MSL", str(profile["msl"]), "hidden"),
        ("RoHS", str(profile["rohs"]), "hidden"), ("Halogen Free", str(profile["halogen"]), "hidden"),
        ("ki_keywords", "diode zener", "hidden"), ("ki_fp_filters", "TO-???* *_Diode_* *SingleDiode* D_*", "hidden"),
    ]
    block = f'\t(symbol "{quote(name)}"\r\n\t\t(extends "{template}")\r\n'
    block += "".join(property_block(p, v, "zener", s) for p, v, s in properties)
    block += "\t\t(embedded_fonts no)\r\n\t)\r\n"
    return name, block


def existing_ferrite_keys(symbols: list[dict[str, object]]) -> dict[tuple[str, str], list[str]]:
    keys: dict[tuple[str, str], list[str]] = defaultdict(list)
    for symbol in symbols:
        props = symbol["properties"]
        assert isinstance(props, dict)
        footprint = str(props.get("Footprint", "")).split(":")[-1]
        impedance = str(props.get("Impedance @ Frequency", props.get("Value", "")))
        if footprint and impedance:
            keys[(footprint, impedance)].append(str(symbol["name"]))
    return keys


def existing_zener_keys(symbols: list[dict[str, object]]) -> dict[tuple[str, Decimal], list[str]]:
    keys: dict[tuple[str, Decimal], list[str]] = defaultdict(list)
    reverse_footprints = {value: key for key, value in ZENER_FOOTPRINTS.items()}
    reverse_footprints.update({"SOD-323F": "SOD-323F", "D_SOD-523": "SOD-523", "D_SMA": "SMA", "SOD-923": "SOD-923"})
    for symbol in symbols:
        props = symbol["properties"]
        assert isinstance(props, dict)
        value = str(props.get("Zener Voltage", props.get("Value", "")))
        footprint = str(props.get("Footprint", "")).split(":")[-1]
        if not footprint or not re.fullmatch(r"[0-9.]+V", value):
            continue
        keys[(reverse_footprints.get(footprint, footprint), Decimal(value[:-1]))].append(str(symbol["name"]))
    return keys


def write_csv(path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def run_cli(library: Path, symbols: list[str], output_root: Path, log) -> None:
    for index, symbol in enumerate(symbols):
        output = output_root / f"{index}_{re.sub(r'[^A-Za-z0-9_-]', '_', symbol)}"
        output.mkdir(parents=True)
        command = [str(KICAD_CLI), "sym", "export", "svg", "--output", str(output), "--symbol", symbol, str(library)]
        result = subprocess.run(command, text=True, capture_output=True, timeout=120)
        log(f"CLI command={subprocess.list2cmdline(command)} exit={result.returncode}")
        if result.stdout.strip(): log(f"CLI stdout={result.stdout.strip()}")
        if result.stderr.strip(): log(f"CLI stderr={result.stderr.strip()}")
        exports = list(output.glob("*.svg"))
        if result.returncode != 0 or not exports or any(item.stat().st_size == 0 for item in exports):
            raise RuntimeError(f"KiCad CLI validation failed for {symbol}")


def main() -> int:
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    logs_dir = FERRITE_ROOT / "Logs"
    logs_dir.mkdir(exist_ok=True)
    log_path = logs_dir / f"ferrite_zener_update_{run_id}.log"
    log_stream = log_path.open("w", encoding="utf-8", newline="\n")
    def log(message: str) -> None:
        log_stream.write(f"[{datetime.now().isoformat(timespec='seconds')}] {message}\n")
        log_stream.flush(); os.fsync(log_stream.fileno())

    mutation_started = False
    backups: dict[Path, Path] = {}
    created_files: list[Path] = []
    created_dirs: list[Path] = []
    footprint_hashes: dict[Path, str] = {}
    try:
        log("BEGIN combined ferrite and Zener symbol update")
        if not KICAD_CLI.is_file(): raise FileNotFoundError(KICAD_CLI)
        original_bytes: dict[Path, bytes] = {}
        original_symbols: dict[str, list[dict[str, object]]] = {}
        for kind, library in (("ferrite", FERRITE_LIBRARY), ("zener", ZENER_LIBRARY)):
            if not library.is_file() or sha256(library) != EXPECTED_LIBRARY_HASHES[library]:
                raise ValueError(f"Library missing or changed: {library}")
            data = library.read_bytes()
            if data.startswith(b"\xef\xbb\xbf") or b"\n" in data.replace(b"\r\n", b""):
                raise ValueError(f"Encoding/newline invariant failed: {library}")
            text = data.decode("utf-8")
            symbols = parse_top_level_symbols(text)
            if len(symbols) != EXPECTED_EXISTING_SYMBOLS[kind]:
                raise ValueError(f"Existing symbol count changed for {kind}: {len(symbols)}")
            original_bytes[library] = data
            original_symbols[kind] = symbols
            log(f"INPUT kind={kind} library={library} bytes={len(data)} sha256={sha256(library)} symbols={len(symbols)}")

        for package, name in FERRITE_FOOTPRINTS.items():
            path = FERRITE_FOOTPRINT_ROOT / f"{name}.kicad_mod"
            if not path.is_file(): raise FileNotFoundError(path)
            footprint_hashes[path] = sha256(path); log(f"FOOTPRINT kind=ferrite package={package} path={path} sha256={footprint_hashes[path]}")
        for package, name in ZENER_FOOTPRINTS.items():
            path = ZENER_FOOTPRINT_ROOT / f"{name}.kicad_mod"
            if not path.is_file(): raise FileNotFoundError(path)
            footprint_hashes[path] = sha256(path); log(f"FOOTPRINT kind=zener package={package} path={path} sha256={footprint_hashes[path]}")

        pdf_text: dict[str, str] = {}
        for pdf_hash, profile in PDF_PROFILES.items():
            path = DOWNLOADS / f"{pdf_hash}.pdf"
            if not path.is_file() or sha256(path) != PDF_HASHES[pdf_hash]:
                raise ValueError(f"Supplied PDF missing or changed: {path}")
            reader = PdfReader(path)
            if not reader.pages: raise ValueError(f"PDF has no pages: {path}")
            text = " ".join("\n".join((page.extract_text() or "") for page in reader.pages).split())
            for token in profile["tokens"]:
                if " ".join(str(token).split()).lower() not in text.lower():
                    raise ValueError(f"PDF {path.name} missing required token {token!r}")
            pdf_text[pdf_hash] = normalized_token(text)
            log(f"PDF kind={profile['kind']} source={path} destination={profile['filename']} pages={len(reader.pages)} bytes={path.stat().st_size} sha256={sha256(path)}")

        ferrite_raw = read_rows(range(73, 80), set(FERRITE_COLUMNS) | {"Datasheet", "Pricing($)"}, log)
        zener_raw = read_rows(range(57, 73), set(ZENER_COLUMNS) | {"Datasheet", "Pricing($)"}, log)
        if len(ferrite_raw) != EXPECTED["ferrite"]["raw"] or len(zener_raw) != EXPECTED["zener"]["raw"]:
            raise ValueError("Raw source row counts changed")
        ferrite_unique = deduplicate(ferrite_raw, pdf_text, log)
        zener_unique = deduplicate(zener_raw, pdf_text, log)
        if len(ferrite_unique) != EXPECTED["ferrite"]["unique"] or len(zener_unique) != EXPECTED["zener"]["unique"]:
            raise ValueError("Unique source row counts changed")

        eligible: dict[str, list[dict[str, str]]] = {"ferrite": [], "zener": []}
        exclusions: dict[str, Counter[str]] = {"ferrite": Counter(), "zener": Counter()}
        for kind, rows, checker in (("ferrite", ferrite_unique, eligible_ferrite), ("zener", zener_unique, eligible_zener)):
            for row in rows:
                failures = checker(row, pdf_text)
                if failures:
                    exclusions[kind].update(failures)
                    log(f"EXCLUDE kind={kind} lcsc={row['LCSC Part#']} mpn={row['MPN']} reasons={','.join(failures)}")
                else:
                    eligible[kind].append(row)
            if len(eligible[kind]) != EXPECTED[kind]["eligible"]:
                raise ValueError(f"Eligible {kind} count changed: {len(eligible[kind])}")
        selected = {"ferrite": select_ferrites(eligible["ferrite"]), "zener": select_zeners(eligible["zener"])}
        for kind in selected:
            if len(selected[kind]) != EXPECTED[kind]["selected"]:
                raise ValueError(f"Selected {kind} count changed: {len(selected[kind])}")

        ferrite_existing_keys = existing_ferrite_keys(original_symbols["ferrite"])
        zener_existing_keys = existing_zener_keys(original_symbols["zener"])
        skipped = {"ferrite": [], "zener": []}
        additions = {"ferrite": [], "zener": []}
        for row in selected["ferrite"]:
            key = (FERRITE_FOOTPRINTS[row["Package"]], row["Impedance @ Frequency"])
            (skipped["ferrite"] if key in ferrite_existing_keys else additions["ferrite"]).append(row)
        for row in selected["zener"]:
            key = (row["Package"], zener_voltage(row))
            (skipped["zener"] if key in zener_existing_keys else additions["zener"]).append(row)
        for kind in additions:
            if len(skipped[kind]) != EXPECTED[kind]["skips"] or len(additions[kind]) != EXPECTED[kind]["parts"]:
                raise ValueError(f"Skip/addition counts changed for {kind}: {len(skipped[kind])}/{len(additions[kind])}")

        for row in selected["ferrite"]:
            log(f"SELECT kind=ferrite name={row['MPN']} lcsc={row['LCSC Part#']} impedance={row['Impedance @ Frequency']} package={row['Package']} current={row['Current Rating']} dcr={row['DC Resistance(DCR)']} tolerance={row['Tolerance']} stock={row['Availability']} pdf={row['_pdf_hash']}")
        for row in selected["zener"]:
            correction = " corrected_csv_5.4V_to_datasheet_5.6V=yes" if row["MPN"] == "MMSZ5232B" else ""
            log(f"SELECT kind=zener name={format_voltage(zener_voltage(row))}_{row['MPN']} lcsc={row['LCSC Part#']} voltage={format_voltage(zener_voltage(row))} package={row['Package']} power={row['Pd - Power Dissipation']} stock={row['Availability']} pdf={row['_pdf_hash']}{correction}")
        for row in skipped["zener"]:
            key = (row["Package"], zener_voltage(row))
            log(f"SKIP kind=zener name={format_voltage(zener_voltage(row))}_{row['MPN']} lcsc={row['LCSC Part#']} reason=same_voltage_and_footprint existing={','.join(zener_existing_keys[key])}")

        generated: dict[str, list[tuple[str, str]]] = {
            "ferrite": [ferrite_template()] + [build_ferrite(row) for row in additions["ferrite"]],
            "zener": [zener_sot23_template()] + [build_zener(row) for row in additions["zener"]],
        }
        for kind in generated:
            generated[kind] = sorted(generated[kind], key=lambda item: item[0])
            names = [name for name, _ in generated[kind]]
            existing_names = {str(symbol["name"]) for symbol in original_symbols[kind]}
            if len(names) != len(set(names)) or set(names) & existing_names:
                raise ValueError(f"Generated name collision for {kind}")
            for name, _ in generated[kind]: log(f"ADD kind={kind} name={name}")

        candidate_text: dict[str, str] = {}
        for kind, library in (("ferrite", FERRITE_LIBRARY), ("zener", ZENER_LIBRARY)):
            original_text = original_bytes[library].decode("utf-8")
            insertion = root_close_offset(original_text)
            candidate = original_text[:insertion] + "".join(block for _, block in generated[kind]) + original_text[insertion:]
            if not parentheses_balanced(candidate): raise ValueError(f"Unbalanced candidate: {kind}")
            symbols = parse_top_level_symbols(candidate)
            if len(symbols) != EXPECTED[kind]["final"]: raise ValueError(f"Final symbol count mismatch: {kind}={len(symbols)}")
            names = [str(symbol["name"]) for symbol in symbols]
            if len(names) != len(set(names)): raise ValueError(f"Duplicate final names: {kind}")
            for before, after in zip(original_symbols[kind], symbols[:len(original_symbols[kind])]):
                if before["block"] != after["block"]: raise ValueError(f"Existing symbol changed: {before['name']}")
            for symbol in symbols:
                if symbol["extends"] and symbol["extends"] not in names: raise ValueError(f"Bad inheritance: {symbol['name']} -> {symbol['extends']}")
            candidate_text[kind] = candidate

        with tempfile.TemporaryDirectory(prefix="pl_ferrite_zener_stage_") as temporary:
            stage = Path(temporary)
            staged_libraries = {"ferrite": stage / FERRITE_LIBRARY.name, "zener": stage / ZENER_LIBRARY.name}
            staged_libraries["ferrite"].write_bytes(candidate_text["ferrite"].encode("utf-8"))
            staged_libraries["zener"].write_bytes(candidate_text["zener"].encode("utf-8"))
            staged_csvs: dict[tuple[str, str], Path] = {}
            for kind, rows_unique, columns in (("ferrite", ferrite_unique, FERRITE_COLUMNS), ("zener", zener_unique, ZENER_COLUMNS)):
                for label, rows in (("merged", rows_unique), ("selected", selected[kind]), ("additions", additions[kind])):
                    path = stage / f"LCSCSearchDownload_{kind}_{label}.csv"
                    write_csv(path, rows, columns)
                    staged_csvs[(kind, label)] = path
                    with path.open("r", encoding="utf-8", newline="") as stream:
                        reader = csv.DictReader(stream)
                        if "Datasheet" in (reader.fieldnames or []) or "Pricing($)" in (reader.fieldnames or []): raise ValueError(f"Forbidden processed CSV column: {path}")
                        count = sum(1 for _ in reader)
                    expected_count = {"merged": EXPECTED[kind]["unique"], "selected": EXPECTED[kind]["selected"], "additions": EXPECTED[kind]["parts"]}[label]
                    if count != expected_count: raise ValueError(f"Staged CSV count mismatch: {path}")
                    log(f"STAGED kind={kind} csv={path.name} rows={count} sha256={sha256(path)}")

            ferrite_reps = ["BPH403025R5-530T"] + [next(name for name, _ in generated["ferrite"] if name == row["MPN"]) for row in (next(r for r in additions["ferrite"] if r["Package"] == package) for package in FERRITE_FOOTPRINTS)]
            zener_reps = ["12V_MM3Z12VB"] + [next(name for name, _ in generated["zener"] if name.endswith("_" + row["MPN"])) for row in (next(r for r in additions["zener"] if r["Package"] == package) for package in ZENER_FOOTPRINTS)]
            run_cli(staged_libraries["ferrite"], ferrite_reps, stage / "pre_ferrite", log)
            run_cli(staged_libraries["zener"], zener_reps, stage / "pre_zener", log)
            log("PREINSTALL validation passed")

            destinations = []
            for kind, root, indices in (("ferrite", FERRITE_ROOT, range(73, 80)), ("zener", ZENER_ROOT, range(57, 73))):
                source_dir = root / "Data" / "LCSC" / "Source" / f"Batch_{run_id}"
                processed_dir = root / "Data" / "LCSC" / "Processed"
                datasheets_dir = root / "Datasheets"
                destinations.extend(source_dir / f"LCSCSearchDownload({index}).csv" for index in indices)
                destinations.extend(processed_dir / staged_csvs[(kind, label)].name for label in ("merged", "selected", "additions"))
                destinations.extend(datasheets_dir / str(profile["filename"]) for profile in PDF_PROFILES.values() if profile["kind"] == kind)
            if any(path.exists() for path in destinations): raise FileExistsError("One-shot destination already exists")

            for root, library in ((FERRITE_ROOT, FERRITE_LIBRARY), (ZENER_ROOT, ZENER_LIBRARY)):
                backup_dir = root / "Backups" / run_id
                backup_dir.mkdir(parents=True, exist_ok=False); created_dirs.append(backup_dir)
                backup = backup_dir / library.name
                shutil.copy2(library, backup)
                if sha256(backup) != EXPECTED_LIBRARY_HASHES[library]: raise RuntimeError(f"Backup verification failed: {library}")
                backups[library] = backup
                log(f"BACKUP library={library} destination={backup} sha256={sha256(backup)}")

            mutation_started = True
            for kind, root, indices in (("ferrite", FERRITE_ROOT, range(73, 80)), ("zener", ZENER_ROOT, range(57, 73))):
                source_dir = root / "Data" / "LCSC" / "Source" / f"Batch_{run_id}"
                processed_dir = root / "Data" / "LCSC" / "Processed"
                datasheets_dir = root / "Datasheets"
                for directory in (source_dir, processed_dir, datasheets_dir):
                    if not directory.exists(): directory.mkdir(parents=True); created_dirs.append(directory)
                for index in indices:
                    source = DOWNLOADS / f"LCSCSearchDownload({index}).csv"; destination = source_dir / source.name
                    shutil.copy2(source, destination); created_files.append(destination)
                    log(f"COPY kind={kind} source={source} destination={destination} sha256={sha256(destination)}")
                for label in ("merged", "selected", "additions"):
                    staged = staged_csvs[(kind, label)]; destination = processed_dir / staged.name
                    os.replace(staged, destination); created_files.append(destination)
                    log(f"INSTALL kind={kind} processed={destination} sha256={sha256(destination)}")
                for pdf_hash, profile in PDF_PROFILES.items():
                    if profile["kind"] != kind: continue
                    source = DOWNLOADS / f"{pdf_hash}.pdf"; destination = datasheets_dir / str(profile["filename"])
                    shutil.copy2(source, destination); created_files.append(destination)
                    log(f"COPY kind={kind} datasheet={destination} sha256={sha256(destination)}")

            os.replace(staged_libraries["ferrite"], FERRITE_LIBRARY)
            os.replace(staged_libraries["zener"], ZENER_LIBRARY)
            log("INSTALL atomic library replacements completed")

            for kind, library in (("ferrite", FERRITE_LIBRARY), ("zener", ZENER_LIBRARY)):
                symbols = parse_top_level_symbols(library.read_bytes().decode("utf-8"))
                if len(symbols) != EXPECTED[kind]["final"]: raise RuntimeError(f"Postinstall count mismatch: {kind}")
                for before, after in zip(original_symbols[kind], symbols[:len(original_symbols[kind])]):
                    if before["block"] != after["block"]: raise RuntimeError(f"Postinstall existing symbol changed: {before['name']}")
                log(f"FINAL kind={kind} library={library} symbols={len(symbols)} bytes={library.stat().st_size} sha256={sha256(library)}")
            for footprint, expected_hash in footprint_hashes.items():
                if sha256(footprint) != expected_hash: raise RuntimeError(f"Footprint changed: {footprint}")
            for root in (FERRITE_ROOT, ZENER_ROOT):
                for bak in root.glob("*.bak"):
                    log(f"UNCHANGED_BAK path={bak} sha256={sha256(bak)}")
            run_cli(FERRITE_LIBRARY, ferrite_reps, stage / "post_ferrite", log)
            run_cli(ZENER_LIBRARY, zener_reps, stage / "post_zener", log)
            log(f"COUNTS ferrite={EXPECTED['ferrite']} zener={EXPECTED['zener']}")
            log(f"EXCLUSIONS ferrite={dict(exclusions['ferrite'])} zener={dict(exclusions['zener'])}")
            log("SUCCESS update completed; rollback not required")
        return 0
    except Exception as error:
        log(f"ERROR {type(error).__name__}: {error}")
        if mutation_started:
            log("ROLLBACK started")
            rollback_errors = []
            for library, backup in backups.items():
                try:
                    if backup.is_file(): shutil.copy2(backup, library)
                except Exception as rollback_error: rollback_errors.append(f"restore {library}: {rollback_error}")
            for path in reversed(created_files):
                try:
                    if path.is_file(): path.unlink()
                except Exception as rollback_error: rollback_errors.append(f"remove {path}: {rollback_error}")
            for path in sorted(created_dirs, key=lambda item: len(item.parts), reverse=True):
                try:
                    if path.is_dir() and not any(path.iterdir()): path.rmdir()
                except Exception as rollback_error: rollback_errors.append(f"remove directory {path}: {rollback_error}")
            log("ROLLBACK " + ("FAILED " + "; ".join(rollback_errors) if rollback_errors else "completed"))
        return 1
    finally:
        log_stream.close()
        print(log_path)


if __name__ == "__main__":
    sys.exit(main())
