# User guide

The [README](../README.md) walks through two complete examples with pictures. This page is the reference:
every control, every file format, and the command line.

## The window

| Section | Control | Notes |
| --- | --- | --- |
| 1. Power readings | **Load file…** | ArgoPower export, manual template, or a CSV exported by this app. The format is detected automatically. |
| | **Save blank template…** | Writes an empty manual-readings table for the lines you name. |
| | **ArgoPower power unit** | uW (default), mW or W. Applies to ArgoPower exports only; changing it reloads the file. |
| 2. Laser lines and fit | **Report** tick boxes | Which lines appear in the table, plot, CSV and report. |
| | **λ used (nm)** | Wavelength for photon numbers. Defaults to the column name. |
| | **Fit window min/max %** | Only readings inside are fitted. Default 0-50 %. |
| | **Through origin** | On: *P* = *m x*. Off: *P* = *m x* + *b*. |
| 3. Illuminated field and optics | **Width, Height (µm)** | Leave both blank for power only. |
| | **Power correction k** | *P*_sample = *k P*_meter. Leave at 1 unless you know the power at the sample differs from what you measured. |
| | **Power measured via / Imaging objective** | Free text, written into the CSV and the report. |
| 4. Acquisition | **Exposure per plane (s)** | Laser-on time per plane. Blank = no dose columns. |
| | **Slices per stack, Timepoints** | Whole numbers, at least 1. |
| 5. Settings to report | text box | `3.15, 6.3` for every line, or `488: 3.15, 6.3; 640: 5` per line. Settings are printed exactly as typed. |
| | **Also a grid every … % up to …** | Adds evenly spaced rows (e.g. every 2.5 %). |
| 6. Details for the report | Instrument, power meter, date, operator | Filled from the file's `#` lines when present. |

Rows you asked for (reported settings) are shaded green in the table; grid rows are white.

## File formats

### ArgoPower export

The raw CSV exported by Argolight's ArgoPower software. The calculator reads the `Result table values`
block:

```
Result table values
power_instruction;488_power;488_error;405_power;405_error;...
0.0;0.0;0.0;-0.0;-0.0;...
10.0;850.0;85.0;160.0;16.0;...
```

`power_instruction` is the laser setting (%), `<nm>_power` the reading and `<nm>_error` the meter's
uncertainty (drawn as error bars). Values are normally in µW.

### Manual readings template

```
# instrument: ...
# objective: ...
# power_meter: ...
# date: ...
# operator: ...
setting_pct,405_mW,488_mW,561_mW,640_mW
0,,,,
10,,,,
```

- Comma-separated. Files saved by Excel with semicolons and decimal commas (`0,85`) also work.
- One column per laser line, named `<nm>_mW` or `<nm>_uW`; the unit is in the name.
- Optional uncertainty columns `<nm>_error_mW` (or `_uW`); drawn as error bars.
- Empty cells are skipped, so you can measure only some lines or settings.
- Repeated settings are kept as replicate points.
- Lines starting with `#` are comments; `# key: value` lines for `instrument`, `objective`,
  `power_meter`, `date` and `operator` are copied into the report.

### CSV export

What **Export CSV…** (or `--csv`) writes. It has three parts:

1. `#` metadata lines: tool and version, date, source file name and SHA-256, objectives, *k*, field
   size and area, exposure, slices, timepoints, fit model and window, and for each line the wavelength
   used and the fit (slope, SE, intercept, R², n), followed by any warnings.
2. `## results`: one row per setting. Columns are `setting_pct`, `row_type` (`reported` or `grid`), then
   for each line `<nm>_P_mW`, `<nm>_P_se_mW`, `<nm>_E_mWcm2`, `<nm>_E_mWmm2`, `<nm>_E_Wcm2`,
   `<nm>_photons_cm2_s`, `<nm>_photons_um2_s`, `<nm>_H_plane_Jcm2`, `<nm>_H_stack_Jcm2`,
   `<nm>_H_total_Jcm2`, `<nm>_photons_plane_cm2`, `<nm>_photons_stack_cm2`, `<nm>_photons_total_cm2`
   (irradiance and dose columns only when the area and exposure are given), and `note`.
3. `## raw_readings`: every reading that was loaded, in mW, with `<nm>_in_fit` = 1 for readings inside
   the fit window. This block has the manual-template format, so loading the export re-fits the
   original readings, and the fit can be checked from this one file.

## Command line

`irradiance-calc` has a flag for every control in the window:

```
irradiance-calc FILE [--input-unit uW|mW|W] [--lines 488,640]
                [--fit-min 0] [--fit-max 50] [--free]
                [--width-um W --height-um H] [--k 1] [--wavelength-nm 640=638]
                [--power-objective TEXT] [--imaging-objective TEXT]
                [--exposure-s T] [--slices N] [--timepoints N]
                [--settings "488: 3.15, 6.3; 640: 5"] [--step 5] [--table-max 100]
                [--instrument TEXT] [--power-meter TEXT] [--date TEXT] [--operator TEXT]
                [--csv OUT.csv] [--report OUT.pdf] [--methods]
irradiance-calc --template OUT.csv [--template-lines 405,488,561,640]
```

Without `--settings` it prints a 5 % grid. `--methods` prints the methods paragraph. The exit code is 2
if the file cannot be read or an input is invalid.

## Re-running a calibration

The slope belongs to one optical path on one day. Measure again when you change objective, filter cube,
fibre or laser, after realignment, and at regular intervals. The power at a fixed percent setting can
change by tens of percent between sessions, which is why the guidelines recommend reporting measured
irradiance, not a percent setting.
