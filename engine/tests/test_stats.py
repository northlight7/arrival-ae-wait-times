"""Proof that stats.quantile / stats.median reproduce numpy to 1e-9.

This file is the one stats.py's own module docstring already claims exists:

    "`test_stats.py` asserts agreement with numpy to 1e-9 across the real
     corpus."

Until now it did not, so the repo asserted a proof it could not produce. The
claim matters because numpy was DELETED as a dependency in order to keep the
app pure Python, and the published forecast numbers were only allowed to
survive that deletion on the promise that the replacement was numerically
identical.

numpy is therefore a TEST-ONLY dependency (see pyproject.toml
[dependency-groups] test). Every comparison below is guarded by
``pytest.importorskip("numpy")`` so this suite still runs, and still checks the
non-numpy invariants, on a machine that has never installed it.

Run the real proof with:   uv run --group test pytest tests/test_stats.py
"""

from __future__ import annotations

import math
import random

import pytest

import stats
from tests._support import CORPUS_SAMPLE, read_json

# numpy's default method is 'linear', a.k.a. R type 7, the one stats.py
# documents itself as reproducing. Named explicitly so a future numpy default
# change turns into a visible edit here rather than a silent drift.
NUMPY_METHOD = "linear"

QUANTILES = [0.0, 0.05, 0.1, 0.25, 1 / 3, 0.5, 0.75, 0.9, 0.95, 0.99, 1.0]


def _assert_matches_numpy(np, values, q, *, tol=1e-9, note=""):
    expected = float(np.quantile(np.asarray(values, dtype=float), q,
                                 method=NUMPY_METHOD))
    actual = stats.quantile(values, q)
    assert math.isclose(actual, expected, rel_tol=tol, abs_tol=tol), (
        f"stats.quantile disagrees with numpy.quantile at q={q!r} {note}\n"
        f"  ours : {actual!r}\n"
        f"  numpy: {expected!r}\n"
        f"  delta: {actual - expected!r}\n"
        f"  n    : {len(values)}"
    )


# ---------------------------------------------------------------------------
# 1. Hand-written edge cases, against numpy
# ---------------------------------------------------------------------------

EDGE_CASES = {
    "n=1": [42.0],
    "n=1 zero": [0.0],
    "n=1 negative": [-7.5],
    "n=2": [1.0, 2.0],
    "n=2 reversed": [2.0, 1.0],
    "n=3 odd": [1.0, 5.0, 9.0],
    "n=4 even": [1.0, 2.0, 3.0, 4.0],
    "all equal": [60.0] * 7,
    "all equal n=2": [3.5, 3.5],
    "all zero": [0.0] * 5,
    "negatives": [-10.0, -3.0, -1.0, -0.5],
    "mixed sign": [-100.0, -1.0, 0.0, 1.0, 100.0],
    "floats": [0.1, 0.2, 0.30000000000000004, 0.4],
    "unsorted": [9.0, 1.0, 5.0, 3.0, 7.0, 2.0],
    "unsorted with ties": [5.0, 1.0, 5.0, 1.0, 3.0],
    "ints not floats": [1, 2, 3, 4, 5],
    "heavy ties": [60.0] * 20 + [90.0] * 20 + [30.0],
    "long tail": [15.0] * 50 + [600.0],
    "tiny spread": [1.0, 1.0 + 1e-12, 1.0 + 2e-12],
    "large magnitude": [1e9, 2e9, 3e9, 4e9],
    "quantised half hours": [30.0, 60.0, 90.0, 120.0, 150.0, 180.0],
}


@pytest.mark.parametrize("name", sorted(EDGE_CASES))
@pytest.mark.parametrize("q", QUANTILES)
def test_edge_cases_match_numpy(name, q):
    np = pytest.importorskip("numpy")
    _assert_matches_numpy(np, EDGE_CASES[name], q, note=f"[{name}]")


@pytest.mark.parametrize("name", sorted(EDGE_CASES))
def test_median_matches_numpy(name):
    np = pytest.importorskip("numpy")
    values = EDGE_CASES[name]
    expected = float(np.median(np.asarray(values, dtype=float)))
    actual = stats.median(values)
    assert math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9), (
        f"stats.median disagrees with numpy.median [{name}]: "
        f"{actual!r} vs {expected!r}"
    )


def test_median_is_the_half_quantile():
    """Not a tautology test: it pins the documented relationship.

    stats.median is defined as quantile(v, 0.5). If someone 'optimises' it to
    statistics.median (which averages the two middle values only for even n and
    is NOT R type 7 in general), this catches it.
    """
    for values in EDGE_CASES.values():
        assert stats.median(values) == stats.quantile(values, 0.5)


# ---------------------------------------------------------------------------
# 2. Iterables: the function advertises Iterable[float], not list[float]
# ---------------------------------------------------------------------------

def test_accepts_a_generator():
    np = pytest.importorskip("numpy")
    data = [9.0, 1.0, 5.0, 3.0, 7.0]
    _assert_matches_numpy(np, data, 0.25, note="[list]")
    assert stats.quantile((v for v in data), 0.25) == stats.quantile(data, 0.25)


def test_accepts_tuples_sets_and_iterators():
    data = [9.0, 1.0, 5.0, 3.0, 7.0]
    ref = stats.quantile(data, 0.75)
    assert stats.quantile(tuple(data), 0.75) == ref
    assert stats.quantile(iter(data), 0.75) == ref
    assert stats.quantile(set(data), 0.75) == ref          # distinct values here
    assert stats.quantile(range(1, 10), 0.5) == 5.0


def test_does_not_mutate_or_consume_the_caller_s_list():
    data = [9.0, 1.0, 5.0, 3.0, 7.0]
    before = list(data)
    stats.quantile(data, 0.5)
    assert data == before, "quantile() sorted the caller's list in place"


# ---------------------------------------------------------------------------
# 3. Invariants that hold with or without numpy installed
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(EDGE_CASES))
def test_q0_is_min_and_q1_is_max(name):
    values = [float(v) for v in EDGE_CASES[name]]
    assert stats.quantile(values, 0.0) == min(values)
    assert stats.quantile(values, 1.0) == max(values)


@pytest.mark.parametrize("name", sorted(EDGE_CASES))
def test_quantile_is_monotone_non_decreasing_in_q(name):
    values = EDGE_CASES[name]
    prev = None
    for q in QUANTILES:
        cur = stats.quantile(values, q)
        if prev is not None:
            assert cur >= prev - 1e-12, (
                f"quantile decreased as q rose [{name}] at q={q}"
            )
        prev = cur


@pytest.mark.parametrize("name", sorted(EDGE_CASES))
def test_result_lies_within_the_data_range(name):
    values = [float(v) for v in EDGE_CASES[name]]
    lo, hi = min(values), max(values)
    for q in QUANTILES:
        r = stats.quantile(values, q)
        assert lo - 1e-12 <= r <= hi + 1e-12


def test_the_interval_the_product_promises_is_ordered():
    """p25 <= median <= p75 is the app's core output contract."""
    rng = random.Random(20260811)
    for _ in range(300):
        n = rng.randint(1, 200)
        values = [rng.uniform(0, 720) for _ in range(n)]
        p25 = stats.quantile(values, 0.25)
        p50 = stats.median(values)
        p75 = stats.quantile(values, 0.75)
        assert p25 <= p50 <= p75


# ---------------------------------------------------------------------------
# 4. Randomised property testing against numpy
# ---------------------------------------------------------------------------

def _random_arrays(rng, count):
    """Arrays shaped like the things a wait-time corpus actually contains."""
    for _ in range(count):
        n = rng.choice([1, 2, 3, 4, 5, 7, 11, 17, 32, 64, 101, 250, 999])
        kind = rng.choice(
            ["uniform", "ints", "ties", "negatives", "wide", "tiny", "constant"]
        )
        if kind == "uniform":
            yield [rng.uniform(0, 720) for _ in range(n)]
        elif kind == "ints":
            yield [float(rng.randint(0, 600)) for _ in range(n)]
        elif kind == "ties":
            pool = [rng.choice([0.0, 15.0, 30.0, 60.0, 90.0]) for _ in range(n)]
            yield pool
        elif kind == "negatives":
            yield [rng.uniform(-500, 500) for _ in range(n)]
        elif kind == "wide":
            yield [rng.uniform(-1e6, 1e6) for _ in range(n)]
        elif kind == "tiny":
            yield [rng.uniform(0, 1e-6) for _ in range(n)]
        else:
            yield [rng.uniform(0, 100)] * n


def test_random_arrays_match_numpy():
    np = pytest.importorskip("numpy")
    rng = random.Random(1_000_003)
    checked = 0
    for values in _random_arrays(rng, 400):
        for _ in range(6):
            q = rng.random()
            _assert_matches_numpy(np, values, q, note="[random]")
            checked += 1
        for q in (0.0, 0.25, 0.5, 0.75, 1.0):
            _assert_matches_numpy(np, values, q, note="[random fixed q]")
            checked += 1
    assert checked >= 4000, "property test did not actually exercise much"


def test_random_arrays_match_numpy_median():
    np = pytest.importorskip("numpy")
    rng = random.Random(77)
    for values in _random_arrays(rng, 300):
        expected = float(np.median(np.asarray(values, dtype=float)))
        actual = stats.median(values)
        assert math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9)


def test_permutation_invariance_against_numpy():
    """Shuffling the input must not move the answer by a single ulp."""
    np = pytest.importorskip("numpy")
    rng = random.Random(4242)
    for _ in range(200):
        base = [rng.uniform(0, 400) for _ in range(rng.randint(2, 60))]
        ref = stats.quantile(base, 0.75)
        for _ in range(3):
            shuffled = base[:]
            rng.shuffle(shuffled)
            assert stats.quantile(shuffled, 0.75) == ref
        _assert_matches_numpy(np, base, 0.75, note="[permutation]")


# ---------------------------------------------------------------------------
# 5. The real corpus: the specific claim stats.py makes
# ---------------------------------------------------------------------------

def _corpus_arrays():
    if not CORPUS_SAMPLE.exists():
        pytest.fail(
            f"missing fixture {CORPUS_SAMPLE}, regenerate with "
            f"`uv run python -m tests.make_corpus_fixture`"
        )
    return read_json(CORPUS_SAMPLE)


def test_corpus_fixture_is_real_and_substantial():
    """Guards the test below from silently becoming vacuous."""
    doc = _corpus_arrays()
    arrays = doc["arrays"]
    assert len(arrays) >= 50, "fixture lost most of its arrays"
    total = sum(len(a["values"]) for a in arrays)
    assert total >= 3000, f"fixture only has {total} values"
    assert any(len(a["values"]) >= 1000 for a in arrays), (
        "fixture has no large pooled array"
    )
    # Real wait data, not synthetic: minutes, non-negative, with ties.
    flat = [v for a in arrays for v in a["values"]]
    assert min(flat) >= 0.0
    assert max(flat) > 60.0
    assert len(set(flat)) < len(flat), "no repeated values: this is not real data"
    assert doc["_source_corpus"]["dates"] > 0


def test_real_corpus_values_match_numpy_to_1e_9():
    """THE claim in stats.py's docstring, finally executable.

    Absolute tolerance, not relative: these are minutes in the range 0–1500,
    so 1e-9 minutes is 60 nanoseconds of disagreement. That is the bar the
    docstring set.
    """
    np = pytest.importorskip("numpy")
    doc = _corpus_arrays()
    worst = 0.0
    worst_where = ""
    for arr in doc["arrays"]:
        values = arr["values"]
        a = np.asarray(values, dtype=float)
        for q in QUANTILES:
            expected = float(np.quantile(a, q, method=NUMPY_METHOD))
            actual = stats.quantile(values, q)
            diff = abs(actual - expected)
            if diff > worst:
                worst, worst_where = diff, f"{arr['label']} q={q}"
            assert diff <= 1e-9, (
                f"stats.quantile != numpy.quantile on real corpus data\n"
                f"  where: {arr['label']}\n"
                f"  q    : {q}\n"
                f"  ours : {actual!r}\n"
                f"  numpy: {expected!r}\n"
                f"  diff : {diff!r}"
            )
        expected_med = float(np.median(a))
        assert abs(stats.median(values) - expected_med) <= 1e-9, (
            f"stats.median != numpy.median on {arr['label']}"
        )
    print(f"\nworst disagreement across the corpus sample: {worst!r} ({worst_where})")


def test_real_corpus_values_match_numpy_at_random_q():
    np = pytest.importorskip("numpy")
    rng = random.Random(9091)
    doc = _corpus_arrays()
    for arr in doc["arrays"]:
        a = np.asarray(arr["values"], dtype=float)
        for _ in range(10):
            q = rng.random()
            expected = float(np.quantile(a, q, method=NUMPY_METHOD))
            actual = stats.quantile(arr["values"], q)
            assert abs(actual - expected) <= 1e-9, (
                f"{arr['label']} q={q}: {actual!r} vs {expected!r}"
            )


# ---------------------------------------------------------------------------
# 6. Error behaviour
# ---------------------------------------------------------------------------

def test_empty_input_raises_value_error():
    with pytest.raises(ValueError, match="empty"):
        stats.quantile([], 0.5)
    with pytest.raises(ValueError, match="empty"):
        stats.median([])
    with pytest.raises(ValueError, match="empty"):
        stats.quantile(iter([]), 0.0)


@pytest.mark.parametrize("q", [-0.001, -1.0, 1.001, 2.0, 100.0, float("inf")])
def test_out_of_range_q_raises_value_error(q):
    with pytest.raises(ValueError, match="q must be in"):
        stats.quantile([1.0, 2.0, 3.0], q)


@pytest.mark.parametrize("q", [-0.5, 1.5])
def test_out_of_range_q_raises_even_for_single_element_input(q):
    """Was xfail(strict=True): `if n == 1: return a[0]` sat above the range
    check, so quantile([5.0], 1.5) returned 5.0 where numpy raises. Fixed by
    moving the range check above the early return, so the marker is gone and this
    is now an ordinary passing test."""
    with pytest.raises(ValueError):
        stats.quantile([5.0], q)


@pytest.mark.parametrize("q", [-0.5, 1.5, -0.001, 1.001, 2.0, float("inf")])
def test_single_element_out_of_range_q_now_agrees_with_numpy(q):
    """The other half of the fix: our raise and numpy's raise now coincide on
    the one input size where they used to diverge."""
    with pytest.raises(ValueError):
        stats.quantile([5.0], q)
    np = pytest.importorskip("numpy")
    with pytest.raises(ValueError):
        np.quantile(np.asarray([5.0]), q, method=NUMPY_METHOD)


@pytest.mark.parametrize("q", [0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0])
def test_single_element_in_range_q_is_unchanged_and_matches_numpy(q):
    """And the fix moves no shipped number: for a valid q, n==1 still returns
    the element, identically to numpy."""
    assert stats.quantile([5.0], q) == 5.0
    np = pytest.importorskip("numpy")
    assert abs(stats.quantile([5.0], q)
               - float(np.quantile(np.asarray([5.0]), q, method=NUMPY_METHOD))) < 1e-9


def test_nan_q_is_rejected():
    """NaN fails every comparison in `0.0 <= q <= 1.0`, so the guard holds."""
    with pytest.raises(ValueError):
        stats.quantile([1.0, 2.0, 3.0], float("nan"))
