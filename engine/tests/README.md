# Test suite: Arrival engine

Two claims in this repo used to be unprovable. This suite makes both executable.

1. `stats.py`'s docstring says *"`test_stats.py` asserts agreement with numpy to
   1e-9 across the real corpus."* That file did not exist. It does now.
2. The release gate requires that a full-corpus rebuild still produces identical
   forecasts. `test_forecast_golden.py` is the detector.

## Commands

```bash
cd engine

uv run pytest                      # everything, numpy comparisons SKIP
uv run --group test pytest         # everything, including the numpy proof
uv run --group test pytest -q      # same, quiet
uv run --group test pytest tests/test_stats.py -v
```

Both forms work from a clean checkout. `uv run pytest` is deliberately usable
without ever installing numpy, see the next section for why that matters, and
watch for `SKIPPED` lines telling you the numpy proof did not run.

To see which numpy tests skipped:

```bash
uv run pytest -q -rs
```

## numpy is a TEST-ONLY dependency, on purpose

`stats.py` exists because numpy was the project's only compiled dependency.
Dropping it made the app pure Python, so the same folder runs unchanged on
Apple Silicon, Intel Mac, x86 Windows and ARM Windows without `uv sync` having
to find a wheel matching the user's CPU. Putting numpy back into
`[project].dependencies` would undo the entire point of the module the tests
are testing.

So `pyproject.toml` splits it:

| group  | installed by | holds | compiled wheels |
|---|---|---|---|
| `dev`  | plain `uv sync` / `uv run` | `pytest` (+ pluggy, iniconfig, packaging, pygments, all pure Python) | none |
| `test` | only `uv sync --group test` / `uv run --group test` | `pytest`, `numpy` | numpy |

Every numpy comparison is wrapped in `pytest.importorskip("numpy")`, so the
suite passes, and still checks its non-numpy invariants, on a machine that
has never installed it.

**Verify the runtime is still wheel-free at any time:**

```bash
cd engine
uv sync                                          # no --group test
find .venv -name '*.so' -o -name '*.pyd'
```

> **Pre-existing finding, not introduced by the tests:** that command already
> prints `markupsafe/_speedups.<abi>.so`. MarkupSafe arrives transitively via
> Flask → Jinja2 and does ship a compiled wheel, so the comment in `stats.py`
> and `pyproject.toml` ("Flask is pure Python, so nothing else pulls a binary
> in") is not accurate today. MarkupSafe degrades to a pure-Python fallback
> when no matching wheel exists, so the app still runs everywhere, but the
> claim as written is too strong. Adding pytest introduced **zero** new
> compiled wheels.

## What each file does

| File | Proves |
|---|---|
| `test_stats.py` | `stats.quantile` / `stats.median` == `numpy.quantile` / `numpy.median` (method `'linear'`, R type 7) to 1e-9, on hand-written edge cases, ~4,000 randomised property checks, and real corpus values. Plus the error contract. |
| `test_forecast_golden.py` | A fixed 77-case query matrix still produces byte-identical forecasts to `fixtures/golden_forecasts.json`. |
| `test_api_contract.py` | The response invariants the frontend and the product's promises depend on, driven through Flask's test client. Includes the `tail` / `tail_p95_median` contract, see below. |
| `golden_matrix.py` | The matrix definition, shared by the test and the regenerator. |
| `regen_golden.py` | Deliberate regeneration of the golden file. |
| `make_corpus_fixture.py` | One-off extractor for `fixtures/corpus_sample.json`. |
| `_support.py` | Corpus memoisation, corpus fingerprinting, and the offline guard. |
| `conftest.py` | Fixtures. The `_no_network` fixture is **autouse**: every test in this directory runs offline. |

## Fixtures

### `fixtures/corpus_sample.json` (231 KB)

43,220 real observed wait values in 145 arrays, pulled from the 232 MB
`data/ae_corpus.json`. Six hospitals spanning the territory plus St John, all
six `(triage, percentile)` pairs the archive records, four hours of the week,
and one 21k-value pooled array.

Real values rather than random ones because real A&E waits have heavy ties,
coarse quantisation to whole minutes and clean half-hours, long right tails and
exact zeros, the shapes where a hand-rolled quantile drifts from numpy.

Regenerate (only after an intentional corpus rebuild):

```bash
cd engine && uv run python -m tests.make_corpus_fixture
```

### `fixtures/golden_forecasts.json` (34 KB)

77 frozen cases. Each records `forecast_median`, `forecast_p25`,
`forecast_p75`, `basis`, `pooled`, `n_observations`, `verdict`, `answered`.

Deliberately **not** recorded: live published minutes, travel time, traffic.
Those feeds move every 15 minutes and pinning them would make the suite flaky
for reasons unrelated to a forecast regression. Every case therefore supplies
its own `published` value as an explicit input, which is also how the matrix
exercises all four verdicts (`reliable`, `caution`, `misleading`,
`no_live_data`) with no network.

The file header records the corpus fingerprint it was generated against:
date count, snapshot count, hospital count, bucket count, and a SHA-256 over
every bucket's `(key, n, sum)`. `test_golden_file_was_generated_against_this_corpus`
fails loudly with both fingerprints if they diverge, so a stale golden file is
self-evident instead of mysterious.

## Regenerating the golden file

```bash
cd engine
uv run python -m tests.regen_golden           # write it
uv run python -m tests.regen_golden --check   # exit 1 if it would change
```

**Only run the first form after an intentional change to the corpus or the
forecast maths, and commit it on its own** so a reviewer reads the forecast
movement as a diff. Running it to make a red test go green without knowing why
the numbers moved deletes the only forecast-regression detector this project
has.

Concretely: when the September 2025 backfill is merged into `ae_corpus.json`,
`test_forecast_golden.py` will go red on every case. That is the gate working.
The correct response is one commit that merges the corpus and one commit that
regenerates this file, so the reviewer can see exactly which forecasts moved
and by how much.

## Hermeticity

- **No network.** `conftest._no_network` is autouse and replaces
  `urllib.request.urlopen` with a raiser for every test.
  `test_the_suite_really_is_offline` asserts the guard bites, so the
  "feed is down" tests cannot pass by accident.
- **No clock or date dependence.** Every case passes an explicit day and hour,
  `test_matrix_does_not_consult_the_clock` re-runs the whole matrix with
  `datetime.now` frozen to 2031 and `time.time` moved forward, and requires
  identical output.
- **No live feeds.** Both `engine._fetch_live_triage` and `routing._http_get`
  already return `None` on failure, so severing the network exercises the app's
  documented degradation path rather than a special test-only branch. Tests
  that need a *present* published figure install a fixed table via the
  `live_feed` fixture.
- **Corpus loaded once.** `engine.query` re-reads and re-buckets all 232 MB on
  every call (~2 s). `_support.memoise_engine_corpus` replaces
  `load_corpus`/`build_buckets`, both pure functions, with cached calls. No
  number changes, the suite goes from minutes to seconds.

## The p95 tail

`test_api_contract.py` section 9 covers `tail` (top level) and
`tail_p95_median` (every `all_hospitals` row). What it defends:

| Test | Promise |
|---|---|
| `test_tail_is_present_and_well_formed` | `tail` always exists, and when available the interval is ordered and above the observation floor |
| `test_tail_basis_is_never_finer_than_the_forecast_basis` | the tail cannot claim an hour-resolution the median beside it does not have |
| `test_the_tail_is_never_below_the_median` | p95 ≥ p50, for the headline and for all 18 rows |
| `test_a_missing_p95_series_refuses_instead_of_scaling_the_p50` | with the p95 buckets deleted, `available:false` and nulls, never a scaled p50 |
| `test_tail_does_not_disturb_any_existing_field` | deleting the p95 series moves no pre-existing field |
| `test_score_tail_*` | the ladder, the `floor_basis` clamp, and that `basis` names the rung actually used |

Measured across all 6,048 hospital × {t3, t45} × hour-of-week combinations in
the current corpus, `p95_median >= p50_median` holds **6,048 / 6,048 times**,
with zero exceptions. So the assertion is safe today, and a failure would be a real
finding about the feed, not a rounding artefact, and the test message says so.

## Notes for whoever reads this next

**The `stats.quantile` n=1 bug is fixed, and its `xfail(strict=True)` is gone.**
`quantile([x], q)` used to return `x` for *any* `q`, including `q=1.5` and
`q=-0.5`, because `if n == 1: return a[0]` sat above the range check.
The range check now comes first, `test_out_of_range_q_raises_even_for_single_element_input`
is an ordinary passing test, and two new tests pin both halves of the fix:
out-of-range `q` raises exactly where numpy raises, and in-range `q` at n=1
still returns the element to within 1e-9 of numpy. Equivalence was re-proved
against numpy over every real corpus bucket (18,650 arrays, 149,192
comparisons) for the code before **and** after the change: max deviation
5.684e-14 in both cases, and the old and new results are bit-identical for
every valid `q`. No published number moved.

**The pooling statistics have been corrected in `server.py`.** It used to say
71% `exact_hour` / 2.4% `hour_window` / 26% `all_hours`. Re-measured against
`ae_corpus.json` as it stands, **all 6,048** hospital × {t3, t45} ×
hour-of-week combinations resolve to `exact_hour`, and so do all 6,048 on the
p95 series, with zero basis disagreement between the two. The other two
branches are unreachable through `engine.query` on a corpus this dense. They
are still live code with UI states attached, reachable on a freshly-seeded or
partially-backfilled corpus, so `golden_matrix.THIN_CASES` locks them by
thinning real corpus buckets deterministically, using real values, with only the
thinness synthetic. Section B of the golden file is labelled
`"thinned_buckets"`.

**`routing._window_forecast` looks like dead code.** Its docstring says it
exists because `engine.score_reliability` raises `UnboundLocalError` on the
`hour_window` branch. `engine.py` now sets `pooled = False` there, so the
branch no longer raises and `routing`'s `except Exception` fallback should
never fire. Removing it is a job for whoever owns `routing.py`.
