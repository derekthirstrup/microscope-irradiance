import math

import pytest

from irradiance_calc import units


def test_photon_constant_matches_independent_calculation():
    h = 6.62607015e-34  # J s, exact
    c = 299792458.0  # m/s, exact
    # 1 mW/cm^2 at 1 nm: energy per photon = h c / 1e-9 m; photons/s/cm^2 = 1e-3 W / that
    expected = 1e-3 / (h * c / 1e-9)
    assert units.PHOTONS_PER_MJ_PER_NM == pytest.approx(expected, rel=1e-12)
    assert units.PHOTONS_PER_MJ_PER_NM == pytest.approx(5.034117e12, rel=1e-6)


def test_irradiance_units():
    a = units.area_mm2(450, 450)
    assert a == pytest.approx(0.2025)
    e = units.irradiance_mw_cm2(1.0, a)
    assert e == pytest.approx(100 / 0.2025)
    assert units.mw_cm2_to_mw_mm2(e) == pytest.approx(1 / 0.2025)
    assert units.mw_cm2_to_w_cm2(e) == pytest.approx(0.1 / 0.2025)
    assert units.irradiance_mw_cm2(1.0, a, k=0.9) == pytest.approx(0.9 * e)


def test_photon_flux_per_um2():
    phi = units.photon_flux_cm2_s(100.0, 500.0)
    assert units.per_cm2_to_per_um2(phi) == pytest.approx(phi * 1e-8)


def test_dose():
    d = units.dose(2.0, 0.5, slices=10, timepoints=3)
    assert d == {"plane": 1.0, "stack": 10.0, "total": 30.0}


@pytest.mark.parametrize("bad", [dict(width_um=0, height_um=1), dict(width_um=-1, height_um=1)])
def test_bad_area(bad):
    with pytest.raises(ValueError):
        units.area_mm2(**bad)


def test_bad_dose_inputs():
    with pytest.raises(ValueError):
        units.dose(1, -1)
    with pytest.raises(ValueError):
        units.dose(1, 1, slices=0)
    assert math.isclose(units.dose(1, 0)["plane"], 0)
