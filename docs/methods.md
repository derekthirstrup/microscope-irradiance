# Methods: formulas, assumptions and uncertainty

This page documents exactly what Irradiance Calculator computes. The code that does it is short and
standard-library only: `src/irradiance_calc/fit.py` (the fit), `units.py` (the conversions; the physical
constants live there and nowhere else) and `table.py` (applying them to each setting).

## 1. Power calibration fit

Readings are pairs (*x*ᵢ, *P*ᵢ): laser setting in %, power in mW. Only readings inside the fit window
[*x*_min, *x*_max] (default 0-50 %) are used.

**Through the origin** (default), *P* = *m x*:

$$m = \frac{\sum x_i P_i}{\sum x_i^2}, \qquad
\mathrm{SE}(m) = \sqrt{\frac{\sum (P_i - m x_i)^2}{(n-1)\sum x_i^2}}$$

A 0 % setting gives no light, so the line is forced through zero. Fitting a free intercept to a handful of
points mostly fits the meter's noise and invents a non-zero power at 0 %.

**Free intercept** (optional), *P* = *m x* + *b*: ordinary least squares, with the usual standard errors
of slope and intercept and of the mean response at *x*.

R² is computed as 1 − SSE/SST about the mean of the readings in the window, for both models.

The default window stops at 50 % because many lasers roll off at high settings; on the example
instrument 100 % of 488 nm reads 8.62 mW where the 0-50 % fit predicts 8.98 mW.

Replicate readings (the same setting on several rows) are all used as separate points.

## 2. Warnings

**Linearity.** A warning is given for a laser line when either

- R² < 0.995 within the fit window, or
- the free-intercept slope and the through-origin slope differ by more than 5 %
  (computed whatever model is selected, if there are at least three distinct settings).

On the example file, 405 nm over 0-50 % has R² = 0.967 and slopes differing by 11 %, and is flagged;
488, 561 and 640 nm are not.

**Extrapolation.** A requested setting is flagged when it is

- below the lowest non-zero setting in the fit window (the value then depends on the fitted line
  between 0 and the first reading), or
- above the fit window or above the highest reading in it.

## 3. Irradiance

With *P* the fitted power at the requested setting and *A* the illuminated area:

$$E = \frac{k\,P}{A}, \qquad E\,[\mathrm{mW\,cm^{-2}}] = 100\,\frac{k\,P\,[\mathrm{mW}]}{A\,[\mathrm{mm^2}]}$$

*A* = width × height of the illuminated field (entered in µm). *k* is an optional correction factor
(default 1) for when the power was measured somewhere other than the sample plane of the imaging path,
for example through a different objective: *P*_sample = *k P*_meter. The reported *P* column already
includes *k*.

Also reported: mW/mm² (= mW/cm² / 100) and W/cm² (= mW/cm² / 1000).

## 4. Photon flux

$$\Phi = E\,\frac{\lambda}{h c}, \qquad
\Phi\,[\mathrm{cm^{-2}\,s^{-1}}] = 5.034117\times10^{12}\;E\,[\mathrm{mW\,cm^{-2}}]\;\lambda\,[\mathrm{nm}]$$

with *h* = 6.626 070 15 × 10⁻³⁴ J s and *c* = 299 792 458 m/s (both exact in the SI). Also reported
per µm² (× 10⁻⁸). λ defaults to the nominal wavelength in the column name and can be changed per line.

## 5. Dose

$$H_\text{plane} = E\,t, \qquad H_\text{stack} = E\,t\,N_z, \qquad H_\text{total} = E\,t\,N_z\,N_t$$

in J/cm² (using *E* in W/cm²), and the same with Φ for photons/cm². *t* is the exposure (laser-on)
time per plane in s, *N_z* the number of slices per z-stack and *N_t* the number of timepoints.

## 6. Assumptions

- *E* is the time- and field-averaged irradiance, not the instantaneous peak at a spinning-disk pinhole
  or in a scanned spot. Illumination is treated as uniform over the rectangle; with a Gaussian or
  vignetted field the centre receives more.
- The per-stack dose assumes every slice exposure illuminates the full axial column, so a given cell
  receives light during all *N_z* exposures. This holds for widefield and spinning-disk confocal; it
  does not hold for light-sheet, where each plane is illuminated separately.
- *t* is the time the laser is on per plane. If the laser is not blanked between exposures (during
  readout, stage moves or filter changes), the real dose is higher.
- Photon numbers count excitation photons delivered to the sample plane, not photons absorbed.

## 7. Uncertainty

The ± on the slope and on each predicted power is the **fit** standard error only. It is usually well
under 1 %. The dominant term is the power meter's own per-reading uncertainty, typically about 10 % for
photodiode sensors (the ArgoPower export lists it in the `_error` columns, and the calculator draws it as
error bars). Quote the meter uncertainty when the absolute irradiance matters. Ratios between settings on
the same laser in the same session are much better determined than the absolute values, because they
share one calibration.

The illuminated area carries its own uncertainty, which enters *E* directly: a 5 % error in each side
is a 10 % error in *A*.

## 8. Test vectors

These are checked in `tests/test_paper_vectors.py` against the committed example file
(`examples/argopower_example.csv`, 0-50 %, through the origin, *k* = 1, *A* = 0.2025 mm²):

| Line | Setting | *P* (mW) | *E* (mW/cm²) | Φ (cm⁻² s⁻¹) |
| --- | --- | --- | --- | --- |
| 488 | 3.15 % | 0.283 | 139.8 | 3.433 × 10¹⁷ |
| 488 | 6.3 % | 0.566 | 279.5 | 6.866 × 10¹⁷ |
| 488 | 12.6 % | 1.132 | 559.0 | 1.373 × 10¹⁸ |
| 488 | 25.2 % | 2.264 | 1118.0 | 2.747 × 10¹⁸ |
| 640 | 5 % | 0.454 | 224.2 | 7.222 × 10¹⁷ |
| 640 | 40.6 % | 3.686 | 1820.2 | 5.864 × 10¹⁸ |

Dose: 488 nm at 3.15 %, *t* = 0.1 s, *N_z* = 305: *H*_plane = 0.01398 J/cm², *H*_stack = 4.262 J/cm²;
3.433 × 10¹⁶ and 1.047 × 10¹⁹ photons/cm².
