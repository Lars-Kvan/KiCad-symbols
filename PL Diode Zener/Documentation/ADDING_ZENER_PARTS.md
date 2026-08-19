# Adding Zener diode parts safely

The 2026-08-19 batch was installed by the guarded updater at:

`../PL Magnetics Ferrite/Tools/bulk_add_ferrite_and_zener_symbols.py`

The local `Tools/bulk_add_ferrite_and_zener_symbols.py` file is a launcher for that
canonical updater. The updater is deliberately one-shot and must refuse to rerun
against the completed library. For a future batch, update a copy only after deriving
new hashes, counts, datasheet mappings, and selection results.

## Current structure and naming

- Preserve every existing top-level symbol block byte-for-byte.
- Two-terminal SOD parts derive from the existing `Zener_Template`.
- SOT-23 parts derive from `Zener_SOT23_Template`.
- The SOT-23 mapping verified from the supplied R+O BZX84C datasheet is cathode pin 3,
  anode pin 1, and no-connect pin 2. Do not reuse the two-pin template for SOT-23.
- Names follow the existing `{Zener voltage}_{MPN}` convention, such as
  `5.1V_MMSZ5231B`.
- Current package mappings are `SOT-23 -> SOT-23-3`, `SOD-123 -> D_SOD-123`, and
  `SOD-323 -> SOD-323`.
- Do not create or edit footprints during a symbol import.

## Selection policy used for this batch

1. Deduplicate identical LCSC part numbers, retaining highest availability.
2. Require one independent diode, Tape & Reel packaging, stock of at least 1,000,
   a supported package, and a supplied local PDF containing the selected MPN.
3. Group by normalized nominal Zener voltage plus package.
4. Prefer highest power, then tightest tolerance, then highest availability.
5. Existing symbols always win for the same voltage and footprint.
6. Abort on unexplained name collisions or conflicts between CSV and datasheet.

The supplied datasheet and voltage range establish `MMSZ5232B` as 5.6 V; the CSV's
5.4 V entry was rejected and corrected explicitly. Future discrepancies must be
resolved from the supplied primary datasheet and logged, never guessed.

Processed CSVs omit `Pricing($)` and `Datasheet`. Availability, prices, order
quantities, and supplier URLs are not symbol properties.

## Required symbol properties

Populate `Reference`, `Value`, `Footprint`, `Datasheet`, `Description`,
`Manufacturer`, `Zener Series`, `Automotive Grade`, `Technology`,
`Diode Configuration`, `Tolerance`, `MPN`, `LCSC Part #`, `Zener Voltage`,
`Zener Voltage Range`, `Rated Power`, `Reverse Leakage Current`,
`Zener Impedance Zzt`, `Zener Impedance Zzk`, `Package`,
`Operating Junction Temperature`, `Packaging`, `MSL`, `RoHS`, `Halogen Free`,
`ki_keywords`, and `ki_fp_filters`.

Datasheets are local links under:

`${PL_SYMBOL_DIR}/PL Diode Zener/Datasheets/<descriptive filename>.pdf`

Use `Not Specified` where the applicable supplied PDF does not substantiate a value.

## Transaction and validation checklist

1. Hash the live library, `.bak` files, source data, PDFs, and referenced footprints.
2. Read every applicable datasheet and verify the family, package, pin map, MPN,
   ratings, compliance claims, and automotive status.
3. Freeze exact source, selection, skip, addition, template, and final counts.
4. Stage the complete candidate and assert all original blocks are byte-identical.
5. Validate S-expressions, unique names, inheritance, fields, footprints, and local
   datasheet paths.
6. Use KiCad 10 CLI to export an unchanged symbol plus a new SOT-23, SOD-123, and
   SOD-323 symbol before installation.
7. Create timestamped backups and logs, atomically replace the library, and repeat
   every validation afterward.
8. Roll back both libraries if a coordinated update fails after mutation begins.

The completed batch's canonical log is at
`../PL Magnetics Ferrite/Logs/ferrite_zener_update_20260819-102022.log`; the original
Zener library is in `Backups/20260819-102022/`.
