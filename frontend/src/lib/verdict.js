import { fmtGap, fmtMinutes, isNum, rangeText } from './format.js'

/**
 * The product's argument, in copy.
 *
 * ---------------------------------------------------------------------------
 * READ THIS BEFORE CHANGING ANY STRING IN THIS FILE
 * ---------------------------------------------------------------------------
 * An earlier version of this module said the Hospital Authority "publishes the
 * wait already endured by patients who have just been seen, a rear-view
 * mirror". That was false, and it was the load-bearing claim of the whole page.
 *
 * The HA's own Data Specification for the feed we consume
 * (aedwtdata2-en.json) defines the fields the other way round:
 *
 *   t3p50: "Estimated A&E waiting time for triage category III (Urgent)
 *            cases. Half of the waiting patients can receive consultation
 *            within this time."
 *            Remark: "Estimated waiting time UPON ARRIVAL at the A&E
 *            department in minutes"
 *
 *   t3p95: "...Majority of the waiting patients can receive consultation
 *            within this time."  Remark: same, upon arrival.
 *
 * https://www.ha.org.hk/opendata/Data-Specification-for-A&E-Waiting-Time-en.pdf
 *
 * So the board is already a forward-looking estimate for the person walking in.
 * The "rear-view" framing belonged to HA's older top-wait feed and was carried
 * over by mistake.
 *
 * That kills the old claim, and it kills the old vocabulary with it. We have no
 * ground truth on what any patient actually waited, so we CANNOT measure how
 * wrong the board is, and nothing here may say we can. What we can measure,
 * because we have sampled the board every 15 minutes for 290 days, is how
 * today's estimate compares with what this same department has published at
 * this same hour across the record.
 *
 * So the gap means "today is unusual for this hour", NOT "the board is wrong".
 * Keep every string in this file on the right side of that line.
 *
 * The backend still names its verdict values `reliable` / `caution` /
 * `misleading`. Those names encode the old, wrong idea. They are mapped to
 * honest language here rather than renamed across the API in the same change.
 */

/** What the board actually is. One short sentence, used to attribute. */
export const BOARD_IS =
  "That is the Hospital Authority's estimate for someone arriving now, not a record of real waits."

/**
 * The refusal text used when the client has to build it itself.
 *
 * The server owns this sentence (`published_comparison.reason`) and whatever it
 * sends is rendered verbatim. This is only the fallback for a payload that
 * predates the field. See `readComparison` in lib/api.js.
 */
export function notComparableReason(whenText) {
  const when = whenText || 'the hour you picked'
  return `The Hospital Authority publishes one figure for right now, not for ${when}. `
    + `Comparing it against another hour would invent a result, so no comparison is `
    + `shown for this time. The range below is still this department's history at ${when}.`
}

/**
 * ---------------------------------------------------------------------------
 * ONE QUANTITY DECIDES "IS TODAY NORMAL?": excess_minutes
 * ---------------------------------------------------------------------------
 * `excess` is the server's own figure: how many minutes today's published
 * figure sits OUTSIDE this department's own p25–p75 band for this hour. It is
 * 0 when the figure is inside the band, and null when there is no comparison.
 *
 * Everything on this page that says how normal today is (the badge, the
 * sentence under it, the table cell, the chart and its annotation) is built
 * from this one number, here. It used to be built from `delta` (published minus
 * the historical MEDIAN) against a flat ±15-minute rule, which ignored the very
 * band the page draws. That produced a green tick reading "well inside its
 * normal spread" thirty pixels from a red chart label reading "10 minutes above
 * the range", on the same department, in the same view. Two independently
 * computed quantities cannot be kept in agreement by care, so there is now only
 * one of them.
 *
 * delta is still shown, as "the board is N minutes above its usual median",
 * but it never decides what "normal" means, and it never sets a colour.
 *
 * THE RULE, matching the server exactly:
 *   inside the band                      -> excess 0        -> reliable
 *   within NEAR_MINUTES of the band      -> excess <= 5     -> reliable
 *   out to 1.5 x the band's own width    -> caution
 *   beyond that                          -> misleading
 * The band width has a 5-minute floor, so a department whose published figure
 * never moves is not called abnormal for being one minute off a zero-width band.
 *
 * ---------------------------------------------------------------------------
 * COLOUR RULE: read before changing a `tone` below
 * ---------------------------------------------------------------------------
 * Tone drives colour, and colour is read before words by someone scanning at
 * speed under stress. Red therefore means ONE thing on this page: this
 * department is busier than it usually is at this hour. It never means
 * "quieter". An earlier version graded on the SIZE of the gap alone, so a
 * department 40 minutes QUIETER than normal, the best news on the page, was
 * painted the same alarm red as one 40 minutes busier.
 *
 * Quieter-than-normal is neutral grey, not green: it is not a promise, only an
 * absence of alarm. And no tone is ever the only carrier of the meaning: the
 * chip label and the body text say "busier" or "quieter" in words.
 */

/**
 * How far outside its own band still counts as normal. Mirrors the server's
 * `excess <= 5 -> reliable` step. Named once so no component can pick its own.
 */
export const NEAR_MINUTES = 5

/**
 * The single reading of "how does today sit against this department's normal?".
 * Every component derives its words and its colour from this and nothing else.
 *
 * Returns:
 *   excess   minutes outside the band (>= 0), or null when unknown
 *   outside  true when excess > 0
 *   near     true when 0 < excess <= NEAR_MINUTES  ("close enough to normal")
 *   busier   true above the band, false below it, null when inside/unknown
 */
export function gapFacts({ excess, published, p25, p75, delta } = {}) {
  const e = isNum(excess) ? Math.max(0, excess) : null

  // Direction comes from which EDGE of the band the figure sits past, so it can
  // never claim "busier" about a figure below the band. The delta sign is only
  // the fallback for a payload with no band.
  let busier = null
  if (e === null || e > 0) {
    if (isNum(published) && isNum(p25) && isNum(p75)) {
      if (published > p75) busier = true
      else if (published < p25) busier = false
    }
    if (busier === null && isNum(delta) && delta !== 0) busier = delta > 0
  }

  return {
    excess: e,
    outside: e === null ? null : e > 0,
    near: e !== null && e > 0 && e <= NEAR_MINUTES,
    busier,
  }
}

/** "12 minutes above its usual range": the phrase, from the facts. */
export function excessPhrase(f) {
  if (!f || !isNum(f.excess) || f.excess <= 0) return null
  const side = f.busier === false ? 'below' : 'above'
  return `${fmtGap(f.excess)} ${side} its usual range`
}


export function readGap({
  verdict, delta, excess, published, p25, p75, whenText, reason,
}) {
  const when = whenText || 'this hour'
  // The server owns the refusal sentence. Rendered verbatim when present.
  const given = typeof reason === 'string' && reason.trim() ? reason.trim() : null

  if (verdict === 'not_comparable') {
    return {
      tone: 'neutral',
      icon: 'ban',
      chip: 'No comparison for this hour',
      title: 'There is no published-versus-normal comparison for this time',
      body: given || notComparableReason(when),
    }
  }

  if (verdict === 'no_live_data' || !isNum(published)) {
    return {
      tone: 'neutral',
      icon: 'ban',
      chip: 'No published figure',
      title: 'There is no live figure to compare against right now',
      body: given
        || 'The live feed did not answer, so there is no board figure to compare today against. The range below still stands, from the stored record of past estimates.',
    }
  }

  const f = gapFacts({ excess, published, p25, p75, delta })
  const board = fmtMinutes(published)
  const range = rangeText(p25, p75)
  const out = excessPhrase(f)
  const busier = f.busier === true

  // Inside the band, or near enough to it that the server calls today normal.
  if (verdict === 'reliable') {
    const inside = f.excess === 0
    return {
      tone: 'good',
      icon: 'check',
      chip: inside ? 'Inside its usual range' : 'Close to its usual range',
      title: 'Today looks normal for this time',
      body: inside
        ? `The board says ${board}, inside this department's usual range at ${when}${range ? ` (${range})` : ''}. ${BOARD_IS} Today, it is normal.`
        : out
          ? `The board says ${board}, ${out}${range ? ` (${range})` : ''}. Within ${NEAR_MINUTES} minutes of the range, so it counts as normal. ${BOARD_IS}`
          : `The board says ${board}, which is what this department usually publishes at ${when}. ${BOARD_IS} Today, it is normal.`,
    }
  }

  // Beyond the band by more than 1.5x its own width.
  if (verdict === 'misleading') {
    return {
      // Alarm colour only when the news is bad. See the COLOUR RULE above.
      tone: busier ? 'crit' : 'neutral',
      icon: busier ? 'alert' : 'info',
      chip: busier ? 'Far above its usual range' : 'Far below its usual range',
      title: out
        ? `Today's figure sits about ${out}`
        : `Today's figure is far from normal for this hour`,
      body: range
        ? `The board says ${board}. Its usual range at ${when} is ${range}, so today is ${out}. That is far from normal for this department, not a near miss. ${BOARD_IS} Plan for today's number, not the usual one.`
        : `The board says ${board}, far from what this department usually publishes at ${when}. It is unusually ${busier ? 'busy' : 'quiet'} for this hour. ${BOARD_IS} Plan for today's number, not the usual one.`,
    }
  }

  // caution: outside the band, but within 1.5x its own width of it.
  return {
    tone: busier ? 'warn' : 'neutral',
    icon: busier ? 'alert' : 'info',
    chip: busier ? 'Above its usual range' : 'Below its usual range',
    title: out
      ? `Today's figure sits about ${out}`
      : `Today's figure is outside its normal range for this hour`,
    body: range
      ? `The board says ${board}. Its usual range at ${when} is ${range}, so today is ${out}. It is somewhat ${busier ? 'busier' : 'quieter'} than usual.`
      : `The board says ${board}, outside what this department usually publishes at ${when}. It is somewhat ${busier ? 'busier' : 'quieter'} than usual.`,
  }
}

/**
 * Row-level chips. `misleading` no longer says the board is misleading. We
 * cannot show that. It says the department is far outside its own normal range.
 *
 * The chip takes the same `gapFacts` every other component takes, so a row's
 * chip cannot say "typical" while the cell beside it says "20 minutes above the
 * range": both read the same excess. The label carries the direction in words,
 * so the meaning survives without hue. Nothing here depends on being able to
 * tell red from grey.
 */
export function verdictChip(verdict, facts) {
  const f = facts && typeof facts === 'object' ? facts : {}
  if (verdict === 'no_live_data') return { tone: 'neutral', label: 'No feed' }
  if (verdict === 'not_comparable') return null

  if (verdict === 'reliable') {
    // Without an excess we know only the server's grade, so the chip claims only
    // that. It must never say "inside its range" on a figure we cannot place.
    if (!isNum(f.excess)) return { tone: 'good', label: 'Normal for this hour' }
    return f.near
      ? { tone: 'good', label: 'Near normal' }
      : { tone: 'good', label: 'Inside its range' }
  }

  const busier = f.busier === true
  if (verdict === 'caution') {
    return busier
      ? { tone: 'warn', label: 'Above its range' }
      : { tone: 'neutral', label: 'Below its range' }
  }
  if (verdict === 'misleading') {
    return busier
      ? { tone: 'crit', label: 'Far above its range' }
      : { tone: 'neutral', label: 'Far below its range' }
  }
  return null
}

export const TRIAGE = [
  {
    key: 't3',
    label: 'Urgent',
    sub: 'Triage 3',
    help: 'Serious, but not immediately life-threatening: chest pain that has settled, a bad fracture, heavy but controlled bleeding.',
  },
  {
    key: 't45',
    label: 'Less urgent',
    sub: 'Triage 4 / 5',
    help: 'Stable and able to wait: sprains, minor cuts, persistent but mild symptoms. Expect hours, not minutes.',
  },
]
