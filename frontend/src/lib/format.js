/**
 * Formatting rules for this product.
 *
 * RULE 1: a wait is never a single number. Every wait renders as an interval.
 * A median may appear only where the word "Median" is on screen beside it.
 * If we cannot build an interval we return null and the caller must say why.
 */

const EN_DASH = '–'

/** true only for a real, finite number. Guards every field from the API. */
export const isNum = (v) => typeof v === 'number' && Number.isFinite(v)

/** Coerce anything to a finite number or null. Never returns NaN. */
export const num = (v) => (isNum(v) ? v : null)

/** One duration, e.g. "35 min" / "1 hr 48 min". Used for travel, never for a wait. */
export function fmtMinutes(m) {
  if (!isNum(m)) return null
  if (m < 1) return '<1 min'
  const r = Math.round(m)
  if (r < 60) return `${r} min`
  const h = Math.floor(r / 60)
  const mins = r % 60
  if (mins === 0) return `${h} hr`
  return `${h} hr ${mins} min`
}

/**
 * The interval renderer. Returns { value, unit } or null.
 * Splitting the unit off lets the hero animate the digits alone.
 *
 * When both ends share the same unit (both minutes or both hours) the unit is
 * stripped from the numbers and returned separately so the digits can animate.
 * Mixed units (one end in minutes, the other in hours) keep their labels inline.
 */
export function fmtRange(lo, hi) {
  if (!isNum(lo) || !isNum(hi)) return null
  const a = Math.min(lo, hi)
  const b = Math.max(lo, hi)
  const aR = Math.round(a)
  const bR = Math.round(b)

  if (bR < 60) {
    // Both under an hour: "12 – 35 min"
    return { value: `${aR} ${EN_DASH} ${bR}`, unit: 'min' }
  }
  if (aR >= 60) {
    // Both over an hour: "1 hr 15 min – 2 hr 30 min"
    const fmt = (x) => {
      const hh = Math.floor(x / 60)
      const mm = x % 60
      return mm === 0 ? `${hh} hr` : `${hh} hr ${mm} min`
    }
    return { value: `${fmt(aR)} ${EN_DASH} ${fmt(bR)}`, unit: '' }
  }
  // Straddles the hour mark: "45 min – 1 hr 15 min"
  return { value: `${aR} min ${EN_DASH} ${fmtMinutes(bR)}`, unit: '' }
}

/** Flat string form of the same interval, for tables and tooltips. */
export function rangeText(lo, hi) {
  const r = fmtRange(lo, hi)
  if (!r) return null
  return r.unit ? `${r.value} ${r.unit}` : r.value
}

/** A "roughly N minutes" phrase for the size of the published-vs-actual gap. */
export function fmtGap(m) {
  if (!isNum(m)) return null
  const a = Math.abs(m)
  const r = Math.round(a)
  if (r < 60) return `${r} ${r === 1 ? 'minute' : 'minutes'}`
  const h = Math.floor(r / 60)
  const mins = r % 60
  if (mins === 0) return `${h} ${h === 1 ? 'hour' : 'hours'}`
  return `${h} ${h === 1 ? 'hour' : 'hours'} ${mins} ${mins === 1 ? 'minute' : 'minutes'}`
}

export function fmtInt(n) {
  return isNum(n) ? Math.round(n).toLocaleString('en-US') : null
}

export function fmtKm(k) {
  if (!isNum(k)) return null
  return `${k < 10 ? k.toFixed(1) : Math.round(k)} km`
}

export const DAYS = [
  'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday',
]

/**
 * Hong Kong wall-clock parts, regardless of where the device is.
 *
 * These forecasts are keyed by hour-of-week in Hong Kong local time, because
 * that is what the archive timestamps are. Reading the DEVICE clock instead
 * silently answers the wrong question for anyone outside HKT. A relative
 * checking from London at 22:00 GMT was being shown Hong Kong Monday 22:00
 * when it is actually Tuesday 06:00 there. No caveat was displayed.
 *
 * HKT is UTC+8 with no daylight saving, but this goes through Intl rather than
 * hard-coding the offset, so it stays correct if that ever changes.
 */
const HK_TZ = 'Asia/Hong_Kong'

const hkParts = (d = new Date()) => {
  const f = new Intl.DateTimeFormat('en-US', {
    timeZone: HK_TZ,
    weekday: 'long',
    hour: 'numeric',
    hour12: false,
  })
  const parts = Object.fromEntries(f.formatToParts(d).map((p) => [p.type, p.value]))
  // 'hour' can come back as '24' for midnight in some engines.
  const hour = Number(parts.hour) % 24
  return { weekday: parts.weekday, hour }
}

export function hkNow(d = new Date()) {
  const { weekday, hour } = hkParts(d)
  return { day: DAYS.includes(weekday) ? weekday : todayName(d), hour }
}

/** True when the device is not on Hong Kong time, so the UI can say so. */
export function deviceIsOffHongKongTime(d = new Date()) {
  return hkParts(d).hour !== d.getHours()
}

export function todayName(d = new Date()) {
  const { weekday } = hkParts(d)
  return DAYS.includes(weekday) ? weekday : DAYS[(d.getDay() + 6) % 7]
}

export function hourLabel(h) {
  const s = String(h).padStart(2, '0')
  return `${s}:00`
}

/** "Monday 14:00": used when the API omits hour_label. */
export function whenLabel(day, hour) {
  return `${day} ${hourLabel(hour)}`
}
