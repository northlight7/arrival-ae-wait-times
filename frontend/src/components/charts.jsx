import {
  Bar, BarChart, CartesianGrid, Cell, LabelList, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { fmtGap, fmtKm, fmtMinutes, isNum, rangeText } from '../lib/format.js'
import { shortName } from '../lib/hospitals.js'
import { useMediaQuery, usePrefersReducedMotion } from '../lib/hooks.js'
import { gapFacts, NEAR_MINUTES } from '../lib/verdict.js'

const C = {
  wait: '#2a78d6',
  waitSoft: '#a8c9f2',
  travel: '#1baf7a',
  crit: '#d03b3b',
  // Quieter-than-normal. Deliberately NOT green: it is not a promise of a short
  // wait, only the absence of an alarm. Slate reads as neutral in greyscale too.
  calm: '#5b7480',
  grid: '#e6ebee',
  axis: '#cbd4da',
  mid: '#9aa5ae',
  ink: '#0d1418',
  ink2: '#47555f',
  ink3: '#78848d',
  surface: '#ffffff',
}

function Key({ swatch, children, shape = 'sw' }) {
  return (
    <span className="key">
      <span className={shape === 'ln' ? 'key__ln' : 'key__sw'} style={{ background: swatch }} />
      {children}
    </span>
  )
}

/**
 * Folds a chart body away on a phone, and leaves it alone everywhere else.
 *
 * A 17-row horizontal bar chart is ~440px of 10px type on a 390px screen, and
 * the door-to-door ranking it draws is already stated twice on the same page,
 * as the top-three cards and as the full table. Folding it is what buys the
 * scroll depth back for the parts a phone reader cannot get elsewhere.
 * Nothing is deleted: one tap opens it, and the heading and the sentence that
 * explains what it shows stay on screen either way.
 */
function ChartFold({ fold, label, children }) {
  if (!fold) return children
  return (
    <details className="chart-fold">
      <summary>{label}</summary>
      <div className="chart-fold__body">{children}</div>
    </details>
  )
}

/* --------------------------------------------------------------- tooltip */

function RowTooltip({ active, payload, mode }) {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload
  if (!d) return null
  const total = isNum(d.travel) && isNum(d.p25)
    ? rangeText(d.p25 + d.travel, d.p75 + d.travel)
    : null
  return (
    <div className="tip">
      <div className="tip__name">{d.name}</div>
      {isNum(d.travel) && (
        <div className="tip__row">
          <span>Travel by {mode === 'transit' ? 'transport' : 'car'}</span>
          <b>{fmtMinutes(d.travel)}</b>
        </div>
      )}
      <div className="tip__row"><span>Forecast wait</span><b>{rangeText(d.p25, d.p75) || 'n/a'}</b></div>
      {isNum(d.median) && <div className="tip__row"><span>Median</span><b>{fmtMinutes(d.median)}</b></div>}
      {total && (
        <>
          <div className="tip__sep" />
          <div className="tip__row"><span>Total, door to door</span><b>{total}</b></div>
        </>
      )}
      <div className="tip__sep" />
      <div className="tip__row">
        <span>Published now</span>
        <b>{isNum(d.published) ? fmtMinutes(d.published) : 'no feed'}</b>
      </div>
      {isNum(d.distanceKm) && d.distanceKm > 0 && (
        <div className="tip__row"><span>Distance</span><b>{fmtKm(d.distanceKm)}</b></div>
      )}
      {d.pooled && (
        <div className="tip__row" style={{ color: '#8a5d05', marginTop: 6 }}>
          Pooled across all hours, not hour-specific
        </div>
      )}
    </div>
  )
}

/**
 * "Understated by" / "Overstated by" used to sit at the bottom of this tooltip.
 * Both claim the board is WRONG, which no public data can show. There is no
 * record of what any patient actually waited. The gap says today is unusual for
 * this department at this hour, and nothing more, so that is what it now reads.
 *
 * The last row reports the server's `excess`, the same quantity the chip and
 * the table cell use, not a distance this file worked out for itself.
 */
function GapTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload
  if (!d) return null
  return (
    <div className="tip">
      <div className="tip__name">{d.name}</div>
      <div className="tip__row"><span>Published now</span><b>{fmtMinutes(d.published)}</b></div>
      <div className="tip__row"><span>Its usual range at this hour</span><b>{rangeText(d.p25, d.p75) || 'n/a'}</b></div>
      <div className="tip__sep" />
      {d.excess === 0 ? (
        <div className="tip__row"><span>Today</span><b>inside that range</b></div>
      ) : (
        <div className="tip__row">
          <span>{d.busier ? 'Above the top of that range by' : 'Below the bottom of that range by'}</span>
          <b>{fmtGap(d.excess)}</b>
        </div>
      )}
      {d.excess > 0 && d.excess <= NEAR_MINUTES && (
        <div className="tip__row" style={{ color: C.ink3 }}>
          Within {NEAR_MINUTES} minutes of it, still counted normal
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------- shared y-axis tick */

function makeTick({ selected, fontSize }) {
  return function Tick({ x, y, payload }) {
    const isSel = payload?.value === selected
    return (
      <text
        x={x}
        y={y}
        dy={4}
        textAnchor="end"
        fill={isSel ? C.ink : C.ink3}
        fontSize={fontSize}
        fontWeight={isSel ? 650 : 450}
      >
        {payload?.value}
      </text>
    )
  }
}

/* =================================================== 1. total-time ranking */

export function RankingChart({ result, mode, selected }) {
  const small = useMediaQuery('(max-width: 720px)')
  const reduced = usePrefersReducedMotion()
  const byTotal = result.rankedBy === 'total'

  const source = result.comparable?.length ? result.comparable : result.ranked
  const excluded = result.unrankable || []
  const data = source.map((r) => ({
    name: shortName(r.hospital),
    full: r.hospital,
    travel: isNum(r.travel) ? r.travel : null,
    travelSeg: isNum(r.travel) ? r.travel : 0,
    p25: r.p25,
    p75: r.p75,
    median: r.median,
    spread: Math.max(0, (r.p75 ?? 0) - (r.p25 ?? 0)),
    published: r.published,
    distanceKm: r.distanceKm,
    pooled: r.pooled === true,
  }))

  if (!data.length) return null

  const maxTotal = Math.max(...data.map((d) => d.travelSeg + (d.p75 ?? 0)))
  const axisMax = Math.ceil((maxTotal * 1.1) / 15) * 15 || 15
  const inHours = axisMax >= 180   // one unit for the whole axis, never a mix
  const rowH = small ? 23 : 27
  const height = data.length * rowH + 46
  const anyTravel = data.some((d) => isNum(d.travel))
  const best = data[0]

  return (
    <section className="card chart-card">
      <div className="chart-head">
        <h3>
          {byTotal ? 'Total time door to door' : 'Forecast wait'}, {data.length} A&E departments
        </h3>
        <p>
          {byTotal
            ? 'Travel plus the wait. The shortest queue is rarely the fastest trip.'
            : 'Give a starting point above and this re-sorts by travel plus wait.'}
          {' '}The solid part is the lower half of the likely range, the pale part the
          upper half. The slow case is what matters.
        </p>
      </div>

      <ChartFold fold={small} label={`Show the ranking as a chart (${data.length} departments)`}>
      <div className="chart-legend">
        {anyTravel && <Key swatch={C.travel}>Travel time</Key>}
        <Key swatch={C.wait}>Wait, lower half of the likely range</Key>
        <Key swatch={C.waitSoft}>Wait, upper half of the likely range</Key>
      </div>

      <div className="chart-body" key={result}>
        <ResponsiveContainer width="100%" height={height}>
          <BarChart
            data={data}
            layout="vertical"
            margin={{ top: 4, right: small ? 14 : 68, bottom: 4, left: 0 }}
            barCategoryGap={small ? '22%' : '26%'}
          >
            <XAxis
              type="number"
              domain={[0, axisMax]}
              tickLine={false}
              axisLine={{ stroke: C.axis }}
              tick={{ fill: C.ink3, fontSize: small ? 10 : 11.5 }}
              tickFormatter={(v) =>
                inHours ? `${(v / 60).toFixed(v % 60 === 0 ? 0 : 1)}h` : `${Math.round(v)}m`
              }
              height={24}
            />
            <YAxis
              type="category"
              dataKey="name"
              width={small ? 118 : 152}
              tickLine={false}
              axisLine={false}
              interval={0}
              tick={makeTick({ selected: shortName(selected), fontSize: small ? 10 : 11.5 })}
            />
            <Tooltip
              cursor={{ fill: 'rgba(13,20,24,.035)' }}
              content={<RowTooltip mode={mode} />}
            />
            {anyTravel && (
              <Bar
                dataKey="travelSeg"
                stackId="t"
                fill={C.travel}
                stroke={C.surface}
                strokeWidth={2}
                maxBarSize={small ? 13 : 17}
                isAnimationActive={!reduced}
                animationDuration={700}
              />
            )}
            <Bar
              dataKey="p25"
              stackId="t"
              fill={C.wait}
              stroke={C.surface}
              strokeWidth={2}
              maxBarSize={small ? 13 : 17}
              isAnimationActive={!reduced}
              animationDuration={700}
              animationBegin={anyTravel ? 120 : 0}
            />
            <Bar
              dataKey="spread"
              stackId="t"
              fill={C.waitSoft}
              stroke={C.surface}
              strokeWidth={2}
              radius={[0, 4, 4, 0]}
              maxBarSize={small ? 13 : 17}
              isAnimationActive={!reduced}
              animationDuration={700}
              animationBegin={anyTravel ? 240 : 120}
            >
              {/* Label only the recommended row: a value on every bar is noise. */}
              <LabelList
                dataKey="name"
                position="right"
                content={(props) => {
                  const { x, y, width, height: h, index } = props
                  if (index !== 0 || small) return null
                  const d = best
                  const txt = rangeText(
                    (d.p25 ?? 0) + d.travelSeg,
                    (d.p75 ?? 0) + d.travelSeg,
                  )
                  if (!txt) return null
                  return (
                    <text
                      x={Number(x) + Number(width) + 8}
                      y={Number(y) + Number(h) / 2}
                      dy={4}
                      fill={C.ink}
                      fontSize={small ? 10.5 : 11.5}
                      fontWeight={650}
                    >
                      {txt}
                    </text>
                  )
                }}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      </ChartFold>

      {/* Outside the fold on purpose: the caveat about estimate error, and the
          named departments that were excluded from the ranking, have to be
          readable without opening anything. */}
      {/* Provenance has to name the model that actually produced the number on
          screen. This line used to credit "the traffic model" in every mode,
          including public transport, where no road speed enters the figure at
          all, and the header pill two inches above correctly says so. A
          car-less reader at 2am is in exactly that mode. */}
      <p className="chart-note">
        {byTotal
          ? (mode === 'transit'
            ? 'Public-transport times are modelled from distance, not routed.'
            : 'Road times are estimated from live detector speeds.')
          : 'No travel estimate was returned, so this ranking answers "shortest queue", not "fastest trip".'}
        {' '}Travel and wait both carry error, so read the ordering, not the exact
        minutes.
        {excluded.length > 0 && (
          <>
            {' '}
            {excluded.map((r) => shortName(r.hospital)).join(', ')}{' '}
            {excluded.length === 1 ? 'is' : 'are'} left out: no honest travel time
            exists.
          </>
        )}
      </p>
    </section>
  )
}

/* ================================================ 2. network-wide gap */

export function NetworkGapChart({ result, selected }) {
  const small = useMediaQuery('(max-width: 720px)')
  const reduced = usePrefersReducedMotion()

  // The refusal, stated where the chart would have been.
  //
  // Without this the empty-data branch below fires and blames the LIVE FEED,
  // "the board did not return enough figures", which is false for a non-now
  // query: the feed is fine, it simply publishes nothing for Sunday 03:00 and
  // the server declined to pretend otherwise. Same slot, same size, and the
  // server's own sentence rather than a guess at one.
  const cmp = result.comparison || { available: true, reason: null }
  if (cmp.available === false) {
    return (
      <section className="card chart-card">
        <div className="chart-head">
          <h3>How unusual is today, department by department?</h3>
        </div>
        <div className="notice notice--info" style={{ marginTop: 14 }}>
          <span>{cmp.reason}</span>
        </div>
        <p className="chart-note">
          The forecast ranges, the 1-in-20 long wait and the travel times on this page
          are all still valid for the hour you asked about. They come from this
          department&apos;s own stored record, not from today&apos;s board.
        </p>
      </section>
    )
  }

  // Signed EXCESS, not delta.
  //
  // This chart used to plot `published − historical median`, while the chips
  // beside it were graded on something else. A department could therefore be
  // drawn an hour from "normal" and labelled "Typical" in the same view. What
  // it plots now is the one quantity the verdict is made of: how far outside
  // its OWN p25–p75 range today's figure sits. A department inside its range
  // draws no bar, because there is nothing to draw.
  const data = result.rows
    .filter((r) => isNum(r.excess) && isNum(r.published) && r.usable)
    .map((r) => {
      const f = gapFacts({
        excess: r.excess, published: r.published, p25: r.p25, p75: r.p75, delta: r.delta,
      })
      return {
        name: shortName(r.hospital),
        full: r.hospital,
        excess: f.excess,
        busier: f.busier === true,
        near: f.near,
        // Negative = below its range, positive = above it. Zero = inside.
        signed: f.excess === 0 ? 0 : (f.busier === true ? f.excess : -f.excess),
        published: r.published,
        p25: r.p25,
        p75: r.p75,
        verdict: r.verdict,
      }
    })
    .sort((a, b) => a.signed - b.signed)

  if (data.length < 3) {
    return (
      <section className="card chart-card">
        <div className="chart-head">
          <h3>How unusual is today, department by department?</h3>
          <p>
            The live Hospital Authority board did not return enough figures to
            compare against right now, so this chart is withheld rather than drawn
            from two or three points.
          </p>
        </div>
      </section>
    )
  }

  const inside = data.filter((d) => d.excess === 0).length
  const peak = Math.max(...data.map((d) => Math.abs(d.signed))) || 5
  const LADDER = [10, 20, 30, 40, 60, 80, 100, 120, 160, 200, 240, 300, 360, 480, 600, 720]
  const m = LADDER.find((v) => v >= peak * 1.08) ?? Math.ceil((peak * 1.08) / 120) * 120
  const gapTicks = [-m, -m / 2, 0, m / 2, m]
  const rowH = small ? 19 : 26
  const height = data.length * rowH + 46
  // data is sorted ascending: furthest BELOW its range first, furthest above last.
  const lowest = data[0]
  const highest = data[data.length - 1]

  return (
    <section className="card chart-card">
      <div className="chart-head">
        <h3>How unusual is today, department by department?</h3>
        <p>
          How far the board figure sits outside each department&apos;s usual range at
          this hour. <b>{inside} of {data.length}</b> are inside their range and
          draw no bar. This is about how unusual today is, not whether the board
          is right.
        </p>
      </div>

      {/* COLOUR RULE. Red meant QUIETER here: bars to the left of zero, the
          best news in the network, painted in the same alarm colour as a
          department running an hour over. Someone scanning for somewhere to go
          reads red as "not this one" and skips the shortest queue on the page.
          Red is now busier-than-normal and nothing else; quieter is a calm
          slate. Direction is also carried by which side of zero a bar sits on
          and by the words in this legend, so hue is never doing it alone. */}
      {/* Folded on a phone, exactly as the ranking chart is, and for the same
          reason: an 18-row bar chart is most of a screen, and the same gap is
          in the table below with the direction written in words. The heading,
          the sentence saying how many departments are quieter than normal, and
          the note underneath all stay on screen either way. What folds is the
          drawing, not the finding. */}
      <ChartFold fold={small} label={`Show the department-by-department chart (${data.length})`}>
      <div className="chart-legend">
        <Key swatch={C.mid}>Inside its usual range, or within {NEAR_MINUTES} min of it</Key>
        <Key swatch={C.crit}>Above its usual range, bars right of zero</Key>
        <Key swatch={C.calm}>Below its usual range, bars left of zero</Key>
      </div>

      <div className="chart-body" key={result}>
        <ResponsiveContainer width="100%" height={height}>
          <BarChart
            data={data}
            layout="vertical"
            margin={{ top: 4, right: small ? 12 : 22, bottom: 4, left: 0 }}
            barCategoryGap={small ? '24%' : '28%'}
          >
            <XAxis
              type="number"
              domain={[-m, m]}
              ticks={gapTicks}
              tickLine={false}
              axisLine={false}
              tick={{ fill: C.ink3, fontSize: small ? 10 : 11.5 }}
              tickFormatter={(v) => {
                if (v === 0) return '0'
                const sign = v > 0 ? '+' : '−'
                const a = Math.abs(v)
                return a >= 90 ? `${sign}${(a / 60).toFixed(1)}h` : `${sign}${Math.round(a)}m`
              }}
              height={24}
            />
            <YAxis
              type="category"
              dataKey="name"
              width={small ? 118 : 152}
              tickLine={false}
              axisLine={false}
              interval={0}
              tick={makeTick({ selected: shortName(selected), fontSize: small ? 10 : 11.5 })}
            />
            <CartesianGrid horizontal={false} stroke={C.grid} strokeWidth={1} />
            <ReferenceLine x={0} stroke={C.axis} strokeWidth={1} />
            <Tooltip cursor={{ fill: 'rgba(13,20,24,.035)' }} content={<GapTooltip />} />
            <Bar
              dataKey="signed"
              maxBarSize={small ? 12 : 15}
              radius={3}
              minPointSize={2}
              isAnimationActive={!reduced}
              animationDuration={750}
            >
              {data.map((d) => (
                <Cell
                  key={d.full}
                  // Grey covers exactly what the chip calls normal: inside the
                  // range, or within the 5-minute tolerance of it. Beyond that,
                  // red only ever means ABOVE its range.
                  fill={
                    d.excess === 0 || d.near
                      ? C.mid
                      : d.busier ? C.crit : C.calm
                  }
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      </ChartFold>

      <p className="chart-note">
        Minutes outside each department&apos;s usual range at this hour. Zero means
        inside, not missing.
        {highest && highest.signed > 0
          ? ` Furthest above: ${highest.name}, ${fmtGap(highest.excess)} past its range.`
          : ''}
        {lowest && lowest.signed < 0
          ? ` Furthest below: ${lowest.name}, ${fmtGap(lowest.excess)} under its range, good news.`
          : ''}
      </p>
    </section>
  )
}
