import { fmtMinutes, fmtRange, isNum, fmtInt, rangeText } from '../lib/format.js'
import { readGap, gapFacts, excessPhrase } from '../lib/verdict.js'
import { Badge, Icon } from '../lib/ui.jsx'
import { useCountUp } from '../lib/hooks.js'

/* ---------------------------------------------------------------- hero */

/**
 * RULE: never a bare number. The hero is always an interval, and the digits
 * count up so the figure reads as something measured rather than asserted.
 */
function HeroInterval({ lo, hi }) {
  const spec = fmtRange(lo, hi)

  // Decide the unit from the settled values, then animate inside that unit,
  // so the label cannot flip from "min" to "hr" mid-animation.
  let aTarget = 0, bTarget = 0, aDec = 0, bDec = 0, aUnit = '', unit = 'min'
  if (spec) {
    if (hi < 60) {
      aTarget = lo; bTarget = hi; unit = 'min'
    } else if (lo >= 60) {
      aTarget = lo / 60; bTarget = hi / 60
      aDec = aTarget < 10 ? 1 : 0
      bDec = bTarget < 10 ? 1 : 0
      unit = 'hr'
    } else {
      aTarget = lo; bTarget = hi / 60
      bDec = bTarget < 10 ? 1 : 0
      aUnit = 'min'; unit = 'hr'
    }
  }

  const a = useCountUp(aTarget, { duration: 800, decimals: aDec })
  const b = useCountUp(bTarget, { duration: 950, decimals: bDec })

  if (!spec) {
    return (
      <div className="hero">
        <span className="hero__value" style={{ fontSize: 34, letterSpacing: '-.02em' }}>
          No interval available
        </span>
      </div>
    )
  }

  const fa = (a ?? aTarget).toFixed(aDec)
  const fb = (b ?? bTarget).toFixed(bDec)

  return (
    <div className="hero">
      <span className="hero__value">
        {fa}
        {aUnit ? <span className="hero__unit"> {aUnit}</span> : null}
        <span style={{ color: 'var(--ink-3)' }}> – </span>
        {fb}
        <span className="hero__unit"> {unit}</span>
      </span>
    </div>
  )
}

/* ------------------------------------------------------- the gap strip */

const clampPct = (v) => Math.max(0, Math.min(100, v))

/**
 * `comparable === false` means the Hospital Authority has published no figure
 * for the hour being asked about, so there is nothing to mark on this strip.
 * The strip still draws: the historical band and its median are this
 * department's own record at that hour and remain valid. But the published
 * marker, its flag and its legend key are SUPPRESSED, not stubbed with a dash.
 * A greyed "unavailable" flag in the marker's place still puts the idea of a
 * board figure on the axis, which is the thing that must not happen.
 */
function GapStrip({ p25, p75, median, published, facts, comparable = true }) {
  const hasBand = isNum(p25) && isNum(p75)
  if (!hasBand) return null

  const pub = comparable ? published : null
  const top = Math.max(p75, isNum(pub) ? pub : 0) * 1.18 || 1
  const pct = (v) => clampPct((v / top) * 100)

  const left = pct(p25)
  const right = pct(p75)
  const width = Math.max(right - left, 1.2)
  const medPos = isNum(median) ? pct(median) : null
  const pubPos = isNum(pub) ? pct(pub) : null

  // The connector runs from the published marker to the nearest edge of the
  // historical interval: its length *is* the departure from normal, to scale.
  // Its colour follows the page's one colour rule: alarm red only when the
  // department is BUSIER than its own normal. A department 40 minutes quieter
  // is the best news on the page and must never be painted as a warning.
  //
  // The LABEL on that connector is not measured off this component's own
  // geometry: it prints the server's `excess`, the same number the badge and
  // the table cell are built from. When those were computed separately this
  // label read "10 minutes above the range" in red beside a green tick reading
  // "well inside its normal spread".
  const f = facts || {}
  const outside = isNum(f.excess) && f.excess > 0
  let conn = null
  if (isNum(pub) && outside) {
    if (pub < p25) conn = { from: pubPos, to: left, busier: false }
    else if (pub > p75) conn = { from: right, to: pubPos, busier: true }
  }
  // Alarm red only when the department is BOTH busier than its own normal AND
  // far enough outside the band that the verdict itself says so. Within the
  // 5-minute tolerance the connector is grey and says "near normal", because
  // the badge above it says the same.
  const connColour = conn?.busier && !f.near ? 'var(--crit)' : 'var(--ink-2)'
  const connText = outside
    ? `${excessPhrase(f)}${f.near ? ', near enough to normal' : ''}`
    : null

  const labelPos = pubPos === null ? 50 : Math.max(9, Math.min(91, pubPos))

  return (
    <div className="strip">
      {pubPos !== null && (
        <div className="strip__labels">
          <div className="strip__flag" style={{ left: `${labelPos}%` }}>
            <div className="strip__flag-k">Published now</div>
            <div className="strip__flag-v">{fmtMinutes(pub)}</div>
          </div>
        </div>
      )}

      {/* The published marker is a sibling of the track, not a child of it:
          .strip__track clips its overflow, which was silently eating the cap
          that identifies the Hospital Authority figure. */}
      <div className="strip__trackwrap">
        <div className="strip__track">
          <div
            className="strip__band"
            key={left.toFixed(1) + '|' + width.toFixed(1)}
            style={{ left: `${left}%`, width: `${width}%` }}
          />
          {medPos !== null && (
            <div className="strip__median" key={medPos} style={{ left: `${medPos}%` }} />
          )}
        </div>
        {pubPos !== null && (
          <div className="strip__pub" style={{ left: `${pubPos}%` }} />
        )}
      </div>

      {conn && connText && (
        <div style={{ position: 'relative', height: 26, marginTop: 4 }}>
          <div
            style={{
              position: 'absolute',
              left: `${conn.from}%`,
              width: `${Math.max(conn.to - conn.from, 0.4)}%`,
              top: 7,
              height: 2,
              background: connColour,
              borderRadius: 2,
            }}
          />
          <div
            style={{
              position: 'absolute',
              left: `${clampPct((conn.from + conn.to) / 2)}%`,
              top: 12,
              transform: 'translateX(-50%)',
              fontSize: 11.5,
              fontWeight: 640,
              color: connColour,
              whiteSpace: 'nowrap',
            }}
          >
            {connText}
          </div>
        </div>
      )}

      <div className="strip__axis">
        <span>0 min</span>
        <span>{fmtMinutes(top)}</span>
      </div>

      <div className="strip__legend">
        <span className="key">
          <span className="key__sw" style={{ background: 'var(--series-wait)' }} />
          Middle 50% of what this department publishes at this hour
        </span>
        {isNum(pub) && (
          <span className="key">
            <span className="key__ln" style={{ background: 'var(--series-published)' }} />
            Hospital Authority published figure
          </span>
        )}
        {isNum(median) && (
          <span className="key" style={{ color: 'var(--ink-3)' }}>
            Median {fmtMinutes(median)}
          </span>
        )}
      </div>
    </div>
  )
}


/* ------------------------------------------------------------- the tail */

/**
 * The long wait, which nothing else shows you.
 *
 * The Hospital Authority publishes TWO figures per department and urgency: a
 * median, and a 95th percentile ("Majority of the waiting patients can receive
 * consultation within this time"). Every A&E app, this one included until now,
 * showed only the median. The middle of a queue is not the thing that hurts.
 *
 * Measured example: Queen Elizabeth, triage 4/5, Tuesday 15:00. The median
 * range is 1.5–2.0 hr while the department's own 95th-percentile figure has run
 * 2.5–3.0 hr. Someone reading "about two hours" and planning around it has
 * roughly a 1-in-20 chance of over three.
 *
 * Rendered as an interval like everything else: it is the middle 50% of the
 * p95 figures this department has published at this hour, so it gets the same
 * treatment and the same honesty as the median beside it. When the series is
 * too thin the component prints the refusal reason rather than disappearing,
 * because a silently absent tail reads as "there isn't one".
 */
function TailNote({ tail, whenText }) {
  if (!tail) return null

  if (!tail.available) {
    return (
      <div className="explain" style={{ marginTop: 12 }}>
        <div className="explain__row">
          <Icon.Ban />
          <span>
            <b>No long-wait figure for this slot.</b>{' '}
            {tail.reason || 'The 95th-percentile series is too thin here.'}
          </span>
        </div>
      </div>
    )
  }

  const band = fmtRange(tail.p25, tail.p75)
  if (!band) {
    return (
      <div className="explain" style={{ marginTop: 12 }}>
        <div className="explain__row">
          <Icon.Ban />
          <span>
            <b>No long-wait figure for this slot.</b>{' '}
            {tail.reason || 'The 95th-percentile series does not resolve to a usable range here.'}
          </span>
        </div>
      </div>
    )
  }

  return (
    <div className="explain explain--tail" style={{ marginTop: 12 }}>
      <div className="explain__row">
        <Icon.Alert />
        <span>
          <b>The long wait, not the typical one.</b> About <b>19 in 20</b> patients
          are seen within this range at {whenText} ({rangeText(tail.p25, tail.p75)}
          {tail.basis && tail.basis !== 'exact_hour' && (
            <>, pooled across {tail.basis === 'hour_window' ? 'nearby hours' : 'all hours'}</>
          )}
          ). The remaining <b>1 in 20</b> waits longer. Plan for the long case, not
          the typical one.
        </span>
      </div>
    </div>
  )
}

/* --------------------------------------------------------------- card */

export default function AnswerCard({
  row, whenText, triageLabel, refetching, mode, tail,
  originLabel, originIsGeo, originAssumed,
  comparison = { available: true, reason: null },
}) {
  const comparable = comparison?.available !== false
  const published = comparable ? row?.published : null
  // ONE reading of "how normal is today", shared by the badge, the sentence and
  // the strip annotation below. They cannot disagree because there is nothing
  // for them to disagree about.
  const facts = gapFacts({
    excess: comparable ? row?.excess : null,
    published,
    p25: row?.p25,
    p75: row?.p75,
    delta: row?.delta,
  })
  const gap = readGap({
    verdict: row?.verdict,
    delta: row?.delta,
    excess: comparable ? row?.excess : null,
    published,
    p25: row?.p25,
    p75: row?.p75,
    whenText,
    reason: comparison?.reason,
  })

  const canInterval = row && isNum(row.p25) && isNum(row.p75)
  const explainClass =
    gap.tone === 'crit' ? 'explain explain--crit'
      : gap.tone === 'warn' ? 'explain explain--warn'
        : 'explain'

  const GapIcon = gap.icon === 'check' ? Icon.Check : gap.icon === 'ban' ? Icon.Ban : Icon.Alert
  const hasTravel = isNum(row?.travel)

  return (
    <section key={row?.hospital} className={`card answer${refetching ? ' is-refetching' : ''}`} aria-busy={refetching || undefined}>
      <div className="answer__head">
        <div className="answer__head-text">
          <span className="eyebrow">Usual published wait at this hour at</span>
          <div className="answer__where" style={{ marginTop: 4 }}>{row?.hospital}</div>
          <div className="answer__when">{whenText} · {triageLabel}</div>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {row?.pooled && (
            <Badge tone="warn" icon={<Icon.Layers />}>Not hour-specific</Badge>
          )}
          <Badge
            tone={gap.tone === 'crit' ? 'crit' : gap.tone === 'warn' ? 'warn' : gap.tone === 'good' ? 'good' : 'neutral'}
            icon={<GapIcon />}
          >
            {gap.chip}
          </Badge>
        </div>
      </div>

      {/* The island fact travels WITH the department it describes.
          St John is on Cheung Chau, car-free, with no road link, reachable only by
          scheduled ferry. That reason used to live in a table footnote roughly
          twelve thousand mobile pixels below this card, so someone who tapped
          the card and read a 15-minute queue never met it. It is the first
          thing in the panel now, because it changes whether any of the rest of
          the panel is usable at all. */}
      {row?.travelReason && (
        <div className="notice notice--warn" style={{ marginTop: 14 }}>
          <Icon.Ban />
          <span>
            <b>You cannot drive or take a bus here.</b> {row.travelReason}
          </span>
        </div>
      )}

      {canInterval ? (
        <>
          <div className="answer__top">
            <div className="answer__hero">
              <HeroInterval lo={row.p25} hi={row.p75} />
              <p className="hero__caption">
                This department&apos;s usual range at this hour, an estimate, not a
                record of real waits.
                {hasTravel && (
                  <>
                    {' '}
                    Travel from{' '}
                    {originIsGeo
                      ? 'your current location'
                      : originLabel
                        ? originLabel
                        : 'your starting point'}
                    {' '}adds about <b>{fmtMinutes(row.travel)}</b> by{' '}
                    {mode === 'transit' ? 'public transport' : 'road'}, so expect{' '}
                    <b>{fmtMinutes(row.p25 + row.travel)} – {fmtMinutes(row.p75 + row.travel)}</b>{' '}
                    door to door.
                  </>
                )}
              </p>
              {originAssumed && originLabel && (
                <span className="muted hero__origin-note" style={{ display: 'block', marginTop: 6, fontSize: 12 }}>
                  {originLabel} is a default, not your position.
                </span>
              )}
              {/* The server's own account of how that travel figure was produced,
                  printed verbatim. It differs by mode, so the page cannot credit
                  road detectors for a number that never touched them. */}
              {hasTravel && row.travelAssumption && (
                <details className="prov">
                  <summary>
                    How that travel time was produced
                    {mode === 'transit' ? ' (modelled, not routed)' : ' (live road speeds)'}
                  </summary>
                  <p>{row.travelAssumption}</p>
                </details>
              )}
            </div>

            <div className="gap">
              <div className="gap__title">
                <div>
                  <span className="eyebrow">Today versus this department&apos;s normal</span>
                  <h3 style={{ fontSize: 16.5, fontWeight: 650, letterSpacing: '-.015em', marginTop: 4 }}>
                    {gap.title}
                  </h3>
                </div>
              </div>

              <GapStrip
                p25={row?.p25}
                p75={row?.p75}
                median={row?.median}
                published={row?.published}
                facts={facts}
                comparable={comparable}
              />

              <div className={explainClass} style={{ marginTop: 18 }}>
                <div className="explain__row">
                  <GapIcon />
                  <span>{gap.body}</span>
                </div>
              </div>
            </div>
          </div>

          {canInterval && <TailNote tail={tail} whenText={whenText} />}

          {row?.pooled && (
            <div className="notice notice--warn">
              <Icon.Layers />
              <span>
                <b>This forecast is not hour-specific.</b> {whenText} alone had too few
                observations, so every hour of the week was pooled into one estimate.
                Treat it as a typical wait here, not a wait at this hour.
              </span>
            </div>
          )}

          {canInterval && row.p25 === row.p75 && (
            <div className="notice notice--info">
              <Icon.Info />
              <span>
                <b>The interval is flat because the source is coarse.</b> The feed
                reports in steps (30 minutes, 1 hour, 2 hours), so a flat range means
                the data is coarse, not that your wait is certain.
              </span>
            </div>
          )}

          {!row?.pooled && row?.basis === 'hour_window' && (
            <div className="notice notice--info">
              <Icon.Info />
              <span>
                <b>Widened to the hours either side.</b> {whenText} alone had too few
                observations, so the hour before and after were added. Close to your
                time, but not that hour alone.
              </span>
            </div>
          )}

          <div className="explain" style={{ marginTop: 10 }}>
            <div className="explain__row">
              <Icon.Info />
              <span>
                Built from <b>{fmtInt(row?.n) ?? 'an unknown number of'}</b> past
                snapshots at this hour{row?.pooled ? ' (all hours pooled)' : ''}.
              </span>
            </div>
          </div>
        </>
      ) : (
        <div className="notice notice--warn" style={{ marginTop: 14 }}>
          <Icon.Ban />
          <span>
            <b>No interval, so no answer.</b> The record here is too thin to bound a
            wait, so we will not print a single number in its place.
          </span>
        </div>
      )}

      <div className="safety">
        <Icon.Alert />
        <span>
          <b>This is not medical advice</b> and it cannot triage you. It forecasts
          queues, not illness. If someone may be having a heart attack, stroke, or
          breathing trouble, <b>call 999 now</b>.
        </span>
      </div>
    </section>
  )
}
