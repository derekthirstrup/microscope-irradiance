"""Command line interface. Every GUI input has a flag here.

Example (regenerates the QUAREP paper numbers)::

    irradiance-calc examples/argopower_example.csv --width-um 450 --height-um 450 \\
        --settings "488: 3.15, 6.3, 12.6, 25.2; 640: 5, 40.6" --lines 488,640 \\
        --exposure-s 0.1 --slices 305 --power-objective "10x" --imaging-objective "40x WI"
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .parse import INPUT_UNIT_FACTORS, METADATA_KEYS, FormatError, blank_template, parse_file
from .table import Inputs, compute, display_table, methods_text, parse_settings, to_csv


def _int_list(s: str) -> list[int]:
    return [int(t) for t in s.replace(";", ",").split(",") if t.strip()]


def _wavelengths(s: str) -> dict[int, float]:
    out = {}
    for part in s.replace(";", ",").split(","):
        if part.strip():
            k, _, v = part.partition("=")
            out[int(k)] = float(v)
    return out


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="irradiance-calc",
        description="Convert a laser setting (%%) into irradiance (mW/cm²), photon flux and dose "
        "from an ArgoPower export or a manual readings table.",
    )
    ap.add_argument(
        "csv", nargs="?", help="ArgoPower export, manual readings table, or an export of this tool."
    )
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    g = ap.add_argument_group("data and fit")
    g.add_argument(
        "--input-unit",
        choices=list(INPUT_UNIT_FACTORS),
        default="uW",
        help="Power unit of an ArgoPower export (default uW). Ignored for manual tables.",
    )
    g.add_argument(
        "--lines", type=_int_list, default=None, help="Laser lines to report, e.g. 488,640 (default all)."
    )
    g.add_argument("--fit-min", type=float, default=0.0, help="Lowest setting %% in the fit (default 0).")
    g.add_argument("--fit-max", type=float, default=50.0, help="Highest setting %% in the fit (default 50).")
    g.add_argument("--free", action="store_true", help="Free intercept instead of through the origin.")
    g = ap.add_argument_group("optics")
    g.add_argument("--width-um", type=float, help="Illuminated field width (µm).")
    g.add_argument("--height-um", type=float, help="Illuminated field height (µm).")
    g.add_argument(
        "--k", type=float, default=1.0, help="Power correction factor, P_sample = k P_meter (default 1)."
    )
    g.add_argument(
        "--wavelength-nm",
        type=_wavelengths,
        default={},
        help="Actual wavelength per line, e.g. 488=488,640=638 (default: the column name).",
    )
    g.add_argument("--power-objective", default="", help="Objective the power was measured through.")
    g.add_argument("--imaging-objective", default="", help="Objective used for imaging.")
    g = ap.add_argument_group("acquisition")
    g.add_argument("--exposure-s", type=float, help="Laser-on time per plane (s); enables dose.")
    g.add_argument("--slices", type=int, default=1, help="Slices per z-stack (default 1).")
    g.add_argument("--timepoints", type=int, default=1, help="Number of timepoints (default 1).")
    g = ap.add_argument_group("table")
    g.add_argument(
        "--settings",
        default="",
        help='Settings to report: "3.15, 6.3" for every line or "488: 3.15, 6.3; 640: 5".',
    )
    g.add_argument(
        "--step",
        type=float,
        default=None,
        help="Also add a stepped grid every STEP %% (default 5 when no --settings).",
    )
    g.add_argument(
        "--table-max", type=float, default=100.0, help="Highest setting in the grid (default 100)."
    )
    g = ap.add_argument_group("metadata (override the file)")
    for k in METADATA_KEYS:
        g.add_argument(f"--{k.replace('_', '-')}", dest=f"meta_{k}", default="")
    g = ap.add_argument_group("output")
    g.add_argument("--csv", dest="csv_out", help="Write the full CSV export here.")
    g.add_argument("--report", help="Write the PDF report here (needs matplotlib).")
    g.add_argument("--methods", action="store_true", help="Print a methods paragraph.")
    g.add_argument("--template", metavar="PATH", help="Write a blank manual-readings template and exit.")
    g.add_argument(
        "--template-lines",
        type=_int_list,
        default=[405, 488, 561, 640],
        help="Laser lines in the template (default 405,488,561,640).",
    )
    return ap


def inputs_from_args(args: argparse.Namespace) -> Inputs:
    return Inputs(
        fit_min=args.fit_min,
        fit_max=args.fit_max,
        through_origin=not args.free,
        lines=args.lines,
        width_um=args.width_um,
        height_um=args.height_um,
        k=args.k,
        wavelengths_nm=args.wavelength_nm,
        exposure_s=args.exposure_s,
        slices=args.slices,
        timepoints=args.timepoints,
        settings=parse_settings(args.settings),
        grid_step=args.step,
        grid_max=args.table_max,
        power_objective=args.power_objective,
        imaging_objective=args.imaging_objective,
        metadata={k: getattr(args, f"meta_{k}") for k in METADATA_KEYS},
    )


def _print_table(heads: list[str], rows: list[list[str]]) -> None:
    heads = heads[:-1]  # notes are printed as warnings
    rows = [r[:-1] for r in rows]
    w = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(heads)]
    print("  ".join(h.rjust(w[i]) for i, h in enumerate(heads)))
    print("  ".join("-" * x for x in w))
    for r in rows:
        print("  ".join(v.rjust(w[i]) for i, v in enumerate(r)))


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass

    if args.template:
        with open(args.template, "w", encoding="utf-8", newline="") as fh:
            fh.write(blank_template(args.template_lines))
        print(f"Wrote blank template {args.template}")
        return 0
    if not args.csv:
        ap.error("give a calibration file (or --template PATH)")

    try:
        cal = parse_file(args.csv, input_unit=args.input_unit)
        result = compute(cal, inputs_from_args(args))
    except (FormatError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"{cal.source_name}  ({cal.source_format}, lines {cal.wavelengths})")
    if result.inputs.area_mm2:
        print(f"Illuminated area A = {result.inputs.area_mm2:.5g} mm²   k = {result.inputs.k:g}")
    print()
    for f in result.fits.values():
        print(f"{f.nm} nm:  {f.equation()}")
    print()
    _print_table(*display_table(result))
    if result.warnings:
        print("\nWarnings:")
        for w in result.warnings:
            print(f"  * {w}")
    print(
        "\n± on the slope is the fit standard error only; the meter's per-reading uncertainty "
        "(typically 10 %) usually dominates."
    )
    if args.methods:
        print("\n" + methods_text(result))
    if args.csv_out:
        with open(args.csv_out, "w", encoding="utf-8", newline="") as fh:
            fh.write(to_csv(result))
        print(f"\nWrote {args.csv_out}")
    if args.report:
        from .report import write_pdf

        n = write_pdf(result, args.report)
        print(f"Wrote {args.report} ({n} pages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
