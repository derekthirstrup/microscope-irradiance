import pytest

from irradiance_calc import cli
from irradiance_calc.parse import parse_file
from irradiance_calc.table import Inputs, compute, parse_settings

PAPER_ARGS = [
    "--width-um",
    "450",
    "--height-um",
    "450",
    "--lines",
    "488,640",
    "--settings",
    "488: 3.15, 6.3, 12.6, 25.2; 640: 5, 40.6",
    "--exposure-s",
    "0.1",
    "--slices",
    "305",
]


def test_cli_reproduces_paper_table(argo_path, capsys, tmp_path):
    out = tmp_path / "paper.csv"
    assert cli.main([str(argo_path), *PAPER_ARGS, "--csv", str(out)]) == 0
    text = capsys.readouterr().out
    for s in ("139.8", "279.5", "559.0", "1118.0", "224.2", "1820.2", "3.4333e+17"):
        assert s in text
    assert out.exists()


def test_cli_template(tmp_path):
    p = tmp_path / "t.csv"
    assert cli.main(["--template", str(p), "--template-lines", "488,561"]) == 0
    assert "setting_pct,488_mW,561_mW" in p.read_text(encoding="utf-8")


def test_cli_bad_file(tmp_path, capsys):
    p = tmp_path / "bad.csv"
    p.write_text("hello\n", encoding="utf-8")
    assert cli.main([str(p)]) == 2
    assert "not in a recognised format" in capsys.readouterr().err


@pytest.mark.parametrize("grid", [None, 1.0])
def test_pdf_report(argo_path, tmp_path, grid):
    pytest.importorskip("matplotlib")
    pypdf = pytest.importorskip("pypdf")
    from irradiance_calc.report import page_count, write_pdf

    inp = Inputs(
        width_um=450,
        height_um=450,
        exposure_s=0.1,
        slices=305,
        lines=[488, 640],
        settings=parse_settings("488: 3.15, 6.3, 12.6, 25.2; 640: 5, 40.6") if grid is None else {},
        grid_step=grid,
    )
    res = compute(parse_file(argo_path), inp)
    out = tmp_path / "r.pdf"
    n = write_pdf(res, out)
    assert out.stat().st_size > 10_000
    assert n == page_count(res) == len(pypdf.PdfReader(out).pages)
    if grid is None:  # reported settings only: summary page + one results page
        assert n == 2
        txt = "".join(p.extract_text() for p in pypdf.PdfReader(out).pages)
        for s in ("139.8", "1118.0", "1820.2", "Methods"):
            assert s in txt
