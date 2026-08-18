import { fmtInt } from '../lib/format.js'
import { NEAR_MINUTES } from '../lib/verdict.js'
import { Icon } from '../lib/ui.jsx'

function Stat({ v, k }) {
  return (
    <div className="stat">
      <div className="stat__v tnum">{v}</div>
      <div className="stat__k">{k}</div>
    </div>
  )
}

export default function Methodology({ stats, traffic, mode }) {
  // The six notes below are the reference essay. They fold behind one tap on
  // every screen so the page never reads as a wall of prose: the counts, the
  // one-line summary and the safety line stay visible by default.
  const body = (
    <div className="method-body">
      <p>
        <b>What the board figure is.</b> The Hospital Authority publishes one
        estimate per department, for someone arriving now. It is not a record of
        people already treated.
      </p>
      <p>
        <b>What this adds.</b> We store the board every 15 minutes for{' '}
        {fmtInt(stats?.dates) ?? 'hundreds of'} days, so we can say whether today
        is normal for this department at this hour. The range is the middle half
        of what this department has published at this hour in the past. It is a
        range of published estimates, not of real waits.
      </p>
      <p>
        <b>How normal is decided.</b> Each department is judged against its own
        usual range at that hour, never against a fixed number of minutes. Inside
        the range is normal. Outside it, we measure how far. Under{' '}
        <b>{NEAR_MINUTES} minutes</b> outside still counts as normal, because the
        feed reports in coarse steps. Past that, the measure is the width of the
        department&apos;s own range: up to <b>one and a half times</b> that width
        is <em>above</em> or <em>below</em> usual, beyond that is <em>far</em>{' '}
        above or below.
      </p>
      <p>
        <b>Why an interval, never a number.</b> A queue is a range, not a single
        value, and one unlabelled number would imply a precision the data does not
        have. Where a median appears, it is labelled.
      </p>
      <p>
        <b>What we cannot tell you.</b> Nobody records what individual patients
        actually waited, so we cannot say whether the board is right, only
        whether today is usual. &ldquo;Far from normal&rdquo; means far from its
        own history, not proven wrong.
      </p>
      <p>
        <b>When the record is thin.</b> Too few observations, and the forecast
        pools every hour of the week and says so on screen. If even that is too
        thin, the tool refuses to answer, and that is the correct output.
      </p>
      {/* The detector count and the territory average speed describe the ROAD
          feed. Printing them under "Travel times" while the page is showing
          public-transport figures credits 700-odd road detectors for a number
          that never touched one, and the header pill on the same screen
          correctly says traffic is not used in this mode. Say which model
          produced the times on screen, and only then what the other feed is. */}
      {mode === 'transit' ? (
        <p>
          <b>Travel times, in public-transport mode.</b> Hong Kong has no free
          point-to-point routing service, so these times are not routed: nothing
          here knows which MTR line or bus you would take. Each is modelled from
          distance, an assumed speed and a flat allowance for walking and waiting.{' '}
          <b>No live data of any kind is in them.</b>
          {traffic?.live
            ? " The road-detector feed is live, but nothing in this mode uses it, so no figure here depends on it."
            : " The road-detector feed is not used in this mode, so no figure here depends on it."}
        </p>
      ) : traffic?.message ? (
        <p>
          <b>Travel times, by road.</b>{' '}
          {traffic.message.charAt(0).toUpperCase() + traffic.message.slice(1)}. These
          are the speeds the car and taxi estimates above are built from.
        </p>
      ) : null}
    </div>
  )

  return (
    <section className="card chart-card">
      <div className="chart-head">
        <h3>What this is built on</h3>
        <p>
          The numbers come from Hong Kong&apos;s open A&amp;E waiting-time feed,
          sampled every 15 minutes and stored. Nothing is simulated.
        </p>
      </div>

      <div className="stat-row" style={{ marginTop: 16 }}>
        <Stat v={fmtInt(stats?.dates) ?? 'n/a'} k="days sampled" />
        <Stat v={fmtInt(stats?.snapshots) ?? 'n/a'} k="15-minute snapshots" />
        <Stat v={fmtInt(stats?.hospitals) ?? 'n/a'} k="A&E departments" />
        <Stat v={fmtInt(stats?.observations) ?? 'n/a'} k="hospital observations" />
      </div>

      <details className="chart-fold chart-fold--method">
        <summary>How the numbers work</summary>
        <div className="chart-fold__body">{body}</div>
      </details>

      <div className="safety" style={{ marginTop: 18 }}>
        <Icon.Alert />
        <span>
          <b>Not medical advice.</b> This forecasts queues, not conditions. It cannot
          tell you whether you need an emergency department. For anything that looks
          life-threatening, <b>call 999</b>.
        </span>
      </div>
    </section>
  )
}
