# KiCad Symbol Property Cleanup Specification

Status: planning document only. The symbol libraries have not been cleaned by
this document.

## Scope and inventory

The active scope is the 64 primary `.kicad_sym` library files in this repository.
They currently contain 1,574 top-level symbols and 34,402 top-level property
blocks, using roughly 226 different property-name spellings.

The following are deliberately outside the first cleanup pass:

- Timestamped files under `Backups/`.
- Staged libraries under `Data/`.
- `PL Diode Zener/New_Library.kicad_sym`.
- Footprints, datasheets, scripts, and source CSV files.

`PL Connector Header/PL Connector Header.kicad_sym` and its `.bak` file already
had uncommitted user changes when this specification was written. A future
cleanup must preserve or explicitly reconcile those changes before touching that
library.

## Property rules

### Common property sets

The tables below use these abbreviations:

- **Core**: `Reference`, `Value`, `Footprint`, `Datasheet`, `Description`. These
  are KiCad's standard fields and remain on every top-level symbol. It is valid
  for `Footprint` or `Datasheet` to be empty on a deliberately generic or virtual
  symbol.
- **Search**: `ki_keywords`, `ki_fp_filters`. Keep each only where it is useful.
- **ID**: `MPN`, `Manufacturer`. Require `MPN` for a manufacturer-specific,
  orderable part. Keep or add `Manufacturer` only when an authoritative source
  supports it. Templates and generic symbols do not get blank ID fields.
- **Batch metadata**: `LCSC Part #`, `Package`, `Packaging`, `MSL`, `RoHS`,
  `Halogen Free`, `Automotive Grade`, and `Technology`. Keep this set only in
  the libraries whose existing, documented batch-import policy calls for it.
  It is not a universal property set.

Every row below means “these fields are allowed in this library,” not “copy all
of these fields into every symbol.” A symbol keeps only properties which apply
to that exact part and have a supported value.

### Per-symbol sparsity and inheritance

1. Do not use a template as a union of every custom property used by its child
   symbols. A template may contain Core fields, useful Search fields, and a
   non-empty default that is genuinely common to every child.
2. Remove empty custom properties from templates and ordinary symbols. Core
   fields are the exception.
3. Remove custom fields containing `N/A`, `None`, or `Unknown`. `Not Specified`
   may remain only where an existing batch-import policy explicitly requires an
   auditable statement that the source did not specify the value.
4. Do not create a field merely because another symbol in the same library has
   it. Examples include `Supply Voltage` on a passive crystal, `Operating
   Temperature` on a mounting-hole template, or `MPN` on a generic symbol.
5. `ki_locked` and `Sim.Enable` are KiCad behavior fields, not component
   metadata. Preserve them only on symbols where their current behavior is
   intentional.

### Globally discard imported bookkeeping

These fields are supplier/SnapEDA bookkeeping or duplicates of Core/ID fields.
Discard them after salvaging a better value into the canonical field when
appropriate:

`Availability`, `Check_prices`, `Price`, `SnapEDA_Link`, `Description_1`, `MF`,
`MP`, `MANUFACTURER`, `MAXIMUM_PACKAGE_HEIGHT`, `PARTREV`, and `STANDARD`.

The salvage rules are:

- `MANUFACTURER` or `MF` may populate `Manufacturer` if the value is verified.
- `MP` may populate `MPN` if it agrees with the part and the existing `MPN`.
- `Description_1` may replace an empty or demonstrably worse `Description`, then
  `Description_1` is removed.
- `MAXIMUM_PACKAGE_HEIGHT` may populate `Height` only in a library whose schema
  allows `Height`, and only after verification.
- Availability, price, order quantities, supplier links, revision markers, and
  footprint-generator standards are removed rather than migrated.

`approval_checks` and `approval_properties` are AI/import workflow artifacts,
not symbol properties. Discard them from all libraries.

### Canonicalization rules

| Existing name(s) | Canonical action |
|---|---|
| `Rated Curretn`, `Rated current`, `Current Rating` | Use `Rated Current` where that is the correct physical quantity. |
| `Contact Current Rating` | Use `Rated Current`; retain `Contact Rating` only when it contains a combined contact rating that cannot be separated reliably. |
| `MANUFACTURER`, `MF` | Use `Manufacturer`. |
| `MP`, `Part Number` | Use `MPN`, but only if the value identifies the same exact part. |
| `Max Reverse Voltage`, `Reverse Voltage` | Use `Reverse Voltage` for ordinary diodes. TVS parts use `Reverse Standoff Voltage` instead. |
| `Reverse Standoff`, `Voltage Breakdown` | Use `Reverse Standoff Voltage`, `Breakdown Voltage`. |
| `Reverese Leakage`, `Reverse Leakage` | Use `Reverse Leakage Current`. |
| `Continous Drain Current`, `Rated Continous Current`, `Rated Continuous Current` | Use `Continuous Drain Current`. |
| `Rated Voltage` on FET/GaN parts | Use `Drain-Source Voltage`. |
| `On Resistance` | Use `On-Resistance`. |
| `Vgs(th)`, `Vgs(th) (Max)` | Use `Gate Threshold Voltage`; preserve min/typ/max qualifiers in the value. |
| `Coss` | Use `Output Capacitance (Coss)`. |
| `Voltage Dropout`, `Voltage Droupout` | Use `Dropout Voltage`. |
| `Max Input Voltage` | Use `Input Voltage Range` only when the minimum/range can be verified; otherwise keep `Max Input Voltage` as a distinct maximum rating. |
| `Voltage Supply`, `Operating Voltage` | Use `Supply Voltage` or `Supply Voltage Range`, based on what the datasheet actually specifies. |
| `Current Supply` | Use `Supply Current`. |
| `Interface Type`, `Protocol Type` | Use `Interface` when they describe an electrical/data interface. |
| `Number of Gates/Channels` | Use `Number of Channels`, with the gate/function detail moved to `Description` if needed. |
| `Z@Freq` | Use `Impedance @ Frequency`. |
| `L (µH)` | Use `Inductance` with units retained in the value. |
| `Tol. L` | Use `Inductance Tolerance`. |
| `IR (A)` | Use `Rated Current`. |
| `ISAT (A)` | Use `Saturation Current`. |
| `RDC max. (mΩ)`, `DC Resistance` | Use `DCR`. |
| `fres (MHz)`, `Resonant Frequency`, `SRF` in inductor libraries | Use `Self Resonant Frequency`. |
| `Shielded` | Use `Shielding`. |
| `Stability`, or `Tolerance` in the crystal library | Use `Frequency Stability` or `Frequency Tolerance`, respectively. |
| `Sample Rate` in the DAC library | Use `Conversion Rate`; ADCs retain `Sample Rate`. |
| `B-Constant/Beta` | Remove when an exact `B0/50`, `B25/50`, `B25/75`, `B25/85`, or `B25/100` field carries the value. |
| `Impedance` in the acoustic library | Use `Rated Impedance` when that is what the datasheet specifies. |
| `Pin Count`, `Number of Contacts`, `Number of Poles/Pins` | Use the library-specific connector field listed below; split conductors and physical pins where necessary. |

Canonicalization is not permission to overwrite a conflict. If aliases on one
symbol disagree, keep neither as authoritative until the exact datasheet has
been checked.

## Library-by-library property decisions

All libraries keep Core. The “keep/allow” column lists additional properties.
The “discard/normalize” column is in addition to the global rules above.

### Passives, connectors, and electromechanical parts

| Library | Keep/allow beyond Core | Discard or normalize |
|---|---|---|
| `PL Battery` | Search; ID | No library-specific discard. Do not put ID fields on a generic battery symbol. |
| `PL Busbar` | ID when orderable; `Material`, `Dimensions` | Remove blank `MPN`/`Material` from templates or generic busbars. |
| `PL Capacitor Electrolytic` | Search; ID; `Tolerance`, `Rated Voltage`, `ESR`, `Ripple Current`, `Operating Temperature` | Discard `approval_checks`, `approval_properties`. Do not force ESR or ripple fields onto a template. |
| `PL Capacitor MLCC` | Search; ID; Batch metadata; `Capacitor Series`, `Capacitor Class`, `Dielectric`, `Tolerance`, `Capacitance`, `Rated Voltage`, `Operating Temperature` | No blanket removal of the documented batch fields. Remove any field from a symbol when it is empty/inapplicable, and do not add generic `Height`. |
| `PL Capacitor Polymer` | Search; ID; `Tolerance`, `Rated Voltage`, `ESR`, `Ripple Current`, `Operating Temperature` | Discard `approval_properties`; remove empty custom fields. |
| `PL Connector Audio` | Search; ID; `Connector Type`, `Number of Conductors`, `Pin Count`, `Rated Current` | Split `Number of Poles/Pins` if evidence permits; normalize `Contact Current Rating`; discard SnapEDA bookkeeping. |
| `PL Connector Barrel` | Search; ID; `Connector Type`, `Pin Diameter`, `Rated Current`, `Rated Voltage` | Merge `Current Rating` into `Rated Current`; remove the duplicate only after checking values. |
| `PL Connector Header` | Search; ID; `Pin Count`, `Number of Rows`, `Pitch`, `Rated Current`, `Rated Voltage` | Do not add these fields to connector templates unless the template has a real common value. Preserve the pre-existing uncommitted edits. |
| `PL Connector Power` | Search; ID; `Number of Contacts`, `Pitch`, `Rated Current`, `Rated Voltage` | Normalize `Pin Count` to `Number of Contacts`; salvage `MF` to `Manufacturer`; discard `SnapEDA_Link`. |
| `PL Connector RF` | Search; ID; `Connector Type`, `Impedance`, `Frequency Range`, `Board Thickness` | Consolidate `Frequency` and `Max Frequency` into `Frequency Range` only after datasheet review. |
| `PL Connector Terminal` | Search; ID; `Number of Contacts`, `Pitch`, `Rated Current`, `Rated Voltage`, `Wire Gauge Range`, `Operating Temperature` | Normalize `Wire Gauge` to `Wire Gauge Range` when it is a range; otherwise retain it only if it represents a distinct nominal wire size. |
| `PL Connector USB` | Search; ID; `Connector Type`, `USB Version`, `Number of Contacts`, `Rated Current`, `Mounting Type`, `Height` | Normalize `Current Rating`; salvage verified manufacturer/height; discard the remaining SnapEDA fields and meaningless `Package = None`. |
| `PL Display` | Search; ID; `Resolution`, `Interface`, `Supply Voltage` | Merge `Interface Type` into `Interface` and `Operating Voltage` into `Supply Voltage`; verify the values because the current duplicates can be wrong. |
| `PL Electromechanical Button` | Search; ID; `Action Type`, `Mounting Type`, `Rated Current`, `Rated Voltage`; `Contact Rating` only if it adds non-duplicated information | Remove redundant `Contact Rating` after its current and voltage have been captured separately. |
| `PL Electromechanical Navigation Switches` | Search; ID; `Number of Positions/Directions`, `Actuation Force`, `Rated Current`, `Rated Voltage`; `Contact Rating` only if non-duplicative | Same contact-rating rule as the button library. |
| `PL Resistor SMD` | Search; ID; Batch metadata; `Resistor Series`, `Resistance`, `Tolerance`, `Rated Power`, `Rated Voltage`, `Maximum Overload Voltage`, `Operating Temperature`, `Temperature Coefficient`, `Height` | Keep the documented Yageo batch schema. Remove empty custom fields from the template and from parts that do not use the batch schema. |
| `PL Resistor Thermistor` | Search; ID; `Nominal Resistance`, `Resistance Tolerance`, `B Value Tolerance`, applicable exact B-ratio fields (`B0/50`, `B25/50`, `B25/75`, `B25/85`, `B25/100`), `Operating Temperature` | Remove empty B-ratio fields. Remove generic `Tolerance` and `B-Constant/Beta` when the precise fields exist. |
| `PL Resistor Variable` | Search; ID; `Resistance Tolerance`, `Rated Power`, `Taper Type` | Rename `Tolerance` to `Resistance Tolerance`; discard `R25` when it is `N/A` or not applicable. |

### Diodes, transistors, and optoelectronics

| Library | Keep/allow beyond Core | Discard or normalize |
|---|---|---|
| `PL Diode LED` | Search; ID; applicable Batch metadata; `Color`, `Forward Voltage`, `Forward Current`, `Viewing Angle`, `Wavelength`, `Luminous Intensity`; `Label` only on a generic/multi-color template that uses it | Normalize `Rated Current` to `Forward Current`. Split or remove `Luminous Intensity / Wavelength` after the two canonical fields are populated. |
| `PL Diode Schottky` | Search; ID; `Forward Voltage`, `Rated Current`, `Reverse Voltage` | Normalize `Max Reverse Voltage` to `Reverse Voltage`; do not add MPN/rating fields to `Schottky_template`. |
| `PL Diode Silicon` | Search; ID; `Forward Voltage`, `Rated Current`, `Reverse Recovery Time`, `Reverse Voltage` when supported | Correct `Rated Curretn` to `Rated Current`; resolve duplicates from the datasheet. |
| `PL Diode TVS` | Search; ID; applicable Batch metadata; `TVS Series`, `Polarity`, `Number of Channels`, `Reverse Standoff Voltage`, `Breakdown Voltage`, `Clamping Voltage`, `Reverse Leakage Current`, `Rated Power`, `Rated Current`, `Operating Temperature` | Normalize `Reverse Standoff` and `Voltage Breakdown`; remove all rating/ID fields from templates unless they are non-empty shared defaults. |
| `PL Diode Zener` | Search; ID; Batch metadata; `Zener Series`, `Diode Configuration`, `Tolerance`, `Zener Voltage`, `Zener Voltage Range`, `Rated Power`, `Reverse Leakage Current`, `Zener Impedance Zzt`, `Zener Impedance Zzk`, `Operating Junction Temperature`, `Operating Temperature` where distinct and supported | Normalize misspelled leakage aliases. Do not put orderable-part or rating fields on `Zener_Template`/`Zener_SOT23_Template`. |
| `PL Optocoupler` | Search; ID; `Number of Channels`, `Isolation Voltage`, `Current Transfer Ratio`, `Data Rate`, `Height` when applicable | Salvage `MANUFACTURER` and verified height; discard `STANDARD` and other import bookkeeping. Do not invent missing electrical fields. |
| `PL Transistor BJT` | Search; ID; `Collector-Emitter Voltage`, `Collector Current`, `DC Current Gain`, `Power Dissipation`, `Operating Temperature` | Normalize `Rated Current` to `Collector Current` and `Rated Power` to `Power Dissipation`; keep neither duplicate if values conflict. |
| `PL Transistor FET` | Search; ID; `Drain-Source Voltage`, `Continuous Drain Current`, `On-Resistance`, `Gate Threshold Voltage`, `Gate Charge`, `Power Dissipation`, `Operating Temperature` when supported | Remove misspelled `Continous Drain Current`; normalize `Vgs(th)` names. Several current aliases conflict and require exact-part datasheet review. |
| `PL Transistor GaN` | Search; ID; `Drain-Source Voltage`, `Continuous Drain Current`, `Peak Drain Current`, `On-Resistance`, `Gate Threshold Voltage`, `Gate Charge`, `Gate Resistance`, `Output Capacitance (Coss)` | Normalize `Rated Voltage`, both continuous-current spellings, `Rated Peak Current`, `On Resistance`, and `Coss`. Resolve EPC2305's conflicting current values from its datasheet. |

### Integrated circuits and modules

| Library | Keep/allow beyond Core | Discard or normalize |
|---|---|---|
| `PL IC Instrumentation Amplifier` | Search; ID; `Gain`, `Bandwidth`, `Common Mode Rejection Ratio`, `Input Offset Voltage`, `Supply Voltage` when supported | Rename `Offset Voltage` if later added; no current library-specific discard. |
| `PL IC ADC` | Search; ID; `Resolution`, `Sample Rate`, `Interface`, `Number of Channels`, `Supply Voltage` when supported | Validate every value; `ADS131M04IPWR` currently appears to have its resolution and sample-rate values swapped. |
| `PL IC Analog Switch` | Search; ID; `Number of Channels`, `Supply Voltage`, `On-Resistance`, `Off-Isolation`, `Bandwidth` when supported | Normalize `Max Supply Voltage` only after deciding whether it is a maximum or a range, not by blind renaming. |
| `PL IC Battery` | Search; ID; `Supply Voltage`, `Charge Voltage`, `Max Charge Current`, `Operating Temperature` | No library-specific discard beyond empty/inapplicable fields. |
| `PL IC Comparator` | Search; ID; `Input Offset Voltage`, `Propagation Delay`, `Supply Voltage` | Current `GBW = N/A` and `Slew Rate = N/A` fields are not useful comparator metadata and should be removed. Normalize `Offset Voltage`. |
| `PL IC Current Amplifier` | Search; ID; `Gain`, `Common Mode Voltage`, `Bandwidth`, `Supply Voltage`, `Input Offset Voltage` when supported | No library-specific discard beyond empty/inapplicable fields. |
| `PL IC DAC` | Search; ID; `Resolution`, `Conversion Rate`, `Interface`, `Number of Channels`, `Supply Voltage` when supported | Remove duplicate `Sample Rate` after confirming `Conversion Rate`; do not copy ADC terminology into DAC symbols. |
| `PL IC Digital` | Search; ID; `Supply Voltage`, `Supply Current`, `Logic Family`, `Propagation Delay` when supported | Normalize `Current Supply` and `Voltage Supply`; discard `N/A` values and resolve conflicting supply-voltage fields from the datasheet. |
| `PL IC Flash` | Search; ID; `Memory Capacity`, `Page Size`, `Interface`, `Supply Voltage` when supported | Normalize `Interface Type` to `Interface`. |
| `PL IC Gate Driver` | Search; ID; `Supply Voltage Range`, `Source Current`, `Sink Current`, `Rise Time`, `Fall Time`, `Propagation Delay` when supported | No library-specific discard beyond empty/inapplicable fields. |
| `PL IC Interface` | Search; ID; `Interface`, `Data Rate` or `Baud Rate` as appropriate, `Supply Voltage`, `Number of Channels` when supported | Normalize `Protocol Type` to `Interface` when it is an interface name; do not conflate baud rate with raw bit rate. |
| `PL IC Isolator` | Search; ID; `Number of Channels`, `Data Rate`, `Isolation Voltage`, `Supply Voltage` when supported | No library-specific discard beyond empty/inapplicable fields. |
| `PL IC Logic` | Search; ID; `Number of Channels`, `Supply Voltage`, `Propagation Delay`, `Logic Family` when supported | Normalize `Number of Gates/Channels`; keep functional detail in `Description`. |
| `PL IC Opamp` | Search; ID; `Gain Bandwidth`, `Slew Rate`, `Input Offset Voltage`, `Output Current`, `Supply Voltage`, `Number of Channels` when supported | Normalize `Offset Voltage` and `Rated Output Current`; remove empty `MPN` and any fields not verified for the exact package/variant. |
| `PL IC Power` | Search; ID; `Input Voltage Range`, `Output Voltage`, `Output Current`, `Switching Frequency`, `Efficiency`, `Quiescent Current` when supported | Discard SnapEDA bookkeeping. Remove `N/A` output/current/efficiency fields rather than retaining placeholders. |
| `PL IC Power Management` | Search; ID; `Input Voltage Range`, `Output Voltage`, `Output Current`, `Quiescent Current`, `Operating Temperature` when supported | No library-specific discard beyond empty/inapplicable fields. |
| `PL IC PWM` | Search; ID; `Switching Frequency Range`, `Supply Voltage`, `Output Current` when supported | No library-specific discard beyond empty/inapplicable fields. |
| `PL IC Regulator Linear` | Search; ID; `Input Voltage Range`, `Output Voltage`, `Output Current`, `Dropout Voltage`, `PSRR`, `Quiescent Current`, `Operating Temperature` | Normalize `Rated Current` to `Output Current` and all dropout misspellings to `Dropout Voltage`; remove empty or `Unknown` PSRR. |
| `PL IC uC` | Search; ID; `Core Architecture`, `Clock Speed`, `Flash Size`, `RAM Size`, `Supply Voltage`, `Interfaces` when supported | No library-specific discard beyond empty/inapplicable fields. |
| `PL IC USB Interface` | Search; ID; `USB Compliance Version`, `Data Rate`, `Supply Voltage`, `Isolation Voltage` when applicable | No library-specific discard beyond empty/inapplicable fields. |
| `PL Power Module` | Search; ID; `Nominal Input Voltage`, `Input Voltage Range`, `Output Voltage`, `Output Current`, `Output Power`, `Efficiency`, `Isolation Voltage` when applicable | Normalize `Vin (V)`, `Vout (V)`, and `Iout (A)` only after checking the datasheet. Discard SnapEDA bookkeeping. Resolve duplicate/conflicting input-voltage fields instead of picking one automatically. |
| `PL Voltage Reference` | Search; ID; `Output Voltage`, `Initial Accuracy`, `Temperature Coefficient`, `Operating Temperature`, `Supply Current` when supported | No library-specific discard beyond empty/inapplicable fields. |

### Magnetics, mechanical, thermal, and schematic-only libraries

| Library | Keep/allow beyond Core | Discard or normalize |
|---|---|---|
| `PL Magnetics Choke` | Search; ID; `Inductance`, `Rated Current`, `DCR`, `Impedance @ Frequency`, `Operating Temperature` when supported | Rename `Z@Freq` to `Impedance @ Frequency`; remove empty `Rated Current`. |
| `PL Magnetics Ferrite` | Search; ID; Batch metadata; `Ferrite Series`, `Impedance @ Frequency`, `Number of Lines`, `DCR`, `Rated Current`, `Tolerance`, `Operating Temperature` | Keep the documented batch schema. Consolidate any older plain `Impedance` into `Impedance @ Frequency` only when the frequency is known. |
| `PL Magnetics Inductor Power` | Search; ID; `Inductance`, `Inductance Tolerance`, `Rated Current`, `Saturation Current`, `DCR`, `Self Resonant Frequency`, `Shielding`, `Core Material`, `Mounting Technology`, `Operating Temperature` | Normalize the Wurth/import aliases in the canonicalization table. Discard `Manufacturer URL`, `Published Date`, `Match Code`, `Size`, and `Critical Parameter`. Treat conflicting duplicate ratings as unresolved. |
| `PL Magnetics Inductor Signal` | Search; ID; `Inductance`, `Inductance Tolerance`, `Rated Current`, `Saturation Current`, `DCR`, `Self Resonant Frequency`, `Shielding`, `Operating Temperature` | Rename generic `Tolerance` to `Inductance Tolerance`; otherwise no library-specific discard. |
| `PL Magnetics Transformer Signal` | Search; ID; `Primary Inductance`, `Turns Ratio`, `Frequency Range`, `Rated Current`, `DCR`, `Isolation Voltage` when supported | No library-specific discard beyond empty/inapplicable fields. |
| `PL Mechanical Mounting Hole` | Search; `Hole Diameter` | No ID or electrical rating fields on generic mounting holes. Remove empty `Hole Diameter`; derive it from the verified footprint only if desired. |
| `PL Mechanical Spacer` | Search; ID; `Thread Size`, `Material`, `Height` when supported | No library-specific discard beyond empty/inapplicable fields. |
| `PL Net Tie` | Search only | No custom part metadata. Preserve only intentional KiCad behavior fields. |
| `PL Oscillator Crystal` | Search; ID; applicable Batch metadata; `Frequency`, `Frequency Tolerance`, `Frequency Stability`, `Load Capacitance`, `Equivalent Series Resistance`, `Operating Temperature`; `Supply Voltage` only for active oscillators | Normalize `Stability` and generic `Tolerance`. Do not place `Supply Voltage` on passive crystals or part fields on templates. |
| `PL Power Symbols` | Search only; intentional `ki_locked` | No custom component metadata. |
| `PL Test Point` | Search; `Label`; ID only for a genuinely orderable test-point component | Do not copy `Label` to unrelated symbols; no other custom metadata is currently justified. |
| `PL Thermal` | Search; ID; applicable `Thermal Resistance`, `Thermal Conductivity`, `Material`, `Dimensions`, `Operating Temperature`, `Temperature Coefficient` | Heat pipes and thermal jumpers use different subsets. Remove blank fields from `Thermal_Jumper_Template` and never union the two subsets. |
| `PL Transducer Acoustic` | Search; ID; `Frequency Range`, `Resonant Frequency`, `Rated Impedance`, `SPL`, `S/N` | Merge plain `Impedance` into `Rated Impedance` when equivalent; keep microphone S/N only where applicable. |
| `PL Wire Pad` | Search; `Label` | No ID or electrical rating fields on generic wire pads. |
| `PL Graphic` | Search; intentional `Sim.Enable`; `Vin` only on `VIN_Marking` while it is used as a visible editable annotation | No procurement or electrical-rating schema. Do not propagate `Vin` to the warning graphics. |

## Confirmed conflict hotspots

These are examples proving that the later cleanup cannot safely be a simple
“keep the first field” operation:

- `PL Magnetics Inductor Power`: `100uH_SRN8040-101M` contains both `Rated
  current` and `Rated Current`; `18uH_SRR1280-180M` contains the same pair with
  conflicting values (`4.8A` versus `4.1A`). Several Wurth symbols also contain
  imported `L (µH)`, `Part Number`, current, and resistance values that visibly
  belong to a different MPN.
- `PL Transistor FET`: several parts contain misspelled and correctly spelled
  drain-current fields with different values.
- `PL Transistor GaN`: both continuous-current spellings occur, and EPC2305 has
  conflicting values.
- `PL IC Regulator Linear`: `Dropout Voltage`, `Voltage Dropout`, and the typo
  `Voltage Droupout` coexist.
- `PL Display`: `Interface`/`Interface Type` and `Supply Voltage`/`Operating
  Voltage` are duplicates.
- `PL IC DAC`: `Sample Rate` and `Conversion Rate` duplicate one another.
- `PL Oscillator Crystal`: `Stability` and `Frequency Stability`, plus generic
  `Tolerance` and `Frequency Tolerance`, coexist.
- `PL Power Module`: abbreviated voltage/current fields coexist with canonical
  fields and at least one input-voltage set is inconsistent.
- `PL Connector Audio`, `PL Connector USB`, `PL IC Power`, `PL Optocoupler`, and
  `PL Power Module` contain obvious SnapEDA/import bookkeeping.
- `PL Capacitor Electrolytic` and `PL Capacitor Polymer` contain approval JSON
  accidentally stored as symbol properties.

## Requirements for the later cleanup pass

1. Make a recoverable backup or a dedicated Git commit before changing any
   primary library.
2. Parse top-level KiCad S-expressions. Do not use an unscoped text replacement
   that could modify nested graphical units or quoted content.
3. Build a per-symbol report containing original name, property, value, action,
   canonical destination, and reason.
4. Apply the allowlist per library and the sparsity rule per symbol. Never copy a
   property from one symbol to another.
5. Merge aliases only when their values agree or the authoritative datasheet for
   that exact MPN resolves the conflict. Put unresolved conflicts in a review
   report and leave the original library unchanged for that symbol.
6. Treat property-name cleanup and property-value validation as separate checks.
   A correctly named field can still contain another part's value.
7. Preserve symbol geometry, pins, inheritance, order, encoding, line endings,
   and all unrelated files byte-for-byte.
8. Validate balanced S-expressions, unique top-level symbol names, valid
   `extends` targets, unique canonical property names per symbol, local datasheet
   paths, and referenced footprints.
9. Parse/export representative changed symbols with the installed KiCad CLI,
   then inspect the final Git diff before accepting the cleanup.

No property value in this specification is approved merely because it currently
exists. Electrical values still need exact-part datasheet validation wherever
there is a conflict, suspicious duplication, or evidence of cross-part copying.
