import { useState } from 'react'
import { fmtInt, fmtKm, fmtMinutes, isNum, rangeText } from '../lib/format.js'
import { verdictChip, gapFacts } from '../lib/verdict.js'
import { useMediaQuery } from '../lib/hooks.js'
import { Icon } from '../lib/ui.jsx'

/* How many departments a phone shows before the reader asks for the rest.
   Five is the whole shortlist a person at 2am can hold in their head. The
   other thirteen are one tap away and nothing is dropped. */
const MOBILE_PREVIEW = 5

function Verdict({ v, facts, pooled }) {
  const spec = verdictChip(v, facts)
  return (
    <span style={{ display: 'inline-flex', gap: 5, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
      {spec ? <span className={`chip chip--${spec.tone}`}>{spec.label}</span> : <span className="chip chip--neutral">n/a</span>}
      {pooled && <span className="chip chip--warn">Pooled</span>}
    </span>
  )
}

/**
 * The "vs its usual range" cell.
 *
 * It prints the SAME `excess` the chip in the last column is graded on, so the
 * two cannot contradict each other. The cell used to print `delta` (today's
 * figure minus the historical MEDIAN) beside a chip graded on something else
 * entirely, which is how a red "+10 min busier" came to sit in the same row as
 * a green "Typical".
 *
 * Two rules survive from that cell, both learned the hard way:
 *  1. RED MEANS BUSIER, and only when the department is far enough outside its
 *     own range for the verdict to say so. A department below its range, the
 *     best row in the table, is never painted as a warning.
 *  2. HUE IS NEVER THE ONLY CARRIER. "above" / "below" / "inside" is written
 *     out, so the cell survives being read in greyscale.
 */
function RangeCell({ facts }) {
  if (!isNum(facts?.excess)) return <span className="muted">n/a</span>
  if (facts.excess === 0) {
    return <span className="muted">inside its range</span>
  }
  const busier = facts.busier === true
  const alarming = busier && !facts.near
  const mins = Math.round(facts.excess)
  return (
    <span style={alarming ? { color: 'var(--crit)' } : undefined}>
      {busier ? '+' : '−'}{mins} min
      <span className="gap-word">{busier ? ' above' : ' below'}</span>
    </span>
  )
}

export default function HospitalTable({ result, onPick, mode, detailHospital }) {
  const rows = result.ranked
  const small = useMediaQuery('(max-width: 720px)')
  const [showAll, setShowAll] = useState(false)
  if (!rows.length) return null
  const withTravel = result.hasTravel
  // No comparison for this hour means no Published, no Gap and no Vs-normal:
  // three whole columns of "n/a" would be worse than the truth. The columns come
  // out and the reason is stated once, below the table.
  const cmp = result.comparison || { available: true, reason: null }
  const showCmp = cmp.available !== false
  const travelLabel = `Travel ${mode === 'transit' ? '(transport)' : '(car)'}`

  const collapsed = small && !showAll && rows.length > MOBILE_PREVIEW
  const visible = collapsed ? rows.slice(0, MOBILE_PREVIEW) : rows

  return (
    <section className="card chart-card">
      <div className="chart-head">
        <h3>Every A&amp;E department, in full</h3>
        <p>
          Every hospital in one table. Select a row to see its details. Every wait is
          an interval, and the median is labelled.
        </p>
      </div>

      <div className="table-wrap" style={{ marginTop: 14 }}>
        <table className="data">
          <thead>
            <tr>
              <th scope="col">Hospital</th>
              {withTravel && <th scope="col">{travelLabel}</th>}
              <th scope="col">Forecast wait</th>
              <th scope="col">Median</th>
              {withTravel && <th scope="col">Door to door</th>}
              {showCmp && <th scope="col">Board says</th>}
              {showCmp && <th scope="col">From its usual range</th>}
              <th scope="col">Obs.</th>
              {showCmp && <th scope="col">How normal</th>}
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => {
              const t = isNum(r.travel) ? r.travel : 0
              // One reading per row, shared by the cell and the chip.
              const facts = gapFacts({
                excess: r.excess, published: r.published, p25: r.p25, p75: r.p75, delta: r.delta,
              })
              return (
                <tr
                  key={r.hospital}
                  className={r.hospital === detailHospital ? 'is-sel' : undefined}
                  onClick={() => onPick(r.hospital)}
                  style={{ cursor: 'pointer' }}
                >
                  {/* data-short drives the stacked card layout under 720px, where
                      a 9-column table cannot survive. The c-* classes decide what
                      is a headline field on a phone and what is supporting detail.
                      See table.data in index.css. */}
                  <td className="c-name" data-short="Hospital">
                    {r.hospital}
                    {/* Only with a real origin. With none the server's
                        distance is measured from the QUERIED hospital, which
                        reads on screen as "how far this is from you". */}
                    {result.originProvided && isNum(r.distanceKm) && r.distanceKm > 0 && (
                      <span className="muted" style={{ fontSize: 11.5, marginLeft: 8 }}>{fmtKm(r.distanceKm)}</span>
                    )}
                    {/* True whether or not a journey was costed. Without it,
                        an origin-less query lists St John as an ordinary short
                        queue with no hint that no road reaches it. */}
                    {r.travelReason && (
                      <span className="chip chip--warn" style={{ marginLeft: 8 }}>Ferry only</span>
                    )}
                    {/* Normally the Pooled chip rides in the Vs-normal column.
                        That column is gone when there is no comparison, and
                        "this forecast is not hour-specific" must not go with
                        it: it qualifies the interval, not the comparison. */}
                    {!showCmp && r.pooled && (
                      <span className="chip chip--warn" style={{ marginLeft: 8 }}>Pooled</span>
                    )}
                  </td>
                  {withTravel && (
                    <td
                      className="num c-travel"
                      data-short="Travel"
                      title={r.travelReason || undefined}
                    >
                      {fmtMinutes(r.travel) || (
                        <span className="muted" style={{ fontStyle: 'italic' }}>not by road</span>
                      )}
                    </td>
                  )}
                  <td className="num c-wait" data-short="Wait on arrival">{rangeText(r.p25, r.p75) || 'no interval'}</td>
                  <td className="num muted c-median" data-short="Median">{fmtMinutes(r.median) || 'n/a'}</td>
                  {withTravel && (
                    <td className="num c-total" data-short="Door to door">{isNum(r.travel) ? rangeText(r.p25 + t, r.p75 + t) || 'n/a' : 'n/a'}</td>
                  )}
                  {showCmp && (
                    <td className="num muted c-published" data-short="Board says">{isNum(r.published) ? fmtMinutes(r.published) : 'no feed'}</td>
                  )}
                  {/* Colour keys off the ROUNDED value that is actually on screen.
                      Keying off the raw float painted a -0.4 gap red and a +0.4 gap
                      neutral, so two cells both reading "0 min" disagreed in colour
                      and the semantics looked arbitrary. */}
                  {showCmp && (
                    <td className="num c-gap" data-short="Vs its range">
                      <RangeCell facts={facts} />
                    </td>
                  )}
                  <td className="num muted c-obs" data-short="Obs.">{fmtInt(r.n) ?? 'n/a'}</td>
                  {showCmp && (
                    <td className="c-verdict" data-short="Vs normal">
                      <Verdict v={r.verdict} facts={facts} pooled={r.pooled === true} />
                    </td>
                  )}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {small && rows.length > MOBILE_PREVIEW && (
        <button
          type="button"
          className="table-more"
          aria-expanded={!collapsed}
          onClick={() => setShowAll((v) => !v)}
        >
          {collapsed
            ? `Show all ${rows.length} departments`
            : `Show only the ${MOBILE_PREVIEW} fastest`}
        </button>
      )}

      {!showCmp && (
        <div className="notice notice--info" style={{ marginTop: 14 }}>
          <Icon.Ban />
          <span>
            <b>No Published, Gap or Vs-normal column for this time.</b> {cmp.reason}
          </span>
        </div>
      )}

      <p className="chart-note">
        {showCmp && (
          <>
            <b>From its usual range</b> shows how far the board figure sits outside
            this department&apos;s usual range at this hour. Red means busier.{' '}
            <b>How normal</b> grades the same distance against the width of that
            range.{' '}
          </>
        )}
        <b>Obs.</b> is how many snapshots built the estimate.
      </p>
    </section>
  )
}
