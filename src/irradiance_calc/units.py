"""Irradiance, photon flux and dose. The physical constants live here and only here.

Conventions
-----------
* Power ``P`` in mW, area ``A`` in mm^2, wavelength in nm, time in s.
* Irradiance ``E`` is reported primarily in mW/cm^2.
* ``k`` is an optional power correction factor, ``P_sample = k * P_meter``
  (default 1.0, i.e. the meter reading is the power at the sample).
"""

from __future__ import annotations

H_PLANCK = 6.62607015e-34
"""Planck constant, J s (exact, SI 2019)."""

C_LIGHT = 299_792_458.0
"""Speed of light in vacuum, m/s (exact)."""

PHOTONS_PER_MJ_PER_NM = 1e-3 * 1e-9 / (H_PLANCK * C_LIGHT)
"""Photons per mJ of energy per nm of wavelength: N = E[mJ] * lambda[nm] * this.

Numerically 5.034117e12, so that
``photon_flux[cm^-2 s^-1] = 5.034117e12 * E[mW/cm^2] * lambda[nm]``.
"""

MM2_PER_CM2 = 100.0
UM2_PER_CM2 = 1e8


def area_mm2(width_um: float, height_um: float) -> float:
    """Rectangular illuminated field area in mm^2 from width and height in um."""
    if width_um <= 0 or height_um <= 0:
        raise ValueError("Illuminated width and height must be positive.")
    return (width_um / 1000.0) * (height_um / 1000.0)


def irradiance_mw_cm2(power_mw: float, area_mm2_: float, k: float = 1.0) -> float:
    """E = k P / A in mW/cm^2 (P in mW, A in mm^2)."""
    if area_mm2_ <= 0:
        raise ValueError("Illuminated area must be positive.")
    return MM2_PER_CM2 * k * power_mw / area_mm2_


def mw_cm2_to_mw_mm2(e_mw_cm2: float) -> float:
    return e_mw_cm2 / MM2_PER_CM2


def mw_cm2_to_w_cm2(e_mw_cm2: float) -> float:
    return e_mw_cm2 * 1e-3


def photon_flux_cm2_s(e_mw_cm2: float, wavelength_nm: float) -> float:
    """Photon flux in photons cm^-2 s^-1 from irradiance in mW/cm^2."""
    if wavelength_nm <= 0:
        raise ValueError("Wavelength must be positive.")
    return PHOTONS_PER_MJ_PER_NM * e_mw_cm2 * wavelength_nm


def per_cm2_to_per_um2(value_per_cm2: float) -> float:
    return value_per_cm2 / UM2_PER_CM2


def dose(value_per_s: float, exposure_s: float, slices: int = 1, timepoints: int = 1) -> dict:
    """Integrate a rate over the exposure.

    ``value_per_s`` is either irradiance in W/cm^2 (giving J/cm^2) or photon
    flux in photons cm^-2 s^-1 (giving photons/cm^2). Returns the per-plane,
    per-stack and total values.

    Assumes the laser is on for ``exposure_s`` per plane and that every slice
    exposure illuminates the full axial column (widefield / spinning disk).
    """
    if exposure_s < 0:
        raise ValueError("Exposure time must not be negative.")
    if slices < 1 or timepoints < 1:
        raise ValueError("Slices and timepoints must be at least 1.")
    plane = value_per_s * exposure_s
    stack = plane * slices
    return {"plane": plane, "stack": stack, "total": stack * timepoints}
