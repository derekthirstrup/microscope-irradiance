"""Section 5 test vectors: the numbers in the QUAREP manuscript, recomputed from the committed export."""

import pytest

from irradiance_calc.parse import parse_file
from irradiance_calc.table import Inputs, compute, parse_settings

REL = 1e-3

SLOPES = {488: (0.0898, 0.9994), 640: (0.0908, 0.9992), 561: (0.0545, None), 405: (0.0275, 0.967)}

VECTORS = [  # line, setting, P mW, E mW/cm2, photons cm-2 s-1
    (488, "3.15", 0.283, 139.8, 3.433e17),
    (488, "6.3", 0.566, 279.5, 6.866e17),
    (488, "12.6", 1.132, 559.0, 1.373e18),
    (488, "25.2", 2.264, 1118.0, 2.747e18),
    (640, "5", 0.454, 224.2, 7.222e17),
    (640, "40.6", 3.686, 1820.3, 5.865e18),
]


@pytest.fixture
def result(argo_path):
    cal = parse_file(argo_path)
    inp = Inputs(
        width_um=450,
        height_um=450,
        exposure_s=0.1,
        slices=305,
        settings=parse_settings("488: 3.15, 6.3, 12.6, 25.2; 640: 5, 40.6"),
    )
    return compute(cal, inp)


def test_slopes(result):
    for nm, (slope, r2) in SLOPES.items():
        f = result.fits[nm]
        assert f.m == pytest.approx(slope, abs=5e-5)
        if r2 is not None:
            assert f.r2 == pytest.approx(r2, abs=5e-4)


@pytest.mark.parametrize("nm,setting,p,e,phi", VECTORS)
def test_vector(result, nm, setting, p, e, phi):
    row = next(
        r for r in result.rows if r.nm == nm and r.setting.text == setting and r.row_type == "reported"
    )
    assert row.p_mw == pytest.approx(p, rel=REL * 2)  # table P is given to 3 decimals
    assert row.e_mw_cm2 == pytest.approx(e, rel=REL)
    assert row.photons_cm2_s == pytest.approx(phi, rel=REL)


def test_dose_vector(result):
    row = next(r for r in result.rows if r.nm == 488 and r.setting.text == "3.15")
    assert row.h_j_cm2["plane"] == pytest.approx(0.01398, rel=REL)
    assert row.h_j_cm2["stack"] == pytest.approx(4.264, rel=REL)
    assert row.photons_cm2["plane"] == pytest.approx(3.433e16, rel=REL)
    assert row.photons_cm2["stack"] == pytest.approx(1.047e19, rel=REL)


def test_405_triggers_linearity_warning(result):
    assert any(w.startswith("405 nm: R²") for w in result.warnings)
    assert not any(w.startswith(("488 nm: R²", "640 nm: R²", "561 nm: R²")) for w in result.warnings)
    assert not any("slope differs" in w and not w.startswith("405") for w in result.warnings)


def test_extrapolation_warnings(result):
    below = {(r.nm, r.setting.text) for r in result.rows if "below the lowest" in r.note}
    assert below == {(488, "3.15"), (488, "6.3"), (640, "5")}
    cal = result.cal
    res = compute(cal, Inputs(settings=parse_settings("60")))
    assert all("above the fit window" in r.note for r in res.rows)
    assert any("above the fit window" in w for w in res.warnings)
