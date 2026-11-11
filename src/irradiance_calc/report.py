"""PDF report, written with matplotlib's PDF backend (no other dependency)."""

from __future__ import annotations

import os
import textwrap

from . import __version__
from .table import TOOL_NAME, Result, display_table, fit_summary, methods_text

PAGE = (8.27, 11.69)  # A4 portrait, inches
ROWS_PER_PAGE = 34


def _mpl():
    # Figure + PdfPages need no pyplot and no GUI backend, so this is safe inside Tk too.
    try:
        from matplotlib.backends.backend_pdf import PdfPages
        from matplotlib.figure import Figure
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("The PDF report needs matplotlib: pip install matplotlib") from exc
    return Figure, PdfPages


def _footer(fig, result: Result, page: int, pages: int) -> None:
    fig.text(
        0.5,
        0.02,
        f"{TOOL_NAME} {__version__} · generated {result.generated} · page {page} of {pages}",
        ha="center",
        fontsize=7,
        color="#555",
    )


def _header(fig, result: Result) -> float:
    meta = result.metadata
    inp = result.inputs
    fig.text(0.06, 0.965, "Irradiance calibration report", fontsize=15, weight="bold", va="top")
    items = [
        ("Instrument", meta.get("instrument", "")),
        ("Power objective", inp.power_objective or meta.get("objective", "")),
        ("Imaging objective", inp.imaging_objective),
        ("Power meter", meta.get("power_meter", "")),
        ("Date", meta.get("date", "")),
        ("Operator", meta.get("operator", "")),
        ("Source file", result.cal.source_name),
        ("SHA-256", (result.cal.source_sha256[:16] + "…") if result.cal.source_sha256 else ""),
    ]
    y = 0.935
    for i, (k, v) in enumerate(items):
        col = i % 2
        if col == 0 and i:
            y -= 0.016
        fig.text(0.06 + col * 0.46, y, f"{k}:", fontsize=8, weight="bold", va="top")
        fig.text(0.06 + col * 0.46 + 0.16, y, v or "—", fontsize=8, va="top")
    return y - 0.025


def _calibration_plots(fig, result: Result, top: float) -> float:
    nms = result.lines
    n = len(nms)
    ncol = 2 if n > 1 else 1
    nrow = (n + ncol - 1) // ncol
    height = min(0.42, 0.21 * nrow)
    bottom = top - height
    cell_h = height / nrow
    for i, nm in enumerate(nms):
        r, c = divmod(i, ncol)
        w = 0.88 / ncol
        ax = fig.add_axes(
            (0.08 + c * w + 0.02, bottom + (nrow - 1 - r) * cell_h + 0.035, w - 0.08, cell_h - 0.06)
        )
        fit = result.fits[nm]
        line = result.cal.line(nm)
        xs = [p.setting_pct for p in line]
        ys = [p.power_mw for p in line]
        errs = [p.error_mw or 0.0 for p in line]
        ax.axvspan(fit.pct_min, fit.pct_max, color="#4c72b0", alpha=0.08, lw=0, label="fit window")
        if any(errs):
            ax.errorbar(xs, ys, yerr=errs, fmt="o", ms=3, capsize=2, color="#333", lw=0.8, label="measured")
        else:
            ax.plot(xs, ys, "o", ms=3, color="#333", label="measured")
        xmax = max(max(xs), result.inputs.grid_max if result.inputs.grid_step else max(xs))
        ax.plot(
            [0, xmax], [fit.predict(0)[0], fit.predict(xmax)[0]], "-", color="#c44e52", lw=1.2, label="fit"
        )
        rep = [row for row in result.rows if row.nm == nm and row.row_type == "reported"]
        if rep:
            ax.plot(
                [row.setting.value for row in rep],
                [row.p_mw / result.inputs.k for row in rep],
                "D",
                ms=4,
                mfc="none",
                color="#55a868",
                label="reported",
            )
        ax.set_title(f"{nm} nm   R² = {fit.r2:.4f}", fontsize=8)
        ax.set_xlabel("Laser setting (%)", fontsize=7)
        ax.set_ylabel("Power (mW)", fontsize=7)
        ax.tick_params(labelsize=6)
        ax.set_xlim(left=0)
        if i == 0:
            ax.legend(fontsize=5.5, loc="upper left", frameon=False)
    return bottom - 0.01


def _table(fig, rect, heads, rows, fontsize=6.5, col_widths=None):
    ax = fig.add_axes(rect)
    ax.axis("off")
    if not rows:
        return ax
    tbl = ax.table(cellText=rows, colLabels=heads, loc="upper center", cellLoc="center", colWidths=col_widths)
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(fontsize)
    tbl.scale(1, 1.25)
    for (r, _), cell in tbl.get_celld().items():
        cell.set_linewidth(0.3)
        if r == 0:
            cell.set_height(cell.get_height() * 1.8)
            cell.set_facecolor("#e8e8e8")
            cell.set_text_props(weight="bold")
    return ax


def _wrap(fig, x, y, text, width=110, fontsize: float = 8, **kw) -> float:
    lines = []
    for para in text.split("\n"):
        lines += textwrap.wrap(para, width) or [""]
    fig.text(x, y, "\n".join(lines), fontsize=fontsize, va="top", linespacing=1.35, **kw)
    return y - len(lines) * fontsize * 1.35 / 72 / PAGE[1] - 0.01


def _results_rows(result: Result) -> tuple[list[str], list[list[str]]]:
    reported = any(r.row_type == "reported" for r in result.rows)
    heads, rows = display_table(result, reported_only=reported)
    # Drop secondary units and the long note column to fit the page; notes go in the warnings list.
    keep = [
        i for i, h in enumerate(heads) if h not in ("E (mW/mm²)", "E (W/cm²)", "Photons µm⁻² s⁻¹", "Note")
    ]

    def wrap(h: str) -> str:
        return h.replace(" (", "\n(") if " (" in h else h.replace(" ", "\n", 1)

    return [wrap(heads[i]) for i in keep], [[r[i] for i in keep] for r in rows]


def page_count(result: Result) -> int:
    _, rows = _results_rows(result)
    return 1 + max(1, -(-len(rows) // ROWS_PER_PAGE))


def write_pdf(result: Result, path: str | os.PathLike) -> int:
    """Write the report. Returns the number of pages."""
    Figure, PdfPages = _mpl()
    heads, rows = _results_rows(result)
    chunks = [rows[i : i + ROWS_PER_PAGE] for i in range(0, len(rows), ROWS_PER_PAGE)] or [[]]
    pages = 1 + len(chunks)
    inp = result.inputs

    with PdfPages(
        os.fspath(path),
        metadata={"Title": "Irradiance calibration report", "Creator": f"{TOOL_NAME} {__version__}"},
    ) as pdf:
        # ---- page 1: header, plots, fit summary, warnings
        fig = Figure(figsize=PAGE)
        y = _header(fig, result)
        y = _calibration_plots(fig, result, y)
        fig.text(0.06, y, "Fit summary", fontsize=10, weight="bold", va="top")
        fs = [fit_summary(f) for f in result.fits.values()]
        fheads = ["Line", "Model", "Slope", "Intercept", "R²", "Fit window", "n"]
        frows = [
            [d["line"], d["model"], d["slope"], d["intercept"], d["r2"], d["window"], d["n"]] for d in fs
        ]
        th = 0.022 * (len(frows) + 1)
        _table(
            fig,
            (0.06, y - 0.02 - th, 0.88, th),
            fheads,
            frows,
            fontsize=7,
            col_widths=[0.08, 0.13, 0.24, 0.2, 0.09, 0.12, 0.05],
        )
        y = y - 0.04 - th
        fig.text(0.06, y, "Warnings", fontsize=10, weight="bold", va="top")
        warn = "\n".join(f"• {w}" for w in result.warnings) or "None."
        _wrap(
            fig, 0.06, y - 0.02, warn, width=120, fontsize=7, color="#8a3b00" if result.warnings else "#333"
        )
        _footer(fig, result, 1, pages)
        pdf.savefig(fig)

        # ---- page 2+: inputs, results, methods
        for i, chunk in enumerate(chunks):
            fig = Figure(figsize=PAGE)
            y = 0.965
            if i == 0:
                fig.text(0.06, y, "Inputs", fontsize=10, weight="bold", va="top")
                area = (
                    f"{inp.width_um:g} × {inp.height_um:g} µm = {inp.area_mm2:.5g} mm²"
                    if inp.area_mm2
                    else "not given (irradiance not calculated)"
                )
                wl = ", ".join(f"{nm}: {inp.wavelength(nm):g} nm" for nm in result.lines)
                items = [
                    ("Illuminated field", area),
                    ("Wavelengths used for photon flux", wl),
                    (
                        "Exposure per plane",
                        f"{inp.exposure_s:g} s" if inp.exposure_s is not None else "not given",
                    ),
                    ("Slices per stack", str(inp.slices)),
                    ("Timepoints", str(inp.timepoints)),
                    ("Power correction k", f"{inp.k:g}"),
                    ("CSV power unit", result.cal.input_unit),
                ]
                y -= 0.025
                for k, v in items:
                    fig.text(0.06, y, f"{k}:", fontsize=8, weight="bold", va="top")
                    fig.text(0.36, y, v, fontsize=8, va="top")
                    y -= 0.016
                y -= 0.01
            title = "Results" if i == 0 else "Results (continued)"
            fig.text(0.06, y, title, fontsize=10, weight="bold", va="top")
            th = 0.0175 * (len(chunk) + 2)
            _table(fig, (0.03, y - 0.015 - th, 0.94, th), heads, chunk, fontsize=6)
            y = y - 0.035 - th
            if i == len(chunks) - 1:
                fig.text(0.06, y, "Methods (ready to edit)", fontsize=10, weight="bold", va="top")
                y = _wrap(fig, 0.06, y - 0.02, methods_text(result), width=115, fontsize=7.5)
                fig.text(0.06, y, "Assumptions", fontsize=10, weight="bold", va="top")
                _wrap(fig, 0.06, y - 0.02, ASSUMPTIONS, width=120, fontsize=7)
            _footer(fig, result, 2 + i, pages)
            pdf.savefig(fig)
    return pages


ASSUMPTIONS = (
    "• E is the time- and field-averaged irradiance over the illuminated area, not the instantaneous "
    "peak at a spinning-disk pinhole or a scanned spot.\n"
    "• Dose per stack assumes every slice exposure illuminates the full axial column, so a given cell "
    "receives light during all slices (true for widefield and spinning disk, not light-sheet).\n"
    "• Exposure time is the time the laser is on per plane; if the laser is not blanked between "
    "exposures the real dose is higher.\n"
    "• Photon numbers count excitation photons delivered, not absorbed.\n"
    "• Uncertainty is dominated by the power meter's per-reading uncertainty (typically 10 %); the fit "
    "standard error is usually below 1 %."
)
