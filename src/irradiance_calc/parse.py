"""Read power calibration files.

Three formats are recognised automatically:

``argopower``
    Raw Argolight ArgoPower export: semicolon-delimited, a ``Result table
    values`` block with a ``power_instruction`` column and ``<nm>_power`` /
    ``<nm>_error`` columns. Power unit is chosen by the caller (normally uW).

``manual``
    Hand-entered readings (e.g. a Thorlabs PM100D with a slide sensor) in the
    template written by :func:`blank_template`. Comma- (or semicolon-)
    delimited, header ``setting_pct,<nm>_mW,...`` with the unit in the column
    name (``_mW`` or ``_uW``), optional ``<nm>_error_mW`` columns, blank cells
    skipped, repeated settings kept as replicates, ``#`` lines are comments and
    ``# key: value`` lines are metadata.

``export``
    A CSV previously written by this tool. Its ``## raw_readings`` block is in
    the manual format, so re-opening an export re-fits the original readings.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import os
import re
from dataclasses import dataclass, field
from decimal import Decimal

INPUT_UNIT_FACTORS = {"uW": 1e-3, "mW": 1.0, "W": 1e3}
"""Multiply a reading in this unit by the factor to get mW."""

METADATA_KEYS = ("instrument", "objective", "power_meter", "date", "operator")
"""Metadata fields offered in the manual template and copied into exports."""

RAW_BLOCK_MARKER = "## raw_readings"
RESULTS_BLOCK_MARKER = "## results"

_META_RE = re.compile(r"^#\s*([A-Za-z][A-Za-z0-9_]*)\s*:\s*(.*?)\s*$")
_MANUAL_COL_RE = re.compile(r"^(\d+)_(mW|uW|W)$")
_MANUAL_ERR_RE = re.compile(r"^(\d+)_error_(mW|uW|W)$")
_OLD_EXPORT_COL_RE = re.compile(r"^(\d+)_P_mW$")


@dataclass
class Reading:
    """One power reading. ``row`` is the source row, so replicates stay distinct."""

    row: int
    setting_pct: float
    nm: int
    power_mw: float
    error_mw: float | None = None


@dataclass
class Calibration:
    readings: list[Reading]
    source_format: str
    source_name: str = ""
    source_sha256: str = ""
    input_unit: str = "mW"
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def wavelengths(self) -> list[int]:
        return sorted({r.nm for r in self.readings})

    def line(self, nm: int) -> list[Reading]:
        return [r for r in self.readings if r.nm == nm]

    def xs(self, nm: int) -> list[float]:
        return [r.setting_pct for r in self.line(nm)]

    def powers(self, nm: int) -> list[float]:
        return [r.power_mw for r in self.line(nm)]


class FormatError(ValueError):
    """The file is not in any recognised format. The message says what was expected."""


EXPECTED_FORMATS_HELP = (
    "Expected one of:\n"
    "  * a raw ArgoPower export (semicolon-delimited, with a 'power_instruction'\n"
    "    column and one '<wavelength>_power' column per laser);\n"
    "  * a manual readings table (header 'setting_pct,488_mW,640_mW,...';\n"
    "    use 'Save blank template...' to get one);\n"
    "  * a CSV exported by this tool."
)


def _to_mw(tok: str, factor: float) -> float | None:
    """Parse a reading and convert it to mW in decimal arithmetic, so '850' uW is exactly 0.85 mW."""
    tok = tok.strip()
    if _to_float(tok) is None:
        return None
    return float(Decimal(tok) * Decimal(repr(factor)))


def _to_float(tok: str) -> float | None:
    tok = tok.strip()
    if not tok:
        return None
    try:
        v = float(tok)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_metadata(lines: list[str]) -> dict[str, str]:
    meta: dict[str, str] = {}
    for ln in lines:
        m = _META_RE.match(ln.strip())
        if m and m.group(2):
            meta.setdefault(m.group(1), m.group(2))
    return meta


# --------------------------------------------------------------------------- #
# ArgoPower
# --------------------------------------------------------------------------- #
def _find_argopower_header(lines: list[str]) -> int | None:
    for i, ln in enumerate(lines):
        if ";" in ln and "power_instruction" in [t.strip() for t in ln.split(";")]:
            return i
    return None


def _parse_argopower(lines: list[str], hdr: int, input_unit: str) -> list[Reading]:
    factor = INPUT_UNIT_FACTORS[input_unit]
    header = [t.strip() for t in lines[hdr].split(";")]
    col = {name: k for k, name in enumerate(header)}
    x_col = col["power_instruction"]
    wl_cols: dict[int, tuple[int, int]] = {}
    for name, k in col.items():
        m = re.fullmatch(r"(\d+)_power", name)
        if m:
            nm = int(m.group(1))
            wl_cols[nm] = (k, col.get(f"{nm}_error", -1))
    if not wl_cols:
        raise FormatError("ArgoPower header has no '<wavelength>_power' columns.")

    readings: list[Reading] = []
    for row, ln in enumerate(lines[hdr + 1 :]):
        toks = ln.split(";")
        x = _to_float(toks[x_col]) if x_col < len(toks) else None
        if x is None:
            break  # blank line or next block ('time;...') ends the table
        for nm, (pc, ec) in sorted(wl_cols.items()):
            p = _to_mw(toks[pc], factor) if pc < len(toks) else None
            if p is None:
                continue
            e = _to_mw(toks[ec], factor) if 0 <= ec < len(toks) else None
            readings.append(Reading(row, x, nm, p, abs(e) if e is not None else None))
    return readings


# --------------------------------------------------------------------------- #
# Manual template / raw block of an export
# --------------------------------------------------------------------------- #
def _split(line: str, delim: str) -> list[str]:
    return [t.strip() for t in next(csv.reader([line], delimiter=delim))]


def _find_manual_header(lines: list[str]) -> tuple[int, str] | None:
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("#"):
            continue
        for delim in (",", ";", "\t"):
            if delim not in ln:
                continue
            toks = _split(ln, delim)
            if "setting_pct" in toks and any(_MANUAL_COL_RE.match(t) for t in toks):
                return i, delim
    return None


def _parse_manual(lines: list[str], hdr: int, delim: str) -> list[Reading]:
    header = _split(lines[hdr], delim)
    x_col = header.index("setting_pct")
    p_cols: dict[int, tuple[int, float]] = {}
    e_cols: dict[int, tuple[int, float]] = {}
    for k, name in enumerate(header):
        if m := _MANUAL_COL_RE.match(name):
            nm = int(m.group(1))
            if nm in p_cols:
                raise FormatError(f"Column for {nm} nm appears twice in the header.")
            p_cols[nm] = (k, INPUT_UNIT_FACTORS[m.group(2)])
        elif m := _MANUAL_ERR_RE.match(name):
            e_cols[int(m.group(1))] = (k, INPUT_UNIT_FACTORS[m.group(2)])

    def norm(tok: str) -> str:
        # Excel in many European locales writes ';' between cells and ',' as the decimal mark.
        return tok.replace(",", ".") if delim == ";" else tok

    def num(tok: str) -> float | None:
        return _to_float(norm(tok))

    def mw(tok: str, factor: float) -> float | None:
        return _to_mw(norm(tok), factor)

    readings: list[Reading] = []
    for row, ln in enumerate(lines[hdr + 1 :]):
        s = ln.strip()
        if s.startswith("##"):
            break  # next block of an export
        if not s or s.startswith("#"):
            continue
        toks = _split(ln, delim)
        raw_x = toks[x_col] if x_col < len(toks) else ""
        x = num(raw_x)
        if x is None:
            if raw_x:
                raise FormatError(f"Line {hdr + row + 2}: setting '{raw_x}' is not a number.")
            continue
        for nm, (pc, f) in sorted(p_cols.items()):
            raw = toks[pc] if pc < len(toks) else ""
            p = mw(raw, f)
            if p is None:
                if raw:
                    raise FormatError(f"Line {hdr + row + 2}: {nm} nm reading '{raw}' is not a number.")
                continue
            err = None
            if nm in e_cols:
                ec, ef = e_cols[nm]
                e = mw(toks[ec], ef) if ec < len(toks) else None
                err = abs(e) if e is not None else None
            readings.append(Reading(row, x, nm, p, err))
    return readings


def _parse_old_export(lines: list[str]) -> list[Reading] | None:
    """Conversion tables from ArgoPower Calibrator 0.x (``setting_pct,488_P_mW,...``)."""
    for i, ln in enumerate(lines):
        toks = [t.strip() for t in ln.split(",")]
        if "setting_pct" in toks and any(_OLD_EXPORT_COL_RE.match(t) for t in toks):
            x_col = toks.index("setting_pct")
            cols = {int(m.group(1)): k for k, t in enumerate(toks) if (m := _OLD_EXPORT_COL_RE.match(t))}
            out = []
            for row, data in enumerate(lines[i + 1 :]):
                if not data.strip() or data.lstrip().startswith("#"):
                    continue
                t = data.split(",")
                x = _to_float(t[x_col]) if x_col < len(t) else None
                if x is None:
                    continue
                for nm, pc in sorted(cols.items()):
                    p = _to_float(t[pc]) if pc < len(t) else None
                    if p is not None:
                        out.append(Reading(row, x, nm, p, None))
            return out or None
    return None


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #
def parse_text(text: str, input_unit: str = "uW", source_name: str = "", sha256: str = "") -> Calibration:
    """Parse file contents. ``input_unit`` applies to ArgoPower exports only."""
    if input_unit not in INPUT_UNIT_FACTORS:
        raise ValueError(f"Unknown input unit {input_unit!r}; use one of {list(INPUT_UNIT_FACTORS)}.")
    text = text.lstrip("﻿")
    lines = text.splitlines()

    hdr = _find_argopower_header(lines)
    if hdr is not None:
        readings = _parse_argopower(lines, hdr, input_unit)
        fmt, unit = "argopower", input_unit
        meta = {"power_meter": "an Argolight power meter (ArgoPower export)"}
        for i, ln in enumerate(lines):
            if ln.strip() == "Analysis name" and i + 1 < len(lines):
                meta["argopower_analysis"] = lines[i + 1].strip()
    else:
        meta = {}
        start = 0
        fmt = "manual"
        for i, ln in enumerate(lines):
            if ln.strip().startswith(RAW_BLOCK_MARKER):
                fmt, start = "export", i + 1
                break
        if fmt == "export":
            meta = _read_metadata(lines[:start])
        found = _find_manual_header(lines[start:])
        if found is not None:
            h, delim = found
            meta = {**_read_metadata(lines[start : start + h]), **meta}
            readings = _parse_manual(lines, start + h, delim)
            unit = "mW"
        else:
            old = _parse_old_export(lines)
            if old is None:
                raise FormatError("This file is not in a recognised format.\n\n" + EXPECTED_FORMATS_HELP)
            readings, fmt, unit = old, "export_v0", "mW"

    if not readings:
        raise FormatError("The file was recognised but contains no power readings.")
    return Calibration(readings, fmt, source_name, sha256, unit, meta)


def parse_file(path: str | os.PathLike, input_unit: str = "uW") -> Calibration:
    with open(path, "rb") as fh:
        data = fh.read()
    text = data.decode("utf-8-sig", errors="replace")
    return parse_text(text, input_unit, os.path.basename(os.fspath(path)), _sha256(data))


def blank_template(
    wavelengths: list[int] | tuple[int, ...] = (405, 488, 561, 640),
    settings: list[float] | None = None,
    with_errors: bool = False,
) -> str:
    """Text of an empty manual-readings template."""
    if settings is None:
        settings = [float(s) for s in range(0, 101, 10)]
    out = io.StringIO()
    out.write(
        "# Manual power measurement template (for example a Thorlabs PM100D/PM400 with a slide sensor)\n"
        "# Fill in one row per laser setting. Leave a cell blank if you did not measure that line.\n"
        "# Powers are in mW, measured at the sample plane through the imaging objective.\n"
        "# Set the meter's wavelength to each laser line before reading it, and zero the sensor with the laser off.\n"
        "# Rename, add or delete the wavelength columns to match your lasers (format <nm>_mW, or <nm>_uW).\n"
        "# You may repeat a setting on extra rows for replicate readings.\n"
    )
    for key in METADATA_KEYS:
        out.write(f"# {key}:\n")
    cols = ["setting_pct"]
    for nm in wavelengths:
        cols.append(f"{nm}_mW")
        if with_errors:
            cols.append(f"{nm}_error_mW")
    out.write(",".join(cols) + "\n")
    for s in settings:
        out.write(f"{s:g}" + "," * (len(cols) - 1) + "\n")
    return out.getvalue()
