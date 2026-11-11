"""Regenerate the README screenshots from the real app running the example files.

Windows only (uses the Win32 PrintWindow call, which renders just the app window,
so nothing else on the screen can end up in an image). Run from the repo root:

    python scripts/capture_screenshots.py

Writes docs/img/*.png and docs/img/report_page1.png (needs pymupdf for the last one).
"""

from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from ctypes import wintypes
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "docs" / "img"
MAX_WIDTH = 1600

from irradiance_calc import gui  # noqa: E402


def capture(widget: tk.Misc, path: Path, callouts: list | None = None) -> None:
    """Render a toplevel window into a PNG with PrintWindow (PW_RENDERFULLCONTENT)."""
    widget.update()
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    hwnd = int(widget.winfo_toplevel().wm_frame(), 16)
    rect = wintypes.RECT()
    ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect))
    full = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(full))
    w, h = full.right - full.left, full.bottom - full.top
    hdc = user32.GetWindowDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    user32.PrintWindow(hwnd, mdc, 2)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    bi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    img = Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
    # crop the invisible resize border to the visible frame
    img = img.crop(
        (
            rect.left - full.left,
            rect.top - full.top,
            w - (full.right - rect.right),
            h - (full.bottom - rect.bottom),
        )
    )
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, hdc)
    path.parent.mkdir(parents=True, exist_ok=True)
    if callouts:
        # client-area origin inside the captured image
        ox = widget.winfo_rootx() - rect.left
        oy = widget.winfo_rooty() - rect.top
        draw_callouts(img, [(w, n, side, ox, oy, widget) for w, n, side in callouts])
    if img.width > MAX_WIDTH:  # keep README images a sensible size on high-DPI screens
        img = img.resize((MAX_WIDTH, round(img.height * MAX_WIDTH / img.width)), Image.LANCZOS)
    img.save(path, optimize=True)
    print("wrote", path.relative_to(ROOT))


def draw_callouts(img: Image.Image, items) -> None:
    """Numbered red circles at the left edge of each widget."""
    from PIL import ImageDraw, ImageFont

    d = ImageDraw.Draw(img)
    r = max(14, img.width // 90)
    try:
        font = ImageFont.truetype("arialbd.ttf", int(r * 1.3))
    except OSError:
        font = ImageFont.load_default()
    for w, n, side, ox, oy, root in items:
        w.update_idletasks()
        left = w.winfo_rootx() - root.winfo_rootx() + ox
        top = w.winfo_rooty() - root.winfo_rooty() + oy
        right, bottom = left + w.winfo_width(), top + w.winfo_height()
        if side == "right":  # just outside the right edge
            x, y = right + r + 4, (top + bottom) // 2
        elif side == "below":  # under the widget, centred
            x, y = (left + right) // 2, bottom + r + 4
        else:  # "tr": inside the top-right corner
            x, y = right - 2 * r - 6, top + r + 4
        d.ellipse((x - r, y - r, x + r, y + r), fill="#d62728", outline="white", width=3)
        d.text((x, y), str(n), fill="white", font=font, anchor="mm")


def main() -> None:
    root = gui.make_root()
    app = gui.App(root)

    def shot(name, callouts=()):
        return lambda: capture(root, OUT / name, [(app.widgets[k], n, side) for k, n, side in callouts])

    def load_argo():
        app.load_path(str(ROOT / "examples" / "argopower_example.csv"))

    def settings():
        app.settings.set("488: 3.15, 6.3, 12.6, 25.2; 640: 5, 40.6")
        app.use_grid.set(False)
        for nm, (b, _) in app.line_vars.items():
            b.set(nm in (488, 640))
        app.exposure.set("0.1")
        app.slices.set("305")
        app.power_obj.set("10x")
        app.imaging_obj.set("40x WI")
        app.meta["instrument"].set("Nikon1 spinning-disk confocal")
        app.calculate_clicked()

    def all_lines():
        for b, _ in app.line_vars.values():
            b.set(True)
        app.settings.set("")
        app.use_grid.set(True)
        app.exposure.set("")
        app.calculate_clicked()

    def load_manual():
        app.path = None
        app.load_path(str(ROOT / "examples" / "manual_example_filled.csv"))

    steps = [
        shot("01_start.png", [("load", 1, "right")]),
        load_argo,
        shot("02_loaded.png", [("unit", 2, "right"), ("lines", 3, "right"), ("messages", 4, "tr")]),
        all_lines,
        shot("03_linearity_warning.png", [("messages", 1, "tr")]),
        settings,
        shot(
            "04_results.png",
            [
                ("field", 5, "tr"),
                ("acquisition", 6, "tr"),
                ("settings", 7, "tr"),
                ("calculate", 8, "below"),
                ("table", 9, "tr"),
                ("export_csv", 10, "below"),
                ("export_pdf", 11, "below"),
            ],
        ),
        load_manual,
        shot("05_manual_loaded.png", [("template", 1, "right"), ("load", 2, "below")]),
    ]

    def run(i=0):
        if i < len(steps):
            steps[i]()
            root.after(700, run, i + 1)
        else:
            if app.result is not None:
                try:
                    import pymupdf

                    from irradiance_calc.report import write_pdf

                    app.load_path(str(ROOT / "examples" / "argopower_example.csv"))
                    settings()
                    pdf = ROOT / "build" / "example_report.pdf"
                    pdf.parent.mkdir(exist_ok=True)
                    write_pdf(app.calculate(), pdf)
                    doc = pymupdf.open(pdf)
                    for n in range(len(doc)):
                        doc[n].get_pixmap(dpi=110).save(OUT / f"report_page{n + 1}.png")
                        print("wrote", f"docs/img/report_page{n + 1}.png")
                except ImportError:
                    print("pymupdf not installed; skipped the report page images")
            root.destroy()

    root.after(800, run)
    root.mainloop()


if __name__ == "__main__":
    main()
