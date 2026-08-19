# Adding Parts to the PL Resistor SMD Library

This document defines the required process for adding further parts to
`PL Resistor SMD.kicad_sym`. Follow it whether the update is performed manually,
with a script, or by an automated agent.

## Folder layout

```text
PL Resistor SMD.kicad_sym       Live symbol library; keep in the root folder
PL Resistor SMD.bak             KiCad backup; keep in the root folder
Backups/                        Timestamped update backups
Data/LCSC/Source/               Original LCSC search-download CSV files
Data/LCSC/Processed/            Merged and filtered working CSV files
Datasheets/                     Manufacturer datasheets
Documentation/                  Maintenance instructions
Logs/                           Timestamped update logs
Tools/                          Bulk-update utilities
```

## Non-negotiable rules

1. Never replace, rewrite, reorder, or silently update an existing symbol.
2. The existing `Resistor_Template` and all existing symbol blocks must remain
   byte-for-byte unchanged.
3. A part is a duplicate when the library already contains the same normalized
   resistance and footprint/package. Skip that candidate even if its MPN,
   availability, power, tolerance, or series differs.
4. If a proposed symbol name already exists but is not a valid duplicate, abort
   the complete update and investigate. Never rename or overwrite the old symbol.
5. Every ordinary new resistor must derive from `Resistor_Template` using:

   ```text
   (extends "Resistor_Template")
   ```

6. Do not modify footprint files as part of a symbol-library update.
7. Generate and validate a staged library before touching the live library.
8. Back up the library and relevant datasheet before mutation, write a detailed
   log, and restore the originals if any mutation-stage operation fails.

## Current library conventions

### Symbol names

Use the existing `{RESISTANCE}_{FOOTPRINT}` convention:

```text
10R_0402
49.9R_0603
1K_0603
4.99K_0603
100K_0805
1M_0805
```

- Preserve decimal points in the numeric portion.
- Use `R` for ohms, uppercase `K` for kilohms, uppercase `M` for megohms,
  and lowercase `m` for milliohms.
- Use `0R` for zero-ohm resistors.
- End the name with the footprint size, such as `_0402`, `_0603`, or `_0805`.
- Add a further suffix only when needed to distinguish a non-default variant,
  following existing forms such as `_10ppm`, `_0.05%`, or `_5W`.

The displayed `Value` uses the existing unit style, for example `4.99kΩ`, while
the symbol name is `4.99K_0603`.

### Footprints

Assign exact footprints with the existing library nickname:

```text
PL Resistor SMD:R0402
PL Resistor SMD:R0603
PL Resistor SMD:R0805
```

Verify the referenced `.kicad_mod` exists before generating a symbol.

## Required source-data checks

The source CSV must contain at least these columns:

```text
LCSC Part#
MPN
Manufacturer
Availability
Package
Packaging
Type
Resistance
Tolerance
Voltage Rating
Power(Watts)
Temperature Coefficient
```

For the current Yageo RC collection, accept only rows that satisfy all of the
following:

- Manufacturer is `YAGEO`.
- MPN begins with `RC`.
- Resistance is an E96 value.
- Package is `0402`, `0603`, or `0805`.
- Tolerance is `±1%`.
- Temperature coefficient is `±100ppm/℃`.
- Availability is at least 1000.
- Packaging is `Tape & Reel (TR)`.
- Type is `Thick Film Resistor`.
- Power and rated voltage agree with the package table below.
- Each CSV contains no duplicate package/resistance keys, MPNs, or LCSC part
  numbers.

Do not store price, availability, minimum order quantity, or order multiples in
the permanent symbol library. They are selection inputs and become stale.

## Properties for Yageo RC derived symbols

Each new Yageo RC symbol must contain these properties:

```text
Reference
Value
Footprint
Datasheet
Description
Manufacturer
Resistor Series
Automotive Grade
Technology
Tolerance
MPN
LCSC Part #
Resistance
Package
Rated Power
Rated Voltage
Maximum Overload Voltage
Operating Temperature
Temperature Coefficient
Height
Packaging
MSL
RoHS
Halogen Free
ki_keywords
ki_fp_filters
```

Fixed Yageo RC values:

| Property | Value |
|---|---|
| Manufacturer | `YAGEO` |
| Resistor Series | `RC` |
| Automotive Grade | `No` |
| Technology | `Thick Film` |
| Tolerance | `±1%` |
| Operating Temperature | `-55℃~+155℃` |
| Temperature Coefficient | `±100ppm/℃` |
| Packaging | `Tape & Reel (TR)` |
| MSL | `1` |
| RoHS | `Yes` |
| Halogen Free | `Yes` |
| ki_keywords | `R res resistor` |
| ki_fp_filters | `R_*` |

Package-specific values:

| Package | Rated Power | Rated Voltage | Maximum Overload Voltage | Height |
|---|---:|---:|---:|---:|
| 0402 | `62.5mW` | `50V` | `100V` | `0.40mm max` |
| 0603 | `100mW` | `75V` | `150V` | `0.55mm max` |
| 0805 | `125mW` | `150V` | `300V` | `0.60mm max` |

Generate a part-specific description using:

```text
Yageo RC series thick-film SMD resistor, {Resistance}, ±1%, {Rated Power}, {Rated Voltage}, {Package}, ±100ppm/℃
```

Example:

```text
Yageo RC series thick-film SMD resistor, 4.99kΩ, ±1%, 100mW, 75V, 0603, ±100ppm/℃
```

## Datasheets

The current Yageo RC datasheet is:

```text
Datasheets/Yageo_RC_L_Series_Chip_Resistors.pdf
```

New Yageo RC symbols must use this portable `Datasheet` field value:

```text
${PL_SYMBOL_DIR}/PL Resistor SMD/Datasheets/Yageo_RC_L_Series_Chip_Resistors.pdf
```

For another resistor series or manufacturer:

1. Obtain the authoritative manufacturer datasheet.
2. Give it a descriptive, stable filename.
3. Store it under `Datasheets`.
4. Link only the applicable new symbols to it.
5. Determine `Resistor Series` and `Automotive Grade` from that datasheet.
   Use `Automotive Grade = Yes` only when the part is explicitly specified as an
   automotive-grade series; do not infer it from marketing text.
6. Do not change datasheet fields on old symbols unless a separate migration is
   explicitly requested and separately backed up.

## Safe update procedure

### 1. Preflight without changing live files

- Hash the input CSV, live library, datasheet, and referenced footprints.
- Parse all existing top-level symbols and retain their exact source blocks.
- Normalize every resistance to ohms and build existing
  `(package, resistance)` keys.
- Validate every input invariant before generating anything.
- Calculate and log the exact skip and addition counts.
- Abort if there are unexplained name collisions, missing footprints, duplicate
  CSV keys, invalid values, or unexpected source counts.

### 2. Generate a staged candidate

- Insert new derived blocks immediately before the library's final root
  parenthesis.
- Sort only the new blocks by symbol name.
- Do not sort or reformat the complete library.
- Preserve UTF-8 without BOM and CRLF line endings.
- Confirm every old top-level symbol block in the staged candidate is
  byte-for-byte identical to its original block.

### 3. Validate the candidate

- Check balanced S-expressions and unique symbol names.
- Check every `extends` target exists.
- Check every new symbol extends `Resistor_Template`.
- Check every required property and package-specific value.
- Check every datasheet link resolves to an existing file.
- Use KiCad 10 to parse/export one unchanged symbol and at least one new symbol
  for every package:

  ```powershell
  & 'C:\Program Files\KiCad\10.0\bin\kicad-cli.exe' sym export svg `
      --output <temporary-output-folder> `
      --symbol <symbol-name> `
      '<staged-library-path>'
  ```

### 4. Back up and install transactionally

- Store timestamped original files under `Backups/<timestamp>/`.
- Write the audit log under `Logs/PL_Resistor_SMD_update_<timestamp>.log`.
- Verify backup hashes before mutation.
- Atomically replace the symbol library only after staged validation succeeds.
- If a datasheet is being renamed, include it in the same transaction.
- On failure, restore the original library and datasheet and verify their hashes.

### 5. Verify after installation

- Verify the installed library hash equals the validated candidate hash.
- Recount symbols and additions.
- Recheck original blocks for byte identity.
- Recheck all new fields, inheritance, datasheet paths, and footprint references.
- Confirm footprint hashes did not change.
- Record final hashes, counts, validation output, and rollback status in the log.

## Audit-log requirements

Every update log must include:

- Start and completion timestamps.
- Input and output paths, sizes, and SHA-256 hashes.
- Input, existing, skipped, added, and final symbol counts.
- One entry for every skipped row, including the matched existing symbol.
- One entry for every added symbol, including name, MPN, LCSC number,
  resistance, and package.
- Datasheet operations.
- Backup paths and hash verification.
- KiCad validation commands, output, and exit codes.
- Any errors and the result of any rollback.

## Existing updater warning

`Tools/bulk_add_yageo_rc_symbols.py` is an auditable record of the completed 2026-08-19
batch. It intentionally contains one-time expected counts and the original PDF
rename precondition. Do **not** rerun it unchanged for another batch.

For a future batch, copy or revise the updater so that it:

- Uses the new source CSV.
- Expects the current live-library symbol count.
- Uses newly calculated skip, addition, and final counts.
- Does not attempt the already-completed datasheet rename.
- Retains all preflight, staging, backup, logging, validation, atomic replacement,
  and rollback safeguards described above.
