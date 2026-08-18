"""The response invariants the frontend and the product's promises rely on.

Driven through Flask's test client, so the real wiring runs: server.py's
live-feed shim, routing.rank_hospitals, engine.query. Nothing here touches the
network: conftest's autouse fixture makes any URL open raise, and the tests
that need a *present* published figure install a fixed table instead of asking
the Hospital Authority.

Each test names the promise it is defending, because a contract test that
nobody can trace back to a promise gets deleted the first time it is
inconvenient.
"""

from __future__ import annotations

import pytest

QMH = "Queen Mary Hospital"
ST_JOHN = "St John Hospital"

HK_ORIGIN = {"lat": 22.2830, "lon": 114.1588}      # Central
OUTSIDE_HK = {"lat": 23.1291, "lon": 113.2644}     # Guangzhou


def _ok(client, **overrides):
    body = {"hospital": QMH, "triage": "t3", "day": "Monday", "hour": 14}
    body.update(overrides)
    r = client.post("/api/query", json=body)
    assert r.status_code == 200, f"{r.status_code}: {r.get_data(as_text=True)[:300]}"
    return r.get_json()


# ---------------------------------------------------------------------------
# 0. The offline guard actually bites
# ---------------------------------------------------------------------------
# Without this, every "the feed is down" test below could be passing because
# the feed happened to be up and returning something benign.

def test_the_suite_really_is_offline():
    import urllib.request

    from tests._support import NetworkAccessInTest

    with pytest.raises(NetworkAccessInTest):
        urllib.request.urlopen("https://example.invalid/")


def test_the_engine_and_routing_live_feeds_are_unreachable():
    import engine
    import routing

    assert routing.live_published_minutes() == {}
    assert routing.get_traffic_snapshot() is None
    assert engine._fetch_live_triage(QMH, "t3") is None


# ---------------------------------------------------------------------------
# 1. An answered forecast always carries an interval
# ---------------------------------------------------------------------------
# Promise: "Output contract: every number is an interval. Never a point
# estimate." (engine.py module docstring)

@pytest.mark.parametrize("day,hour,triage", [
    ("Monday", 14, "t3"),
    ("Sunday", 3, "t3"),
    ("Friday", 20, "t45"),
    ("Wednesday", 0, "t3"),
    ("Saturday", 23, "t45"),
])
def test_answered_forecast_always_has_an_ordered_interval(client, day, hour, triage):
    d = _ok(client, day=day, hour=hour, triage=triage)
    assert d["forecast_median"] is not None
    assert d["forecast_p25"] is not None
    assert d["forecast_p75"] is not None
    assert d["forecast_p25"] <= d["forecast_median"] <= d["forecast_p75"], (
        f"interval out of order: {d['forecast_p25']} / {d['forecast_median']} "
        f"/ {d['forecast_p75']}"
    )
    assert isinstance(d["forecast_interval"], str)
    assert d["forecast_interval"].strip(), "forecast_interval is empty"
    assert "–" in d["forecast_interval"], (
        f"forecast_interval {d['forecast_interval']!r} is not a range: the UI "
        "renders this string verbatim next to the word 'Median'"
    )


def test_every_hospital_in_the_table_that_has_a_forecast_has_an_interval(client):
    """The comparison table is 18 rows, and every one of them makes the same
    promise as the headline number."""
    d = _ok(client)
    rows = d["all_hospitals"]
    assert len(rows) == 18
    scored = 0
    for row in rows:
        if row["forecast_median"] is None:
            # Allowed, but it must then be totally absent, not half-rendered.
            assert row["forecast_p25"] is None, row["hospital"]
            assert row["forecast_p75"] is None, row["hospital"]
            assert row["forecast_interval"] is None, row["hospital"]
            assert row["reason"], (
                f"{row['hospital']} has no forecast and no reason why"
            )
            continue
        scored += 1
        assert row["forecast_p25"] <= row["forecast_median"] <= row["forecast_p75"], (
            f"{row['hospital']}: interval out of order"
        )
        assert row["forecast_interval"] and row["forecast_interval"].strip()
    assert scored >= 15, f"only {scored}/18 hospitals scored: table is hollow"


# ---------------------------------------------------------------------------
# 2. Input validation returns 4xx, never 500
# ---------------------------------------------------------------------------
# Promise: bogus values must not "silently produce wrong answers"
# (server.py comment). A 500 is not validation, it is a crash.

BAD_REQUESTS = [
    ("missing hospital", {"hospital": "", "day": "Monday", "hour": 14}),
    ("no hospital key", {"day": "Monday", "hour": 14}),
    ("bad day", {"hospital": QMH, "day": "Funday", "hour": 14}),
    ("lowercase day", {"hospital": QMH, "day": "monday", "hour": 14}),
    ("numeric day", {"hospital": QMH, "day": 1, "hour": 14}),
    ("null day", {"hospital": QMH, "day": None, "hour": 14}),
    ("hour too high", {"hospital": QMH, "day": "Monday", "hour": 24}),
    ("hour negative", {"hospital": QMH, "day": "Monday", "hour": -1}),
    ("hour way out", {"hospital": QMH, "day": "Monday", "hour": 99}),
    ("hour not a number", {"hospital": QMH, "day": "Monday", "hour": "lunchtime"}),
    ("hour null", {"hospital": QMH, "day": "Monday", "hour": None}),
    ("hour is a list", {"hospital": QMH, "day": "Monday", "hour": [14]}),
    ("bad mode", {"hospital": QMH, "day": "Monday", "hour": 14, "mode": "jetpack"}),
    ("empty mode", {"hospital": QMH, "day": "Monday", "hour": 14, "mode": ""}),
    ("null mode", {"hospital": QMH, "day": "Monday", "hour": 14, "mode": None}),
    ("walking mode", {"hospital": QMH, "day": "Monday", "hour": 14, "mode": "walk"}),
    ("origin is a string", {"hospital": QMH, "day": "Monday", "hour": 14,
                            "origin": "Central"}),
    ("origin is a list", {"hospital": QMH, "day": "Monday", "hour": 14,
                          "origin": [22.3, 114.2]}),
    ("origin is a number", {"hospital": QMH, "day": "Monday", "hour": 14,
                            "origin": 22.3}),
    ("origin missing lon", {"hospital": QMH, "day": "Monday", "hour": 14,
                            "origin": {"lat": 22.3}}),
    ("origin empty dict", {"hospital": QMH, "day": "Monday", "hour": 14,
                           "origin": {}}),
    ("origin lat not a number", {"hospital": QMH, "day": "Monday", "hour": 14,
                                 "origin": {"lat": "here", "lon": 114.2}}),
    ("origin lat null", {"hospital": QMH, "day": "Monday", "hour": 14,
                         "origin": {"lat": None, "lon": 114.2}}),
    ("lat out of range", {"hospital": QMH, "day": "Monday", "hour": 14,
                          "origin": {"lat": 91.0, "lon": 114.2}}),
    ("lat far out of range", {"hospital": QMH, "day": "Monday", "hour": 14,
                              "origin": {"lat": 999.0, "lon": 0.0}}),
    ("lon out of range", {"hospital": QMH, "day": "Monday", "hour": 14,
                          "origin": {"lat": 22.3, "lon": 181.0}}),
    ("lon far negative", {"hospital": QMH, "day": "Monday", "hour": 14,
                          "origin": {"lat": 22.3, "lon": -400.0}}),
    ("published not a number", {"hospital": QMH, "day": "Monday", "hour": 14,
                                "published": "soon"}),
]


@pytest.mark.parametrize("label,body", BAD_REQUESTS, ids=[b[0] for b in BAD_REQUESTS])
def test_bad_input_is_rejected_with_4xx_not_500(client, label, body):
    r = client.post("/api/query", json=body)
    assert 400 <= r.status_code < 500, (
        f"{label}: expected a 4xx, got {r.status_code}\n"
        f"{r.get_data(as_text=True)[:400]}"
    )
    assert r.status_code == 400, f"{label}: documented status is 400, got {r.status_code}"
    payload = r.get_json()
    assert payload and payload.get("error"), (
        f"{label}: 400 with no error message for the UI to show"
    )


def test_malformed_json_body_is_a_4xx(client):
    r = client.post("/api/query", data="{not json", content_type="application/json")
    assert 400 <= r.status_code < 500, r.status_code


def test_a_rejected_request_never_leaks_a_forecast(client):
    """A 4xx must not also carry numbers the UI might render."""
    r = client.post("/api/query", json={"hospital": QMH, "day": "Funday", "hour": 14})
    body = r.get_json()
    for leaky in ("forecast_median", "forecast_p25", "forecast_p75", "verdict"):
        assert leaky not in body, f"error response leaked {leaky}"


def test_unknown_hospital_refuses_rather_than_guessing(client):
    """Not a validation error, but a genuine 'no data' refusal, documented as 503."""
    r = client.post("/api/query", json={
        "hospital": "Somewhere Imaginary Hospital", "day": "Monday", "hour": 14,
    })
    assert r.status_code == 503, r.status_code
    body = r.get_json()
    assert body["error"]
    assert "forecast_median" not in body


# ---------------------------------------------------------------------------
# 3. No origin means no invented position
# ---------------------------------------------------------------------------
# Promise: WORKFLOW.md non-negotiable 4: "The default origin is not passed off
# as the user's real position." server.py: "a fabricated origin would produce
# confident travel times for a place the user is not."

@pytest.mark.parametrize("origin_field", ["absent", "null"])
def test_no_origin_never_fabricates_a_position(client, origin_field):
    body = {"hospital": QMH, "triage": "t3", "day": "Monday", "hour": 14}
    if origin_field == "null":
        body["origin"] = None
    r = client.post("/api/query", json=body)
    assert r.status_code == 200
    d = r.get_json()

    assert d["origin_provided"] is False
    assert d["travel_minutes"] is None, "travel time invented without an origin"
    assert d["travel_basis"] is None
    assert d["travel_is_estimate"] is False
    assert d["origin_outside_hong_kong"] is False

    assumption = d["travel_assumption"] or ""
    assert "no origin" in assumption.lower(), (
        f"travel_assumption must say no origin was supplied, got {assumption!r}"
    )

    # And not one of the 18 rows may carry a travel figure either.
    for row in d["all_hospitals"]:
        assert row["travel_minutes"] is None, (
            f"{row['hospital']} got a travel time with no origin"
        )
        assert row["distance_from_origin_km"] is None, (
            f"{row['hospital']} got a distance from an origin that was never given"
        )

    # total_minutes must then be wait only, not wait + a phantom journey.
    assert d["total_minutes"] == d["forecast_median"]


def test_no_origin_means_traffic_is_not_claimed_to_be_live(client):
    d = _ok(client)
    assert d["traffic_live"] is False


# ---------------------------------------------------------------------------
# 4. Honest degradation when the live feed is down
# ---------------------------------------------------------------------------
# Promise: engine._fetch_live_triage docstring: the caller "handles None by
# returning verdict='no_live_data' rather than fabricating a number."

def test_dead_live_feed_reports_no_live_data_and_invents_nothing(client, live_feed):
    live_feed(None)
    d = _ok(client)
    assert d["published_minutes"] is None, "a published figure appeared from a dead feed"
    assert d["verdict"] == "no_live_data"
    assert d["delta_minutes"] is None
    assert d["delta_direction"] == "live feed unavailable"
    assert d["traffic_feed_live"] is False
    # The forecast itself is history-based, so it must still be there.
    assert d["forecast_median"] is not None

    for row in d["all_hospitals"]:
        assert row["published_minutes"] is None, row["hospital"]
        assert row["delta_minutes"] is None, row["hospital"]


def test_a_live_figure_produces_a_delta_and_a_real_verdict(client, live_feed):
    """The other half of the same contract: when the feed IS there, the delta
    is computed and the verdict stops being 'no_live_data'."""
    live_feed({QMH: {"t3": 400.0}})
    d = _ok(client)
    assert d["published_minutes"] == 400.0
    assert d["verdict"] in ("reliable", "caution", "misleading")
    assert d["delta_minutes"] == pytest.approx(400.0 - d["forecast_median"])
    # Not "hospital understates wait": this tool has never measured what any
    # patient waited, so it cannot say the board is wrong, only where today's
    # figure sits against this department's own history.
    assert d["delta_direction"] == "busier than its normal"


def test_traffic_status_endpoint_admits_the_feed_is_down(client):
    r = client.get("/api/traffic-status")
    assert r.status_code == 200
    d = r.get_json()
    assert d["live"] is False
    assert d["detectors_used"] == 0
    assert d["message"], "no explanation of why traffic is not live"


def test_car_estimate_without_traffic_is_labelled_an_estimate(client):
    d = _ok(client, origin=HK_ORIGIN, mode="car")
    assert d["travel_is_estimate"] is True
    assert d["traffic_live"] is False, (
        "claimed live traffic while the detector feed is unreachable"
    )
    assert d["travel_basis"] == "static_fallback"
    assert "fixed" in (d["travel_assumption"] or "").lower()


# ---------------------------------------------------------------------------
# 5. pooled / basis are always present and always agree
# ---------------------------------------------------------------------------
# Promise: WORKFLOW.md non-negotiable 3: pooled:true or basis:"all_hours"
# must render an amber "not hour-specific" notice. The UI switches on both
# fields, so they must never contradict.

ENGINE_BASES = {"exact_hour", "hour_window", "all_hours"}
ROUTING_BASES = {"hour_bucket", "hour_window", "pooled_all_hours", "unavailable"}


@pytest.mark.parametrize("day,hour,triage", [
    ("Monday", 14, "t3"),
    ("Sunday", 3, "t45"),
    ("Thursday", 7, "t3"),
])
def test_pooled_and_basis_are_present_and_consistent(client, day, hour, triage):
    d = _ok(client, day=day, hour=hour, triage=triage)
    assert "pooled" in d and "basis" in d
    assert isinstance(d["pooled"], bool)
    assert d["basis"] in ENGINE_BASES, d["basis"]
    assert d["pooled"] == (d["basis"] == "all_hours"), (
        f"pooled={d['pooled']} contradicts basis={d['basis']!r}"
    )

    for row in d["all_hospitals"]:
        assert isinstance(row["pooled"], bool), row["hospital"]
        assert row["forecast_basis"] in ROUTING_BASES, (
            f"{row['hospital']}: unknown forecast_basis {row['forecast_basis']!r}"
        )
        assert row["pooled"] == (row["forecast_basis"] == "pooled_all_hours"), (
            f"{row['hospital']}: pooled={row['pooled']} contradicts "
            f"forecast_basis={row['forecast_basis']!r}"
        )
        if row["forecast_median"] is None:
            assert row["forecast_basis"] == "unavailable", row["hospital"]


def test_n_observations_is_present_and_above_the_engine_floor(client):
    d = _ok(client)
    assert d["n_observations"] >= 5, (
        "answered from fewer observations than the engine's own "
        "min_observations=5 floor"
    )


# ---------------------------------------------------------------------------
# 6. St John Hospital is never given a road journey
# ---------------------------------------------------------------------------
# Promise: routing.FERRY_ONLY_HOSPITALS: "We refuse to produce a number rather
# than produce a wrong one." WORKFLOW.md manual check 1.

@pytest.mark.parametrize("mode", ["car", "transit"])
def test_st_john_never_gets_a_road_travel_time(client, mode):
    d = _ok(client, origin=HK_ORIGIN, mode=mode)
    row = next(r for r in d["all_hospitals"] if r["hospital"] == ST_JOHN)

    assert row["travel_minutes"] is None, (
        f"St John was given a {row['travel_minutes']} min {mode} journey to a "
        "car-free island"
    )
    assert row["travel_basis"] == "not_road_reachable"
    assert row["total_minutes"] is None, (
        "St John carries a total time, so it can be ranked as the fast option"
    )
    assert row["travel_assumption"], "no explanation of why there is no travel time"
    assert "ferry" in row["travel_assumption"].lower()
    assert "Cheung Chau" in row["travel_assumption"]


def test_st_john_still_reports_its_wait_and_is_not_dropped(client):
    """Refusing a travel time must not mean deleting the hospital: someone
    already on Cheung Chau needs its number."""
    d = _ok(client, origin=HK_ORIGIN, mode="car")
    row = next(r for r in d["all_hospitals"] if r["hospital"] == ST_JOHN)
    assert row["forecast_median"] is not None
    assert row["forecast_interval"]


def test_st_john_sorts_last_never_first(client):
    """Anything with no total time must not be presented as the best choice."""
    d = _ok(client, origin=HK_ORIGIN, mode="car")
    names = [r["hospital"] for r in d["all_hospitals"]]
    ranked = [r for r in d["all_hospitals"] if r["total_minutes"] is not None]
    assert names[0] != ST_JOHN
    assert names.index(ST_JOHN) >= len(ranked)


def test_querying_st_john_directly_still_refuses_the_travel_time(client):
    d = _ok(client, hospital=ST_JOHN, origin=HK_ORIGIN, mode="car")
    assert d["travel_minutes"] is None
    assert d["travel_basis"] == "not_road_reachable"
    assert d["forecast_median"] is not None


# ---------------------------------------------------------------------------
# 7. An origin outside Hong Kong is flagged
# ---------------------------------------------------------------------------
# Promise: server.HK_BBOX comment: such an origin "is not rejected ... but it
# is flagged, because every distance in the response would then be a straight
# line across territory this tool has no traffic data for."

def test_origin_outside_hong_kong_is_flagged(client):
    d = _ok(client, origin=OUTSIDE_HK, mode="car")
    assert d["origin_provided"] is True
    assert d["origin_outside_hong_kong"] is True


@pytest.mark.parametrize("lat,lon,expected", [
    (22.2830, 114.1588, False),   # Central
    (22.1, 113.80, False),        # exactly the SW corner of the bbox
    (22.65, 114.50, False),       # exactly the NE corner
    (22.05, 114.20, True),        # just south
    (22.70, 114.20, True),        # just north
    (22.30, 113.70, True),        # just west
    (22.30, 114.60, True),        # just east
    (23.1291, 113.2644, True),    # Guangzhou
    (51.5074, -0.1278, True),     # London
    (0.0, 0.0, True),             # null island
])
def test_hong_kong_bounding_box_edges(client, lat, lon, expected):
    d = _ok(client, origin={"lat": lat, "lon": lon})
    assert d["origin_outside_hong_kong"] is expected, (
        f"lat={lat} lon={lon}: expected outside={expected}"
    )


def test_an_origin_inside_hong_kong_is_not_flagged(client):
    d = _ok(client, origin=HK_ORIGIN)
    assert d["origin_outside_hong_kong"] is False
    assert d["origin_provided"] is True
    assert d["travel_minutes"] is not None


# ---------------------------------------------------------------------------
# 8. Cross-cutting: the response shape the frontend reads
# ---------------------------------------------------------------------------

REQUIRED_TOP_LEVEL = [
    "hospital", "triage", "hour_label",
    "forecast_median", "forecast_p25", "forecast_p75", "forecast_interval",
    "published_minutes", "delta_minutes", "delta_direction",
    "verdict", "pooled", "basis", "n_observations", "tail",
    "mode", "origin_provided", "origin_outside_hong_kong",
    "travel_minutes", "travel_basis", "travel_is_estimate", "travel_assumption",
    "total_minutes", "traffic_live", "traffic_feed_live",
    "alternatives", "all_hospitals",
]

REQUIRED_ROW_FIELDS = [
    "hospital", "lat", "lon", "distance_km",
    "travel_minutes", "travel_basis", "travel_is_estimate", "travel_assumption",
    "forecast_median", "forecast_p25", "forecast_p75", "forecast_interval",
    "forecast_basis", "verdict", "pooled", "n_observations",
    "published_minutes", "delta_minutes", "total_minutes", "reason",
    "tail", "tail_p95_median",
    # legacy names the shipped frontend still reads
    "published", "n", "distance_from_origin_km", "distance_from_query_hospital_km",
]


def test_every_documented_field_is_present(client):
    d = _ok(client, origin=HK_ORIGIN)
    missing = [k for k in REQUIRED_TOP_LEVEL if k not in d]
    assert not missing, f"response is missing {missing}"
    for row in d["all_hospitals"]:
        row_missing = [k for k in REQUIRED_ROW_FIELDS if k not in row]
        assert not row_missing, f"{row['hospital']} row missing {row_missing}"


def test_legacy_row_aliases_still_mirror_their_sources(client):
    d = _ok(client, origin=HK_ORIGIN)
    for row in d["all_hospitals"]:
        assert row["published"] == row["published_minutes"], row["hospital"]
        assert row["n"] == row["n_observations"], row["hospital"]
        assert row["distance_from_origin_km"] == row["distance_km"], row["hospital"]


def test_hospitals_endpoint_lists_all_eighteen(client):
    r = client.get("/api/hospitals")
    assert r.status_code == 200
    data = r.get_json()
    assert len(data) == 18
    assert ST_JOHN in {h["name"] for h in data}
    for h in data:
        assert 22.0 < h["lat"] < 22.7, h
        assert 113.8 < h["lon"] < 114.6, h


def test_corpus_stats_reports_the_corpus_it_is_actually_using(client):
    from tests._support import current_fingerprint
    r = client.get("/api/corpus-stats")
    assert r.status_code == 200
    d = r.get_json()
    fp = current_fingerprint()
    assert d["dates"] == fp["dates"]
    assert d["snapshots"] == fp["snapshots"]
    assert d["hospitals"] == fp["hospitals"]


def test_alternatives_never_recommend_the_queried_hospital(client):
    d = _ok(client)
    for alt in d["alternatives"]:
        assert alt["hospital"] != QMH
        assert alt["forecast_interval"]
        assert alt["forecast_median"] < d["forecast_median"], (
            "an 'alternative' with a worse forecast than the hospital you asked "
            "about is not an alternative"
        )


def test_the_same_request_twice_gives_the_same_answer(client, live_feed):
    live_feed({QMH: {"t3": 55.0}})
    a = _ok(client, origin=HK_ORIGIN)
    b = _ok(client, origin=HK_ORIGIN)
    for k in ("forecast_median", "forecast_p25", "forecast_p75", "basis",
              "pooled", "n_observations", "verdict", "published_minutes",
              "travel_minutes", "total_minutes"):
        assert a[k] == b[k], f"{k} changed between two identical requests"


def test_transit_mode_does_not_claim_live_traffic(client):
    """WORKFLOW.md manual check: transit must read 'traffic not used'."""
    d = _ok(client, origin=HK_ORIGIN, mode="transit")
    assert d["mode"] == "transit"
    assert d["traffic_live"] is False
    assert d["travel_basis"] == "transit_model"
    assert d["travel_is_estimate"] is True


# ---------------------------------------------------------------------------
# 9. The p95 tail
# ---------------------------------------------------------------------------
# Promise: HA's Data Specification defines t3p95/t45p95 as "Majority of the
# waiting patients can receive consultation within this time", published for
# the same instant as the p50. The engine bucketed that series from the start
# and read it nowhere, so the product showed only the middle of the
# distribution and never its tail. `tail` exposes it, and must refuse rather
# than guess, never scale the p50, and never claim a finer hour-resolution
# than the median it is printed beside.
# Spec: https://www.ha.org.hk/opendata/Data-Specification-for-A&E-Waiting-Time-en.pdf

TAIL_FIELDS = ["p95_median", "p95_p25", "p95_p75",
               "n_observations", "basis", "available", "reason"]

LADDER = ["exact_hour", "hour_window", "all_hours"]   # finest first


def _no_p95(hospitals):
    """A bucket set with every p95 series for `hospitals` deleted.

    The p50 buckets are untouched, so the forecast still answers and the tail
    is the only thing with nothing behind it, which is exactly the state the
    'refuse rather than guess' rule exists for. Real values throughout, and the
    only synthetic element is the absence.
    """
    from tests import _support

    def _build():
        return {
            k: v for k, v in _support.build_buckets_once().items()
            if not (k[0] in hospitals and k[2] == "p95")
        }
    return _build


@pytest.mark.parametrize("day,hour,triage", [
    ("Monday", 14, "t3"),
    ("Tuesday", 14, "t45"),
    ("Sunday", 3, "t3"),
    ("Friday", 20, "t45"),
])
def test_tail_is_present_and_well_formed(client, day, hour, triage):
    d = _ok(client, day=day, hour=hour, triage=triage)
    t = d["tail"]
    assert isinstance(t, dict)
    missing = [k for k in TAIL_FIELDS if k not in t]
    assert not missing, f"tail is missing {missing}"
    assert isinstance(t["available"], bool)

    if not t["available"]:
        for k in ("p95_median", "p95_p25", "p95_p75", "basis"):
            assert t[k] is None, f"tail unavailable but {k} carries {t[k]!r}"
        assert t["reason"], "tail refused with no reason the UI can show"
        return

    assert t["p95_median"] is not None
    assert t["p95_p25"] <= t["p95_median"] <= t["p95_p75"], (
        f"tail interval out of order: {t['p95_p25']} / {t['p95_median']} "
        f"/ {t['p95_p75']}"
    )
    assert t["n_observations"] >= 5, (
        "tail quoted from fewer observations than the engine's own floor"
    )
    assert t["basis"] in LADDER, t["basis"]


@pytest.mark.parametrize("day,hour,triage", [
    ("Monday", 14, "t3"),
    ("Tuesday", 14, "t45"),
    ("Sunday", 3, "t3"),
    ("Wednesday", 0, "t45"),
])
def test_tail_basis_is_never_finer_than_the_forecast_basis(client, day, hour, triage):
    """A tail quoted at 'this exact hour' next to a median pooled across the
    whole week would let the page claim a precision it does not have."""
    d = _ok(client, day=day, hour=hour, triage=triage)
    t = d["tail"]
    if not t["available"]:
        return
    assert LADDER.index(t["basis"]) >= LADDER.index(d["basis"]), (
        f"tail basis {t['basis']!r} is finer than forecast basis {d['basis']!r}"
    )


@pytest.mark.parametrize("day,hour,triage", [
    ("Monday", 14, "t3"),
    ("Tuesday", 14, "t45"),
    ("Saturday", 23, "t45"),
    ("Thursday", 7, "t3"),
])
def test_the_tail_is_never_below_the_median(client, day, hour, triage):
    """p95 is 'majority seen within', p50 is 'half seen within', published for
    the same instant, so the tail must sit at or above the median. Measured
    across all 6,048 hospital x {t3,t45} x hour-of-week combinations in the
    current corpus, this holds 6,048 / 6,048 times with zero exceptions. A
    failure here is a real finding about the feed, not a rounding artefact."""
    d = _ok(client, day=day, hour=hour, triage=triage)
    if d["tail"]["available"]:
        assert d["tail"]["p95_median"] >= d["forecast_median"], (
            f"{d['hospital']} {triage} {day} {hour}: p95 median "
            f"{d['tail']['p95_median']} is BELOW p50 median "
            f"{d['forecast_median']}"
        )
    for row in d["all_hospitals"]:
        if row["tail_p95_median"] is None or row["forecast_median"] is None:
            continue
        assert row["tail_p95_median"] >= row["forecast_median"], (
            f"{row['hospital']}: p95 median {row['tail_p95_median']} is BELOW "
            f"p50 median {row['forecast_median']}"
        )


def test_every_row_that_has_a_forecast_also_carries_a_tail(client):
    d = _ok(client)
    rows = d["all_hospitals"]
    assert len(rows) == 18
    with_tail = 0
    for row in rows:
        assert "tail_p95_median" in row, row["hospital"]
        assert isinstance(row["tail"], dict), row["hospital"]
        if row["forecast_median"] is None:
            assert row["tail_p95_median"] is None, (
                f"{row['hospital']} has a tail with no median to be the tail of"
            )
            assert row["tail"]["available"] is False, row["hospital"]
            continue
        if row["tail_p95_median"] is not None:
            with_tail += 1
    assert with_tail >= 15, (
        f"only {with_tail}/18 rows carry a tail: the column would be hollow"
    )


# The row-level tail exists because App.jsx drives the answer card from a ROW
# (`normalised.ranked[0]`), not from the top level. A tail read from the top
# level and rendered onto a row would attach one department's long wait to
# another department's name. And it is a full object rather than a bare median
# because of the project's hard invariant that no unqualified wait number may
# appear on the page: a median needs its interval, basis and observation count
# travelling with it.

@pytest.mark.parametrize("day,hour,triage", [
    ("Monday", 14, "t3"),
    ("Tuesday", 14, "t45"),
    ("Sunday", 3, "t3"),
    ("Friday", 20, "t45"),
    ("Wednesday", 0, "t45"),
])
def test_every_row_tail_is_a_complete_well_formed_object(client, day, hour, triage):
    d = _ok(client, day=day, hour=hour, triage=triage)
    for row in d["all_hospitals"]:
        t = row["tail"]
        who = row["hospital"]
        assert isinstance(t, dict), who
        missing = [k for k in TAIL_FIELDS if k not in t]
        assert not missing, f"{who}: row tail is missing {missing}"
        assert isinstance(t["available"], bool), who

        if not t["available"]:
            for k in ("p95_median", "p95_p25", "p95_p75", "basis"):
                assert t[k] is None, f"{who}: unavailable but {k} is {t[k]!r}"
            assert t["reason"], f"{who}: row tail refused with no reason"
            continue

        assert t["p95_p25"] <= t["p95_median"] <= t["p95_p75"], (
            f"{who}: row tail interval out of order: {t['p95_p25']} / "
            f"{t['p95_median']} / {t['p95_p75']}"
        )
        assert t["n_observations"] >= 5, who
        assert t["basis"] in LADDER, f"{who}: {t['basis']!r}"


# routing reports the row's p50 resolution in its own vocabulary, and the tail
# ladder uses the engine's. This is the mapping between them.
ROW_BASIS_TO_LADDER = {
    "hour_bucket": "exact_hour",
    "hour_window": "hour_window",
    "pooled_all_hours": "all_hours",
}


@pytest.mark.parametrize("day,hour,triage", [
    ("Monday", 14, "t3"),
    ("Tuesday", 14, "t45"),
    ("Sunday", 3, "t3"),
    ("Saturday", 23, "t45"),
])
def test_every_row_tail_basis_is_never_finer_than_that_rows_own_basis(
    client, day, hour, triage
):
    d = _ok(client, day=day, hour=hour, triage=triage)
    for row in d["all_hospitals"]:
        t = row["tail"]
        if not t["available"]:
            continue
        own = ROW_BASIS_TO_LADDER.get(row["forecast_basis"])
        assert own is not None, (
            f"{row['hospital']}: tail present but forecast_basis is "
            f"{row['forecast_basis']!r}"
        )
        assert LADDER.index(t["basis"]) >= LADDER.index(own), (
            f"{row['hospital']}: row tail basis {t['basis']!r} is finer than "
            f"the row's own forecast_basis {row['forecast_basis']!r}"
        )


def test_a_row_whose_p50_is_coarse_gets_a_coarse_tail_too(client, monkeypatch):
    """Guards against the previous assertion being inert. On this corpus every
    row resolves to exact_hour, so `basis >= own basis` is trivially true.
    Thin ONE hospital's p50 exact-hour bucket and its p50 drops to the ±1-hour
    window: its tail must drop with it, even though its own p95 bucket is
    still dense enough for exact_hour."""
    import routing
    from engine import HourBucket
    from tests import _support

    how = DAYS.index("Monday") * 24 + 14

    def _build():
        src = _support.build_buckets_once()
        out = dict(src)
        key = (QMH, "t3", "p50", how)
        kept = list(src[key].values[:2])
        out[key] = HourBucket(hospital=QMH, triage="t3", percentile="p50",
                              hour_of_week=how, values=kept, n=len(kept))
        return out

    monkeypatch.setattr(routing, "_buckets", _build)

    d = _ok(client)
    row = next(r for r in d["all_hospitals"] if r["hospital"] == QMH)

    assert row["forecast_basis"] == "hour_window", (
        f"the p50 did not actually get coarser: {row['forecast_basis']!r}, "
        "this test is not exercising what it claims to"
    )
    assert row["tail"]["available"] is True
    assert row["tail"]["basis"] == "hour_window", (
        f"row p50 fell back to the ±1-hour window but its tail still claims "
        f"{row['tail']['basis']!r}"
    )

    # An untouched hospital keeps the fine rung, so the coarsening is local.
    other = next(r for r in d["all_hospitals"]
                 if r["hospital"] != QMH and r["tail"]["available"])
    assert other["tail"]["basis"] == "exact_hour"


@pytest.mark.parametrize("day,hour,triage", [
    ("Monday", 14, "t3"),
    ("Tuesday", 14, "t45"),
    ("Thursday", 7, "t3"),
])
def test_row_tail_median_and_the_scalar_alias_never_diverge(client, day, hour, triage):
    """`tail_p95_median` is kept for whatever already reads it. It must stay a
    pure alias, or the page can show two different tails for one row."""
    d = _ok(client, day=day, hour=hour, triage=triage)
    for row in d["all_hospitals"]:
        assert row["tail_p95_median"] == row["tail"]["p95_median"], (
            f"{row['hospital']}: tail_p95_median {row['tail_p95_median']} != "
            f"tail.p95_median {row['tail']['p95_median']}"
        )


@pytest.mark.parametrize("hospital,day,hour,triage", [
    (QMH, "Monday", 14, "t3"),
    ("Queen Elizabeth Hospital", "Tuesday", 14, "t45"),
    (ST_JOHN, "Sunday", 3, "t3"),
    ("Tuen Mun Hospital", "Friday", 20, "t45"),
])
def test_the_queried_hospitals_row_tail_equals_the_top_level_tail(
    client, hospital, day, hour, triage
):
    """The invariant that stops the headline and the table disagreeing. The
    server takes the same dict rather than recomputing, so this is structural,
    but it is asserted because the wiring is what a refactor would break."""
    d = _ok(client, hospital=hospital, day=day, hour=hour, triage=triage)
    row = next(r for r in d["all_hospitals"] if r["hospital"] == hospital)
    assert row["tail"] == d["tail"], (
        f"{hospital}: row tail {row['tail']} != top-level tail {d['tail']}"
    )
    assert row["tail_p95_median"] == d["tail"]["p95_median"]


def test_a_missing_p95_series_refuses_instead_of_scaling_the_p50(client, monkeypatch):
    """The whole point of the field. With no p95 data the answer is 'we don't
    know', not the p50 multiplied by something plausible."""
    import routing
    monkeypatch.setattr(routing, "_buckets", _no_p95({QMH}))

    d = _ok(client)
    t = d["tail"]
    assert t["available"] is False
    assert t["p95_median"] is None
    assert t["p95_p25"] is None
    assert t["p95_p75"] is None
    assert t["basis"] is None
    assert t["reason"], "refused with no reason"

    row = next(r for r in d["all_hospitals"] if r["hospital"] == QMH)
    assert row["tail_p95_median"] is None
    # The row object refuses in exactly the same shape, so the UI has one code
    # path and one place to read the reason from.
    assert row["tail"] == d["tail"]
    assert row["tail"]["available"] is False
    assert row["tail"]["p95_median"] is None
    assert row["tail"]["p95_p25"] is None
    assert row["tail"]["p95_p75"] is None
    assert row["tail"]["basis"] is None
    assert row["tail"]["reason"]
    # ...and the p50 forecast is untouched by the tail's absence.
    assert d["forecast_median"] is not None
    assert row["forecast_median"] is not None

    # Other hospitals still have theirs: the refusal is local, not global.
    other = next(r for r in d["all_hospitals"]
                 if r["hospital"] != QMH and r["forecast_median"] is not None)
    assert other["tail_p95_median"] is not None
    assert other["tail"]["available"] is True


def test_tail_does_not_disturb_any_existing_field(client, live_feed, monkeypatch):
    """The tail is additive. Every previously-locked field must be identical
    with the p95 series present and with it deleted."""
    import routing
    live_feed({QMH: {"t3": 55.0}})

    before = _ok(client)
    monkeypatch.setattr(routing, "_buckets", _no_p95({QMH}))
    after = _ok(client)

    for k in ("forecast_median", "forecast_p25", "forecast_p75",
              "forecast_interval", "basis", "pooled", "n_observations",
              "verdict", "published_minutes", "delta_minutes",
              "delta_direction", "total_minutes"):
        assert before[k] == after[k], f"deleting the p95 series moved {k}"


# --- score_tail directly, where the thin rungs are reachable ---------------
# Through the API every combination resolves to exact_hour (measured: 6,048 of
# 6,048), so the window and pooled rungs of the tail ladder can only be
# exercised by thinning buckets, exactly as golden_matrix.THIN_CASES does for
# the p50.

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday",
        "Friday", "Saturday", "Sunday"]


def _thin_p95(buckets, hospital, triage, hours, keep):
    from engine import HourBucket
    out = dict(buckets)
    for h in hours:
        key = (hospital, triage, "p95", h)
        src = out.get(key)
        if src is None:
            continue
        kept = list(src.values[:keep])
        out[key] = HourBucket(hospital=hospital, triage=triage,
                              percentile="p95", hour_of_week=h,
                              values=kept, n=len(kept))
    return out


def test_score_tail_walks_the_same_ladder_as_the_forecast(buckets):
    import engine

    how = DAYS.index("Monday") * 24 + 14
    hosp, triage = QMH, "t3"

    exact = engine.score_tail(hosp, triage, how, buckets)
    assert exact.available and exact.basis == "exact_hour"

    thinned = _thin_p95(buckets, hosp, triage, [how], keep=2)
    window = engine.score_tail(hosp, triage, how, thinned)
    assert window.available and window.basis == "hour_window", window

    thinned = _thin_p95(buckets, hosp, triage,
                        [(how - 1) % 168, how, (how + 1) % 168], keep=1)
    pooled = engine.score_tail(hosp, triage, how, thinned)
    assert pooled.available and pooled.basis == "all_hours", pooled

    thinned = _thin_p95(buckets, hosp, triage, list(range(168)), keep=0)
    gone = engine.score_tail(hosp, triage, how, thinned)
    assert gone.available is False
    assert gone.p95_median is None and gone.basis is None
    assert gone.reason


@pytest.mark.parametrize("floor,expected", [
    ("exact_hour", "exact_hour"),
    ("hour_window", "hour_window"),
    ("all_hours", "all_hours"),
])
def test_score_tail_never_starts_above_the_floor_it_is_given(buckets, floor, expected):
    """floor_basis is the p50's actual basis. Even where the p95 series is dense
    enough for a finer rung, the tail must not use it."""
    import engine

    how = DAYS.index("Monday") * 24 + 14
    t = engine.score_tail(QMH, "t3", how, buckets, floor_basis=floor)
    assert t.available
    assert t.basis == expected, (
        f"floor_basis={floor!r} produced basis={t.basis!r}"
    )


def test_score_tail_reports_the_rung_it_really_used_not_the_floor(buckets):
    """`basis` is reported independently: given a fine floor but a thin series,
    it names the coarser rung that actually answered."""
    import engine

    how = DAYS.index("Monday") * 24 + 14
    thinned = _thin_p95(buckets, QMH, "t3", [how], keep=2)
    t = engine.score_tail(QMH, "t3", how, thinned, floor_basis="exact_hour")
    assert t.basis == "hour_window", (
        "claimed exact_hour while answering from the ±1-hour window"
    )


def test_score_tail_reads_p95_and_never_p50(buckets):
    """Deleting only the p95 series must make the tail refuse: proof it is not
    quietly reading, or scaling, the p50 buckets."""
    import engine

    how = DAYS.index("Tuesday") * 24 + 14
    stripped = {k: v for k, v in buckets.items()
                if not (k[0] == "Queen Elizabeth Hospital" and k[2] == "p95")}
    t = engine.score_tail("Queen Elizabeth Hospital", "t45", how, stripped)
    assert t.available is False
    # The p50 for the same cell is still perfectly answerable.
    s = engine.score_reliability("Queen Elizabeth Hospital", "t45", how,
                                 None, stripped)
    assert s is not None and s.forecast_median is not None
