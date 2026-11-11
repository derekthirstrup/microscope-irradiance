"""Smoke test of the Tk app. Skipped when there is no display."""

import pytest

tk = pytest.importorskip("tkinter")


@pytest.fixture
def app():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    root.withdraw()
    from irradiance_calc.gui import App

    a = App(root)
    yield a
    root.destroy()


def test_gui_matches_core(app, argo_path, tmp_path):
    from irradiance_calc.parse import parse_file
    from irradiance_calc.table import display_table, to_csv

    app.settings.set("488: 3.15, 6.3, 12.6, 25.2; 640: 5, 40.6")
    app.use_grid.set(False)
    app.exposure.set("0.1")
    app.slices.set("305")
    assert app.load_path(str(argo_path))
    shown = app.table_values()
    _, expected = display_table(app.result)
    assert shown == expected
    row = next(r for r in shown if r[0] == "488" and r[1] == "3.15")
    assert row[3] == "139.8"

    out = tmp_path / "gui_export.csv"
    out.write_text(to_csv(app.calculate()), encoding="utf-8")
    assert app.load_path(str(out))
    assert app.table_values() == shown
    assert parse_file(out).source_format == "export"
