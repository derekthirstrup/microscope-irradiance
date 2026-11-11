# Changelog

## [1.0.0] - unreleased

First public release. Rewrite of the internal "ArgoPower Calibrator" (0.x).

### Added
- Irradiance in mW/cm² (primary), alongside mW/mm² and W/cm².
- Photon flux (photons cm⁻² s⁻¹ and µm⁻² s⁻¹) with an editable wavelength per line.
- Dose per plane, per z-stack and in total, in J/cm² and photons/cm².
- Reported-settings list (`3.15, 6.3` or `488: 3.15; 640: 5`), printed with the precision typed.
- Manual-readings template for stand-alone meters (Thorlabs etc.), with a *Save blank template* button.
- Linearity warning (R² < 0.995 or free/through-origin slopes differing by > 5 %) and extrapolation warning.
- Optional power correction factor *k*, and fields for the objective used to measure power and to image.
- PDF report with plots, fit summary, results, inputs and a methods paragraph.
- Full CSV export with a metadata block (tool version, source SHA-256, fit, inputs) and the raw readings.
- Command line with a flag for every GUI input.
- Installers for Windows, macOS and Linux built in CI.

### Fixed
- An exported table can be loaded again (it re-fits the raw readings stored in the export).
- Settings such as 2.5 % or 3.15 % are no longer rounded to whole numbers.
- Build: relative paths in the PyInstaller spec, no UPX, Windows version resource.
