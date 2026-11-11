# -*- mode: python ; coding: utf-8 -*-
# Build from the repo root:  pyinstaller packaging/irradiance_calc.spec --noconfirm
# One-folder build (faster start, fewer antivirus false positives than one-file), no UPX.
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821  (SPECPATH is defined by PyInstaller)
sys.path.insert(0, str(ROOT / "src"))
from irradiance_calc import __version__  # noqa: E402

NAME = "IrradianceCalculator"

a = Analysis(
    [str(ROOT / "packaging" / "launch_gui.py")],
    pathex=[str(ROOT / "src")],
    datas=[(str(ROOT / "examples"), "examples")],
    hiddenimports=["irradiance_calc.report", "matplotlib.backends.backend_pdf", "matplotlib.backends.backend_tkagg"],
    excludes=["PyQt5", "PyQt6", "PySide2", "PySide6", "IPython", "pytest", "pandas", "scipy", "notebook"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    console=False,
    upx=False,
    version=str(ROOT / "packaging" / "version_info.txt") if sys.platform == "win32" else None,
)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name=NAME)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{NAME}.app",
        bundle_identifier="io.github.derekthirstrup.irradiancecalc",
        info_plist={"CFBundleShortVersionString": __version__, "NSHighResolutionCapable": True},
    )
