# Adding Parts to the PL Capacitor MLCC Library

This document defines the required process for adding parts to
`PL Capacitor MLCC.kicad_sym`. Follow it for manual, scripted, and automated
updates.

## Folder layout

```text
PL Capacitor MLCC.kicad_sym     Live symbol library; keep in the root folder
PL Capacitor MLCC.bak           KiCad backup; keep in the root folder
Backups/                        Timestamped update backups
Data/LCSC/Source/               Original capacitor LCSC CSV files
Data/LCSC/Processed/            Merged and filtered working CSV files
Data/Excluded/Resistor/         Unrelated resistor downloads retained for recovery
Datasheets/                     Manufacturer datasheets
Documentation/                  Maintenance instructions
Logs/                           Timestamped update logs
Tools/                          Bulk-update utilities
```

## Non-negotiable rules

1. Never replace, rewrite, reorder, or silently update an existing symbol.
2. Preserve both templates and every existing symbol block byte-for-byte.
3. Treat the same normalized capacitance and footprint/package as a duplicate.
   Skip it regardless of MPN, voltage, tolerance, dielectric, or series.
4. Existing symbols always win. Abort on a symbol-name collision that is not an
   explained capacitance/package duplicate.
5. Every ordinary MLCC must derive from `Capacitor_Template`. Feed-through
   capacitors derive from `Capacitor_Feed_Through_Template` and are excluded from
   ordinary MLCC duplicate matching.
6. Do not modify footprint files during a symbol-library update.
7. Stage and validate the complete library before touching the live file.
8. Back up the library and affected datasheet, log every decision, and roll back
   the complete mutation if an installation-stage check fails.

## Naming and footprints

Use `{CAPACITANCE}_{PACKAGE}` with lowercase engineering prefixes:

```text
100pF_0402
1.5nF_0603
100nF_0805
10uF_1210
```

Normalize microfarads to `uF`, retain decimal points, and use the most practical
unit: pF below 1 nF, nF below 1 uF, and uF from 1 uF upward. Normalize duplicate
checks numerically, so equivalent forms such as `1000pF` and `1nF` collide.

Use exact footprint assignments such as:

```text
PL Capacitor MLCC:C0402
PL Capacitor MLCC:C0603
PL Capacitor MLCC:C0805
PL Capacitor MLCC:C1206
PL Capacitor MLCC:C1210
```

## Original Yageo CC X7R selection policy

The current batch accepts only:

- Manufacturer `YAGEO`
- MPN beginning with `CC`
- X7R dielectric
- E6 capacitance values
- 0402, 0603, 0805, 1206, or 1210 package
- Rated voltage from above 0 V through 250 V
- Availability of at least 1,000
- `Tape & Reel (TR)` packaging

After exact LCSC-part deduplication, group rows by normalized capacitance and
package. Select highest rated voltage, then tightest tolerance, then highest
availability. Break a remaining exact tie by ascending MPN and LCSC part number
to keep generation deterministic.

## Multi-family selection policy

The later multi-family batch removes the E6 restriction and accepts C0G, NP0,
and X7R parts from supported manufacturer families when all of these conditions
are met:

- Package is 0402, 0603, 0805, 1206, or 1210.
- Stock is at least 1,000.
- Packaging is `Tape & Reel (TR)`.
- The selected family has a validated local manufacturer datasheet profile.

Selection remains one part per normalized capacitance and package. Existing
symbols win. For new keys, choose highest rated voltage, then tightest tolerance,
then highest availability, followed by ascending MPN and LCSC number.

Family metadata must not be generalized across manufacturers:

- X7R is `Class 2`; C0G/NP0 is `Class 1`.
- Yageo AC and Murata GCM are automotive grade.
- A KEMET part is automotive only when its ordering code explicitly uses the
  `AUTO` grade.
- Yageo CC/CQ, Murata GRM/GJM/GQM, standard KEMET C0G, and standard KYOCERA AVX
  C0G/NP0 parts are not automotive grade.
- Use `Not Specified` for compliance metadata not established by the applicable
  datasheet; never convert missing evidence into `No` or `Yes`.

Availability and commercial fields are selection inputs. Do not copy pricing,
availability, minimum quantities, order multiples, or supplier datasheet URLs
into symbols.

## Required Yageo CC properties

Each new symbol contains:

```text
Reference
Value
Footprint
Datasheet
Description
Manufacturer
Capacitor Series
Automotive Grade
Technology
Capacitor Class
Dielectric
Tolerance
MPN
LCSC Part #
Capacitance
Package
Rated Voltage
Operating Temperature
Packaging
MSL
RoHS
Halogen Free
ki_keywords
ki_fp_filters
```

Use these fixed values:

| Property | Value |
|---|---|
| Manufacturer | `YAGEO` |
| Capacitor Series | `CC` |
| Automotive Grade | `No` |
| Technology | `MLCC` |
| Capacitor Class | `Class 2` |
| Dielectric | `X7R` |
| Operating Temperature | `-55℃~+125℃` |
| Packaging | `Tape & Reel (TR)` |
| MSL | `1` |
| RoHS | `Yes` |
| Halogen Free | `Yes` |
| ki_keywords | `cap capacitor` |
| ki_fp_filters | `C_*` |

Read capacitance, tolerance, rated voltage, MPN, and LCSC part number from the
selected row. Do not add a generic `Height`; MLCC thickness depends on the exact
capacitance, voltage, and construction.

Generate descriptions as:

```text
Yageo CC series X7R Class 2 MLCC, {Capacitance}, {Tolerance}, {Rated Voltage}, {Package}, -55℃~+125℃
```

## Datasheet

The current commercial Yageo CC X7R datasheet is:

```text
Datasheets/Yageo_X7R_General_Purpose_High_Capacitance_MLCC.pdf
```

New applicable symbols use:

```text
${PL_SYMBOL_DIR}/PL Capacitor MLCC/Datasheets/Yageo_X7R_General_Purpose_High_Capacitance_MLCC.pdf
```

Do not change old symbols' datasheet fields as part of a bulk addition. Set
`Automotive Grade = Yes` only for a series whose manufacturer datasheet
explicitly identifies it as automotive grade.

## Safe update procedure

1. Hash the live library, `.bak`, datasheet, source CSVs, and footprints.
2. Parse existing top-level symbols and retain their exact source blocks.
3. Validate source columns, counts, family rules, normalized values, and
   duplicate precedence before mutation.
4. Append only new derived blocks immediately before the root closing
   parenthesis, sorting only the new blocks by symbol name.
5. Preserve UTF-8 without BOM and CRLF line endings.
6. Validate balanced S-expressions, unique names and properties, inheritance,
   all field values, and byte identity of every old symbol block.
7. Use KiCad 10 CLI to export an unchanged symbol and one new symbol for every
   package from the staged library.
8. Create timestamped backups and an audit log, then install with atomic library
   replacement. Include datasheet renames and source moves in rollback handling.
9. Repeat structural and KiCad CLI checks against the installed library, verify
   `.bak` and footprint hashes, and record final hashes and counts.

## Audit log

Record source and output hashes, source counts, every deduplication, preferred
selection, skip and addition, backup verification, file move, CLI command and
result, final validation, error, and rollback result.

## Existing updater warning

`Tools/bulk_add_yageo_cc_x7r_capacitors.py` and
`Tools/bulk_add_multifamily_capacitors_non_e6.py` are one-shot, auditable records
of the 2026-08-19 batches. They contain fixed source counts and original-path
preconditions and intentionally refuse to rerun after success.

For a future batch, revise or copy it with new input paths and freshly calculated
expected counts. Preserve all collision, staging, backup, logging, CLI,
transaction, rollback, and post-install checks.
