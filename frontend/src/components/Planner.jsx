import { useState } from 'react'
import { Icon } from '../lib/ui.jsx'
import { DAYS, deviceIsOffHongKongTime, hourLabel } from '../lib/format.js'
import { DISTRICTS } from '../lib/hospitals.js'
import { TRIAGE } from '../lib/verdict.js'

const HK_BBOX = { latMin: 22.1, latMax: 22.65, lonMin: 113.80, lonMax: 114.50 }

function inHongKong({ lat, lon }) {
  return lat >= HK_BBOX.latMin && lat <= HK_BBOX.latMax
    && lon >= HK_BBOX.lonMin && lon <= HK_BBOX.lonMax
}

/**
 * Name the fix in words a person recognises.
 *
 * There is no reverse-geocoding service here and inventing one would mean
 * sending the reader's coordinates to a third party. The district list is
 * already on the client, so the nearest entry gives a truthful landmark,
 * phrased as "near X" because it is a nearest-neighbour label, not an address.
 */
function describeFix({ lat, lon }) {
  if (!inHongKong({ lat, lon })) return 'a point outside Hong Kong'
  let best = null
  let bestKm = Infinity
  for (const d of DISTRICTS) {
    // Equirectangular approximation: at HK's latitude, over a few km, the
    // error against haversine is far below the precision of the label.
    const x = (d.lon - lon) * Math.cos((lat * Math.PI) / 180) * 111.32
    const y = (d.lat - lat) * 110.57
    const km = Math.hypot(x, y)
    if (km < bestKm) { bestKm = km; best = d }
  }
  if (!best) return 'an unnamed point in Hong Kong'
  return bestKm < 1.2 ? best.name : `near ${best.name}`
}

function Seg({ options, value, onChange, ariaLabel }) {
  return (
    <div className="seg" role="group" aria-label={ariaLabel}>
      {options.map((o) => (
        <button
          key={o.key}
          type="button"
          className={`seg__btn${value === o.key ? ' is-on' : ''}`}
          aria-pressed={value === o.key}
          title={o.help || undefined}
          onClick={() => onChange(o.key)}
        >
          {o.icon}
          {o.label}
        </button>
      ))}
    </div>
  )
}

export default function Planner({
  triage, setTriage,
  useNow, setUseNow, day, setDay, hour, setHour,
  mode, setMode,
  originId, setOriginId, geoState, geoCoords, requestGeo,
  onSubmit, busy, dirty, dirtyIsClock, answeredWhen,
}) {
  const [timeOpen, setTimeOpen] = useState(false)

  // Forecasts are keyed by hour-of-week in Hong Kong time, so the clock we
  // follow is Hong Kong's, not the device's. Say which, and say so loudly when
  // the device disagrees, otherwise someone checking from abroad reads an
  // answer for the wrong hour with nothing on screen to warn them.
  const offHkTime = useNow && deviceIsOffHongKongTime()
  const whenSummary = useNow
    ? `${day} ${hourLabel(hour)} Hong Kong time, following the clock`
    : `${day} ${hourLabel(hour)} Hong Kong time`

  return (
    <div className="planner-band">
      <div className="page planner">
        <div className="planner__lede">
          <h1>Which emergency room should you actually go to?</h1>
          <p>
            Hospitals publish one wait figure, with no sense of whether it is
            normal. This shows its usual range at this hour, the 1-in-20 long
            wait, and the journey there.
          </p>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault()
            onSubmit()
          }}
        >
          <div className="planner__grid">
            <div className="field">
              <span className="field__label">How urgent</span>
              <Seg
                ariaLabel="How urgent"
                value={triage}
                onChange={setTriage}
                options={TRIAGE.map((t) => ({ key: t.key, label: t.label, help: t.help }))}
              />
            </div>

            <div className="field">
              <span className="field__label">Arriving</span>
              <Seg
                ariaLabel="Arriving"
                value={timeOpen ? 'pick' : 'now'}
                onChange={(k) => {
                  const pick = k === 'pick'
                  setTimeOpen(pick)
                  setUseNow(!pick)
                }}
                options={[
                  { key: 'now', label: 'Now', icon: <Icon.Clock /> },
                  { key: 'pick', label: 'Another time' },
                ]}
              />
            </div>

            {timeOpen && (
              <div className="field" />  /* keep grid balanced */
            )}
          </div>

          {timeOpen && (
            <div className="planner__grid" style={{ marginTop: 12 }}>
              <div className="field">
                <label className="field__label" htmlFor="day">Day</label>
                <select id="day" className="control" value={day} onChange={(e) => setDay(e.target.value)}>
                  {DAYS.map((d) => <option key={d} value={d}>{d}</option>)}
                </select>
              </div>
              <div className="field">
                <label className="field__label" htmlFor="hour">Hour of arrival</label>
                <select id="hour" className="control" value={hour} onChange={(e) => setHour(Number(e.target.value))}>
                  {Array.from({ length: 24 }, (_, i) => (
                    <option key={i} value={i}>{hourLabel(i)}</option>
                  ))}
                </select>
              </div>
              <div />
            </div>
          )}

          <div className="planner__row2">
            <div className="field">
              <span className="field__label">Getting there by</span>
              <Seg
                ariaLabel="Getting there by"
                value={mode}
                onChange={setMode}
                options={[
                  { key: 'car', label: 'Car or taxi', icon: <Icon.Car /> },
                  { key: 'transit', label: 'Public transport', icon: <Icon.Transit /> },
                ]}
              />
            </div>

            <div className="field">
              <label className="field__label" htmlFor="origin">Starting from</label>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <select
                  id="origin"
                  className="control"
                  style={{ flex: '1 1 170px', minWidth: 0 }}
                  value={originId}
                  onChange={(e) => setOriginId(e.target.value)}
                >
                  <option value="">Anywhere (no travel time)</option>
                  {geoState === 'ok' && <option value="__geo">My current location</option>}
                  {DISTRICTS.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                </select>
                <button
                  type="button"
                  className={`btn-ghost${originId === '__geo' ? ' is-on' : ''}`}
                  onClick={requestGeo}
                  disabled={geoState === 'pending'}
                >
                  <Icon.Pin />
                  {geoState === 'pending' ? 'Locating…' : 'Use my location'}
                </button>
              </div>
              {/* Confirm back exactly what was read from the device. A travel
                  time is only as good as the point it starts from, and a wrong
                  or stale fix should be visible before it silently reorders the
                  ranking, so show the fix, name the nearest recognisable area,
                  and give a one-click way to reject it. */}
              {geoState === 'ok' && geoCoords && originId === '__geo' && (
                <div className="geo-fix">
                  <Icon.Pin />
                  <span>
                    Using your location: <b>{describeFix(geoCoords)}</b>
                    <span className="muted">
                      {' '}({geoCoords.lat.toFixed(4)}, {geoCoords.lon.toFixed(4)}
                      {typeof geoCoords.accuracy === 'number'
                        ? `, ±${Math.round(geoCoords.accuracy)} m`
                        : ''})
                    </span>
                    {!inHongKong(geoCoords) && (
                      <span className="geo-fix__warn">
                        {' '}That point is outside Hong Kong, so travel times will not
                        be meaningful. Pick a district instead.
                      </span>
                    )}
                    {/* A coarse fix, typically wifi or cell positioning rather
                        than GPS, can be off by more than the distance between
                        two hospitals, which is enough to reorder the ranking. */}
                    {inHongKong(geoCoords)
                      && typeof geoCoords.accuracy === 'number'
                      && geoCoords.accuracy > 1000 && (
                      <span className="geo-fix__warn">
                        {' '}This fix is only accurate to about{' '}
                        {(geoCoords.accuracy / 1000).toFixed(1)} km, which is far
                        enough to change the ranking. Pick a district if it looks wrong.
                      </span>
                    )}
                  </span>
                  <button
                    type="button"
                    className="geo-fix__undo"
                    onClick={() => setOriginId('')}
                  >
                    Not right?
                  </button>
                </div>
              )}

              {geoState === 'denied' && (
                <p className="origin-note">
                  Location was declined, which is fine. Pick a district above and the
                  ranking still works.
                </p>
              )}
              {geoState === 'unsupported' && (
                <p className="origin-note">
                  This browser will not share a location here. Pick a district instead.
                </p>
              )}
            </div>

            <div className="field" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <button className="btn-primary" type="submit" disabled={busy}>
                {busy ? 'Checking…' : (originId ? 'Find the fastest hospital' : 'Find the shortest queue')}
              </button>
            </div>
          </div>

          <p className="origin-note" style={{ marginTop: 10 }}>
            {dirty ? (
              <span className="pending">
                <Icon.Alert style={{ verticalAlign: '-3px', marginRight: 6 }} />
                {dirtyIsClock ? (
                  <>
                    The Hong Kong hour has moved on. The answer below is for{' '}
                    {answeredWhen || 'the earlier hour'}.
                  </>
                ) : (
                  <>
                    Your selections have changed. The answer below is for the
                    previous query
                    {answeredWhen ? <> ({answeredWhen})</> : null}.
                  </>
                )}
                {' '}Nothing has been recalculated. Press{' '}
                <b>{originId ? 'Find the fastest hospital' : 'Find the shortest queue'}</b> to update.
              </span>
            ) : (
              <>
                <Icon.Clock style={{ verticalAlign: '-2px', marginRight: 6 }} />
                {whenSummary}
                {offHkTime && (
                  <span className="muted">
                    {' '}Your device is on a different time zone, so this is the
                    Hong Kong hour, not your local one.
                  </span>
                )}
              </>
            )}
          </p>
        </form>
      </div>
    </div>
  )
}
