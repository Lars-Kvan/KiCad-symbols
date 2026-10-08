# Dataset-driven radial electrolytic generation

Use this reference when a task turns supplier capacitor exports and manufacturer PDFs into PL symbols, through-hole footprints, and matching 3D models. It records the failure modes and validation invariants that are easy to miss in a large generated batch.

## Select only documented parts

- Union all relevant exports by exact manufacturer part number (MPN). Accept duplicate rows only when their electrical and mechanical identity fields agree; fail on conflicting duplicates rather than choosing one silently.
- Treat supplier rows as an index. A generated production symbol must resolve to either a supplied local manufacturer PDF or a non-empty datasheet URL. Keep undocumented rows in the manifest as rejected; do not emit symbols for them.
- Prefer local PDFs and reference them through `${PL_SYMBOL_DIR}`. A remote URL is still a datasheet, but record it as a localization fallback rather than reporting it as missing documentation.
- Filter polarization explicitly. Do not infer polar versus bi-polar from the description or package name.
- Omit empty optional properties. Never convert a missing ESR, ripple-current, lifetime, or tolerance into an invented default.

## Normalize and name deterministically

- Normalize capacitance and voltage before forming identifiers. A useful manufacturer-specific identifier is `{capacitance}_{voltage}_{MPN}`, for example `100uF_10V_ECE-A1AN101X`.
- For shared mechanical assets use `CP_Radial_D{D:.1f}mm_L{L:.1f}mm_P{P:.1f}mm`. Add a package-style suffix such as `_SnapIn` when identical D/L/P dimensions would otherwise collide with a mechanically different package.
- Keep exact source MPNs searchable. Do not put supplier stock or pricing into library properties.
- Derive every UUID from stable semantic inputs. The same source data must produce byte-identical output on a repeat run.

## Keep package mechanics distinct

- Ordinary radial cans and snap-in cans are not interchangeable. Do not select drill, pad, or terminal geometry from D/L/P alone.
- For ordinary radial leads, derive lead diameter from an authoritative manufacturer table. Finished drill is normally lead diameter plus fabrication clearance, rounded upward to the library grid. Check the required annular ring after limiting pad diameter for pad-to-pad clearance.
- For snap-ins, verify the terminal count and layout from the datasheet. Supplier package text such as `Radial, Can - Snap-In` does not prove whether a part has two electrical blades, three terminals, or stabilizer lugs. If the dataset establishes only a two-terminal standard layout, state that batch assumption in the report and do not generalize it to other series.
- Share a footprint/model only when package style, body envelope, pitch, hole geometry, and terminal count agree.

## Footprint visual and mechanical invariants

- Put pad 1 on negative X as a roundrect and pad 2 on positive X as a circle unless the local library establishes another convention.
- For a cylindrical body, make F.CrtYd a circle centered on the body. Do not approximate it with a square bounding box.
- Place the silk `+` polarity mark fully outside the body circle; putting it outside the circular courtyard as well is preferred when clearance permits. Scale its span and stroke with body diameter, cap it for very large cans, and keep the separate F.Fab polarity mark readable inside the body.
- Clip negative-side diagonal hatching to the circular body so each visible stripe reaches the outer circle. Apply pad clearance after circle clipping; do not leave floating stripe fragments.
- Include F.Fab polarity marking, exact body dimensions, deterministic identifiers, and a direct `${PL}` model link with an explicit transform only when required.

## Model the component rather than a cylinder

- Match nominal diameter, seated height, lead pitch, and terminal section. Check model extents numerically before visual review.
- Use a smooth revolved profile for the sleeve shoulders. Rounded shoulders should be part of the can profile, not separate torus-like beads.
- A convincing neutral model can include a satin dark sleeve, restrained gray polarity band with repeated minus marks, rolled lower crimp, recessed aluminum top, stamped vent grooves, lower rubber bung, and tinned leads or blades.
- Keep materials separate and restrained. Do not invent manufacturer-specific sleeve colors when geometry is shared across manufacturers.
- Generate artwork on the actual curved surface so bands and marks follow shoulder transitions without floating or clipping.

## Safe regeneration and pruning

- Stage the complete batch, validate it, and install atomically. Preserve all pre-existing top-level symbol blocks byte-for-byte.
- Appending with `preserve_existing` is safe for additions but cannot remove an earlier generated symbol that becomes ineligible. For pruning, use an ownership manifest or reconstruct from a verified pre-generation baseline, then prove that all baseline blocks are unchanged. Never delete a symbol merely because it is absent from the latest supplier export.
- Report source rows, rejected rows and reasons, datasheet resolution, symbol, footprint, model, geometry source, and any fallback assumption.

## Validation checklist

1. Assert source partition counts: generated, excluded by policy, and rejected must equal the unique MPN count.
2. Confirm every generated symbol has a datasheet reference and every referenced local PDF resolves.
3. Check every footprint for pad/drill safety, exactly one circular F.CrtYd graphic, model-path resolution, and balanced S-expressions.
4. Check every model for exact nominal extents, seated height, pitch, terminal type, and required detail markers.
5. Run the PL symbol audit, then use the installed KiCad CLI to export representative symbols and every new footprint. Include small, median, large, and each package style in visual/3D sampling.
6. Regenerate from the installed result and compare hashes for the symbol library, manifest, report, footprints, and models. A successful repeat produces zero symbol additions and zero content differences.
7. Remove only known temporary caches. Do not commit or push unless the user explicitly asks.
