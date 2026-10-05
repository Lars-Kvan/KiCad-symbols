# PL library conventions

Read this reference when choosing equivalents, symbol names, templates, display fields, or metadata.

## Source priority

1. Exact manufacturer datasheet supplied by the user.
2. Existing verified local datasheet for the same series and ratings.
3. Manufacturer product page or official series documentation.
4. Supplier export for stock, order code, packaging, lifecycle, and search metadata.

Do not infer a rating from an MPN pattern when the datasheet does not support it. Record uncertainty instead of inventing a value.

## Functional equivalence

An existing symbol is reusable only if package compatibility is established and every important capability is equal or better.

- **SMD resistor:** same resistance and package; rated power and working voltage at least as high. Tolerance and temperature coefficient must be compatible with the design need.
- **MLCC:** same capacitance and package; rated voltage at least as high; tolerance no worse; dielectric compatible. Treat C0G and NP0 as equivalent names. C0G/NP0 can normally satisfy an X7R stability requirement, but X7R is not an equivalent for a C0G/NP0 requirement.
- **Ferrite bead:** same package and impedance at the stated frequency; rated current at least as high; DCR no higher; tolerance compatible.
- **Diode:** same diode function, polarity/configuration, footprint pinout, and package compatibility. Check reverse voltage, current, dissipation, forward drop, recovery behavior, leakage, and surge or clamp ratings as applicable.

If one candidate has higher voltage but worse dielectric, lower DCR but lower current, or another incomparable tradeoff, neither dominates. Keep a capability-specific variant.

## Naming

- Resistors: `<value>_<package>`, for example `2.37K_1206`.
- Generic MLCCs: `<value>_<package>`, for example `33nF_1210`.
- MLCC capability variants: `<value>_<package>_<voltage>_<dielectric>`, for example `10nF_1210_630V_C0G`.
- Use exact MPNs where interchangeability is unsafe or the library already uses MPN names for that family.
- Use canonical engineering notation: `R`, `K`, `M` for resistor names and `pF`, `nF`, `uF` for capacitance. Normalize Unicode micro signs before parsing.

Do not encode supplier names or stock quantities in symbol names.

## Templates and footprints

| Family | Symbol library | Template | PL footprint convention |
|---|---|---|---|
| SMD resistor | `PL Resistor SMD` | `Resistor_Template` | `PL Resistor SMD:R<package>` |
| MLCC | `PL Capacitor MLCC` | `Capacitor_Template` | `PL Capacitor MLCC:C<package>` |
| Ferrite bead | `PL Magnetics Ferrite` | `Ferrite_Bead_Template` | Verified `PL Magnetics Ferrite:*` footprint |
| Schottky diode | `PL Diode Schottky` | Existing Schottky template | Verified `PL Diode Schottky:*` footprint |
| TVS diode | `PL Diode TVS` | Matching polarity template | Verified `PL Diode TVS:*` footprint |

Inspect the live template before generation; it is authoritative if its layout has changed.

## Display fields

New MLCC symbols derived from `Capacitor_Template` use the established visible layout:

| Property | Position | Alignment | Visibility |
|---|---|---|---|
| `Reference` | `2.54 2.032 0` | left | visible |
| `Value` | `2.54 0 0` | left | visible |
| `Rated Voltage` | `2.54 -2.032 0` | left | visible |

Use the normal Reference/Value text color inherited from the template. Do not add an explicit color override. Set `do_not_autoplace yes` for these three visible fields.

The established resistor template places Reference at `-2.794 3.81 0`, Value at `-2.794 2.032 0`, and the hidden footprint at `-1.778 0 90`.

## Property schemas

Populate only fields supported by the source. Empty custom properties should be omitted.

**SMD resistor:** `Manufacturer`, `Resistor Series`, `Technology`, `Tolerance`, `MPN`, supplier part number when useful, `Resistance`, `Package`, `Rated Power`, `Rated Voltage`, `Maximum Overload Voltage`, `Temperature Coefficient`, `Operating Temperature`, `Height`, and `Packaging`.

**MLCC:** `Manufacturer`, `Capacitor Series`, `Automotive Grade` when known, `Technology`, `Capacitor Class`, `Dielectric`, `Tolerance`, `MPN`, supplier part number when useful, `Capacitance`, `Package`, `Rated Voltage`, `Operating Temperature`, `Packaging`, and applicable application/rating fields.

**Ferrite bead:** `Manufacturer`, `Ferrite Series`, `Technology`, `Tolerance`, `MPN`, supplier part number when useful, `Impedance @ Frequency`, `Number of Lines`, `DCR`, `Rated Current`, `Package`, `Operating Temperature`, and `Packaging`.

For diode-family fields, follow `SYMBOL_PROPERTY_CLEANUP_SPEC.md` in the repository root. Never copy a union of properties from unrelated symbols.

## Datasheets

- Store datasheets under `<library>/Datasheets/` with stable human-readable filenames.
- Reference them as `${PL_SYMBOL_DIR}/<library>/Datasheets/<file>.pdf`.
- Verify the file begins with `%PDF` and is not an HTML error page.
- A series datasheet may support many generated symbols only when its package/value/rating tables actually cover those parts.
