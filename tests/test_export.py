import pytest

from irradiance_calc import __version__
from irradiance_calc.parse import parse_file, parse_text
from irradiance_calc.table import Inputs, compute, display_table, grid_settings, parse_settings, to_csv


def _inputs(**kw):
    base = dict(
        width_um=450,
        height_um=450,
        exposure_s=0.1,
        slices=305,
        timepoints=2,
        k=1.0,
        settings=parse_settings("488: 3.15, 6.3, 12.6, 25.2; 640: 5, 40.6"),
        grid_step=2.5,
        power_objective="10x",
        imaging_objective="40x WI",
        metadata={"operator": "DT"},
    )
    base.update(kw)
    return Inputs(**base)


def test_settings_keep_typed_precision():
    s = parse_settings("3.15, 6.30; 640: 5")
    assert [x.text for x in s[None]] == ["3.15", "6.30"]
    assert [x.text for x in grid_settings(2.5, 10)] == ["0", "2.5", "5", "7.5", "10"]


def test_settings_errors():
    with pytest.raises(ValueError):
        parse_settings("3.15, abc")
    with pytest.raises(ValueError):
        parse_settings("-1")


def test_metadata_block(argo_path):
    res = compute(parse_file(argo_path), _inputs())
    text = to_csv(res)
    head = [ln for ln in text.splitlines() if ln.startswith("#")]
    joined = "\n".join(head)
    for needle in (
        f"# tool_version: {__version__}",
        "# source_file: argopower_example.csv",
        "# source_sha256: ",
        "# fit_window_pct: 0-50",
        "# illuminated_area_mm2: 0.2025",
        "# power_correction_k: 1",
        "# power_measured_through_objective: 10x",
        "# imaging_objective: 40x WI",
        "# exposure_s: 0.1",
        "# slices_per_stack: 305",
        "# timepoints: 2",
        "# wavelength_488_nm: 488",
        "# fit_488: slope_mW_per_pct=0.0898",
        "# operator: DT",
        "# warning: 405 nm: R²",
    ):
        assert needle in joined, needle
    assert "3.15,reported," in text
    assert "2.5,grid," in text


def test_round_trip(argo_path, tmp_path):
    cal = parse_file(argo_path)
    res = compute(cal, _inputs())
    out = tmp_path / "export.csv"
    out.write_text(to_csv(res), encoding="utf-8")
    cal2 = parse_file(out)
    assert cal2.source_format == "export"
    assert cal2.metadata["power_measured_through_objective"] == "10x"
    assert cal2.metadata["operator"] == "DT"
    assert len(cal2.readings) == len(cal.readings)
    for a, b in zip(cal.readings, cal2.readings, strict=True):
        assert (a.setting_pct, a.nm) == (b.setting_pct, b.nm)
        assert b.power_mw == pytest.approx(a.power_mw, rel=1e-9, abs=1e-12)
        assert b.error_mw == pytest.approx(a.error_mw, rel=1e-9, abs=1e-12)
    res2 = compute(cal2, _inputs())
    assert display_table(res2)[1] == display_table(res)[1]
    # an export of an export records where the readings first came from
    assert f"# original_source_sha256: {cal.source_sha256}" in to_csv(res2)
    out2 = tmp_path / "export2.csv"
    out2.write_text(to_csv(res2), encoding="utf-8")
    assert f"# original_source_sha256: {cal.source_sha256}" in to_csv(compute(parse_file(out2), _inputs()))


def test_csv_values_equal_displayed_values(argo_path):
    res = compute(parse_file(argo_path), _inputs())
    heads, shown = display_table(res)
    lines = to_csv(res).split("## results\n")[1].split("\n\n")[0].splitlines()
    header = lines[0].split(",")
    rows = {(r.split(",")[1], r.split(",")[0]): r.split(",") for r in lines[1:]}
    for r, disp in zip(res.rows, shown, strict=True):
        csv_row = rows[(r.row_type, r.setting.text)]
        val = dict(zip(header, csv_row, strict=False))  # quoted notes may contain commas
        # same number, to the precision the table shows (the CSV carries 7 significant figures)
        assert float(val[f"{r.nm}_E_mWcm2"]) == pytest.approx(
            float(disp[heads.index("E (mW/cm²)")]), abs=0.05
        )
        assert float(val[f"{r.nm}_photons_cm2_s"]) == pytest.approx(
            float(disp[heads.index("Photons cm⁻² s⁻¹")]), rel=1e-4
        )
        assert float(val[f"{r.nm}_H_stack_Jcm2"]) == pytest.approx(
            float(disp[heads.index("Dose/stack (J/cm²)")]), rel=1e-3
        )
        assert float(val[f"{r.nm}_E_mWcm2"]) == pytest.approx(r.e_mw_cm2, rel=1e-6)


def test_k_factor_scales_everything(argo_path):
    cal = parse_file(argo_path)
    a = compute(cal, _inputs(k=1.0))
    b = compute(cal, _inputs(k=0.9))
    for ra, rb in zip(a.rows, b.rows, strict=True):
        assert rb.p_mw == pytest.approx(0.9 * ra.p_mw)
        assert rb.e_mw_cm2 == pytest.approx(0.9 * ra.e_mw_cm2)
        assert rb.h_j_cm2["total"] == pytest.approx(0.9 * ra.h_j_cm2["total"])


def test_no_area_means_power_only(argo_path):
    res = compute(parse_file(argo_path), Inputs())
    heads, rows = display_table(res)
    assert heads == ["Line (nm)", "Setting (%)", "P (mW)", "Note"]
    assert len(rows) == 4 * 21
    text = to_csv(res)
    assert "_E_mWcm2" not in text
    assert parse_text(text).wavelengths == [405, 488, 561, 640]


def test_unknown_line_rejected(argo_path):
    with pytest.raises(ValueError, match="not in the file"):
        compute(parse_file(argo_path), Inputs(lines=[532]))
    with pytest.raises(ValueError, match="not among the lines"):
        compute(parse_file(argo_path), Inputs(lines=[488], settings=parse_settings("640: 5")))
