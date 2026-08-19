# Adding ferrite parts safely

The 2026-08-19 batch was installed by `Tools/bulk_add_ferrite_and_zener_symbols.py`.
That script is deliberately one-shot: its input hashes, expected counts, and original
library hash describe the completed batch. It must refuse to run against the updated
library. Do not weaken those guards just to make a later batch run.

## Current structure and naming

- Preserve every existing top-level symbol block byte-for-byte.
- New two-terminal parts derive from `Ferrite_Bead_Template`.
- Part-specific symbol names and `Value` fields use the MPN, matching the original
  library convention.
- Package mappings are `0402 -> FL0402`, `0603 -> FL0603`, and `0805 -> FL0805`.
- Do not create or edit footprints as part of a symbol import.

## Selection policy used for this batch

1. Read all source CSVs and deduplicate identical LCSC part numbers, retaining the
   row with the highest availability.
2. Require Tape & Reel packaging, one line, stock of at least 1,000, one of the
   three supported packages, parseable impedance/current/DCR data, and a supplied
   local PDF that contains the selected MPN.
3. Group by package plus the complete `Impedance @ Frequency` value.
4. Prefer highest rated current, then lowest DCR, then tightest stated tolerance,
   then highest availability. An unstated tolerance is stored as `Not Specified`;
   never invent one.
5. Existing symbols win for an already represented functional key and footprint.
6. Abort on any unexplained symbol-name collision.

Availability, prices, order quantities, and supplier datasheet URLs do not belong
in symbols. Processed CSVs omit both `Pricing($)` and `Datasheet`.

## Required symbol properties

Populate `Reference`, `Value`, `Footprint`, `Datasheet`, `Description`,
`Manufacturer`, `Ferrite Series`, `Automotive Grade`, `Technology`, `Tolerance`,
`MPN`, `LCSC Part #`, `Impedance @ Frequency`, `Number of Lines`, `DCR`,
`Rated Current`, `Package`, `Operating Temperature`, `Packaging`, `MSL`, `RoHS`,
`Halogen Free`, `ki_keywords`, and `ki_fp_filters`.

Use `Not Specified` when a supplied source does not substantiate a compliance or
handling value. Set automotive status only when the applicable datasheet identifies
the family as automotive/AEC-Q200.

Datasheets are local links under:

`${PL_SYMBOL_DIR}/PL Magnetics Ferrite/Datasheets/<descriptive filename>.pdf`

## Transaction and validation checklist

For every future batch:

1. Inventory and hash the live library, all `.bak` files, source CSVs/PDFs, and all
   referenced footprints.
2. Read the supplied PDFs. Verify each selected MPN and every fixed metadata claim.
3. Calculate and freeze exact raw, unique, eligible, selected, skipped, added, and
   final-symbol counts before mutation.
4. Stage the complete candidate library and processed CSVs in a temporary directory.
5. Check balanced S-expressions, unique names, valid inheritance, required fields,
   existing-block byte identity, and local datasheet existence.
6. Export one unchanged symbol and representative new symbols for every package with
   KiCad 10 CLI.
7. Create a timestamped backup and log, then atomically replace the live library.
8. Re-run all checks after installation and compare footprint and `.bak` hashes.
9. Roll back the library and remove newly installed outputs if any mutation-stage
   check fails.

The completed batch log is in `Logs/ferrite_zener_update_20260819-102022.log` and
its original library is in `Backups/20260819-102022/`.
