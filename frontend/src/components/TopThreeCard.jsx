import { fmtMinutes, isNum, rangeText } from '../lib/format.js'
import { verdictChip, gapFacts } from '../lib/verdict.js'

function ChevronRight() {
  return <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden><path d="M6 4l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
}
function ChevronDown() {
  return <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden><path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
}

/**
 * The first sentences of the server's travel refusal, for the card face.
 *
 * A card cannot carry the whole paragraph, and a chip on its own ("Ferry only")
 * is a label, not a reason. The reason used to live in a table footnote far
 * below the fold, so a reader who tapped the card and saw a short queue never
 * met it. Two sentences is enough to carry the fact that decides everything:
 * island, no road, scheduled ferry. The full text is in the detail panel.
 */
function firstSentences(s, n = 2) {
  if (typeof s !== 'string' || !s.trim()) return null
  const parts = s.trim().match(/[^.]+\.(?:\s|$)/g)
  if (!parts) return s.trim()
  return parts.slice(0, n).join('').trim()
}

export default function TopThreeCard({
  result, top3, detailHospital, onSelect,
  whenText, triageLabel,
  originLabel, originAssumed,
}) {
  const showTravel = result.hasTravel
  const comparable = result.comparison?.available !== false

  // Without an origin there is no travel time, so "door to door" and "fastest"
  // are both false. The card used to claim them anyway while the chart below it
  // correctly disowned them, so the page contradicted itself. St John, the
  // ferry-only island hospital, was presented as a top-3 "door to door" option.
  const article = /^[aeiou]/i.test(triageLabel) ? 'an' : 'a'

  return (
    <section className="top3-wrap">
      <div className="top3-head">
        <h2>
          {showTravel
            ? `Top ${Math.min(3, top3.length)} fastest, door to door`
            : `Top ${Math.min(3, top3.length)} shortest queues`}
        </h2>
        <p className="sec" style={{ fontSize: 13.5 }}>
          {/* This used to interpolate `**${originLabel}**`. Markdown asterisks
              rendered literally on screen as "**Central & Sheung Wan**". */}
          {showTravel ? (
            <>
              Travel time plus forecast wait, ranked{originLabel ? <> from <strong>{originLabel}</strong></> : null} for {article}{' '}
              {triageLabel.toLowerCase()} arrival at <strong>{whenText}</strong>.
            </>
          ) : (
            <>
              Forecast wait only, for {article} {triageLabel.toLowerCase()} arrival at{' '}
              <strong>{whenText}</strong>. No travel time is included, so these are{' '}
              <strong>not</strong> ranked by how long the trip would take.
            </>
          )}
          {originAssumed && (
            <span className="muted"> {originLabel || 'Central'} is a default, not your position.</span>
          )}
        </p>
      </div>

      <div className="top3-list">
        {top3.map((r, i) => {
          const sel = r.hospital === detailHospital
          const hasT = isNum(r.travel)
          const total = hasT ? rangeText(r.travel + (r.p25 ?? 0), r.travel + (r.p75 ?? 0)) : rangeText(r.p25, r.p75)
          // Suppressed outright when there is no comparison for this hour.
          // the chip is the badge a scanning reader takes as the verdict, and
          // there is no verdict to give. `verdictChip` returns null for
          // `not_comparable`. The refusal is stated once, in the card below.
          const spec = comparable
            ? verdictChip(
              r.verdict,
              gapFacts({ excess: r.excess, published: r.published, p25: r.p25, p75: r.p75, delta: r.delta }),
            )
            : null

          return (
            <button
              key={r.hospital}
              type="button"
              className={`top3-row${sel ? ' is-sel' : ''}`}
              onClick={() => onSelect(r.hospital)}
            >
              <span className="top3-rank">#{i + 1}</span>
              <span className="top3-body">
                <span className="top3-name">
                  {r.hospital}
                  {/* Only shown with a real origin. With none, distance_km silently
                      means "from the queried hospital", which is not a fact anyone
                      asked for and reads identically to "from you". */}
                  {result.originProvided && isNum(r.distanceKm) && r.distanceKm > 0 && (
                    <span className="top3-dist muted" style={{ fontSize: 12, marginLeft: 8 }}>
                      {r.distanceKm < 1 ? `${Math.round(r.distanceKm * 1000)} m` : `${r.distanceKm.toFixed(1)} km`}
                    </span>
                  )}
                </span>
                <span className="top3-meta">
                  {comparable && isNum(r.published) && (
                    <span className="muted" style={{ fontSize: 12 }}>
                      Board says {fmtMinutes(r.published)}
                    </span>
                  )}
                  {r.pooled && <span className="chip chip--warn">Pooled</span>}
                  {/* St John is on Cheung Chau: ferry only, no road link. Ranked
                      here on queue length alone, it would otherwise read as an
                      ordinary 15-minute option to someone who never scrolls to
                      the table. */}
                  {r.travelReason && <span className="chip chip--warn">Ferry only, no road link</span>}
                  {spec && <span className={`chip chip--${spec.tone}`}>{spec.label}</span>}
                </span>
                {r.travelReason && (
                  <span className="top3-why">{firstSentences(r.travelReason)}</span>
                )}
              </span>
              <span className="top3-totalwrap">
                <span className="top3-total">{total}</span>
                <span className="top3-sub muted" style={{ fontSize: 13 }}>
                  {hasT ? (
                    <>door to door: {fmtMinutes(r.travel)} + wait {rangeText(r.p25, r.p75)}</>
                  ) : (
                    'queue only, no travel time'
                  )}
                </span>
              </span>
              <span className="top3-chevron">
                {sel ? <ChevronDown /> : <ChevronRight />}
              </span>
            </button>
          )
        })}
      </div>
    </section>
  )
}
