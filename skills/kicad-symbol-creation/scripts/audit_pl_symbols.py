#!/usr/bin/env python3
"""Audit PL KiCad symbol libraries and their local asset references."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Symbol:
    name: str
    block: str


def expression_end(text: str, start: int) -> int:
    depth = 0
    quoted = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index + 1
    raise ValueError(f"Unterminated expression at byte offset {start}")


def top_expressions(text: str, prefix: str) -> list[str]:
    found: list[str] = []
    depth = 0
    quoted = False
    escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            index += 1
            continue
        if char == '"':
            quoted = True
        elif char == "(":
            if depth == 1 and text.startswith(prefix, index):
                end = expression_end(text, index)
                found.append(text[index:end])
                index = end
                continue
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                raise ValueError("Closing parenthesis without matching opener")
        index += 1
    if depth != 0 or quoted:
        raise ValueError("Unbalanced library or unterminated quoted string")
    return found


def symbols(text: str) -> list[Symbol]:
    result: list[Symbol] = []
    for block in top_expressions(text, '(symbol "'):
        match = re.match(r'\(symbol "((?:\\.|[^"\\])*)"', block)
        if not match:
            raise ValueError("Malformed top-level symbol")
        result.append(Symbol(match.group(1), block))
    return result


def properties(block: str) -> list[tuple[str, str, str]]:
    result: list[tuple[str, str, str]] = []
    for expression in top_expressions(block, '(property "'):
        match = re.match(r'\(property "((?:\\.|[^"\\])*)" "((?:\\.|[^"\\])*)"', expression)
        if not match:
            raise ValueError("Malformed top-level property")
        result.append((match.group(1), match.group(2), expression))
    return result


def resolve_footprint(footprint_root: Path, value: str) -> Path | None:
    if ":" not in value:
        return None
    library, name = value.split(":", 1)
    return footprint_root / library / f"{library}.pretty" / f"{name}.kicad_mod"


def audit_library(path: Path, symbol_root: Path, footprint_root: Path | None) -> dict[str, object]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        data = path.read_bytes()
        if data.startswith(b"\xef\xbb\xbf"):
            errors.append("unexpected UTF-8 BOM")
        text = data.decode("utf-8-sig")
        parsed = symbols(text)
    except (OSError, UnicodeError, ValueError) as error:
        return {"library": str(path), "symbols": 0, "errors": [str(error)], "warnings": []}

    names = [symbol.name for symbol in parsed]
    available = set(names)
    if len(names) != len(available):
        duplicates = sorted(name for name in available if names.count(name) > 1)
        errors.append(f"duplicate symbol names: {', '.join(duplicates)}")

    for symbol in parsed:
        try:
            props = properties(symbol.block)
        except ValueError as error:
            errors.append(f"{symbol.name}: {error}")
            continue
        prop_names = [name for name, _, _ in props]
        duplicates = sorted(name for name in set(prop_names) if prop_names.count(name) > 1)
        if duplicates:
            errors.append(f"{symbol.name}: duplicate properties: {', '.join(duplicates)}")
        values = {name: value for name, value, _ in props}

        extends = re.search(r'\(extends "([^"]+)"\)', symbol.block)
        if extends and extends.group(1) not in available:
            errors.append(f"{symbol.name}: missing extends target {extends.group(1)}")

        footprint = values.get("Footprint", "")
        if footprint:
            if not footprint.startswith("PL "):
                errors.append(f"{symbol.name}: non-PL footprint {footprint}")
            elif footprint_root:
                resolved = resolve_footprint(footprint_root, footprint)
                if resolved is None or not resolved.is_file():
                    errors.append(f"{symbol.name}: missing footprint file for {footprint}")

        datasheet = values.get("Datasheet", "")
        prefix = "${PL_SYMBOL_DIR}/"
        if datasheet.startswith(prefix):
            resolved = symbol_root / datasheet[len(prefix):]
            if not resolved.is_file():
                errors.append(f"{symbol.name}: missing local datasheet {datasheet}")
            elif resolved.suffix.lower() == ".pdf" and resolved.read_bytes()[:4] != b"%PDF":
                errors.append(f"{symbol.name}: invalid PDF header {datasheet}")
        elif datasheet and datasheet.startswith("http"):
            warnings.append(f"{symbol.name}: remote datasheet URL")

    return {
        "library": str(path),
        "symbols": len(parsed),
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    default_symbol_root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol-root", type=Path, default=default_symbol_root)
    parser.add_argument("--footprint-root", type=Path)
    parser.add_argument("--library", action="append", help="Library folder name; repeat as needed")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args()

    symbol_root = args.symbol_root.resolve()
    footprint_root = args.footprint_root.resolve() if args.footprint_root else None
    libraries = sorted(symbol_root.glob("PL */*.kicad_sym"))
    if args.library:
        wanted = set(args.library)
        libraries = [path for path in libraries if path.parent.name in wanted]
    if not libraries:
        parser.error("No matching .kicad_sym libraries found")

    reports = [audit_library(path, symbol_root, footprint_root) for path in libraries]
    error_count = sum(len(report["errors"]) for report in reports)
    warning_count = sum(len(report["warnings"]) for report in reports)
    symbol_count = sum(int(report["symbols"]) for report in reports)

    if args.json:
        print(json.dumps({
            "libraries": reports,
            "summary": {
                "library_count": len(reports),
                "symbol_count": symbol_count,
                "error_count": error_count,
                "warning_count": warning_count,
            },
        }, indent=2))
    else:
        for report in reports:
            print(f"{report['library']}: symbols={report['symbols']} errors={len(report['errors'])} warnings={len(report['warnings'])}")
            for message in report["errors"]:
                print(f"  ERROR: {message}")
            for message in report["warnings"]:
                print(f"  WARNING: {message}")
        print(f"TOTAL libraries={len(reports)} symbols={symbol_count} errors={error_count} warnings={warning_count}")
    return 1 if error_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
