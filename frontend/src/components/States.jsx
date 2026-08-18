import { Icon } from '../lib/ui.jsx'

/**
 * A refusal is a designed answer, not an error. When the record is too thin to
 * bound a wait, the honest output is "we will not guess" plus the reason,
 * printed with the same care as a real forecast.
 */
export function RefusalCard({ hospital, whenText, triageLabel, onRelax, onPooled }) {
  return (
    <section className="card refusal" style={{ maxWidth: 760 }}>
      <div className="refusal__icon">
        <Icon.Ban width="22" height="22" style={{ color: 'var(--ink-2)' }} />
      </div>
      <h2>We will not guess this one</h2>
      <p>
        There is not enough of a record for <b>{hospital}</b> at {whenText} in the{' '}
        {triageLabel.toLowerCase()} queue to put an honest interval around your wait,
        so we decline instead of guessing.
      </p>
      <ul>
        <li>
          <Icon.Info />
          <span>Small departments in the small hours have too few snapshots.</span>
        </li>
        <li>
          <Icon.Info />
          <span>A wait built on a thin slice is noise with a decimal point, not a
            cautious estimate.</span>
        </li>
        <li>
          <Icon.Alert />
          <span>This says nothing about how busy the department is. If you need care,
            go. We decline to forecast.</span>
        </li>
      </ul>
      <div className="refusal__actions">
        {onRelax && (
          <button type="button" className="btn-ghost" onClick={onRelax}>
            <Icon.Clock /> Try the current hour instead
          </button>
        )}
        {onPooled && (
          <button type="button" className="btn-ghost" onClick={onPooled}>
            <Icon.Layers /> Try the less-urgent queue
          </button>
        )}
        <a className="emergency" href="tel:999" style={{ height: 42 }}>
          <Icon.Cross /> In an emergency, call 999
        </a>
      </div>
    </section>
  )
}

export function ErrorCard({ message, onRetry }) {
  return (
    <section className="card refusal" style={{ maxWidth: 760 }}>
      <div className="refusal__icon">
        <Icon.Alert width="22" height="22" style={{ color: 'var(--crit)' }} />
      </div>
      <h2>The forecast service did not answer</h2>
      <p>{message} Nothing on this page is a stand-in for a real answer, so nothing is shown.</p>
      <div className="refusal__actions">
        <button type="button" className="btn-primary" onClick={onRetry}>Try again</button>
        <a className="emergency" href="tel:999" style={{ height: 46 }}>
          <Icon.Cross /> In an emergency, call 999
        </a>
      </div>
    </section>
  )
}

/**
 * Shown while a search runs, in place of the previous answer.
 *
 * The old behaviour dimmed the previous result and left it on screen. Greyed
 * numbers still read as numbers, so someone who changed their starting district
 * could take a wait computed for somewhere else as the new answer. Nothing
 * quantitative appears here on purpose, only the query being run.
 */
export function LoadingCard({ whenText, triageLabel, originLabel, mode }) {
  return (
    <section className="card answer" aria-busy="true" aria-live="polite">
      <span className="eyebrow">Working out the fastest hospital</span>
      <div className="answer__where" style={{ marginTop: 4 }}>
        Checking all 18 A&amp;E departments.
      </div>
      <div className="answer__when">
        {[whenText, triageLabel, originLabel && `from ${originLabel}`,
          mode === 'transit' ? 'by public transport' : 'by car or taxi']
          .filter(Boolean).join(' · ')}
      </div>

      <div className="skel" style={{ height: 58, width: '62%', margin: '20px 0 14px', animationDelay: '0ms' }} />
      <div className="skel" style={{ height: 12, width: '86%', marginBottom: 8, animationDelay: '60ms' }} />
      <div className="skel" style={{ height: 12, width: '54%', animationDelay: '120ms' }} />
      <div className="skel" style={{ height: 46, width: '100%', margin: '26px 0 12px', borderRadius: 10, animationDelay: '180ms' }} />
      <div className="skel" style={{ height: 12, width: '70%', animationDelay: '240ms' }} />

      {/* "adding live travel times" was printed in every mode. In public
          transport there is nothing live in the figure at all. It is modelled
          from distance, and with no starting point there is no travel step to
          describe. Name only the work actually being done. */}
      <p className="origin-head origin-note" style={{ marginTop: 22 }}>
        Reading the live board for every department against its record.
      </p>
    </section>
  )
}
