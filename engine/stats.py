"""Median and quantile, without numpy.

numpy was the only compiled dependency in this project. Dropping it makes the
whole app pure Python, so `uv sync` needs no wheel matching the user's CPU and
the same folder runs unchanged on Apple Silicon, Intel Mac, x86 Windows and ARM
Windows. Flask is pure Python, so nothing else pulls a binary in.

These reproduce numpy's DEFAULT quantile method ('linear', a.k.a. R type 7)
exactly, which matters because the published forecast numbers must not shift
when the dependency goes away:

    position h = q * (n - 1)
    lo = floor(h), hi = ceil(h)
    result = a[lo] + (h - lo) * (a[hi] - a[lo])

`test_stats.py` asserts agreement with numpy to 1e-9 across the real corpus.
"""

from __future__ import annotations

import math
from collections.abc import Iterable


def quantile(values: Iterable[float], q: float) -> float:
    """Linear-interpolated quantile, matching numpy.quantile's default method.

    Raises ValueError on empty input, like numpy does: callers already guard
    with `if self.values else None`, and a silent 0.0 would be a wrong answer
    dressed as a real one.
    """
    a = sorted(float(v) for v in values)
    n = len(a)
    if n == 0:
        raise ValueError("quantile() of an empty sequence")
    # The range check has to come BEFORE the n==1 short-circuit. It used to sit
    # after it, so quantile([5.0], 1.5) returned 5.0 where numpy raises
    # ValueError, the one input size where the docstring's promise above was
    # false. No shipped number moves: for a valid q and n==1 the answer is
    # still a[0], by this function and by numpy alike.
    if not 0.0 <= q <= 1.0:
        raise ValueError(f"q must be in [0, 1], got {q}")
    if n == 1:
        return a[0]

    h = q * (n - 1)
    lo = math.floor(h)
    hi = math.ceil(h)
    if lo == hi:
        return a[lo]
    return a[lo] + (h - lo) * (a[hi] - a[lo])


def median(values: Iterable[float]) -> float:
    """The 0.5 quantile, by the same rule numpy uses."""
    return quantile(values, 0.5)
