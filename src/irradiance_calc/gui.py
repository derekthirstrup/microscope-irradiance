"""Desktop app: laser setting (%) -> irradiance, photon flux and dose.

Tkinter only; matplotlib is used for the plot and the PDF report when present.
"""

from __future__ import annotations

import os
import sys
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import __version__
from .parse import INPUT_UNIT_FACTORS, METADATA_KEYS, Calibration, blank_template, parse_file
from .table import Inputs, Result, compute, display_table, parse_settings, to_csv
from .units import area_mm2

try:
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure

    HAVE_MPL = True
except Exception:  # pragma: no cover
    HAVE_MPL = False

APP_TITLE = f"Irradiance Calculator {__version__}"

HELP_TEXT = f"""\
{APP_TITLE}

WHAT IT DOES
Converts a laser setting (%) into what actually reaches the sample:
  • irradiance E (mW/cm², also mW/mm² and W/cm²)
  • photon flux Φ (photons cm⁻² s⁻¹, also photons µm⁻² s⁻¹)
  • dose per plane, per z-stack and in total (J/cm² and photons/cm²)

STEPS
 1. Load an ArgoPower export or a filled-in manual template
    ("Save blank template..." gives you one).
 2. For ArgoPower files, check the power unit (normally µW).
 3. Tick the laser lines to report; correct the wavelength if your laser is
    not exactly the nominal line.
 4. Check the fit window (default 0-50 %) and look at the plot: the points
    must lie on the line inside the shaded window.
 5. Enter the illuminated field width and height (µm).
 6. Enter the settings you imaged at, e.g. "3.15, 6.3" or
    "488: 3.15, 6.3; 640: 5". Optionally add a stepped grid.
 7. For dose, enter exposure time per plane, slices per stack and timepoints.
 8. Calculate, then export the CSV and/or the PDF report.

FORMULAS
  E = k·P / A          (k = power correction factor, default 1)
  Φ = E·λ / (h·c)      = 5.034117×10¹² · E[mW/cm²] · λ[nm]  photons cm⁻² s⁻¹
  H_plane = E·t,  H_stack = E·t·N_slices,  H_total = H_stack·N_timepoints

ASSUMPTIONS
  • E is the time- and field-averaged irradiance, not the peak at a
    spinning-disk pinhole or a scanned spot.
  • Dose per stack assumes every slice exposure illuminates the full axial
    column (true for widefield and spinning disk, not for light-sheet).
  • t is the time the laser is on per plane. If the laser is not blanked
    between exposures, the real dose is higher.
  • Photon numbers count photons delivered, not absorbed.
  • Uncertainty is dominated by the power meter (typically 10 % per reading);
    the fit standard error is usually below 1 %.

WARNINGS
  • Linearity: R² below 0.995, or a free-intercept slope that differs from
    the through-origin slope by more than 5 %. Narrow the fit window.
  • Extrapolation: a setting below the lowest non-zero measured point or above
    the fit window.
"""


def examples_dir() -> str | None:
    """Folder with the example files: bundled with the installer, or in a source checkout."""
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [os.path.join(here, "..", "..", "examples")]
    if getattr(sys, "_MEIPASS", None):
        cands.insert(0, os.path.join(sys._MEIPASS, "examples"))  # type: ignore[attr-defined]
    for cand in cands:
        if os.path.isfile(os.path.join(cand, "argopower_example.csv")):
            return os.path.normpath(cand)
    return None


def _num(var: tk.StringVar, name: str, *, allow_blank: bool = False, integer: bool = False):
    s = var.get().strip()
    if not s:
        if allow_blank:
            return None
        raise ValueError(f"'{name}' is empty.")
    try:
        return int(s) if integer else float(s)
    except ValueError:
        raise ValueError(
            f"'{name}' must be {'a whole number' if integer else 'a number'} (got '{s}')."
        ) from None


class App(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master, padding=8)
        self.master = master
        self.grid(sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        self.cal: Calibration | None = None
        self.path: str | None = None
        self.result: Result | None = None
        self.line_vars: dict[int, tuple[tk.BooleanVar, tk.StringVar]] = {}
        self.widgets: dict[str, tk.Misc] = {}  # key controls, for documentation screenshots

        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 8))
        right = ttk.Frame(self)
        right.grid(row=0, column=1, sticky="nsew")
        self._build_controls(left)
        self._build_output(right)

    # ------------------------------------------------------------------ UI --
    def _entry(self, parent, row, label, value="", width=10, col=0, tip=""):
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="e", padx=(0, 4), pady=1)
        var = tk.StringVar(value=value)
        ttk.Entry(parent, textvariable=var, width=width).grid(row=row, column=col + 1, sticky="w", pady=1)
        if tip:
            ttk.Label(parent, text=tip, foreground="#777").grid(row=row, column=col + 2, sticky="w", padx=4)
        return var

    def _build_controls(self, p):
        # 1. file
        f = ttk.LabelFrame(p, text="1. Power readings", padding=6)
        f.grid(row=0, column=0, sticky="ew")
        self.widgets["load"] = ttk.Button(f, text="Load file...", command=self.load_dialog)
        self.widgets["load"].grid(row=0, column=0, sticky="w")
        self.widgets["template"] = ttk.Button(f, text="Save blank template...", command=self.save_template)
        self.widgets["template"].grid(row=0, column=1, sticky="w", padx=4)
        self.file_lbl = ttk.Label(f, text="No file loaded", foreground="#555", wraplength="3.3i")
        self.file_lbl.grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Label(f, text="ArgoPower power unit:").grid(row=2, column=0, sticky="e")
        self.unit = tk.StringVar(value="uW")
        cb = ttk.Combobox(
            f, textvariable=self.unit, width=5, state="readonly", values=list(INPUT_UNIT_FACTORS)
        )
        cb.grid(row=2, column=1, sticky="w")
        self.widgets["unit"] = cb
        cb.bind("<<ComboboxSelected>>", lambda _e: self.reload())

        # 2. lines and fit
        f = ttk.LabelFrame(p, text="2. Laser lines and fit", padding=6)
        f.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.lines_frame = ttk.Frame(f)
        self.lines_frame.grid(row=0, column=0, columnspan=4, sticky="w")
        self.widgets["lines"] = self.lines_frame
        ttk.Label(self.lines_frame, text="(load a file)", foreground="#777").grid(row=0, column=0)
        self.fit_min = self._entry(f, 1, "Fit window min %:", "0", 6)
        self.fit_max = self._entry(f, 2, "Fit window max %:", "50", 6)
        self.origin = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="Through origin (P = m·x)", variable=self.origin).grid(
            row=3, column=0, columnspan=3, sticky="w"
        )

        # 3. optics
        f = ttk.LabelFrame(p, text="3. Illuminated field and optics", padding=6)
        self.widgets["field"] = f
        f.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self.width = self._entry(f, 0, "Width (µm):", "450", 8)
        self.height = self._entry(f, 1, "Height (µm):", "450", 8)
        self.area_lbl = ttk.Label(f, text="", foreground="#555")
        self.area_lbl.grid(row=2, column=1, columnspan=2, sticky="w")
        for v in (self.width, self.height):
            v.trace_add("write", lambda *_: self._update_area())
        self._update_area()
        self.k = self._entry(f, 3, "Power correction k:", "1", 8, tip="P_sample = k·P_meter")
        self.power_obj = self._entry(f, 4, "Power measured via:", "", 16, tip="objective")
        self.imaging_obj = self._entry(f, 5, "Imaging objective:", "", 16)

        # 4. acquisition
        f = ttk.LabelFrame(p, text="4. Acquisition (for dose)", padding=6)
        self.widgets["acquisition"] = f
        f.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.exposure = self._entry(f, 0, "Exposure per plane (s):", "", 8, tip="blank = no dose")
        self.slices = self._entry(f, 1, "Slices per stack:", "1", 8)
        self.timepoints = self._entry(f, 2, "Timepoints:", "1", 8)

        # 5. settings
        f = ttk.LabelFrame(p, text="5. Settings to report", padding=6)
        self.widgets["settings"] = f
        f.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        self.settings = tk.StringVar(value="")
        ttk.Entry(f, textvariable=self.settings, width=40).grid(row=0, column=0, columnspan=4, sticky="ew")
        ttk.Label(f, text='e.g. "3.15, 6.3, 12.6" or "488: 3.15, 6.3; 640: 5"', foreground="#777").grid(
            row=1, column=0, columnspan=4, sticky="w"
        )
        self.use_grid = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="Also a grid every", variable=self.use_grid).grid(row=2, column=0, sticky="w")
        self.step = tk.StringVar(value="5")
        ttk.Entry(f, textvariable=self.step, width=5).grid(row=2, column=1, sticky="w")
        ttk.Label(f, text="% up to").grid(row=2, column=2, sticky="w")
        self.grid_max = tk.StringVar(value="100")
        ttk.Entry(f, textvariable=self.grid_max, width=5).grid(row=2, column=3, sticky="w")

        # 6. details
        f = ttk.LabelFrame(p, text="6. Details for the report (optional)", padding=6)
        f.grid(row=5, column=0, sticky="ew", pady=(6, 0))
        self.meta = {
            k: self._entry(f, i, k.replace("_", " ").capitalize() + ":", "", 24)
            for i, k in enumerate(METADATA_KEYS)
            if k != "objective"
        }

        # actions
        a = ttk.Frame(p, padding=(0, 8, 0, 0))
        a.grid(row=6, column=0, sticky="ew")
        self.widgets["calculate"] = ttk.Button(a, text="Calculate", command=self.calculate_clicked)
        self.widgets["calculate"].grid(row=0, column=0, sticky="ew")
        self.widgets["export_csv"] = ttk.Button(a, text="Export CSV...", command=self.export_csv)
        self.widgets["export_csv"].grid(row=0, column=1, sticky="ew", padx=4)
        self.pdf_btn = ttk.Button(a, text="Export PDF report...", command=self.export_pdf)
        self.pdf_btn.grid(row=0, column=2, sticky="ew")
        self.widgets["export_pdf"] = self.pdf_btn
        if not HAVE_MPL:
            self.pdf_btn.state(["disabled"])
        ttk.Button(a, text="Help", command=self.show_help).grid(row=0, column=3, sticky="ew", padx=(4, 0))

    def _build_output(self, p):
        p.columnconfigure(0, weight=1)
        p.rowconfigure(1, weight=1)
        self.msg = tk.Text(p, height=10, wrap="word", font=("TkDefaultFont", 9))
        self.msg.grid(row=0, column=0, sticky="ew")
        self.widgets["messages"] = self.msg
        msb = ttk.Scrollbar(p, orient="vertical", command=self.msg.yview)
        msb.grid(row=0, column=1, sticky="ns")
        self.msg.configure(yscrollcommand=msb.set)
        self.msg.tag_configure("warn", foreground="#a04000")
        self.msg.tag_configure("head", font=("TkDefaultFont", 9, "bold"))
        self.msg.configure(state="disabled")

        self.tree = ttk.Treeview(p, show="headings", height=12)
        self.tree.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        self.widgets["table"] = self.tree
        vsb = ttk.Scrollbar(p, orient="vertical", command=self.tree.yview)
        vsb.grid(row=1, column=1, sticky="ns", pady=(6, 0))
        hsb = ttk.Scrollbar(p, orient="horizontal", command=self.tree.xview)
        hsb.grid(row=2, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.tag_configure("reported", background="#eef6ee")

        if HAVE_MPL:
            self.fig = Figure(figsize=(7, 3.0), dpi=90)
            self.canvas = FigureCanvasTkAgg(self.fig, master=p)
            self.canvas.get_tk_widget().grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self._message(
            [
                (
                    "Press 'Load file...' to start. The file dialog opens in the examples folder; "
                    "argopower_example.csv is a working example. Press Help for the steps.",
                    "",
                )
            ]
        )

    def _message(self, parts):
        self.msg.configure(state="normal")
        self.msg.delete("1.0", "end")
        for text, tag in parts:
            self.msg.insert("end", text + "\n", tag)
        self.msg.configure(state="disabled")

    def _update_area(self):
        try:
            a = area_mm2(float(self.width.get()), float(self.height.get()))
            self.area_lbl.config(text=f"A = {a:.5g} mm²")
        except ValueError:
            self.area_lbl.config(text="A = (none; irradiance not calculated)")

    def _rebuild_lines(self):
        for w in self.lines_frame.winfo_children():
            w.destroy()
        old = {nm: (b.get(), s.get()) for nm, (b, s) in self.line_vars.items()}
        self.line_vars = {}
        assert self.cal is not None
        ttk.Label(self.lines_frame, text="Report").grid(row=0, column=0, sticky="w")
        ttk.Label(self.lines_frame, text="λ used (nm)").grid(row=0, column=1, sticky="w", padx=6)
        for i, nm in enumerate(self.cal.wavelengths, start=1):
            on, wl = old.get(nm, (True, str(nm)))
            b, s = tk.BooleanVar(value=on), tk.StringVar(value=wl)
            ttk.Checkbutton(self.lines_frame, text=f"{nm} nm", variable=b).grid(row=i, column=0, sticky="w")
            ttk.Entry(self.lines_frame, textvariable=s, width=7).grid(row=i, column=1, sticky="w", padx=6)
            self.line_vars[nm] = (b, s)

    # --------------------------------------------------------------- logic --
    def load_dialog(self):
        start = os.path.dirname(self.path) if self.path else examples_dir()
        path = filedialog.askopenfilename(
            title="Select power readings (ArgoPower export, manual template or earlier export)",
            initialdir=start or os.path.expanduser("~"),
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if path:
            self.load_path(path)

    def load_path(self, path: str) -> bool:
        try:
            cal = parse_file(path, input_unit=self.unit.get())
        except ValueError as exc:
            messagebox.showerror("Could not read this file", str(exc))
            return False
        except Exception as exc:
            messagebox.showerror("Could not read this file", f"{exc}\n\n{traceback.format_exc()}")
            return False
        self.cal, self.path = cal, path
        kind = {
            "argopower": "ArgoPower export",
            "manual": "manual readings",
            "export": "earlier export (re-fitting its raw readings)",
            "export_v0": "old conversion table",
        }.get(cal.source_format, cal.source_format)
        unit_note = f", values in {self.unit.get()}" if cal.source_format == "argopower" else ""
        self.file_lbl.config(text=f"{os.path.basename(path)}\n{kind}{unit_note}; lines {cal.wavelengths}")
        for k, var in self.meta.items():
            if cal.metadata.get(k) and not var.get():
                var.set(cal.metadata[k])
        if cal.metadata.get("objective") and not self.power_obj.get():
            self.power_obj.set(cal.metadata["objective"])
        for key, var in (
            ("power_measured_through_objective", self.power_obj),
            ("imaging_objective", self.imaging_obj),
        ):
            if cal.metadata.get(key) and not var.get():
                var.set(cal.metadata[key])
        self._rebuild_lines()
        self.calculate_clicked()
        return True

    def reload(self):
        if self.path:
            self.load_path(self.path)

    def gather_inputs(self) -> Inputs:
        lines = [nm for nm, (b, _) in self.line_vars.items() if b.get()]
        if not lines:
            raise ValueError("Tick at least one laser line.")
        wl = {}
        for nm, (_, s) in self.line_vars.items():
            wl[nm] = _num(s, f"wavelength for {nm} nm")
        w = _num(self.width, "Width", allow_blank=True)
        h = _num(self.height, "Height", allow_blank=True)
        if (w is None) != (h is None):
            raise ValueError("Give both the illuminated width and height, or neither.")
        step = _num(self.step, "Grid step") if self.use_grid.get() else None
        settings = parse_settings(self.settings.get())
        return Inputs(
            fit_min=_num(self.fit_min, "Fit window min"),
            fit_max=_num(self.fit_max, "Fit window max"),
            through_origin=self.origin.get(),
            lines=lines,
            width_um=w,
            height_um=h,
            k=_num(self.k, "Power correction k"),
            wavelengths_nm=wl,
            exposure_s=_num(self.exposure, "Exposure per plane", allow_blank=True),
            slices=_num(self.slices, "Slices per stack", integer=True),
            timepoints=_num(self.timepoints, "Timepoints", integer=True),
            settings=settings,
            grid_step=step if (step or not settings) else None,
            grid_max=_num(self.grid_max, "Grid maximum"),
            power_objective=self.power_obj.get().strip(),
            imaging_objective=self.imaging_obj.get().strip(),
            metadata={k: v.get().strip() for k, v in self.meta.items()},
        )

    def calculate(self) -> Result:
        if self.cal is None:
            raise ValueError("Load a power-readings file first.")
        self.result = compute(self.cal, self.gather_inputs())
        return self.result

    def calculate_clicked(self):
        try:
            res = self.calculate()
        except ValueError as exc:
            messagebox.showerror("Check the inputs", str(exc))
            return
        except Exception as exc:
            messagebox.showerror("Error", f"{exc}\n\n{traceback.format_exc()}")
            return
        parts = [("Fits", "head")]
        parts += [(f"{f.nm} nm:  {f.equation()}", "") for f in res.fits.values()]
        if res.warnings:
            parts.append(("Warnings", "head"))
            parts += [(f"• {w}", "warn") for w in res.warnings]
        if not res.has_area:
            parts.append(("Enter the illuminated width and height to get irradiance.", "warn"))
        parts.append(
            (
                "± is the fit standard error only; the power meter's per-reading uncertainty "
                "(typically 10 %) usually dominates.",
                "",
            )
        )
        self._message(parts)
        self._fill_table(res)
        self._plot(res)

    def _fill_table(self, res: Result):
        heads, rows = display_table(res)
        self.tree.delete(*self.tree.get_children())
        cols = [f"c{i}" for i in range(len(heads))]
        self.tree["columns"] = cols
        import tkinter.font as tkfont

        font = tkfont.nametofont("TkDefaultFont")
        pad = font.measure("  ")
        for i, (c, h) in enumerate(zip(cols, heads, strict=True)):
            self.tree.heading(c, text=h)
            texts = [h] + [r[i] for r in rows]
            if h == "Note":
                wide = font.measure("x" * 60)
            else:
                wide = max(font.measure(t) for t in texts) + 2 * pad
            self.tree.column(
                c,
                width=wide,
                minwidth=wide // 2,
                anchor="w" if h == "Note" else "center",
                stretch=h == "Note",
            )
        for r, vals in zip(res.rows, rows, strict=True):
            self.tree.insert("", "end", values=vals, tags=(r.row_type,))

    def table_values(self) -> list[list[str]]:
        """What the table shows, row by row (used by tests)."""
        return [list(map(str, self.tree.item(i)["values"])) for i in self.tree.get_children()]

    def _plot(self, res: Result):
        if not HAVE_MPL:
            return
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        colours = {
            405: "#7b3fbf",
            445: "#3f4fbf",
            488: "#1f9fd0",
            514: "#2ca02c",
            561: "#c9a300",
            594: "#e07b00",
            640: "#c0302b",
            647: "#c0302b",
        }
        any_fit = next(iter(res.fits.values()))
        ax.axvspan(any_fit.pct_min, any_fit.pct_max, color="#4c72b0", alpha=0.07, lw=0)
        for nm, fit in res.fits.items():
            c = colours.get(nm, None)
            line = res.cal.line(nm)
            xs = [r.setting_pct for r in line]
            ys = [r.power_mw for r in line]
            es = [r.error_mw or 0 for r in line]
            if any(es):
                ax.errorbar(xs, ys, yerr=es, fmt="o", ms=3, capsize=2, color=c, lw=0.8, label=f"{nm} nm")
            else:
                ax.plot(xs, ys, "o", ms=3, color=c, label=f"{nm} nm")
            xm = max(xs)
            ax.plot([0, xm], [fit.predict(0)[0], fit.predict(xm)[0]], "-", lw=1, color=c)
        ax.set_xlabel("Laser setting (%)")
        ax.set_ylabel("Power at meter (mW)")
        ax.set_title("Readings, fit (lines) and fit window (shaded)", fontsize=9)
        ax.legend(fontsize=7, ncol=4)
        self.fig.tight_layout()
        self.canvas.draw()

    def _need_result(self) -> Result | None:
        if self.cal is None:
            messagebox.showinfo("Nothing to export", "Load a file and press Calculate first.")
            return None
        try:
            return self.calculate()
        except ValueError as exc:
            messagebox.showerror("Check the inputs", str(exc))
            return None

    def _default_name(self, suffix: str) -> str:
        base = os.path.splitext(os.path.basename(self.path or "irradiance"))[0]
        return f"{base}_irradiance{suffix}"

    def export_csv(self):
        res = self._need_result()
        if res is None:
            return
        path = filedialog.asksaveasfilename(
            title="Save CSV with all data",
            defaultextension=".csv",
            initialfile=self._default_name(".csv"),
            filetypes=[("CSV", "*.csv")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(to_csv(res))
        except OSError as exc:
            messagebox.showerror("Could not save", str(exc))
            return
        self.file_lbl.config(
            text=self.file_lbl.cget("text").split("\n✓")[0] + f"\n✓ saved {os.path.basename(path)}"
        )

    def export_pdf(self):
        res = self._need_result()
        if res is None:
            return
        path = filedialog.asksaveasfilename(
            title="Save PDF report",
            defaultextension=".pdf",
            initialfile=self._default_name(".pdf"),
            filetypes=[("PDF", "*.pdf")],
        )
        if not path:
            return
        from .report import write_pdf

        try:
            write_pdf(res, path)
        except Exception as exc:
            messagebox.showerror("Could not write the report", f"{exc}\n\n{traceback.format_exc()}")
            return
        self.file_lbl.config(
            text=self.file_lbl.cget("text").split("\n✓")[0] + f"\n✓ saved {os.path.basename(path)}"
        )

    def save_template(self):
        default = ", ".join(map(str, self.cal.wavelengths)) if self.cal else "405, 488, 561, 640"
        ans = simpledialog.askstring(
            "Blank template",
            "Laser lines to include (nm, comma-separated):",
            initialvalue=default,
            parent=self,
        )
        if ans is None:
            return
        try:
            nms = [int(t) for t in ans.replace(";", ",").replace(" ", ",").split(",") if t.strip()]
            if not nms:
                raise ValueError
        except ValueError:
            messagebox.showerror("Blank template", "Give wavelengths as whole numbers, e.g. 488, 640.")
            return
        path = filedialog.asksaveasfilename(
            title="Save blank template",
            defaultextension=".csv",
            initialfile="manual_power_readings.csv",
            filetypes=[("CSV", "*.csv")],
        )
        if path:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(blank_template(nms))
            messagebox.showinfo(
                "Blank template",
                f"Saved {os.path.basename(path)}.\n\nOpen it in Excel, type "
                "your readings in mW, save as CSV and load it here.",
            )

    def show_help(self):
        top = tk.Toplevel(self)
        top.title("Help")
        t = tk.Text(top, wrap="word", width=90, height=44, font=("TkFixedFont", 9))
        t.insert("1.0", HELP_TEXT)
        t.configure(state="disabled")
        t.pack(fill="both", expand=True)


def make_root() -> tk.Tk:
    """Tk root sized for the screen's DPI (sharp text on high-DPI Windows displays)."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()
    root.title(APP_TITLE)
    scale = max(1.0, root.winfo_fpixels("1i") / 96.0)
    w = min(int(1420 * scale), int(root.winfo_screenwidth() * 0.95))
    h = min(int(930 * scale), int(root.winfo_screenheight() * 0.9))
    root.geometry(f"{w}x{h}+{int(30 * scale)}+{int(20 * scale)}")
    style = ttk.Style(root)
    try:
        import tkinter.font as tkfont

        style.configure(
            "Treeview", rowheight=int(tkfont.nametofont("TkDefaultFont").metrics("linespace") * 1.35)
        )
    except Exception:
        pass
    return root


def main(argv: list[str] | None = None) -> None:
    root = make_root()
    app = App(root)
    args = sys.argv[1:] if argv is None else argv
    if args:
        root.after(100, lambda: app.load_path(args[0]))
    root.mainloop()


if __name__ == "__main__":
    main()
