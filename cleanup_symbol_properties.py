#!/usr/bin/env python3
"""Normalize top-level KiCad symbol properties according to the cleanup spec.

The default mode is a dry run. Use ``--apply`` only after reviewing the summary.
Only the 64 active library files are considered; archives, staged libraries,
backups, and ``New_Library.kicad_sym`` are excluded.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
import os
import re
import subprocess
import sys

from find_missing_datasheets import (
    PROPERTY_RE,
    SYMBOL_NAME_RE,
    decode_kicad_string,
    top_level_symbol_blocks,
)


CORE = {"Reference", "Value", "Footprint", "Datasheet", "Description"}
SYSTEM = {"ki_keywords", "ki_fp_filters", "ki_locked", "Sim.Enable"}
ID = {"MPN", "Manufacturer"}
BATCH = {
    "LCSC Part #", "Package", "Packaging", "MSL", "RoHS", "Halogen Free",
    "Automotive Grade", "Technology",
}
COMMON = CORE | SYSTEM
EMPTY_CUSTOM = {"", "n/a", "none", "unknown"}
GLOBAL_DROP = {
    "Availability", "Check_prices", "Price", "SnapEDA_Link", "Description_1",
    "PARTREV", "STANDARD", "approval_checks", "approval_properties",
}


def fields(*names: str) -> set[str]:
    return set(names)


ALLOW: dict[str, set[str]] = {
    "PL Battery": COMMON | ID,
    "PL Busbar": COMMON | ID | fields("Material", "Dimensions"),
    "PL Capacitor Electrolytic": COMMON | ID | fields(
        "Tolerance", "Rated Voltage", "ESR", "Ripple Current", "Operating Temperature"
    ),
    "PL Capacitor MLCC": COMMON | ID | BATCH | fields(
        "Capacitor Series", "Capacitor Class", "Dielectric", "Tolerance",
        "Capacitance", "Rated Voltage", "Operating Temperature",
    ),
    "PL Capacitor Polymer": COMMON | ID | fields(
        "Tolerance", "Rated Voltage", "ESR", "Ripple Current", "Operating Temperature"
    ),
    "PL Connector Audio": COMMON | ID | fields(
        "Connector Type", "Number of Conductors", "Pin Count", "Rated Current"
    ),
    "PL Connector Barrel": COMMON | ID | fields(
        "Connector Type", "Pin Diameter", "Rated Current", "Rated Voltage"
    ),
    "PL Connector Header": COMMON | ID | fields(
        "Pin Count", "Number of Rows", "Pitch", "Rated Current", "Rated Voltage"
    ),
    "PL Connector Power": COMMON | ID | fields(
        "Number of Contacts", "Pitch", "Rated Current", "Rated Voltage"
    ),
    "PL Connector RF": COMMON | ID | fields(
        "Connector Type", "Impedance", "Frequency Range", "Board Thickness"
    ),
    "PL Connector Terminal": COMMON | ID | fields(
        "Number of Contacts", "Pitch", "Rated Current", "Rated Voltage",
        "Wire Gauge Range", "Operating Temperature",
    ),
    "PL Connector USB": COMMON | ID | fields(
        "Connector Type", "USB Version", "Number of Contacts", "Rated Current",
        "Mounting Type", "Height",
    ),
    "PL Diode LED": COMMON | ID | BATCH | fields(
        "Color", "Forward Voltage", "Forward Current", "Viewing Angle", "Wavelength",
        "Luminous Intensity", "Label", "Operating Temperature",
    ),
    "PL Diode Schottky": COMMON | ID | fields(
        "Forward Voltage", "Rated Current", "Reverse Voltage"
    ),
    "PL Diode Silicon": COMMON | ID | fields(
        "Forward Voltage", "Rated Current", "Reverse Recovery Time", "Reverse Voltage"
    ),
    "PL Diode TVS": COMMON | ID | BATCH | fields(
        "TVS Series", "Polarity", "Number of Channels", "Reverse Standoff Voltage",
        "Breakdown Voltage", "Clamping Voltage", "Reverse Leakage Current",
        "Rated Power", "Rated Current", "Operating Temperature",
    ),
    "PL Diode Zener": COMMON | ID | BATCH | fields(
        "Zener Series", "Diode Configuration", "Tolerance", "Zener Voltage",
        "Zener Voltage Range", "Rated Power", "Reverse Leakage Current",
        "Zener Impedance Zzt", "Zener Impedance Zzk", "Operating Junction Temperature",
        "Operating Temperature", "Rated Current",
    ),
    "PL Display": COMMON | ID | fields("Resolution", "Interface", "Supply Voltage"),
    "PL Electromechanical Button": COMMON | ID | fields(
        "Action Type", "Mounting Type", "Rated Current", "Rated Voltage", "Contact Rating"
    ),
    "PL Electromechanical Navigation Switches": COMMON | ID | fields(
        "Number of Positions/Directions", "Actuation Force", "Rated Current",
        "Rated Voltage", "Contact Rating",
    ),
    "PL Graphic": COMMON | fields("Vin"),
    "PL IC ADC": COMMON | ID | fields(
        "Resolution", "Sample Rate", "Interface", "Number of Channels", "Supply Voltage"
    ),
    "PL IC Analog Switch": COMMON | ID | fields(
        "Number of Channels", "Supply Voltage", "Max Supply Voltage", "On-Resistance",
        "Off-Isolation", "Bandwidth",
    ),
    "PL IC Battery": COMMON | ID | fields(
        "Supply Voltage", "Charge Voltage", "Max Charge Current", "Operating Temperature"
    ),
    "PL IC Comparator": COMMON | ID | fields(
        "Input Offset Voltage", "Propagation Delay", "Supply Voltage"
    ),
    "PL IC Current Amplifier": COMMON | ID | fields(
        "Gain", "Common Mode Voltage", "Bandwidth", "Supply Voltage", "Input Offset Voltage"
    ),
    "PL IC DAC": COMMON | ID | fields(
        "Resolution", "Conversion Rate", "Interface", "Number of Channels", "Supply Voltage"
    ),
    "PL IC Digital": COMMON | ID | fields(
        "Supply Voltage", "Input Voltage Range", "Supply Current", "Logic Family",
        "Propagation Delay",
    ),
    "PL IC Flash": COMMON | ID | fields(
        "Memory Capacity", "Page Size", "Interface", "Supply Voltage"
    ),
    "PL IC Gate Driver": COMMON | ID | fields(
        "Supply Voltage Range", "Source Current", "Sink Current", "Rise Time", "Fall Time",
        "Propagation Delay",
    ),
    "PL IC Instrumentation Amplifier": COMMON | ID | fields(
        "Gain", "Bandwidth", "Common Mode Rejection Ratio", "Input Offset Voltage",
        "Supply Voltage",
    ),
    "PL IC Interface": COMMON | ID | fields(
        "Interface", "Data Rate", "Baud Rate", "Supply Voltage", "Number of Channels"
    ),
    "PL IC Isolator": COMMON | ID | fields(
        "Number of Channels", "Data Rate", "Isolation Voltage", "Supply Voltage"
    ),
    "PL IC Logic": COMMON | ID | fields(
        "Number of Channels", "Supply Voltage", "Propagation Delay", "Logic Family"
    ),
    "PL IC Opamp": COMMON | ID | fields(
        "Gain Bandwidth", "Slew Rate", "Input Offset Voltage", "Output Current",
        "Supply Voltage", "Number of Channels",
    ),
    "PL IC Power": COMMON | ID | fields(
        "Input Voltage Range", "Output Voltage", "Output Current", "Switching Frequency",
        "Efficiency", "Quiescent Current",
    ),
    "PL IC Power Management": COMMON | ID | fields(
        "Input Voltage Range", "Output Voltage", "Output Current", "Quiescent Current",
        "Operating Temperature",
    ),
    "PL IC PWM": COMMON | ID | fields(
        "Switching Frequency Range", "Supply Voltage", "Output Current"
    ),
    "PL IC Regulator Linear": COMMON | ID | fields(
        "Input Voltage Range", "Max Input Voltage", "Output Voltage", "Output Current",
        "Dropout Voltage", "PSRR", "Quiescent Current", "Operating Temperature",
    ),
    "PL IC uC": COMMON | ID | fields(
        "Core Architecture", "Clock Speed", "Flash Size", "RAM Size", "Supply Voltage",
        "Interfaces",
    ),
    "PL IC USB Interface": COMMON | ID | fields(
        "USB Compliance Version", "Data Rate", "Supply Voltage", "Isolation Voltage"
    ),
    "PL Magnetics Choke": COMMON | ID | fields(
        "Inductance", "Rated Current", "DCR", "Impedance @ Frequency", "Operating Temperature"
    ),
    "PL Magnetics Ferrite": COMMON | ID | BATCH | fields(
        "Ferrite Series", "Impedance @ Frequency", "Number of Lines", "DCR",
        "Rated Current", "Tolerance", "Operating Temperature",
    ),
    "PL Magnetics Inductor Power": COMMON | ID | fields(
        "Inductance", "Inductance Tolerance", "Rated Current", "Saturation Current", "DCR",
        "Self Resonant Frequency", "Shielding", "Core Material", "Mounting Technology",
        "Operating Temperature",
    ),
    "PL Magnetics Inductor Signal": COMMON | ID | fields(
        "Inductance", "Inductance Tolerance", "Rated Current", "Saturation Current", "DCR",
        "Self Resonant Frequency", "Shielding", "Operating Temperature",
    ),
    "PL Magnetics Transformer Signal": COMMON | ID | fields(
        "Primary Inductance", "Turns Ratio", "Frequency Range", "Rated Current", "DCR",
        "Isolation Voltage",
    ),
    "PL Mechanical Mounting Hole": COMMON | fields("Hole Diameter"),
    "PL Mechanical Spacer": COMMON | ID | fields("Thread Size", "Material", "Height"),
    "PL Net Tie": COMMON,
    "PL Optocoupler": COMMON | ID | fields(
        "Number of Channels", "Isolation Voltage", "Current Transfer Ratio", "Data Rate", "Height"
    ),
    "PL Oscillator Crystal": COMMON | ID | BATCH | fields(
        "Frequency", "Frequency Tolerance", "Frequency Stability", "Load Capacitance",
        "Equivalent Series Resistance", "Operating Temperature", "Supply Voltage",
    ),
    "PL Power Module": COMMON | ID | fields(
        "Nominal Input Voltage", "Input Voltage Range", "Output Voltage", "Output Current",
        "Output Power", "Efficiency", "Isolation Voltage",
    ),
    "PL Power Symbols": COMMON,
    "PL Resistor SMD": COMMON | ID | BATCH | fields(
        "Resistor Series", "Resistance", "Tolerance", "Rated Power", "Rated Voltage",
        "Maximum Overload Voltage", "Operating Temperature", "Temperature Coefficient", "Height",
    ),
    "PL Resistor Thermistor": COMMON | ID | fields(
        "Nominal Resistance", "Resistance Tolerance", "B Value Tolerance", "B0/50",
        "B25/50", "B25/75", "B25/85", "B25/100", "Operating Temperature",
    ),
    "PL Resistor Variable": COMMON | ID | fields(
        "Resistance Tolerance", "Rated Power", "Taper Type"
    ),
    "PL Test Point": COMMON | ID | fields("Label"),
    "PL Thermal": COMMON | ID | fields(
        "Thermal Resistance", "Thermal Conductivity", "Material", "Dimensions",
        "Operating Temperature", "Temperature Coefficient",
    ),
    "PL Transducer Acoustic": COMMON | ID | fields(
        "Frequency Range", "Resonant Frequency", "Rated Impedance", "SPL", "S/N"
    ),
    "PL Transistor BJT": COMMON | ID | fields(
        "Collector-Emitter Voltage", "Collector Current", "DC Current Gain", "Power Dissipation",
        "Operating Temperature",
    ),
    "PL Transistor FET": COMMON | ID | fields(
        "Drain-Source Voltage", "Continuous Drain Current", "On-Resistance",
        "Gate Threshold Voltage", "Gate Charge", "Power Dissipation", "Operating Temperature",
    ),
    "PL Transistor GaN": COMMON | ID | fields(
        "Drain-Source Voltage", "Continuous Drain Current", "Peak Drain Current", "On-Resistance",
        "Gate Threshold Voltage", "Gate Charge", "Gate Resistance", "Output Capacitance (Coss)",
    ),
    "PL Voltage Reference": COMMON | ID | fields(
        "Output Voltage", "Initial Accuracy", "Temperature Coefficient", "Operating Temperature",
        "Supply Current",
    ),
    "PL Wire Pad": COMMON | fields("Label"),
}


@dataclass(frozen=True)
class Property:
    name: str
    value: str
    name_start: int
    name_end: int
    value_start: int
    value_end: int
    full_start: int
    full_end: int


@dataclass
class Action:
    library: str
    symbol: str
    action: str
    source: str
    target: str
    value: str
    reason: str


def encode_kicad_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def expression_end(text: str, start: int) -> int:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
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
            if depth == 0:
                return index + 1
    raise ValueError("Unterminated property expression")


def top_level_property_records(block: str) -> list[Property]:
    records: list[Property] = []
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
            if depth == 1 and block.startswith("(property", index):
                match = PROPERTY_RE.match(block, index)
                if not match:
                    raise ValueError(f"Malformed property near offset {index}")
                expr_end = expression_end(block, index)
                line_start = block.rfind("\n", 0, index) + 1
                full_start = line_start if block[line_start:index].strip() == "" else index
                full_end = expr_end
                suffix = block[expr_end:]
                whitespace = re.match(r"[\t ]*(\r\n|\n|\r)", suffix)
                if whitespace:
                    full_end += whitespace.end()
                records.append(
                    Property(
                        decode_kicad_string(match.group(1)),
                        decode_kicad_string(match.group(2)),
                        match.start(1), match.end(1), match.start(2), match.end(2),
                        full_start, full_end,
                    )
                )
            depth += 1
        elif character == ")":
            depth -= 1
        index += 1
    return records


def primary_libraries(root: Path) -> list[Path]:
    result = []
    for path in sorted(root.rglob("*.kicad_sym")):
        relative = path.relative_to(root)
        lower_parts = {part.casefold() for part in relative.parts}
        if lower_parts & {".git", "backups", "data", "__pycache__"}:
            continue
        if path.name == "New_Library.kicad_sym":
            continue
        result.append(path)
    return result


def library_name(root: Path, path: Path) -> str:
    relative = path.relative_to(root)
    return relative.parts[0] if len(relative.parts) > 1 else path.stem


def canonical_name(library: str, symbol: str, name: str) -> str | None:
    if name in GLOBAL_DROP:
        return None
    if name in {"MANUFACTURER", "MF"}:
        return "Manufacturer"
    if name in {"MP", "Part Number"}:
        return "MPN"
    if name == "MAXIMUM_PACKAGE_HEIGHT":
        return "Height"

    aliases: dict[str, str | None] = {}
    if library in {"PL Connector Barrel", "PL Connector USB"}:
        aliases["Current Rating"] = "Rated Current"
    if library == "PL Connector Audio":
        aliases.update({
            "Contact Current Rating": "Rated Current",
            "Number of Poles/Pins": "Number of Conductors",
        })
    if library == "PL Connector Power":
        aliases["Pin Count"] = "Number of Contacts"
    if library == "PL Connector RF":
        aliases.update({"Frequency": "Frequency Range", "Max Frequency": "Frequency Range"})
    if library == "PL Connector Terminal":
        aliases["Wire Gauge"] = "Wire Gauge Range"
    if library == "PL Diode LED":
        aliases["Rated Current"] = "Forward Current"
        aliases["Luminous Intensity / Wavelength"] = (
            "Luminous Intensity" if symbol == "Red_0603" else None
        )
    if library == "PL Diode Schottky":
        aliases["Max Reverse Voltage"] = "Reverse Voltage"
    if library == "PL Diode Silicon":
        aliases["Rated Curretn"] = "Rated Current"
    if library == "PL Diode TVS":
        aliases.update({"Reverse Standoff": "Reverse Standoff Voltage", "Voltage Breakdown": "Breakdown Voltage"})
    if library == "PL Diode Zener":
        aliases.update({"Reverese Leakage": "Reverse Leakage Current", "Reverse Leakage": "Reverse Leakage Current"})
    if library == "PL Display":
        aliases.update({"Interface Type": "Interface", "Operating Voltage": "Supply Voltage"})
    if library == "PL IC Comparator":
        aliases.update({"Offset Voltage": "Input Offset Voltage", "GBW": None, "Slew Rate": None})
    if library == "PL IC Current Amplifier":
        aliases["Offset Voltage"] = "Input Offset Voltage"
    if library == "PL IC DAC":
        aliases["Sample Rate"] = "Conversion Rate"
    if library == "PL IC Digital":
        aliases.update({"Current Supply": "Supply Current", "Voltage Supply": "Input Voltage Range"})
    if library == "PL IC Flash":
        aliases["Interface Type"] = "Interface"
    if library == "PL IC Interface":
        aliases["Protocol Type"] = "Interface"
    if library == "PL IC Logic":
        aliases["Number of Gates/Channels"] = "Number of Channels"
    if library == "PL IC Opamp":
        aliases.update({"Offset Voltage": "Input Offset Voltage", "Rated Output Current": "Output Current"})
    if library == "PL IC Regulator Linear":
        aliases.update({
            "Rated Current": "Output Current", "Voltage Dropout": "Dropout Voltage",
            "Voltage Droupout": "Dropout Voltage",
        })
    if library == "PL Magnetics Choke":
        aliases["Z@Freq"] = "Impedance @ Frequency"
    if library == "PL Magnetics Ferrite":
        aliases["Impedance"] = "Impedance @ Frequency"
    if library == "PL Magnetics Inductor Power":
        aliases.update({
            "L (µH)": "Inductance", "Tol. L": "Inductance Tolerance",
            "IR (A)": "Rated Current", "ISAT (A)": "Saturation Current",
            "RDC max. (mΩ)": "DCR", "DC Resistance": "DCR",
            "fres (MHz)": "Self Resonant Frequency", "Resonant Frequency": "Self Resonant Frequency",
            "SRF": "Self Resonant Frequency", "Shielded": "Shielding",
            "Rated current": "Rated Current", "Current Rating": "Rated Current",
            "Manufacturer URL": None, "Published Date": None, "Match Code": None,
            "Size": None, "Critical Parameter": None,
        })
    if library == "PL Magnetics Inductor Signal":
        aliases.update({"Tolerance": "Inductance Tolerance", "SRF": "Self Resonant Frequency", "Shielded": "Shielding"})
    if library == "PL Oscillator Crystal":
        aliases.update({"Stability": "Frequency Stability", "Tolerance": "Frequency Tolerance"})
    if library == "PL Power Module":
        aliases.update({
            "Input Voltage": "Nominal Input Voltage", "Vin (V)": None,
            "Vout (V)": None, "Iout (A)": None,
        })
    if library == "PL Resistor Thermistor":
        aliases.update({"Tolerance": None, "B-Constant/Beta": None})
    if library == "PL Resistor Variable":
        aliases.update({"Tolerance": "Resistance Tolerance", "R25": None})
    if library == "PL Transducer Acoustic":
        aliases["Impedance"] = "Rated Impedance"
    if library == "PL Transistor BJT":
        aliases.update({"Rated Current": "Collector Current", "Rated Power": "Power Dissipation"})
    if library == "PL Transistor FET":
        aliases.update({
            "Continous Drain Current": "Continuous Drain Current",
            "Vgs(th)": "Gate Threshold Voltage", "Vgs(th) (Max)": "Gate Threshold Voltage",
        })
    if library == "PL Transistor GaN":
        aliases.update({
            "Rated Voltage": "Drain-Source Voltage",
            "Rated Continous Current": "Continuous Drain Current",
            "Rated Continuous Current": "Continuous Drain Current",
            "Rated Peak Current": "Peak Drain Current", "On Resistance": "On-Resistance",
            "Coss": "Output Capacitance (Coss)",
        })
    return aliases.get(name, name)


# Exact-part resolutions made from the local/official datasheet or unambiguous source text.
OVERRIDES: dict[tuple[str, str, str], str] = {
    ("PL Connector USB", "GSB1C4621DSHR", "Manufacturer"): "Amphenol",
    ("PL Connector USB", "GSB1C4621DSHR", "USB Version"): "USB 2.0 Type-C",
    ("PL Connector USB", "UJ2-BH-BL1-TH", "USB Version"): "USB 2.0 Type-B",
    ("PL Connector Audio", "SJ1-3535NG", "Number of Conductors"): "3",
    ("PL IC ADC", "ADS131M04IPWR", "Resolution"): "24-bit",
    ("PL IC ADC", "ADS131M04IPWR", "Sample Rate"): "64kSPS",
    ("PL Power Module", "RFM-0505S", "Manufacturer"): "RECOM Power",
    ("PL Diode LED", "Emerald_Green_0603", "Forward Current"): "20mA",
    ("PL Diode LED", "Red_0603", "Luminous Intensity"): "100–200 mcd",
    ("PL Magnetics Inductor Power", "18uH_SRR1280-180M", "Rated Current"): "4.8A",
    ("PL Magnetics Inductor Power", "1.2uH_74437625200122", "Core Material"): "Metal alloy",
    ("PL Magnetics Inductor Power", "1.2uH_74437625200122", "Datasheet"): "https://www.we-online.com/components/products/datasheet/74437625200122.pdf",
    ("PL Magnetics Inductor Power", "1.2uH_74437625200122", "Inductance"): "1.2µH",
    ("PL Magnetics Inductor Power", "1.2uH_74437625200122", "Self Resonant Frequency"): "89.75MHz",
    ("PL Magnetics Inductor Power", "1.2uH_74437625200122", "ki_fp_filters"): "*WE-HCFT*2520*",
    ("PL Magnetics Inductor Power", "2.2uH_74437625200222", "Core Material"): "Metal alloy",
    ("PL Magnetics Inductor Power", "2.2uH_74437625200222", "Datasheet"): "https://www.we-online.com/components/products/datasheet/74437625200222.pdf",
    ("PL Magnetics Inductor Power", "2.2uH_74437625200222", "Inductance"): "2.2µH",
    ("PL Magnetics Inductor Power", "2.2uH_74437625200222", "Rated Current"): "70.6A",
    ("PL Magnetics Inductor Power", "2.2uH_74437625200222", "Saturation Current"): "122.4A",
    ("PL Magnetics Inductor Power", "2.2uH_74437625200222", "DCR"): "0.38mΩ",
    ("PL Magnetics Inductor Power", "2.2uH_74437625200222", "Self Resonant Frequency"): "62.24MHz",
    ("PL Magnetics Inductor Power", "2.2uH_74437625200222", "ki_fp_filters"): "*WE-HCFT*2520*",
    ("PL Magnetics Inductor Power", "6.8uH_74437625200682", "Core Material"): "Metal alloy",
    ("PL Magnetics Inductor Power", "6.8uH_74437625200682", "Datasheet"): "https://www.we-online.com/components/products/datasheet/74437625200682.pdf",
    ("PL Magnetics Inductor Power", "6.8uH_74437625200682", "DCR"): "1mΩ",
    ("PL Magnetics Inductor Power", "6.8uH_74437625200682", "Footprint"): "",
    ("PL Magnetics Inductor Power", "6.8uH_74437625200682", "Inductance"): "6.8µH",
    ("PL Magnetics Inductor Power", "6.8uH_74437625200682", "Rated Current"): "54.7A",
    ("PL Magnetics Inductor Power", "6.8uH_74437625200682", "ki_fp_filters"): "*WE-HCFT*2520*",
    ("PL Transistor GaN", "EPC2305", "Continuous Drain Current"): "133A",
    ("PL Transistor GaN", "EPC2306", "Continuous Drain Current"): "63A",
}

# Verified fields that were conflated in the source and therefore need a new property.
SYNTHETIC: dict[tuple[str, str, str], str] = {
    ("PL Connector Audio", "SJ1-3535NG", "Pin Count"): "5",
}

# In these groups the already-canonical property is the authoritative one; the alias is old,
# generic, or demonstrably copied from a different part.
PREFER_CANONICAL_LIBRARIES = {
    "PL Connector Terminal", "PL Magnetics Ferrite", "PL Magnetics Inductor Power",
    "PL Oscillator Crystal", "PL Transistor FET",
}


def normalized_value(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold().replace("±", "")


def hidden_property(name: str, value: str) -> str:
    return (
        f'\t\t(property "{encode_kicad_string(name)}" "{encode_kicad_string(value)}"\n'
        "\t\t\t(at 0 0 0)\n"
        "\t\t\t(show_name no)\n"
        "\t\t\t(do_not_autoplace no)\n"
        "\t\t\t(hide yes)\n"
        "\t\t\t(effects\n"
        "\t\t\t\t(font\n"
        "\t\t\t\t\t(size 1.27 1.27)\n"
        "\t\t\t\t)\n"
        "\t\t\t)\n"
        "\t\t)\n"
    )


def choose_candidate(
    library: str,
    symbol: str,
    target: str,
    candidates: list[Property],
) -> tuple[Property | None, str | None, str | None]:
    override = OVERRIDES.get((library, symbol, target))
    exact = [prop for prop in candidates if prop.name == target]
    if override is not None:
        return (exact[0] if exact else candidates[0]), override, "verified override"
    distinct = {normalized_value(prop.value) for prop in candidates}
    if len(distinct) == 1:
        return (exact[0] if exact else candidates[0]), None, "equivalent aliases"
    if exact and library in PREFER_CANONICAL_LIBRARIES:
        return exact[0], None, "canonical field preferred over stale/import alias"
    values = "; ".join(f"{prop.name}={prop.value!r}" for prop in candidates)
    return None, None, values


def rewrite_symbol(library: str, symbol: str, block: str) -> tuple[str, list[Action], list[str]]:
    properties = top_level_property_records(block)
    allowed = ALLOW[library]
    actions: list[Action] = []
    conflicts: list[str] = []
    candidates: dict[str, list[tuple[str, Property]]] = defaultdict(list)
    discarded: list[tuple[Property, str]] = []

    for prop in properties:
        target = canonical_name(library, symbol, prop.name)
        if target is None:
            discarded.append((prop, "discarded by schema"))
            continue
        if prop.name not in (CORE | SYSTEM) and prop.value.strip().casefold() in EMPTY_CUSTOM:
            discarded.append((prop, "empty/sentinel custom value"))
            continue
        if target not in allowed:
            discarded.append((prop, "not allowed in library schema"))
            continue
        candidates[target.casefold()].append((target, prop))

    selected: dict[int, tuple[str, str | None, str]] = {}
    duplicate_discards: list[tuple[Property, str]] = []
    for group in candidates.values():
        target = group[0][0]
        props = [item[1] for item in group]
        chosen, value_override, reason = choose_candidate(library, symbol, target, props)
        if chosen is None:
            conflicts.append(f"{target}: {reason}")
            continue
        selected[id(chosen)] = (target, value_override, reason or "kept")
        for prop in props:
            if prop is not chosen:
                duplicate_discards.append((prop, f"duplicate/alias of {target}"))

    if conflicts:
        actions.append(Action(library, symbol, "skip", "", "", "", " | ".join(conflicts)))
        return block, actions, conflicts

    edits: list[tuple[int, int, str]] = []
    for prop, reason in discarded + duplicate_discards:
        edits.append((prop.full_start, prop.full_end, ""))
        actions.append(Action(library, symbol, "remove", prop.name, "", prop.value, reason))

    for group in candidates.values():
        for _, prop in group:
            choice = selected.get(id(prop))
            if choice is None:
                continue
            target, value_override, reason = choice
            if prop.name != target:
                edits.append((prop.name_start, prop.name_end, encode_kicad_string(target)))
                actions.append(Action(library, symbol, "rename", prop.name, target, prop.value, reason))
            if value_override is not None and prop.value != value_override:
                edits.append((prop.value_start, prop.value_end, encode_kicad_string(value_override)))
                actions.append(Action(library, symbol, "replace value", target, target, value_override, reason))

    existing_targets = {target.casefold() for group in candidates.values() for target, _ in group}
    additions = [
        (target, value)
        for (item_library, item_symbol, target), value in SYNTHETIC.items()
        if item_library == library and item_symbol == symbol and target.casefold() not in existing_targets
    ]
    if additions:
        if not properties:
            raise ValueError(f"{library}:{symbol}: cannot place a synthetic property")
        for target, value in additions:
            if target not in allowed:
                raise ValueError(f"{library}:{symbol}: synthetic property {target!r} is not allowed")
            edits.append((properties[-1].full_end, properties[-1].full_end, hidden_property(target, value)))
            actions.append(Action(library, symbol, "add", "", target, value, "verified split field"))

    rewritten = block
    for start, end, replacement in sorted(edits, reverse=True):
        rewritten = rewritten[:start] + replacement + rewritten[end:]
    return rewritten, actions, []


def balanced(text: str) -> bool:
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


def validate_library(text: str, library: str) -> None:
    if not balanced(text):
        raise ValueError(f"{library}: unbalanced S-expression")
    names: list[str] = []
    blocks: dict[str, str] = {}
    for _, block in top_level_symbol_blocks(text):
        match = SYMBOL_NAME_RE.match(block)
        if not match:
            raise ValueError(f"{library}: top-level symbol without a name")
        name = decode_kicad_string(match.group(1))
        names.append(name)
        blocks[name] = block
        props = top_level_property_records(block)
        prop_names = {prop.name for prop in props}
        missing_core = CORE - prop_names
        if missing_core:
            raise ValueError(f"{library}:{name}: missing core properties {sorted(missing_core)}")
        unexpected = prop_names - ALLOW[library]
        if unexpected:
            raise ValueError(f"{library}:{name}: properties outside schema {sorted(unexpected)}")
        canonical = [prop.name.casefold() for prop in props]
        if len(canonical) != len(set(canonical)):
            raise ValueError(f"{library}:{name}: duplicate property names remain")
    if len(names) != len(set(names)):
        raise ValueError(f"{library}: duplicate symbol names")
    for name, block in blocks.items():
        match = re.search(r'^\t\(extends\s+"((?:\\.|[^"])*)"\)', block, re.MULTILINE)
        if match and decode_kicad_string(match.group(1)) not in blocks:
            raise ValueError(f"{library}:{name}: missing extends target")


def without_top_level_properties(text: str) -> str:
    edits: list[tuple[int, int]] = []
    for offset, block in top_level_symbol_blocks(text):
        edits.extend(
            (offset + prop.full_start, offset + prop.full_end)
            for prop in top_level_property_records(block)
        )
    pieces: list[str] = []
    cursor = 0
    for start, end in sorted(edits):
        pieces.append(text[cursor:start])
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


def transform_library(root: Path, path: Path, original: str) -> tuple[str, list[Action], list[str], int]:
    library = library_name(root, path)
    if library not in ALLOW:
        raise ValueError(f"No schema for {library}")
    replacements: list[tuple[int, int, str]] = []
    actions: list[Action] = []
    conflicts: list[str] = []
    symbol_count = 0
    for offset, block in top_level_symbol_blocks(original):
        match = SYMBOL_NAME_RE.match(block)
        if not match:
            raise ValueError(f"{library}: cannot read symbol name")
        symbol = decode_kicad_string(match.group(1))
        rewritten, symbol_actions, symbol_conflicts = rewrite_symbol(library, symbol, block)
        symbol_count += 1
        actions.extend(symbol_actions)
        conflicts.extend(f"{library}:{symbol}: {item}" for item in symbol_conflicts)
        if rewritten != block:
            replacements.append((offset, offset + len(block), rewritten))
    result = original
    for start, end, replacement in reversed(replacements):
        result = result[:start] + replacement + result[end:]
    if without_top_level_properties(original) != without_top_level_properties(result):
        raise ValueError(f"{library}: non-property symbol content changed")
    validate_library(result, library)
    return result, actions, conflicts, symbol_count


def source_text(root: Path, path: Path, source_ref: str | None) -> str:
    if source_ref is None:
        return path.read_text(encoding="utf-8")
    relative = path.relative_to(root).as_posix()
    completed = subprocess.run(
        ["git", "-C", str(root), "show", f"{source_ref}:{relative}"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout.decode("utf-8")


def write_reports(root: Path, actions: list[Action], conflicts: list[str], summary: Counter) -> None:
    audit_path = root / "SYMBOL_PROPERTY_CLEANUP_AUDIT.csv"
    with audit_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Library", "Symbol", "Action", "Source property", "Target property", "Value", "Reason"])
        for item in actions:
            writer.writerow([item.library, item.symbol, item.action, item.source, item.target, item.value, item.reason])

    report_path = root / "SYMBOL_PROPERTY_CLEANUP_REPORT.md"
    lines = [
        "# Symbol Property Cleanup Report", "",
        f"- Primary libraries checked: {summary['libraries']}",
        f"- Top-level symbols checked: {summary['symbols']}",
        f"- Libraries changed: {summary['libraries_changed']}",
        f"- Properties removed: {summary['remove']}",
        f"- Properties renamed: {summary['rename']}",
        f"- Properties added: {summary['add']}",
        f"- Property values replaced: {summary['replace value']}",
        f"- Unresolved conflicts: {len(conflicts)}", "",
        "The complete per-property action log is in `SYMBOL_PROPERTY_CLEANUP_AUDIT.csv`.", "",
        "## Unresolved conflicts", "",
    ]
    lines.extend((f"- `{item}`" for item in conflicts) if conflicts else ["None."])
    lines.extend([
        "", "## Scope", "",
        "Only primary `.kicad_sym` libraries were changed. Backups, staged libraries,",
        "datasheets, footprints, scripts other than the cleanup utility, and source data",
        "were not rewritten.", "",
    ])
    report_path.write_text("\n".join(lines), encoding="utf-8", newline="")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--source-ref",
        help="Rebuild from this Git revision before applying (used to repeat a migration exactly).",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    paths = primary_libraries(root)
    if len(paths) != 64:
        raise SystemExit(f"Expected 64 primary libraries, found {len(paths)}")

    pending: list[tuple[Path, str]] = []
    actions: list[Action] = []
    conflicts: list[str] = []
    summary: Counter = Counter(libraries=len(paths))
    for path in paths:
        original = source_text(root, path, args.source_ref)
        result, file_actions, file_conflicts, symbol_count = transform_library(root, path, original)
        current = path.read_text(encoding="utf-8")
        summary["symbols"] += symbol_count
        actions.extend(file_actions)
        conflicts.extend(file_conflicts)
        if result != original:
            summary["libraries_changed"] += 1
        if result != current:
            pending.append((path, result))
    summary.update(item.action for item in actions)

    print(f"Libraries: {summary['libraries']} ({summary['libraries_changed']} would change)")
    print(f"Symbols: {summary['symbols']}")
    print(
        f"Remove: {summary['remove']}; rename: {summary['rename']}; "
        f"add: {summary['add']}; value replacements: {summary['replace value']}"
    )
    print(f"Unresolved conflicts: {len(conflicts)}")
    for conflict in conflicts:
        print(f"CONFLICT {conflict}")

    if not args.apply:
        print("Dry run only; use --apply after conflicts are resolved.")
        return 2 if conflicts else 0
    if conflicts:
        print("Refusing to apply with unresolved conflicts.", file=sys.stderr)
        return 2

    for path, result in pending:
        temporary = path.with_name(path.name + ".cleanup-tmp")
        with temporary.open("w", encoding="utf-8", newline="") as stream:
            stream.write(result)
        os.replace(temporary, path)
    write_reports(root, actions, conflicts, summary)
    print("Cleanup applied and reports written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
