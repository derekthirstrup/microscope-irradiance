import pytest

from irradiance_calc.fit import fit_line
from irradiance_calc.parse import FormatError, blank_template, parse_file, parse_text
from irradiance_calc.table import Inputs, compute, display_table, parse_settings


def test_argopower(argo_path):
    cal = parse_file(argo_path)
    assert cal.source_format == "argopower"
    assert cal.wavelengths == [405, 488, 561, 640]
    assert cal.powers(488)[1] == pytest.approx(0.85)
    assert cal.line(488)[1].error_mw == pytest.approx(0.085)
    assert len(cal.source_sha256) == 64


def test_argopower_unit_selector(argo_path):
    assert parse_file(argo_path, "mW").powers(488)[1] == pytest.approx(850.0)


def test_manual_and_argopower_give_identical_results(argo_path, manual_path):
    a, m = parse_file(argo_path), parse_file(manual_path)
    assert m.source_format == "manual"
    assert m.wavelengths == a.wavelengths
    assert m.metadata["instrument"] == "Nikon1 spinning-disk confocal"
    inp = Inputs(
        width_um=450,
        height_um=450,
        exposure_s=0.1,
        slices=10,
        grid_step=5,
        settings=parse_settings("3.15, 6.3"),
    )
    ra, rm = compute(a, inp), compute(m, inp)
    for nm in a.wavelengths:
        assert rm.fits[nm].m == pytest.approx(ra.fits[nm].m, rel=1e-12)
        assert rm.fits[nm].r2 == pytest.approx(ra.fits[nm].r2, rel=1e-12)
    assert display_table(ra)[1] == display_table(rm)[1]


def test_manual_features():
    text = (
        "# instrument: Scope A\n"
        "# operator:\n"
        "# a free comment: with a colon\n"
        "setting_pct,488_uW,488_error_uW,640_mW\n"
        "0,0,,0\n"
        "10,1000,100,\n"
        "10,1100,,2.0\n"
        "# a comment between rows\n"
        "20,2000,200,4.0\n"
        ",,,\n"
    )
    cal = parse_text(text, source_name="x.csv")
    assert cal.metadata == {"instrument": "Scope A"}
    assert cal.xs(488) == [0, 10, 10, 20]  # replicates kept
    assert cal.powers(488) == pytest.approx([0, 1.0, 1.1, 2.0])  # uW -> mW
    assert cal.line(488)[1].error_mw == pytest.approx(0.1)
    assert cal.line(488)[2].error_mw is None
    assert cal.xs(640) == [0, 10, 20]  # blank cell skipped
    f = fit_line(cal, 488)
    assert f.n == 4


def test_excel_european_semicolon_decimal_comma():
    text = "setting_pct;488_mW\n0;0\n10;0,85\n20;1,747\n"
    cal = parse_text(text)
    assert cal.powers(488) == pytest.approx([0, 0.85, 1.747])


def test_bom_and_crlf():
    cal = parse_text("﻿setting_pct,488_mW\r\n0,0\r\n10,1\r\n")
    assert cal.powers(488) == [0, 1]


def test_bad_number_is_reported():
    with pytest.raises(FormatError, match="not a number"):
        parse_text("setting_pct,488_mW\n10,abc\n")


def test_unrecognised_file():
    with pytest.raises(FormatError, match="not in a recognised format"):
        parse_text("a,b,c\n1,2,3\n")


def test_blank_template_parses_but_has_no_readings():
    t = blank_template([488, 640])
    assert "setting_pct,488_mW,640_mW" in t
    with pytest.raises(FormatError, match="no power readings"):
        parse_text(t)


def test_blank_template_matches_shipped_file(manual_path):
    shipped = (manual_path.parent / "manual_template_blank.csv").read_text(encoding="utf-8")
    assert shipped == blank_template([405, 488, 561, 640])


def test_old_v0_export_still_opens():
    text = "setting_pct,488_P_mW,488_mWmm2\n0,0,0\n10,0.9,4.4\n20,1.8,8.9\n"
    cal = parse_text(text)
    assert cal.source_format == "export_v0"
    assert cal.powers(488) == [0, 0.9, 1.8]
