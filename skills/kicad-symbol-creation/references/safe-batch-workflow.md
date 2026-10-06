# Safe batch workflow

Read this reference before a batch generation or any operation that modifies a primary `.kicad_sym` library.

## Input and selection audit

- Enumerate new CSV, XLSX, PDF, and report files with timestamps and sizes.
- Record all column names before writing a parser; supplier exports use different labels for the same concepts.
- Parse stock values after removing separators. Apply lifecycle and manufacturer filters explicitly.
- Normalize `µ` and `μ` to `u` before SI parsing. Keep lowercase `m` distinct from uppercase `M`.
- Deduplicate packaging variants by functional key. Select representatives with explicit ranking criteria and report the discarded duplicates.
- Keep the original source row attached to each generated candidate so reports and properties remain traceable.

## Existing-library comparison

Parse top-level S-expressions, not lines. Build maps by symbol name and family-specific functional key. Use properties first, then descriptions only as supporting evidence. A missing or ambiguous rating is not proof of equivalence.

When an existing generic name has inadequate capability, retain it and add a suffixed variant. Never overwrite it merely because a new MPN is preferred.

## Candidate construction

1. Read each original library as bytes and reject an unexpected BOM or mixed newline style.
2. Build only new top-level symbol blocks.
3. Insert them immediately before the root closing parenthesis.
4. Parse the candidate and confirm the original blocks are byte-identical and in the same order.
5. Confirm the candidate count equals original count plus additions.
6. Confirm unique names, valid `extends` targets, unique top-level property names, PL-only footprints, and resolvable local assets.

## Transaction

- Stage candidate libraries, PDFs, footprints, and reports in a temporary directory.
- Validate staged artifacts before touching live files.
- Create a timestamped local backup under the workspace reports area and verify its bytes against each live source.
- Install new assets first and primary libraries last using same-volume temporary files plus atomic replacement.
- Track every installed path. On failure, restore all replaced libraries and remove only files created by the current run.
- Do not delete or rewrite pre-existing assets during rollback.

A Git backup or push is separate from the local transaction. Perform it only when the user asks.

## Validation

- Check balanced S-expressions and parse every top-level symbol.
- Run `scripts/audit_pl_symbols.py` against affected libraries.
- Export at least the first, middle, and last generated symbols with `kicad-cli sym export svg` for a large homogeneous batch; export every symbol when the batch is small or structurally diverse.
- Export every new footprint with `kicad-cli fp export svg` from an isolated temporary `.pretty` directory.
- Confirm all source PDFs and installed copies are valid and all symbol paths resolve.
- Run the generator again without `--apply`; it must propose zero additions.
- Inspect Git status and diff statistics without altering unrelated changes.

## Reporting

Each selected row should report:

- category and action (`add`, capability variant, reused equivalent, rejected, or review);
- generated or reused symbol name;
- manufacturer and MPN;
- supplier identifier and stock;
- normalized package/value and key ratings;
- footprint and datasheet;
- reason for equivalence, rejection, or variant creation.

The summary should include eligible source rows, unique selected keys, additions, variants, reused equivalents, footprints created/reused, validation results, and backup location.
