"""Turn fits into result rows, and write the CSV export.

Everything the GUI table, the CSV and the PDF show comes from :func:`compute`,
so the three cannot disagree.
"""

from __future__ import annotations

import io
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import __version__, units
from .fit import Fit, fit_line, in_window
from .parse import METADATA_KEYS, RAW_BLOCK_MARKER, RESULTS_BLOCK_MARKER, Calibration

TOOL_NAME = "irradiance-calc"


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #
@dataclass
class Setting:
    """A laser setting, keeping the text the user typed so 3.15 prints as 3.15."""

    text: str
    value: float

    @classmethod
    def of(cls, value: float | str) -> Setting:
        if isinstance(value, str):
            v = float(value.strip())
            return cls(_clean_number_text(value.strip()), v)
        return cls(f"{value:g}", float(value))


def _clean_number_text(t: str) -> str:
    try:
        float(t)
    except ValueError:
        raise ValueError(f"'{t}' is not a number.") from None
    return t.lstrip("+") or "0"


def parse_settings(spec: str) -> dict[int | None, list[Setting]]:
    """Parse ``"3.15, 6.3"`` (all lines) or ``"488: 3.15, 6.3; 640: 5, 40.6"`` (per line).

    Key ``None`` means "every line". Both forms can be mixed.
    """
    out: dict[int | None, list[Setting]] = {}
    spec = spec.strip()
    if not spec:
        return out
    for group in re.split(r"[;\n]", spec):
        group = group.strip()
        if not group:
            continue
        key: int | None = None
        m = re.match(r"^(\d+)\s*(?:nm)?\s*[:=]\s*(.*)$", group)
        if m:
            key, group = int(m.group(1)), m.group(2)
        vals = [t for t in re.split(r"[,\s]+", group) if t]
        if not vals:
            continue
        settings = [Setting.of(t) for t in vals]
        for s in settings:
            if s.value < 0:
                raise ValueError(f"Setting {s.text} % is negative.")
        out.setdefault(key, []).extend(settings)
    return out


def grid_settings(step: float, maximum: float = 100.0, minimum: float = 0.0) -> list[Setting]:
    if step <= 0:
        raise ValueError("Table step must be positive.")
    n = int(math.floor((maximum - minimum) / step + 1e-9))
    out = []
    for i in range(n + 1):
        v = round(minimum + i * step, 10)
        out.append(Setting(f"{v:g}", v))
    return out


@dataclass
class Inputs:
    fit_min: float = 0.0
    fit_max: float = 50.0
    through_origin: bool = True
    lines: list[int] | None = None
    """Wavelengths to report; None = all in the file."""
    width_um: float | None = None
    height_um: float | None = None
    k: float = 1.0
    wavelengths_nm: dict[int, float] = field(default_factory=dict)
    """Actual wavelength per line, if not the nominal one in the column name."""
    exposure_s: float | None = None
    slices: int = 1
    timepoints: int = 1
    settings: dict[int | None, list[Setting]] = field(default_factory=dict)
    grid_step: float | None = None
    grid_max: float = 100.0
    power_objective: str = ""
    """Objective the power was measured through."""
    imaging_objective: str = ""
    metadata: dict[str, str] = field(default_factory=dict)
    """instrument, power_meter, date, operator ... overriding the file's values."""

    @property
    def area_mm2(self) -> float | None:
        if self.width_um and self.height_um:
            return units.area_mm2(self.width_um, self.height_um)
        return None

    def wavelength(self, nm: int) -> float:
        return float(self.wavelengths_nm.get(nm, nm))


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #
@dataclass
class Row:
    nm: int
    setting: Setting
    row_type: str  # "reported" or "grid"
    p_mw: float
    p_se_mw: float
    e_mw_cm2: float | None = None
    photons_cm2_s: float | None = None
    h_j_cm2: dict | None = None  # plane / stack / total
    photons_cm2: dict | None = None
    note: str = ""

    @property
    def e_mw_mm2(self) -> float | None:
        return None if self.e_mw_cm2 is None else units.mw_cm2_to_mw_mm2(self.e_mw_cm2)

    @property
    def e_w_cm2(self) -> float | None:
        return None if self.e_mw_cm2 is None else units.mw_cm2_to_w_cm2(self.e_mw_cm2)

    @property
    def photons_um2_s(self) -> float | None:
        return None if self.photons_cm2_s is None else units.per_cm2_to_per_um2(self.photons_cm2_s)


@dataclass
class Result:
    cal: Calibration
    inputs: Inputs
    fits: dict[int, Fit]
    rows: list[Row]
    warnings: list[str]
    generated: str

    @property
    def lines(self) -> list[int]:
        return list(self.fits)

    @property
    def has_area(self) -> bool:
        return self.inputs.area_mm2 is not None

    @property
    def has_dose(self) -> bool:
        return self.has_area and self.inputs.exposure_s is not None

    @property
    def metadata(self) -> dict[str, str]:
        meta = {k: v for k, v in self.cal.metadata.items() if k in METADATA_KEYS}
        meta.update({k: v for k, v in self.inputs.metadata.items() if v})
        return meta


def compute(cal: Calibration, inputs: Inputs) -> Result:
    lines = inputs.lines or cal.wavelengths
    missing = [nm for nm in lines if nm not in cal.wavelengths]
    if missing:
        raise ValueError(f"{', '.join(map(str, missing))} nm not in the file (it has {cal.wavelengths}).")
    if inputs.k <= 0:
        raise ValueError("Power correction factor k must be positive.")
    for key in inputs.settings:
        if key is not None and key not in lines:
            raise ValueError(f"Settings given for {key} nm, which is not among the lines {lines}.")

    fits = {nm: fit_line(cal, nm, inputs.fit_min, inputs.fit_max, inputs.through_origin) for nm in lines}
    warnings = [w for f in fits.values() for w in f.warnings]
    area = inputs.area_mm2

    grid = None
    if inputs.grid_step:
        grid = grid_settings(inputs.grid_step, inputs.grid_max)
    elif not inputs.settings:
        grid = grid_settings(5.0, inputs.grid_max)

    rows: list[Row] = []
    for nm in lines:
        fit = fits[nm]
        reported = list(inputs.settings.get(None, [])) + list(inputs.settings.get(nm, []))
        seen: set[str] = set()
        todo = []
        for s in reported:
            if s.text not in seen:
                seen.add(s.text)
                todo.append((s, "reported"))
        todo.sort(key=lambda t: t[0].value)
        todo += [(s, "grid") for s in (grid or [])]
        for s, kind in todo:
            p_fit, se_fit = fit.predict(s.value)
            row = Row(nm, s, kind, inputs.k * p_fit, inputs.k * se_fit)
            if area is not None:
                row.e_mw_cm2 = units.irradiance_mw_cm2(p_fit, area, inputs.k)
                row.photons_cm2_s = units.photon_flux_cm2_s(row.e_mw_cm2, inputs.wavelength(nm))
                if inputs.exposure_s is not None:
                    row.h_j_cm2 = units.dose(
                        units.mw_cm2_to_w_cm2(row.e_mw_cm2),
                        inputs.exposure_s,
                        inputs.slices,
                        inputs.timepoints,
                    )
                    row.photons_cm2 = units.dose(
                        row.photons_cm2_s, inputs.exposure_s, inputs.slices, inputs.timepoints
                    )
            note = fit.extrapolation_warning(s.value)
            if note:
                row.note = note
                if kind == "reported":
                    warnings.append(f"{nm} nm: {note}")
            if p_fit < 0:
                row.note = (row.note + " " if row.note else "") + "Fitted power is negative."
            rows.append(row)

    return Result(
        cal,
        inputs,
        fits,
        rows,
        warnings,
        datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    )


# --------------------------------------------------------------------------- #
# Display (shared by GUI and PDF)
# --------------------------------------------------------------------------- #
def _f(v: float | None, fmt: str) -> str:
    return "" if v is None else format(v, fmt)


def display_table(result: Result, reported_only: bool = False) -> tuple[list[str], list[list[str]]]:
    """Long-format table: one row per (line, setting). Returns (headings, rows of strings)."""
    heads = ["Line (nm)", "Setting (%)", "P (mW)"]
    if result.has_area:
        heads += ["E (mW/cm²)", "E (mW/mm²)", "E (W/cm²)", "Photons cm⁻² s⁻¹", "Photons µm⁻² s⁻¹"]
    if result.has_dose:
        heads += ["Dose/plane (J/cm²)", "Dose/stack (J/cm²)"]
        if result.inputs.timepoints > 1:
            heads += ["Dose total (J/cm²)"]
        heads += ["Photons/plane (cm⁻²)", "Photons/stack (cm⁻²)"]
        if result.inputs.timepoints > 1:
            heads += ["Photons total (cm⁻²)"]
    heads += ["Note"]
    out = []
    for r in result.rows:
        if reported_only and r.row_type != "reported":
            continue
        vals = [str(r.nm), r.setting.text, _f(r.p_mw, ".4f")]
        if result.has_area:
            vals += [
                _f(r.e_mw_cm2, ".1f"),
                _f(r.e_mw_mm2, ".3f"),
                _f(r.e_w_cm2, ".4f"),
                _f(r.photons_cm2_s, ".4e"),
                _f(r.photons_um2_s, ".4e"),
            ]
        if result.has_dose:
            assert r.h_j_cm2 is not None and r.photons_cm2 is not None
            vals += [_f(r.h_j_cm2["plane"], ".4g"), _f(r.h_j_cm2["stack"], ".4g")]
            if result.inputs.timepoints > 1:
                vals += [_f(r.h_j_cm2["total"], ".4g")]
            vals += [_f(r.photons_cm2["plane"], ".4e"), _f(r.photons_cm2["stack"], ".4e")]
            if result.inputs.timepoints > 1:
                vals += [_f(r.photons_cm2["total"], ".4e")]
        vals.append(r.note)
        out.append(vals)
    return heads, out


def fit_summary(fit: Fit) -> dict[str, str]:
    d = {
        "line": f"{fit.nm} nm",
        "model": "through origin" if fit.model == "origin" else "free intercept",
        "slope": f"{fit.m:.5f} ± {fit.se_m:.5f} mW/%",
        "intercept": "0 (fixed)" if fit.model == "origin" else f"{fit.b:+.4f} ± {fit.se_b:.4f} mW",
        "r2": f"{fit.r2:.4f}",
        "window": f"{fit.pct_min:g}-{fit.pct_max:g} %",
        "n": str(fit.n),
    }
    return d


def methods_text(result: Result) -> str:
    """A paragraph that can be pasted into a methods section, with the numbers filled in."""
    inp = result.inputs
    meta = result.metadata
    meter = meta.get("power_meter", "a power meter")
    obj = inp.power_objective or meta.get("objective", "")
    where = f" through the {obj} objective" if obj else ""
    instr = f" of the {meta['instrument']}" if meta.get("instrument") else ""
    nms = [str(nm) for nm in result.lines]
    lines = nms[0] if len(nms) == 1 else ", ".join(nms[:-1]) + " and " + nms[-1]
    xs = [r.setting_pct for nm in result.lines for r in result.cal.line(nm)]
    lo, hi = min(xs), max(xs)
    fits = "; ".join(
        f"{nm} nm, P = {f.m:.4f}·x mW (R² = {f.r2:.4f})"
        if f.model == "origin"
        else f"{nm} nm, P = {f.m:.4f}·x {'−' if f.b < 0 else '+'} {abs(f.b):.4f} mW (R² = {f.r2:.4f})"
        for nm, f in result.fits.items()
    )
    any_fit = next(iter(result.fits.values()))
    model = "through the origin" if any_fit.model == "origin" else "with a free intercept"
    txt = (
        f"Laser power at the sample plane{instr} was measured with {meter}{where} "
        f"at laser settings from {lo:g} to {hi:g} % for the {lines} nm line{'s' if len(nms) > 1 else ''}. "
        f"Power P was fitted against the setting x by least squares {model} over "
        f"{any_fit.pct_min:g}-{any_fit.pct_max:g} % ({fits}). "
    )
    if inp.k != 1.0:
        txt += f"Powers were multiplied by a correction factor k = {inp.k:g}. "
    if result.has_area:
        assert inp.width_um and inp.height_um and inp.area_mm2
        txt += (
            f"Irradiance was calculated as E = kP/A with an illuminated field of "
            f"{inp.width_um:g} × {inp.height_um:g} µm (A = {inp.area_mm2:.4g} mm²), and photon flux as "
            f"Φ = Eλ/(hc). "
        )
        rep = [r for r in result.rows if r.row_type == "reported"] or []
        if rep:
            parts = [
                f"{r.nm} nm at {r.setting.text} %: {r.e_mw_cm2:.0f} mW/cm² "
                f"({_sci(r.photons_cm2_s)} photons cm⁻² s⁻¹)"
                for r in rep
            ]
            txt += "Irradiances at the settings used were " + "; ".join(parts) + ". "
        if result.has_dose:
            txt += (
                f"Radiant exposure (dose) was calculated as H = E·t per plane and H = E·t·N per stack, "
                f"with t = {inp.exposure_s:g} s per plane and N = {inp.slices} planes per stack"
                + (f", over {inp.timepoints} timepoints" if inp.timepoints > 1 else "")
                + ". "
            )
    txt += (
        "The uncertainty is dominated by the power meter's per-reading uncertainty "
        "(typically 10 %); the fit standard error is smaller. "
        f"Calculated with {TOOL_NAME} {__version__}."
    )
    return txt


def _sci(v: float | None) -> str:
    if v is None:
        return ""
    e = int(math.floor(math.log10(abs(v)))) if v else 0
    return f"{v / 10**e:.2f} × 10^{e}"


# --------------------------------------------------------------------------- #
# CSV export
# --------------------------------------------------------------------------- #
def _num(v: float | None, fmt: str = ".7g") -> str:
    return "" if v is None else format(v, fmt)


def _clean(s: str) -> str:
    return " ".join(str(s).split())


def metadata_lines(result: Result) -> list[str]:
    cal, inp = result.cal, result.inputs
    out = [
        f"# tool: {TOOL_NAME}",
        f"# tool_version: {__version__}",
        f"# generated: {result.generated}",
        f"# source_file: {_clean(cal.source_name)}",
        f"# source_sha256: {cal.source_sha256}",
        f"# source_format: {cal.source_format}",
        f"# source_power_unit: {cal.input_unit}",
    ]
    if cal.source_format == "export":
        for k in ("source_file", "source_sha256"):
            # keep the very first source when an export is re-exported more than once
            v = cal.metadata.get(f"original_{k}") or cal.metadata.get(k)
            if v:
                out.append(f"# original_{k}: {_clean(v)}")
    if "argopower_analysis" in cal.metadata:
        out.append(f"# argopower_analysis: {_clean(cal.metadata['argopower_analysis'])}")
    for k, v in result.metadata.items():
        out.append(f"# {k}: {_clean(v)}")
    out += [
        f"# power_measured_through_objective: {_clean(inp.power_objective)}",
        f"# imaging_objective: {_clean(inp.imaging_objective)}",
        f"# power_correction_k: {inp.k:g}",
        f"# illuminated_width_um: {_num(inp.width_um, 'g')}",
        f"# illuminated_height_um: {_num(inp.height_um, 'g')}",
        f"# illuminated_area_mm2: {_num(inp.area_mm2, '.6g')}",
        f"# exposure_s: {_num(inp.exposure_s, 'g')}",
        f"# slices_per_stack: {inp.slices}",
        f"# timepoints: {inp.timepoints}",
        f"# fit_model: {'through_origin' if inp.through_origin else 'free_intercept'}",
        f"# fit_window_pct: {inp.fit_min:g}-{inp.fit_max:g}",
    ]
    for nm, f in result.fits.items():
        out.append(f"# wavelength_{nm}_nm: {inp.wavelength(nm):g}")
        out.append(
            f"# fit_{nm}: slope_mW_per_pct={f.m:.7g} slope_se={f.se_m:.3g} intercept_mW={f.b:.5g} "
            f"intercept_se={f.se_b:.3g} r2={f.r2:.6f} n={f.n}"
        )
    for w in result.warnings:
        out.append(f"# warning: {_clean(w)}")
    out.append(
        "# Formulas: E = k*P/A; photons = E*lambda/(h*c); dose_plane = E*t; "
        "dose_stack = E*t*N_slices; dose_total = dose_stack*N_timepoints"
    )
    return out


RESULT_FIELDS: list[tuple[str, Callable[[Row], float | None]]] = [
    ("P_mW", lambda r: r.p_mw),
    ("P_se_mW", lambda r: r.p_se_mw),
    ("E_mWcm2", lambda r: r.e_mw_cm2),
    ("E_mWmm2", lambda r: r.e_mw_mm2),
    ("E_Wcm2", lambda r: r.e_w_cm2),
    ("photons_cm2_s", lambda r: r.photons_cm2_s),
    ("photons_um2_s", lambda r: r.photons_um2_s),
    ("H_plane_Jcm2", lambda r: r.h_j_cm2 and r.h_j_cm2["plane"]),
    ("H_stack_Jcm2", lambda r: r.h_j_cm2 and r.h_j_cm2["stack"]),
    ("H_total_Jcm2", lambda r: r.h_j_cm2 and r.h_j_cm2["total"]),
    ("photons_plane_cm2", lambda r: r.photons_cm2 and r.photons_cm2["plane"]),
    ("photons_stack_cm2", lambda r: r.photons_cm2 and r.photons_cm2["stack"]),
    ("photons_total_cm2", lambda r: r.photons_cm2 and r.photons_cm2["total"]),
]


def _result_fields(result: Result) -> list[tuple[str, Callable[[Row], float | None]]]:
    n = 2
    if result.has_area:
        n = 7
    if result.has_dose:
        n = len(RESULT_FIELDS)
    return RESULT_FIELDS[:n]


def to_csv(result: Result) -> str:
    """Full export: metadata, results (wide, one row per setting), raw readings."""
    buf = io.StringIO()
    for ln in metadata_lines(result):
        buf.write(ln + "\n")

    fields = _result_fields(result)
    buf.write(RESULTS_BLOCK_MARKER + "\n")
    head = ["setting_pct", "row_type"]
    for nm in result.lines:
        head += [f"{nm}_{name}" for name, _ in fields]
    head.append("note")
    buf.write(",".join(head) + "\n")

    keyed: dict[tuple[str, str], dict[int, Row]] = {}
    order: list[tuple[str, str]] = []
    for r in result.rows:
        key = (r.row_type, r.setting.text)
        if key not in keyed:
            keyed[key] = {}
            order.append(key)
        keyed[key][r.nm] = r
    order.sort(key=lambda k: (k[0] != "reported", float(k[1])))
    for key in order:
        per = keyed[key]
        vals = [key[1], key[0]]
        notes = []
        for nm in result.lines:
            r = per.get(nm)
            vals += [_num(get(r)) if r else "" for _, get in fields]
            if r and r.note:
                notes.append(f"{nm} nm: {r.note}")
        vals.append('"' + " | ".join(notes).replace('"', "'") + '"' if notes else "")
        buf.write(",".join(vals) + "\n")

    buf.write("\n" + RAW_BLOCK_MARKER + "\n")
    buf.write(raw_block(result))
    return buf.getvalue()


def raw_block(result: Result) -> str:
    """The loaded readings in manual-template form, with which ones were in the fit window."""
    cal = result.cal
    nms = cal.wavelengths
    has_err = {nm: any(r.error_mw is not None for r in cal.line(nm)) for nm in nms}
    head = ["setting_pct"]
    for nm in nms:
        head.append(f"{nm}_mW")
        if has_err[nm]:
            head.append(f"{nm}_error_mW")
        head.append(f"{nm}_in_fit")
    lines = [",".join(head)]
    by_row: dict[int, list] = {}
    for r in cal.readings:
        by_row.setdefault(r.row, []).append(r)
    inp = result.inputs
    for row in sorted(by_row):
        rs = by_row[row]
        x = rs[0].setting_pct
        cells = {r.nm: r for r in rs}
        vals = [repr(x)]
        for nm in nms:
            r = cells.get(nm)
            vals.append(repr(r.power_mw) if r else "")
            if has_err[nm]:
                vals.append(repr(r.error_mw) if r and r.error_mw is not None else "")
            used = r is not None and nm in result.fits and in_window(x, inp.fit_min, inp.fit_max)
            vals.append(("1" if used else "0") if r else "")
        lines.append(",".join(vals))
    return "\n".join(lines) + "\n"
