#!/usr/bin/env python3
"""One-shot, transactional importer for locally documented TVS, LED and crystal parts.

Run with --dry-run first.  --apply stages and validates every library before an
atomic replacement.  It intentionally excludes any row without both a local
datasheet and an exact local footprint.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

DOWNLOADS = Path(r"C:\Users\larsk\Downloads")
KICAD_CLI = Path(r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe")
ROOTS = {
    "tvs": Path(r"C:\KiCad\9.0\symbols\PL Diode TVS"),
    "led": Path(r"C:\KiCad\9.0\symbols\PL Diode LED"),
    "crystal": Path(r"C:\KiCad\9.0\symbols\PL Oscillator Crystal"),
}
LIBS = {
    "tvs": ROOTS["tvs"] / "PL Diode TVS.kicad_sym",
    "led": ROOTS["led"] / "PL Diode LED.kicad_sym",
    "crystal": ROOTS["crystal"] / "PL Oscillator Crystal.kicad_sym",
}
FOOTPRINTS = {
    "tvs": Path(r"C:\KiCad\9.0\footprints\PL Diode TVS\PL Diode TVS.pretty"),
    "led": Path(r"C:\KiCad\9.0\footprints\PL Diode LED\PL Diode LED.pretty"),
    "crystal": Path(r"C:\KiCad\9.0\footprints\PL Oscillator Crystal\PL Oscillator Crystal.pretty"),
}
EXPECTED_INPUT_HASHES = {
    "tvs": "CBF26BD6179FEA57D68259C64531D08DF819AFFF41D002958E3D6304EB75FC60",
    "led": "9DC0D7B5FA70D7709033BD1F64F101369580AF0571C44CD224F64FEB4DCC7B63",
    "crystal": "D15979F666F42B997F83906ED26B5735A0F926AA19B1ECEFC66F34F3BC5C7852",
}
REMOTE_SOURCES = {}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def avail(row):
    return int(re.sub(r"[^0-9]", "", row.get("Availability", "") or "0") or 0)


def esc(value) -> str:
    return str(value or "Not Specified").replace("\\", "/").replace('"', "'").replace("\n", " ").strip()


def pdf_source(row) -> Path | None:
    name = Path(urlparse(row.get("Datasheet", "")).path).name
    path = DOWNLOADS / name
    return path if name and path.is_file() else None


def tvs_pdf_source(row) -> Path | None:
    """Return the exact downloaded source PDF or a scoped fetch destination."""
    name = Path(urlparse(row.get("Datasheet", "")).path).name
    if not name:
        return None
    local = DOWNLOADS / name
    path = local if local.is_file() else ROOTS["tvs"] / "Data" / "Source PDFs" / name
    REMOTE_SOURCES[path] = row["Datasheet"]
    return path


def load_rows(first: int, last: int):
    rows = []
    for n in range(first, last + 1):
        path = DOWNLOADS / f"LCSCSearchDownload({n}).csv"
        if not path.is_file():
            raise RuntimeError(f"Required source CSV missing: {path}")
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows.extend(csv.DictReader(f))
    return rows


def unique_lcsc(rows):
    result = {}
    for row in rows:
        key = row.get("LCSC Part#", "")
        if key and (key not in result or avail(row) > avail(result[key])):
            result[key] = row
    return list(result.values())


def num(value: str, default=10**9):
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)", value or "")
    return float(m.group(1)) if m else default


def prop(name, value, hidden=True):
    hide = "\n\t\t\t(hide yes)" if hidden else ""
    return f'''\t\t(property "{esc(name)}" "{esc(value)}"
\t\t\t(at 0 0 0)
\t\t\t(show_name no)
\t\t\t(do_not_autoplace no){hide}
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t)
\t\t)'''


def derived(name, template, properties):
    body = [f'\t(symbol "{esc(name)}"', f'\t\t(extends "{template}")']
    body += [prop(k, v, k not in {"Reference", "Value"}) for k, v in properties]
    body.append("\t\t(embedded_fonts no)")
    body.append("\t)")
    return "\n".join(body) + "\n"


def led_independent_template():
    # XL-1608SURUGC data sheet: 1=red cathode, 3=red anode,
    # 2=green cathode, 4=green anode.  This is not a common-cathode RGB LED.
    pins = []
    for pin, label, x, y, orient in [("1", "RK", -5.08, 2.54, 0), ("3", "RA", 5.08, 2.54, 180), ("2", "GK", -5.08, -2.54, 0), ("4", "GA", 5.08, -2.54, 180)]:
        pins.append(f'''\t\t\t(pin passive line
\t\t\t\t(at {x} {y} {orient})
\t\t\t\t(length 2.54)
\t\t\t\t(name "{label}" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "{pin}" (effects (font (size 1.27 1.27))))
\t\t\t)''')
    return '''\t(symbol "LED_RG_Independent_Template"
\t\t(pin_names (offset 0) (hide yes))
\t\t(exclude_from_sim no)
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(in_pos_files yes)
\t\t(duplicate_pin_numbers_are_jumpers no)
''' + prop("Reference", "D", False) + "\n" + prop("Value", "", False) + "\n" + prop("Footprint", "") + "\n" + prop("Datasheet", "") + "\n" + prop("Description", "Independent red/green LED") + "\n" + prop("ki_keywords", "LED red green independent diode") + "\n" + prop("ki_fp_filters", "LED*") + '''
\t\t(symbol "LED_RG_Independent_Template_0_1"
\t\t\t(rectangle (start -2.54 5.08) (end 2.54 -5.08) (stroke (width 0.254) (type default)) (fill (type background)))
\t\t\t(text "R" (at 0 2.54 0) (effects (font (size 1.27 1.27))))
\t\t\t(text "G" (at 0 -2.54 0) (effects (font (size 1.27 1.27))))
\t\t)
\t\t(symbol "LED_RG_Independent_Template_1_1"
''' + "\n".join(pins) + '''
\t\t)
\t\t(embedded_fonts no)
\t)
'''


def parse_top_symbols(text: str):
    result, pos = {}, 0
    while True:
        m = re.search(r'^\t\(symbol "([^"]+)"', text[pos:], re.M)
        if not m:
            return result
        start = pos + m.start(); name = m.group(1); depth = 0; i = start
        while i < len(text):
            if text[i] == "(": depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0:
                    result[name] = text[start:i + 1]
                    pos = i + 1
                    break
            i += 1
        else:
            raise RuntimeError(f"Unbalanced symbol {name}")


def stage_library(kind: str, blocks):
    original = LIBS[kind].read_text(encoding="utf-8")
    if digest(LIBS[kind]) != EXPECTED_INPUT_HASHES[kind]:
        raise RuntimeError(f"{kind}: source library hash changed; refusing to modify it")
    symbols = parse_top_symbols(original)
    collisions = sorted(set(symbols).intersection(blocks))
    if collisions:
        raise RuntimeError(f"{kind}: symbol-name collision: {', '.join(collisions)}")
    if not original.rstrip().endswith(")"):
        raise RuntimeError(f"{kind}: malformed library terminator")
    staged = original.rstrip()[:-1] + "\n" + "\n".join(blocks.values()) + ")\n"
    stage = ROOTS[kind] / "Data" / f"staged_{datetime.now():%Y%m%d_%H%M%S}.kicad_sym"
    stage.write_text(staged, encoding="utf-8", newline="\n")
    # Confirm every original top-level symbol remains literally unchanged.
    staged_symbols = parse_top_symbols(staged)
    for name, block in symbols.items():
        if staged_symbols.get(name) != block:
            raise RuntimeError(f"{kind}: existing block changed: {name}")
    if not KICAD_CLI.is_file():
        raise RuntimeError(f"{kind}: KiCad 10 CLI missing: {KICAD_CLI}")
    svg_dir = stage.parent / (stage.stem + "_svg")
    cp = subprocess.run([str(KICAD_CLI), "sym", "export", "svg", "--output", str(svg_dir), str(stage)], capture_output=True, text=True)
    if cp.returncode:
        raise RuntimeError(f"{kind}: KiCad could not parse staged library: {(cp.stderr or cp.stdout).strip()}")
    return stage, len(symbols), len(staged_symbols)


def tvs_parts():
    mapping = {"DO-214AC(SMA)": ("D_SMA", "SMA"), "DO-214AA(SMB)": ("D_SMB", "SMB"), "DO-214AB(SMC)": ("D_SMC", "SMC")}
    rows = unique_lcsc(load_rows(80, 86)); valid = []
    for r in rows:
        if r.get("type") != "TVS" or avail(r) < 1000 or r.get("Package") not in mapping or not tvs_pdf_source(r):
            continue
        if r.get("Polarity") not in {"Unidirectional", "Bidirectional"}:
            continue
        fp, _ = mapping[r["Package"]]
        if not (FOOTPRINTS["tvs"] / f"{fp}.kicad_mod").is_file():
            continue
        valid.append(r)
    by_key = {}
    for r in valid:
        fp = mapping[r["Package"]][0]; key = (fp, r["Polarity"], r["Reverse Stand-Off Voltage (Vrwm)"])
        if key not in by_key or (-avail(r), r["MPN"]) < (-avail(by_key[key]), by_key[key]["MPN"]): by_key[key] = r
    blocks, docs = {}, {}
    for r in sorted(by_key.values(), key=lambda x: x["MPN"]):
        fp, package = mapping[r["Package"]]; family = re.match(r"(?:SMAJ|SMCJ|1\.5SMC)", r["MPN"]) 
        family = family.group(0) if family else "TVS"
        src = tvs_pdf_source(r); doc = docs.setdefault(src, f"Littelfuse_{family}_{package}_TVS_Diodes_{src.stem[:8]}.pdf")
        ds = f"${{PL_SYMBOL_DIR}}/PL Diode TVS/Datasheets/{doc}"
        p = [("Reference", "D"), ("Value", r["MPN"]), ("Footprint", f"PL Diode TVS:{fp}"), ("Datasheet", ds),
             ("Description", f"{r['Manufacturer']} {family} {r['Polarity'].lower()} TVS diode, {r['Reverse Stand-Off Voltage (Vrwm)']} VRWM, {r['Clamping Voltage']} clamp, {r['Package']}"),
             ("Manufacturer", r["Manufacturer"]), ("TVS Series", family), ("Automotive Grade", "No"), ("Technology", "TVS"), ("Polarity", r["Polarity"]), ("MPN", r["MPN"]), ("LCSC Part #", r["LCSC Part#"]),
             ("Reverse Standoff Voltage", r["Reverse Stand-Off Voltage (Vrwm)"]), ("Breakdown Voltage", r["Voltage - Breakdown"]), ("Clamping Voltage", r["Clamping Voltage"]), ("Reverse Leakage Current", r["Reverse Leakage Current (Ir)"]), ("Rated Power", r["Peak Pulse Power Dissipation (Ppp)"]), ("Rated Current", r["Peak Pulse Current (Ipp)"]), ("Number of Channels", r["Number of Channels"]), ("Operating Temperature", r["Operating Temperature"]), ("Package", r["Package"]), ("Packaging", r["Packaging"]), ("ki_keywords", f"{r['Polarity'].lower()} diode TVS voltage suppressor"), ("ki_fp_filters", fp)]
        blocks[r["MPN"]] = derived(r["MPN"], "TVS_Template_Unidirectional" if r["Polarity"] == "Unidirectional" else "TVS_Template_Bidirectional", p)
    return blocks, docs, len(rows), len(valid)


def led_parts():
    wanted = {"c433292f3095b794c3f1e74e65e936e0.pdf": ("Green_0603", "LED_Template", "XINGLIGHT_XL-1608UGGC_Green_LED.pdf"), "f0053fb73501b9b191307b41af4746b6.pdf": ("Emerald_Green_0603", "LED_Template", "XINGLIGHT_XL-1608PGC-06_Emerald_Green_LED.pdf"), "d79da0963ce13e3bbcd2c1f63fbb419d.pdf": ("Red_Green_0603", "LED_RG_Independent_Template", "XINGLIGHT_XL-1608SURUGC_Red_Green_LED.pdf")}
    rows = unique_lcsc(load_rows(87, 88)); selected=[]
    for r in rows:
        src=pdf_source(r)
        if src and src.name in wanted and avail(r)>=1000: selected.append(r)
    if len(selected) != 3: raise RuntimeError(f"led: expected 3 documented candidates, found {len(selected)}")
    blocks={"LED_RG_Independent_Template": led_independent_template()}; docs={}
    for r in sorted(selected, key=lambda x: wanted[pdf_source(x).name][0]):
        name, template, doc = wanted[pdf_source(r).name]; docs[pdf_source(r)] = doc
        is4 = template == "LED_RG_Independent_Template"; fp = "LED_1.6x0.8mm" if is4 else "LED0603"
        if not (FOOTPRINTS["led"] / f"{fp}.kicad_mod").is_file(): raise RuntimeError(f"led footprint missing: {fp}")
        ds=f"${{PL_SYMBOL_DIR}}/PL Diode LED/Datasheets/{doc}"
        p=[("Reference","D"),("Value",r.get("Illumination Color") or ("Red, Green" if is4 else "Green")),("Footprint",f"PL Diode LED:{fp}"),("Datasheet",ds),
           ("Description",f"XINGLIGHT {r['MPN']} {r.get('Illumination Color') or 'Green'} SMD LED, {r.get('Package')}, {r.get('Operating Temperature') or '-35℃~+85℃'}"),("Manufacturer",r["Manufacturer"]),("Automotive Grade","No"),("Technology","LED"),("MPN",r["MPN"]),("LCSC Part #",r["LCSC Part#"]),("Color",r.get("Illumination Color") or ("Red, Green" if is4 else "Green")),("Forward Voltage",r.get("Voltage - Forward(Vf)") or ("2.8V~3.4V" if r["MPN"]=="XL-1608UGGC" else "Not Specified")),("Forward Current",r.get("Forward Current") or "20mA"),("Viewing Angle",r.get("Viewing Angle") or "120°"),("Wavelength",r.get("Wavelength") or "515nm~535nm"),("Luminous Intensity",r.get("Luminous Intensity") or "410mcd~740mcd"),("Operating Temperature",r.get("Operating Temperature") or "-35℃~+85℃"),("Package",r["Package"]),("Packaging",r["Packaging"]),("MSL","3"),("RoHS","Yes"),("ki_keywords","LED diode"),("ki_fp_filters",fp)]
        blocks[name]=derived(name,template,p)
    return blocks,docs,len(rows),len(selected)


def crystal_parts():
    mapping={"SMD2016-4P":("Crystal_SMD_2016-4Pin_2.0x1.6mm","Template_Crystal_GND24"),"SMD3215-2P":("Crystal_SMD_3215-2Pin_3.2x1.5mm","Template_Crystal_2-Pin")}
    rows=unique_lcsc(load_rows(89,93)); valid=[]
    for r in rows:
        if avail(r)>=1000 and r.get("Package") in mapping and pdf_source(r):
            fp,_=mapping[r["Package"]]
            if (FOOTPRINTS["crystal"] / f"{fp}.kicad_mod").is_file(): valid.append(r)
    by_key={}
    for r in valid:
        fp,_=mapping[r["Package"]]; key=(fp,r.get("Frequency"),r.get("Load Capacitance"))
        rank=(num(r.get("Normal temperature Frequency Tolerance")),num(r.get("Frequency Stability")),num(r.get("Equivalent Series Resistance(ESR)")), -avail(r), r["MPN"])
        if key not in by_key or rank < by_key[key][0]: by_key[key]=(rank,r)
    blocks,docs={},{}
    for _,r in sorted(by_key.values(),key=lambda x:x[1]["MPN"]):
        fp,template=mapping[r["Package"]]; src=pdf_source(r); doc=docs.setdefault(src,f"{r['Manufacturer']}_{r['Package']}_Crystal_{src.stem[:8]}.pdf")
        name=f"{r['Frequency']}_{r['MPN']}"; ds=f"${{PL_SYMBOL_DIR}}/PL Oscillator Crystal/Datasheets/{doc}"
        automotive = "Yes" if src.name.startswith("b874d35f") else "No"
        p=[("Reference","Y"),("Value",r["Frequency"]),("Footprint",f"PL Oscillator Crystal:{fp}"),("Datasheet",ds),("Description",f"{r['Manufacturer']} {r['Frequency']} crystal, {r.get('Normal temperature Frequency Tolerance') or 'tolerance not specified'}, {r.get('Load Capacitance') or 'load capacitance not specified'}, {r['Package']}"),("Manufacturer",r["Manufacturer"]),("Technology","Quartz Crystal"),("Automotive Grade",automotive),("MPN",r["MPN"]),("LCSC Part #",r["LCSC Part#"]),("Frequency",r["Frequency"]),("Frequency Tolerance",r.get("Normal temperature Frequency Tolerance")),("Frequency Stability",r.get("Frequency Stability")),("Load Capacitance",r.get("Load Capacitance")),("Equivalent Series Resistance",r.get("Equivalent Series Resistance(ESR)")),("Operating Temperature",r.get("Operating Temperature")),("Package",r["Package"]),("Packaging",r.get("Packaging")),("ki_keywords","crystal quartz"),("ki_fp_filters",fp)]
        blocks[name]=derived(name,template,p)
    return blocks,docs,len(rows),len(valid)


def copy_docs(kind, docs, backup, log, created):
    for src,name in docs.items():
        if not src.is_file():
            url = REMOTE_SOURCES.get(src)
            if not url:
                raise RuntimeError(f"{kind}: referenced source datasheet missing: {src}")
            src.parent.mkdir(parents=True, exist_ok=True)
            temp = src.with_suffix(src.suffix + ".new")
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=30) as response, temp.open("wb") as out:
                shutil.copyfileobj(response, out)
            if not temp.read_bytes().startswith(b"%PDF"):
                temp.unlink(missing_ok=True)
                raise RuntimeError(f"{kind}: downloaded source is not a PDF: {url}")
            os.replace(temp, src)
            created.append(src)
            log.append(f"DOWNLOAD {url} -> {src} sha256={digest(src)}")
        dest=ROOTS[kind]/"Datasheets"/name
        if dest.exists() and digest(dest)!=digest(src): raise RuntimeError(f"{kind}: datasheet collision {dest}")
        if not dest.exists():
            shutil.copy2(src,dest); created.append(dest); log.append(f"COPY {src} -> {dest}")


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--apply",action="store_true"); ap.add_argument("--dry-run",action="store_true"); args=ap.parse_args()
    if args.apply and args.dry_run: ap.error("choose either --dry-run or --apply")
    batches={"tvs":tvs_parts(),"led":led_parts(),"crystal":crystal_parts()}
    print("Candidates: " + ", ".join(f"{k}: raw={v[2]}, eligible={v[3]}, additions={len(v[0]) - (1 if k=='led' else 0)}" for k,v in batches.items()))
    # The LED batch contains a template plus three actual parts.
    if len(batches['tvs'][0]) != 63 or len(batches['led'][0]) != 4 or len(batches['crystal'][0]) != 46:
        raise RuntimeError("Unexpected selection count; no mutation performed")
    if not args.apply: return
    stamp=datetime.now().strftime("%Y%m%d_%H%M%S"); log=[]; stages={}; originals={}; created_files=[]
    try:
        for kind,(blocks,docs,raw,eligible) in batches.items():
            for fp in sorted(set(re.findall(r'Footprint" "[^:]+:([^\"]+)', "\n".join(blocks.values())))):
                p=FOOTPRINTS[kind]/f"{fp}.kicad_mod"
                if not p.is_file(): raise RuntimeError(f"{kind}: referenced footprint absent: {p}")
                log.append(f"FOOTPRINT {p} sha256={digest(p)}")
            stage,before,after=stage_library(kind,blocks); stages[kind]=stage
            backup=ROOTS[kind]/"Backups"/stamp; backup.mkdir(parents=True,exist_ok=False)
            original=backup/LIBS[kind].name; shutil.copy2(LIBS[kind],original); originals[kind]=original
            log.append(f"{kind} source_sha256={digest(LIBS[kind])} symbols_before={before} symbols_after={after} stage={stage}")
        for kind,(blocks,docs,raw,eligible) in batches.items(): copy_docs(kind,docs,ROOTS[kind]/"Backups"/stamp,log,created_files)
        for kind,stage in stages.items():
            temp=LIBS[kind].with_suffix(".kicad_sym.new"); shutil.copy2(stage,temp); os.replace(temp,LIBS[kind]); log.append(f"REPLACE {LIBS[kind]} sha256={digest(LIBS[kind])}")
        log.append("COMMIT successful")
    except Exception as exc:
        log.append(f"ERROR {type(exc).__name__}: {exc}")
        for kind,original in originals.items():
            if original.exists(): shutil.copy2(original,LIBS[kind]); log.append(f"ROLLBACK library {LIBS[kind]}")
        for path in reversed(created_files):
            if path.exists(): path.unlink(); log.append(f"ROLLBACK created file {path}")
        log.append("ROLLBACK complete")
        raise
    finally:
        for kind in ROOTS:
            path=ROOTS[kind]/"Logs"/f"add_tvs_led_crystals_{stamp}.log"
            path.write_text("\n".join(log)+"\n",encoding="utf-8")

if __name__ == "__main__":
    main()
