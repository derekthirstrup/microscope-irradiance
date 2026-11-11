"""Ordinary least squares fits of power (mW) against laser setting (%).

Pure Python so the fit stays small and auditable.

* Default window is 0-50 %: many lasers roll off at high settings, which
  injects a spurious positive intercept into a full-range linear fit.
* Default model is through the origin (P = m x), since 0 % is 0 mW physically.
* The +/- on the slope is the fit standard error only. The power meter's own
  per-reading uncertainty (typically ~10 %) usually dominates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .parse import Calibration

R2_WARN = 0.995
"""Warn about non-linearity below this R^2."""

SLOPE_DIFF_WARN = 0.05
"""Warn when the free-intercept slope differs from the through-origin slope by more than this."""


@dataclass
class Fit:
    nm: int
    model: str  # "origin" or "free"
    m: float
    b: float
    se_m: float
    se_b: float
    r2: float
    n: int
    s: float
    pct_min: float
    pct_max: float
    xs: list[float]
    ys: list[float]
    xbar: float = 0.0
    sxx_c: float = 0.0
    warnings: list[str] = field(default_factory=list)

    @property
    def lowest_nonzero(self) -> float | None:
        nz = [x for x in self.xs if x > 0]
        return min(nz) if nz else None

    @property
    def highest(self) -> float:
        return max(self.xs)

    def predict(self, x: float) -> tuple[float, float]:
        """(power mW, fit standard error of the mean response) at setting x."""
        if self.model == "origin":
            return self.m * x, abs(x) * self.se_m
        yh = self.m * x + self.b
        se = self.s * math.sqrt(1.0 / self.n + (x - self.xbar) ** 2 / self.sxx_c)
        return yh, se

    def equation(self) -> str:
        win = f"{self.pct_min:g}-{self.pct_max:g} %"
        if self.model == "origin":
            return (
                f"P = ({self.m:.4f} ± {self.se_m:.4f}) × x mW    R² = {self.r2:.4f}"
                f"   (n = {self.n}, through origin, {win})"
            )
        return (
            f"P = ({self.m:.4f} ± {self.se_m:.4f}) × x {'−' if self.b < 0 else '+'} ({abs(self.b):.4f} ± {self.se_b:.4f}) mW"
            f"    R² = {self.r2:.4f}   (n = {self.n}, free intercept, {win})"
        )

    def extrapolation_warning(self, x: float) -> str | None:
        lo = self.lowest_nonzero
        if x > self.pct_max + 1e-9 or x > self.highest + 1e-9:
            top = min(self.pct_max, self.highest)
            return (
                f"{x:g} % is above the fit window (highest point used: {top:g} %); the value is extrapolated."
            )
        if lo is not None and 0 < x < lo - 1e-9:
            return (
                f"{x:g} % is below the lowest non-zero measured setting ({lo:g} %); "
                "the value relies on the fitted line between 0 and the first point."
            )
        return None


def _r2(ys: list[float], yhat: list[float]) -> float:
    n = len(ys)
    ybar = sum(ys) / n
    sst = sum((y - ybar) ** 2 for y in ys)
    sse = sum((y - f) ** 2 for y, f in zip(ys, yhat))
    return 1 - sse / sst if sst > 0 else float("nan")


def ols_origin(xs: list[float], ys: list[float]) -> dict:
    n = len(xs)
    if n < 2:
        raise ValueError(f"Need at least 2 points for a through-origin fit (got {n}).")
    sxx = sum(x * x for x in xs)
    if sxx == 0:
        raise ValueError("All settings in the fit window are 0 %.")
    m = sum(x * y for x, y in zip(xs, ys)) / sxx
    yhat = [m * x for x in xs]
    sse = sum((y - f) ** 2 for y, f in zip(ys, yhat))
    s2 = sse / (n - 1)
    return {
        "model": "origin",
        "m": m,
        "b": 0.0,
        "se_m": math.sqrt(s2 / sxx),
        "se_b": 0.0,
        "r2": _r2(ys, yhat),
        "n": n,
        "s": math.sqrt(s2),
    }


def ols_free(xs: list[float], ys: list[float]) -> dict:
    n = len(xs)
    if n < 3:
        raise ValueError(f"Need at least 3 points for a free-intercept fit (got {n}).")
    xbar = sum(xs) / n
    ybar = sum(ys) / n
    sxx_c = sum((x - xbar) ** 2 for x in xs)
    if sxx_c == 0:
        raise ValueError("All settings in the fit window are identical.")
    m = sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys)) / sxx_c
    b = ybar - m * xbar
    yhat = [m * x + b for x in xs]
    sse = sum((y - f) ** 2 for y, f in zip(ys, yhat))
    s2 = sse / (n - 2)
    return {
        "model": "free",
        "m": m,
        "b": b,
        "se_m": math.sqrt(s2 / sxx_c),
        "se_b": math.sqrt(s2 * (1.0 / n + xbar * xbar / sxx_c)),
        "r2": _r2(ys, yhat),
        "n": n,
        "s": math.sqrt(s2),
        "xbar": xbar,
        "sxx_c": sxx_c,
    }


def in_window(x: float, pct_min: float, pct_max: float) -> bool:
    return pct_min - 1e-9 <= x <= pct_max + 1e-9


def fit_line(
    cal: Calibration, nm: int, pct_min: float = 0.0, pct_max: float = 50.0, through_origin: bool = True
) -> Fit:
    if pct_max <= pct_min:
        raise ValueError("Fit window maximum must be larger than its minimum.")
    pts = [(r.setting_pct, r.power_mw) for r in cal.line(nm) if in_window(r.setting_pct, pct_min, pct_max)]
    if not pts:
        raise ValueError(f"{nm} nm: no readings inside the fit window {pct_min:g}-{pct_max:g} %.")
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    res = ols_origin(xs, ys) if through_origin else ols_free(xs, ys)
    fit = Fit(nm=nm, pct_min=pct_min, pct_max=pct_max, xs=xs, ys=ys, **res)
    fit.warnings = linearity_warnings(fit)
    return fit


def linearity_warnings(fit: Fit) -> list[str]:
    """Plain-language warnings when the readings in the window are not a straight line."""
    out: list[str] = []
    advice = "Narrow the fit window to the straight part of the curve" + (
        " or untick 'through origin' to allow an intercept." if fit.model == "origin" else "."
    )
    if not math.isnan(fit.r2) and fit.r2 < R2_WARN:
        out.append(
            f"{fit.nm} nm: R² = {fit.r2:.3f} is below {R2_WARN}; the readings are not linear "
            f"over {fit.pct_min:g}-{fit.pct_max:g} %. {advice}"
        )
    if fit.n >= 3 and len(set(fit.xs)) >= 3:
        origin = ols_origin(fit.xs, fit.ys)["m"]
        free = ols_free(fit.xs, fit.ys)["m"]
        if origin != 0:
            diff = (free - origin) / origin
            if abs(diff) > SLOPE_DIFF_WARN:
                out.append(
                    f"{fit.nm} nm: the free-intercept slope differs from the through-origin slope "
                    f"by {diff:+.0%}, so the curve bends or has an offset. {advice}"
                )
    return out
