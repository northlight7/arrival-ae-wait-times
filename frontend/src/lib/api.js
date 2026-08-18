import { num, isNum } from './format.js'
import { accessNote, haversineKm } from './hospitals.js'
import { notComparableReason } from './verdict.js'

/**
 * Every field below is optional on the wire. The routing half of the contract
 * (mode / travel_* / total_minutes / traffic_live) is being added server-side
 * while this client ships, so nothing here may assume a field exists. Missing
 * means null, and null means the UI says so rather than printing "NaN".
 */

async function getJSON(url, signal) {
  const r = await fetch(url, { signal, headers: { Accept: 'application/json' } })
  const ct = r.headers.get('content-type') || ''
  if (!r.ok || !ct.includes('application/json')) {
    throw new Error(`${url} returned ${r.status}`)
  }
  return r.json()
}

export async function fetchHospitals(signal) {
  const d = await getJSON('/api/hospitals', signal)
  return Array.isArray(d)
    ? d
        .filter((h) => h && typeof h.name === 'string')
        .map((h) => ({ name: h.name, lat: num(h.lat), lon: num(h.lon) }))
    : []
}

export async function fetchCorpusStats(signal) {
  const d = await getJSON('/api/corpus-stats', signal)
  return {
    dates: num(d?.dates),
    snapshots: num(d?.snapshots),
    hospitals: num(d?.hospitals),
    observations: num(d?.observations),
  }
}

/** Optional endpoint. Absent for now; resolves to null instead of throwing. */
export async function fetchTrafficStatus(signal) {
  try {
    const d = await getJSON('/api/traffic-status', signal)
    if (!d || typeof d !== 'object') return null
    return {
      live: d.live === true,
      detectorsUsed: num(d.detectors_used),
      observedAt: typeof d.observed_at === 'string' ? d.observed_at : null,
      avgSpeed: num(d.territory_avg_speed),
      message: typeof d.message === 'string' ? d.message : null,
    }
  } catch {
    return null
  }
}

export class SparseDataError extends Error {
  constructor(message, hospital) {
    super(message)
    this.name = 'SparseDataError'
    this.hospital = hospital || null
  }
}

export class ApiError extends Error {}

/** POST /api/query, then normalise. Throws SparseDataError on 503. */
export async function runQuery(body, signal) {
  let r
  try {
    r = await fetch('/api/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    })
  } catch (e) {
    if (e?.name === 'AbortError') throw e
    throw new ApiError('Cannot reach the forecast service.')
  }

  let data = null
  try {
    data = await r.json()
  } catch {
    data = null
  }

  if (r.status === 503) {
    throw new SparseDataError(
      data?.error || 'There is not enough data to answer this honestly.',
      data?.hospital || body.hospital,
    )
  }
  if (!r.ok) throw new ApiError(data?.error || `The service returned ${r.status}.`)
  if (!data || typeof data !== 'object') throw new ApiError('The service returned an unreadable response.')
  return data
}

/** One hospital row, whatever shape the server sent it in. */
/** The p95 series, in the one shape the UI reads. Server guarantees the object
    is always present on a row, so a missing one means a genuinely old payload. */
function readTail(t) {
  if (!t || typeof t !== 'object') return null
  return {
    available: t.available === true,
    p25: num(t.p95_p25),
    median: num(t.p95_median),
    p75: num(t.p95_p75),
    basis: typeof t.basis === 'string' ? t.basis : null,
    n: num(t.n_observations),
    reason: typeof t.reason === 'string' ? t.reason : null,
  }
}

/**
 * May the page compare today's published figure against this hour's normal?
 *
 * ---------------------------------------------------------------------------
 * WHY THIS EXISTS: do not "simplify" it back into `isNum(published)`
 * ---------------------------------------------------------------------------
 * The Hospital Authority publishes exactly ONE figure per department: an
 * estimate for someone arriving NOW. It publishes nothing for Sunday 03:00.
 * The server used to fetch today's board whatever hour was asked for and score
 * it against that hour's history, so one reading produced a different "verdict"
 * for every hour of the week, an artefact rendered as fact, under a green tick
 * reading "PUBLISHED NOW".
 *
 * The server now refuses instead: for any hour that is not the current Hong
 * Kong hour, `published_minutes` and `delta_minutes` are null everywhere,
 * `verdict` is `not_comparable`, and `published_comparison` carries the
 * sentence explaining the refusal. That sentence is the server's to write and
 * is rendered VERBATIM. `notComparableReason` here is only the fallback for a
 * payload that predates the field.
 *
 * Tolerance rule, per the round-3 contract: a response with no
 * `published_comparison` at all is treated as comparable only if it actually
 * carries a published figure.
 */
function readComparison(raw) {
  const label =
    (typeof raw?.hour_label === 'string' && raw.hour_label) || 'the hour you picked'
  const pc = raw?.published_comparison

  if (pc && typeof pc === 'object') {
    if (pc.available === true) return { available: true, reason: null }
    const reason = typeof pc.reason === 'string' && pc.reason.trim() ? pc.reason.trim() : null
    return { available: false, reason: reason || notComparableReason(label) }
  }

  // Old payload: no contract field. Comparable only if there is a real figure.
  if (isNum(num(raw?.published_minutes))) return { available: true, reason: null }
  return { available: false, reason: notComparableReason(label) }
}

function normaliseRow(r, coordsByName, originCoords) {
  if (!r || typeof r.hospital !== 'string') return null

  const p25 = num(r.forecast_p25)
  const p75 = num(r.forecast_p75)
  const median = num(r.forecast_median)
  const published = num(r.published_minutes ?? r.published)
  const explicitDelta = num(r.delta_minutes)
  const coord = coordsByName?.get(r.hospital) || null
  const lat = num(r.lat) ?? coord?.lat ?? null
  const lon = num(r.lon) ?? coord?.lon ?? null

  const travel = num(r.travel_minutes)
  const totalFromApi = num(r.total_minutes)
  const total =
    totalFromApi ?? (isNum(travel) && isNum(median) ? travel + median : null)

  let distanceKm = num(r.distance_km)
  if (distanceKm === null && originCoords && isNum(lat) && isNum(lon)) {
    distanceKm = haversineKm(originCoords, { lat, lon })
  }

  return {
    hospital: r.hospital,
    lat,
    lon,
    distanceKm,
    p25,
    p75,
    median,
    // interval string is derived client-side so the format is consistent;
    // the server's own string is kept only as a fallback.
    apiInterval: typeof r.forecast_interval === 'string' ? r.forecast_interval : null,
    published,
    delta: explicitDelta ?? (isNum(published) && isNum(median) ? published - median : null),
    // Minutes outside THIS department's own p25–p75 band. 0 when the published
    // figure sits inside it, null when no comparison exists. The single number
    // every "is today normal?" string on the page is derived from. It is the
    // server's own quantity. Nothing here recomputes it from p25/p75, because
    // a second, independently-computed version of it is precisely what let the
    // badge, the prose and the chart annotation disagree.
    excess: num(r.excess_minutes),
    verdict: typeof r.verdict === 'string' ? r.verdict : null,
    basis: typeof (r.basis ?? r.forecast_basis) === 'string' ? (r.basis ?? r.forecast_basis) : null,
    pooled: typeof r.pooled === 'boolean' ? r.pooled : null,
    n: num(r.n_observations ?? r.n),
    travel,
    travelBasis: typeof r.travel_basis === 'string' ? r.travel_basis : null,
    travelAssumption: typeof r.travel_assumption === 'string' ? r.travel_assumption : null,
    // The server's refusal when it has one. Otherwise the standing access fact
    // for this hospital. Without the fallback the ferry-only warning on St John
    // disappeared entirely whenever no starting point was given, which is the
    // one case where St John rises up the ranking on queue length alone.
    travelReason:
      (typeof r.reason === 'string' && r.reason ? r.reason : null)
      ?? accessNote(r.hospital),
    travelIsEstimate: typeof r.travel_is_estimate === 'boolean' ? r.travel_is_estimate : null,
    total,
    // Per row, so the long-wait figure can never be attached to a department it
    // does not describe. The card shows the top-RANKED row, not the queried one.
    tail: readTail(r.tail),
    // A row is only usable in a chart if it can produce a real interval.
    usable: isNum(p25) && isNum(p75),
  }
}

/**
 * Fold the API response into the single shape the UI renders from.
 * `hospitals` is the /api/hospitals list, used to backfill coordinates.
 */
export function normaliseResult(raw, { hospitals = [], origin = null } = {}) {
  const coordsByName = new Map(
    hospitals.filter((h) => isNum(h.lat) && isNum(h.lon)).map((h) => [h.name, h]),
  )

  const comparison = readComparison(raw)

  const primary = normaliseRow(
    {
      hospital: raw.hospital,
      forecast_p25: raw.forecast_p25,
      forecast_p75: raw.forecast_p75,
      forecast_median: raw.forecast_median,
      forecast_interval: raw.forecast_interval,
      published_minutes: raw.published_minutes,
      delta_minutes: raw.delta_minutes,
      excess_minutes: raw.excess_minutes,
      verdict: raw.verdict,
      basis: raw.basis,
      pooled: raw.pooled,
      n_observations: raw.n_observations,
      travel_minutes: raw.travel_minutes,
      travel_basis: raw.travel_basis,
      travel_assumption: raw.travel_assumption,
      reason: raw.reason,
      travel_is_estimate: raw.travel_is_estimate,
      total_minutes: raw.total_minutes,
      distance_km: 0,
      tail: raw.tail,
    },
    coordsByName,
    origin,
  )

  const rows = []
  const seen = new Set()
  if (primary) {
    // When an origin is given the primary hospital has a real distance too.
    if (origin && isNum(primary.lat) && isNum(primary.lon)) {
      primary.distanceKm = haversineKm(origin, { lat: primary.lat, lon: primary.lon })
    } else {
      primary.distanceKm = 0
    }
    rows.push(primary)
    seen.add(primary.hospital)
  }
  if (Array.isArray(raw.all_hospitals)) {
    for (const r of raw.all_hospitals) {
      const row = normaliseRow(r, coordsByName, origin)
      if (row && !seen.has(row.hospital)) {
        rows.push(row)
        seen.add(row.hospital)
      }
    }
  }

  // Belt and braces. The server already nulls these for a non-now hour, but a
  // single stale figure leaking through would be drawn as a marker on the hero
  // strip and read as today's board for an hour nobody published one for. One
  // gate, applied once, so no component has to remember the rule.
  if (!comparison.available) {
    for (const r of rows) {
      r.published = null
      r.delta = null
      r.excess = null
      if (r.verdict !== 'no_live_data') r.verdict = 'not_comparable'
    }
  }

  const usable = rows.filter((r) => r.usable)
  const hasTravel = usable.some((r) => isNum(r.travel))
  const hasDistance = usable.some((r) => isNum(r.distanceKm))

  // Ranking statistic: travel plus the TOP of the likely wait range.
  //
  // Ranking on the median (what total_minutes carries) makes the printed
  // intervals run out of order on screen, because a hospital with a lower
  // median can still have a longer tail. Ranking on the upper end keeps what
  // the reader sees and what the list claims in agreement, and it is the right
  // decision rule anyway: in an emergency you plan for the slow case.
  //
  // A hospital the routing service will not cost (Cheung Chau is ferry-only)
  // is NOT treated as zero travel. That would hand it first place. It is
  // incomparable, and is listed apart with the reason.
  for (const r of usable) r.comparable = !hasTravel || isNum(r.travel)
  const comparable = usable.filter((r) => r.comparable)
  const unrankable = usable.filter((r) => !r.comparable)
  const rankKey = (r) =>
    (isNum(r.travel) ? r.travel : 0) + (isNum(r.p75) ? r.p75 : Number.POSITIVE_INFINITY)
  const ranked = [
    ...comparable.sort((a, b) => rankKey(a) - rankKey(b)),
    ...unrankable,
  ]

  return {
    hospital: typeof raw.hospital === 'string' ? raw.hospital : null,
    triage: raw.triage === 't45' ? 't45' : 't3',
    hourLabel: typeof raw.hour_label === 'string' ? raw.hour_label : null,
    verdict: comparison.available
      ? (typeof raw.verdict === 'string' ? raw.verdict : null)
      : (raw.verdict === 'no_live_data' ? 'no_live_data' : 'not_comparable'),
    // Whether a published-vs-normal comparison is allowed at all, and the
    // server's sentence saying why not. Read by every component that would
    // otherwise draw a board figure, a gap or a vs-normal badge.
    comparison,
    arrivalIsNow: raw.arrival_is_now === true,
    nowDay: typeof raw.now_day === 'string' ? raw.now_day : null,
    nowHour: isNum(num(raw.now_hour)) ? num(raw.now_hour) : null,
    basis: typeof raw.basis === 'string' ? raw.basis : null,
    pooled: raw.pooled === true,
    primary,
    rows,
    ranked,
    comparable: hasTravel ? comparable : ranked,
    unrankable: hasTravel ? unrankable : [],
    hasTravel,
    hasDistance,
    rankedBy: hasTravel ? 'total' : 'wait',
    mode: raw.mode === 'transit' || raw.mode === 'car' ? raw.mode : null,
    originProvided: raw.origin_provided === true,
    // The 95th-percentile series HA publishes alongside the median. Passed
    // through as-is, including its refusal reason, because the page has to be
    // able to say WHY there is no tail rather than just omitting it.
    tail: readTail(raw.tail),
    trafficLive: typeof raw.traffic_live === 'boolean' ? raw.traffic_live : null,
    travelAssumption:
      typeof raw.travel_assumption === 'string' ? raw.travel_assumption : null,
  }
}
