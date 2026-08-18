import { fmtKm, fmtMinutes, fmtRange, isNum, rangeText } from '../lib/format.js'
import { shortName } from '../lib/hospitals.js'
import { Badge, Icon } from '../lib/ui.jsx'

/** Total time is an interval too: travel is a point, the wait is not. */
function totalRange(row) {
  if (!isNum(row?.p25) || !isNum(row?.p75)) return null
  const t = isNum(row.travel) ? row.travel : 0
  return fmtRange(row.p25 + t, row.p75 + t)
}

export default function RecoCard({ result, onPick, mode, refetching, originLabel, originAssumed }) {
  const ranked = result.comparable?.length ? result.comparable : result.ranked
  const unrankable = result.unrankable || []
  if (!ranked.length) return null

  const best = ranked[0]
  const alreadyBest = best.hospital === result.hospital
  const byTotal = result.rankedBy === 'total'
  const chosen = result.primary

  const bestTotal = totalRange(best)
  const modeWord = mode === 'transit' ? 'public transport' : 'car or taxi'

  // Stated on the same statistic the list is ranked by, so the claim and the
  // ordering can never disagree.
  let saving = null
  if (!alreadyBest && chosen && isNum(chosen.p75) && isNum(best.p75)) {
    const a = (isNum(chosen.travel) ? chosen.travel : 0) + chosen.p75
    const b = (isNum(best.travel) ? best.travel : 0) + best.p75
    if (a - b >= 5) saving = a - b
  }

  return (
    <aside className={`card reco${refetching ? ' is-refetching' : ''}`}>
      <div className="reco__head">
        <span className="eyebrow">{byTotal ? 'Lowest total time' : 'Shortest forecast wait'}</span>
        {alreadyBest && <Badge tone="good" icon={<Icon.Check />}>Your pick</Badge>}
      </div>

      <div className="reco__pick">
        <div className="reco__name">{best.hospital}</div>
        {bestTotal ? (
          <div className="reco__total tnum">
            {bestTotal.value} <span>{bestTotal.unit} {byTotal && isNum(best.travel) ? 'door to door' : 'waiting'}</span>
          </div>
        ) : (
          <div className="reco__total" style={{ fontSize: 15, fontWeight: 600, color: 'var(--ink-2)' }}>
            No interval available for this hospital
          </div>
        )}

        <div className="breakdown">
          {isNum(best.travel) && (
            <div className="breakdown__row">
              {mode === 'transit' ? <Icon.Transit /> : <Icon.Car />}
              Travel by {modeWord}
              <b>{fmtMinutes(best.travel)}</b>
            </div>
          )}
          <div className="breakdown__row">
            <Icon.Clock />
            Wait after arriving
            <b>{rangeText(best.p25, best.p75) || 'unavailable'}</b>
          </div>
          {isNum(best.distanceKm) && best.distanceKm > 0 && (
            <div className="breakdown__row">
              <Icon.Pin />
              {result.originProvided || byTotal ? 'Distance' : `Distance from ${shortName(result.hospital)}`}
              <b>{fmtKm(best.distanceKm)}</b>
            </div>
          )}
        </div>
      </div>

      {byTotal && originAssumed && originLabel && (
        <div className="notice notice--warn" style={{ marginTop: 12 }}>
          <Icon.Pin />
          <span>
            Travel times assume you are starting in <b>{originLabel}</b>, which is a
            default, not your actual position. Change &ldquo;Starting from&rdquo; above
            if it is wrong. The ranking will change with it.
          </span>
        </div>
      )}

      {byTotal && best.travelAssumption && (
        <details className="disclose">
          <summary>How this travel time was estimated</summary>
          <p>{best.travelAssumption}</p>
          {best.travelIsEstimate && (
            <p style={{ marginTop: 8 }}>
              It is an estimate, not a routed journey. Treat the ordering as more
              reliable than the minutes.
            </p>
          )}
        </details>
      )}

      {!byTotal && (
        <div className="notice notice--info" style={{ marginTop: 12 }}>
          <Icon.Info />
          <span>
            <b>Ranked by wait alone.</b> Travel times are not available for this
            query, so a nearer hospital with a slightly longer queue may still get
            you seen sooner. Add a starting point above to rank by total time.
          </span>
        </div>
      )}

      {saving && (
        <div className="notice notice--info" style={{ marginTop: 12 }}>
          <Icon.Arrow />
          <span>
            Switching from {shortName(result.hospital)} saves roughly{' '}
            <b>{fmtMinutes(saving)}</b> off the slow end of the range, worth it only
            if the patient is stable enough to travel.
          </span>
        </div>
      )}

      {unrankable.map((r) => (
        <details className="disclose" key={r.hospital}>
          <summary>{shortName(r.hospital)} cannot be ranked here</summary>
          <p>{r.travelReason || 'No travel estimate could be produced for this hospital, so it is left out of the total-time ranking rather than shown as if the journey were free.'}</p>
          <p style={{ marginTop: 8 }}>
            Its forecast wait is <b>{rangeText(r.p25, r.p75) || 'unavailable'}</b>.
          </p>
        </details>
      ))}

      <div style={{ marginTop: 16 }}>
        <span className="eyebrow">Next best</span>
        <p className="origin-note" style={{ marginTop: 4, marginBottom: 2 }}>
          Ordered by the top of the likely range, the time worth planning for, not
          the lucky case.
        </p>
        <div className="alt-list">
          {ranked.slice(1, 6).map((r, i) => {
            const tr = totalRange(r)
            return (
              <button key={r.hospital} type="button" className="alt" onClick={() => onPick(r.hospital)}>
                <span className="alt__rank tnum">{i + 2}</span>
                <span style={{ minWidth: 0 }}>
                  <span className="alt__name" style={{ display: 'block' }}>{shortName(r.hospital)}</span>
                  <span className="alt__meta">
                    {isNum(r.travel) ? `${fmtMinutes(r.travel)} travel` : fmtKm(r.distanceKm) || 'distance unknown'}
                    {isNum(r.median) ? ` · median ${fmtMinutes(r.median)} wait` : ''}
                    {r.pooled ? ' · pooled' : ''}
                  </span>
                </span>
                <span className="alt__val">{tr ? `${tr.value} ${tr.unit}` : 'n/a'}</span>
              </button>
            )
          })}
        </div>
      </div>
    </aside>
  )
}
