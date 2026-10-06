# Symbol Property Cleanup Report

- Primary libraries checked: 64
- Top-level symbols checked: 1574
- Libraries changed: 42
- Properties removed: 403
- Properties renamed: 74
- Properties added: 1
- Property values replaced: 30
- Unresolved conflicts: 0

The complete per-property action log is in `SYMBOL_PROPERTY_CLEANUP_AUDIT.csv`.

## Unresolved conflicts

None.

## Verified value corrections

- Corrected `ADS131M04IPWR` to `Resolution = 24-bit` and
  `Sample Rate = 64kSPS`.
- Corrected the USB connector variants to `USB 2.0 Type-C` and
  `USB 2.0 Type-B` instead of the copied Micro-B value.
- Split the audio jack's conflated field into `Number of Conductors = 3` and
  `Pin Count = 5`.
- Corrected the three Würth `744376252...` inductors from exact official
  datasheets, including inductance, current ratings, DCR, self-resonant
  frequency, core material, and footprint filter where applicable. Their
  `Datasheet` fields now link to the exact official PDFs.
- Cleared the `6.8uH_74437625200682` footprint because the assigned 2012-series
  footprint does not match the exact 2520-series part. A verified footprint must
  be created or assigned before PCB use.

## Validation

- A second dry run is clean: 64 libraries and 1,574 symbols checked, with zero
  pending actions or unresolved conflicts.
- The migration validates balanced S-expressions, required Core properties,
  per-library allowlists, unique symbol/property names, and valid `extends`
  targets.
- Checkpoint/current comparison found zero non-property differences; symbol
  geometry, pins, inheritance, and other non-property content are unchanged.
- No Core property was removed or renamed, and all 10 intentional `ki_locked`
  fields were preserved.
- KiCad 10 successfully parsed and exported one changed symbol from each of the
  42 changed libraries (42/42 passed).

## Scope

Only primary `.kicad_sym` libraries were changed. Backups, staged libraries,
datasheets, footprints, scripts other than the cleanup utility, and source data
were not rewritten. The now-unreferenced local file
`PL Magnetics Inductor Power/Datasheets/74437625200122.pdf` remains untouched,
but its contents identify part `7443782012068`; it should be replaced or renamed
in a separate datasheet-maintenance pass.
