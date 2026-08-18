import { Icon } from '../lib/ui.jsx'
import { isNum } from '../lib/format.js'

export default function TopBar({ traffic, liveFeedOk, mode, apiDown, boardNotAsked }) {
  // Three different things, which must not collapse into one red pill:
  //   - the board was read and answered              → live
  //   - the board was read and did not answer        → unreachable
  //   - the board was never read, because the query  → not read for this hour
  //     is about an hour it publishes nothing for
  // The third used to render as "Live board unreachable", which accuses a feed
  // that is working perfectly and undermines the very refusal the page is
  // making three inches below.
  const feedLabel =
    boardNotAsked
      ? 'Board not read for this hour'
      : liveFeedOk === null
        ? 'Checking the live board'
        : liveFeedOk
          ? 'Live Hospital Authority board'
          : 'Live board unreachable'

  // The traffic pill must describe the number actually on screen, not the feed
  // in the abstract. Road speeds never enter a public-transport estimate, and a
  // green "Live traffic" badge beside a modelled transit time claims a currency
  // that figure does not have. Same when the API has stopped answering: the
  // cached status object is still truthy, so it would otherwise sit there green
  // over a dead page.
  const trafficUsed = traffic?.live && mode !== 'transit' && !apiDown
  const trafficLabel = apiDown
    ? 'Traffic status unknown'
    : mode === 'transit'
      ? 'Traffic not used in transport mode'
      : traffic?.live
        ? `Live traffic${isNum(traffic.detectorsUsed) && traffic.detectorsUsed > 0 ? ` · ${traffic.detectorsUsed} detectors` : ''}`
        : 'Traffic feed offline'

  return (
    <header className="topbar">
      <div className="page topbar__in">
        <div className="brand">
          <span className="brand__mark" aria-hidden>
            <svg width="16" height="16" viewBox="0 0 16 16">
              <path d="M2 8.6h3l1.4-3.4 2.2 6.2L10.2 8.6H14" fill="none" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          <span style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
            <span className="brand__name">Arrival</span>
            <span className="brand__sub">Honest A&amp;E waits for Hong Kong</span>
          </span>
        </div>

        <div className="topbar__spacer" />

        {traffic && (
          <span
            className="pill pill--wide"
            title={
              mode === 'transit'
                ? 'Public-transport times are modelled from distance, not from road speeds. Live traffic does not inform this figure.'
                : traffic.message || undefined
            }
          >
            <span className={`dot ${trafficUsed ? 'dot--live' : 'dot--stale'}`} />
            {trafficLabel}
          </span>
        )}

        <span
          className="pill"
          title={
            boardNotAsked && !apiDown
              ? 'The Hospital Authority publishes one figure, for right now. This answer is about a different hour, so the board was not read and no comparison is shown.'
              : feedLabel
          }
        >
          <span className={`dot ${liveFeedOk && !apiDown && !boardNotAsked ? 'dot--live' : 'dot--stale'}`} />
          {apiDown ? 'Live board unreachable' : feedLabel}
        </span>

        <a className="emergency" href="tel:999">
          <Icon.Cross />
          Life-threatening? Call 999
        </a>
      </div>
    </header>
  )
}
