import re
from pathlib import Path

from irradiance_calc import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_version_resource_matches_package():
    text = (ROOT / "packaging" / "version_info.txt").read_text(encoding="utf-8")
    nums = ", ".join(__version__.split(".")[:3] + ["0"])
    assert f"filevers=({nums})" in text
    assert f"prodvers=({nums})" in text
    assert f"StringStruct('FileVersion', '{__version__}')" in text
    assert f"StringStruct('ProductVersion', '{__version__}')" in text


def test_spec_has_no_absolute_paths_and_no_upx():
    spec = (ROOT / "packaging" / "irradiance_calc.spec").read_text(encoding="utf-8")
    assert not re.search(r"[A-Za-z]:[/\\\\]", spec)
    assert "upx=True" not in spec


def test_citation_and_changelog_versions():
    assert f"version: {__version__}" in (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    assert f"## [{__version__}]" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
