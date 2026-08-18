import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import TopBar from './components/TopBar.jsx'
import Planner from './components/Planner.jsx'
import AnswerCard from './components/AnswerCard.jsx'
import TopThreeCard from './components/TopThreeCard.jsx'
import { NetworkGapChart, RankingChart } from './components/charts.jsx'
import HospitalTable from './components/HospitalTable.jsx'
import Methodology from './components/Methodology.jsx'
import { ErrorCard, LoadingCard, RefusalCard } from './components/States.jsx'
import { Reveal } from './lib/ui.jsx'
import {
  ApiError, SparseDataError, fetchCorpusStats, fetchHospitals,
  fetchTrafficStatus, normaliseResult, runQuery,
} from './lib/api.js'
import { DISTRICTS } from './lib/hospitals.js'
import { hkNow, isNum, todayName, whenLabel } from './lib/format.js'
import { TRIAGE } from './lib/verdict.js'

const DEFAULT_ORIGIN = 'central'

export default function App() {
  const [hospitals, setHospitals] = useState([])
  const [stats, setStats] = useState(null)
  const [traffic, setTraffic] = useState(null)

  const [triage, setTriage] = useState('t3')
  const [useNow, setUseNow] = useState(true)
  const [day, setDay] = useState(() => todayName())
  const [hour, setHour] = useState(() => hkNow().hour)
  const [mode, setMode] = useState('car')
  const [originId, setOriginId] = useState(DEFAULT_ORIGIN)
  const [originTouched, setOriginTouched] = useState(false)
  const [geo, setGeo] = useState({ state: 'idle', coords: null })

  const [result, setResult] = useState(null)
  const [status, setStatus] = useState('loading')
  const [errorText, setErrorText] = useState('')
  const [sparseFor, setSparseFor] = useState(null)
  const [busy, setBusy] = useState(false)
  const [answered, setAnswered] = useState(null)
  const [detailHospital, setDetailHospital] = useState(null)

  const seq = useRef(0)
  const abortRef = useRef(null)

  /* Bootstrap: load hospitals, then start querying as soon as we have them. */

  useEffect(() => {
    const ac = new AbortController()
    fetchHospitals(ac.signal)
      .then((list) => { setHospitals(list) })
      .catch(() => {
        if (!ac.signal.aborted) {
          setStatus('error')
          setErrorText('The list of hospitals could not be loaded.')
        }
      })
    fetchCorpusStats(ac.signal).then(setStats).catch(() => {})
    fetchTrafficStatus(ac.signal).then(setTraffic).catch(() => {})
    return () => ac.abort()
  }, [])

  /* origin */

  const origin = useMemo(() => {
    if (originId === '__geo') return geo.coords
    if (!originId) return null
    const d = DISTRICTS.find((x) => x.id === originId)
    return d ? { lat: d.lat, lon: d.lon } : null
  }, [originId, geo.coords])

  const originLabel = useMemo(() => {
    if (originId === '__geo') return 'your current location'
    const d = DISTRICTS.find((x) => x.id === originId)
    return d ? d.name : null
  }, [originId])

  const requestGeo = useCallback(() => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) {
      setGeo({ state: 'unsupported', coords: null }); return
    }
    setGeo((g) => ({ ...g, state: 'pending' }))
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setGeo({
          state: 'ok',
          coords: {
            lat: pos.coords.latitude,
            lon: pos.coords.longitude,
            // Carried so the planner can show how precise the fix actually is.
            // A ±2 km reading and a ±10 m reading justify very different trust
            // in the travel times built on top of them.
            accuracy: pos.coords.accuracy,
          },
        })
        setOriginTouched(true); setOriginId('__geo')
      },
      () => setGeo({ state: 'denied', coords: null }),
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 300000 },
    )
  }, [])

  /* Query: auto-picks the first hospital for the API call so the ranking is complete. */

  const submit = useCallback(
    async (override = {}) => {
      // The API needs a hospital to build from; pick the first one available.
      const h = override.hospital ?? hospitals[0]?.name
      if (!h) return

      const nowDay = useNow ? todayName() : day
      const nowHour = useNow ? hkNow().hour : hour
      const t = override.triage ?? triage
      const d = override.day ?? nowDay
      const hr = override.hour ?? nowHour

      const mine = ++seq.current
      abortRef.current?.abort()
      const ac = new AbortController()
      abortRef.current = ac

      setBusy(true)
      // Clear the previous answer before asking for a new one.
      //
      // Dimming the old result and leaving it on screen reads as "these numbers,
      // slightly greyed" rather than "these numbers are stale". Someone who
      // changes their starting district and glances back sees a wait time that
      // was computed for somewhere else. In a tool people use under stress, a
      // visibly empty loading state is safer than a plausible wrong one.
      setResult(null)
      setAnswered(null)
      setDetailHospital(null)
      setSparseFor(null)
      setStatus('loading')

      const body = { hospital: h, triage: t, day: d, hour: hr, mode, origin }

      try {
        const raw = await runQuery(body, ac.signal)
        if (mine !== seq.current) return
        const normalised = normaliseResult(raw, { hospitals, origin })
        setResult(normalised)
        setAnswered({ triage: t, day: d, hour: hr, mode, originId })
        setStatus('ready')
        setSparseFor(null)
        setDetailHospital(normalised.ranked[0]?.hospital ?? null)
      } catch (e) {
        if (e?.name === 'AbortError' || mine !== seq.current) return
        setResult(null)
        if (e instanceof SparseDataError) {
          setSparseFor({ hospital: e.hospital || h, day: d, hour: hr, triage: t })
          setStatus('sparse')
        } else {
          setErrorText(e instanceof ApiError ? e.message : 'The request failed.')
          setStatus('error')
        }
      } finally {
        if (mine === seq.current) setBusy(false)
      }
    },
    // `result` is deliberately absent: submit() no longer reads it, and keeping
    // it here rebuilt this callback on every answer.
    [triage, day, hour, useNow, mode, origin, originId, hospitals],
  )

  // Fire the first query as soon as hospitals arrive.
  const booted = useRef(false)
  useEffect(() => {
    if (booted.current || hospitals.length === 0) return
    booted.current = true
    submit()
  }, [hospitals, submit])

  /* labels */

  const effDay = useNow ? todayName() : day
  const effHour = useNow ? hkNow().hour : hour
  const whenText = result?.hourLabel
    || (answered ? whenLabel(answered.day, answered.hour) : whenLabel(effDay, hour))
  const answeredTriage = result?.triage || answered?.triage || triage
  const triageLabel = TRIAGE.find((x) => x.key === answeredTriage)?.label ?? 'Urgent'

  /* ------------------------------------------------------------------ *
   * What the answer on screen is allowed to describe.
   *
   * Every result component below is fed from `answered`, the query that
   * actually produced the numbers. It is never fed the live form state.
   * Feeding them the live state made the page recompute its PROSE while keeping its
   * NUMBERS: flipping to Public transport without pressing the button silently
   * relabelled every travel figure "public transport, modelled" over minutes
   * computed from road speeds, while the amber banner directly above insisted
   * "the answer below still describes the previous query". One of the two was
   * lying; now they agree, and the banner is the one telling the truth.
   * ------------------------------------------------------------------ */
  const shownMode = answered?.mode ?? mode
  const shownOriginId = answered?.originId ?? originId
  const shownOriginLabel = shownOriginId === '__geo'
    ? 'your current location'
    : (DISTRICTS.find((x) => x.id === shownOriginId)?.name ?? null)
  // True only when the origin is a real geolocation fix. A manually chosen
  // district is also not "your position", but it was chosen on purpose, so
  // only the untouched default gets the explicit "not your position" caveat.
  const shownOriginIsGeo = shownOriginId === '__geo'
  const shownOriginAssumed = !originTouched && shownOriginId === DEFAULT_ORIGIN

  const pickChanged = !!answered && (
    answered.triage !== triage
    || answered.mode !== mode
    || answered.originId !== originId
    || answered.day !== effDay
    || answered.hour !== effHour
  )
  // Following the clock, the answer can go stale without anyone touching the
  // form: the Hong Kong hour simply rolls over. That is still an out-of-date
  // answer, but "your selections have changed" would be a lie about it, so the
  // banner names which of the two happened.
  const clockOnly = !!answered && useNow
    && answered.triage === triage && answered.mode === mode
    && answered.originId === originId
    && (answered.day !== effDay || answered.hour !== effHour)
  const dirty = pickChanged && !busy
  // "The board was never read" is not "the board is down". See TopBar.
  const boardNotAsked = !!result && result.comparison?.available === false
  const liveFeedOk = result && !boardNotAsked
    ? isNum(result.primary?.published) || result.rows.some((r) => isNum(r.published))
    : (result ? null : null)

  // Find the top 3 from the ranked list and the current detail row.
  const top3 = useMemo(() => {
    if (!result?.ranked) return []
    return result.ranked.slice(0, 3)
  }, [result])

  const detailRow = useMemo(() => {
    if (!detailHospital || !result?.ranked) return null
    return result.ranked.find((r) => r.hospital === detailHospital) ?? null
  }, [detailHospital, result])

  return (
    <>
      {busy && <div className="progress" role="status" aria-label="Loading forecast" />}
      <TopBar
        traffic={traffic}
        liveFeedOk={liveFeedOk}
        mode={answered?.mode ?? mode}
        apiDown={status === 'error'}
        boardNotAsked={boardNotAsked}
      />

      <Planner
        triage={triage}
        setTriage={setTriage}
        useNow={useNow}
        setUseNow={setUseNow}
        day={effDay}
        setDay={setDay}
        hour={hour}
        setHour={setHour}
        mode={mode}
        setMode={setMode}
        originId={originId}
        setOriginId={(v) => { setOriginTouched(true); setOriginId(v) }}
        geoState={geo.state}
        geoCoords={geo.coords}
        requestGeo={requestGeo}
        onSubmit={submit}
        busy={busy}
        dirty={dirty}
        dirtyIsClock={clockOnly}
        answeredWhen={answered ? whenLabel(answered.day, answered.hour) : null}
      />

      <main className="page main">
        {status === 'loading' && !result && (
          <LoadingCard
            whenText={whenText}
            triageLabel={triageLabel}
            originLabel={originLabel}
            mode={mode}
          />
        )}

        {status === 'error' && !result && (
          <ErrorCard message={errorText} onRetry={() => submit()} />
        )}

        {status === 'sparse' && !result && sparseFor && (
          <RefusalCard
            hospital={sparseFor.hospital}
            whenText={whenLabel(sparseFor.day, sparseFor.hour)}
            triageLabel={TRIAGE.find((x) => x.key === sparseFor.triage)?.label ?? 'Urgent'}
            onRelax={
              sparseFor.hour !== hkNow().hour
                ? () => { setUseNow(true); submit({ day: todayName(), hour: hkNow().hour }) }
                : null
            }
            onPooled={
              sparseFor.triage === 't3'
                ? () => { setTriage('t45'); submit({ triage: 't45' }) }
                : null
            }
          />
        )}

        {result && (
          <>
            {/* TOP 3 RECOMMENDATIONS */}
            <Reveal>
              <TopThreeCard
                result={result}
                top3={top3}
                detailHospital={detailHospital}
                onSelect={(h) => setDetailHospital(h)}
                whenText={whenText}
                triageLabel={triageLabel}
                mode={shownMode}
                originLabel={shownOriginLabel}
                originAssumed={shownOriginAssumed}
              />
            </Reveal>

            {/* DETAIL: gap analysis for the selected hospital */}
            {detailRow && (
              <Reveal delay={90}>
                <div style={{ marginTop: 18 }}>
                  <AnswerCard
                    row={detailRow}
                    whenText={whenText}
                    triageLabel={triageLabel}
                    mode={shownMode}
                    originLabel={shownOriginLabel}
                    originIsGeo={shownOriginIsGeo}
                    originAssumed={shownOriginAssumed}
                    comparison={result.comparison}
                    /* The row's own tail, not the top-level one: this card shows
                       the top-RANKED hospital, which is usually not the queried
                       one, and a long wait must never be shown under the wrong
                       department's name. */
                    tail={detailRow.tail}
                  />
                </div>
              </Reveal>
            )}

            <div className="section-gap" />

            {/* CHARTS + FULL TABLE */}
            <Reveal delay={170}>
              <div>
                <div className="chart-grid">
                  <RankingChart result={result} mode={shownMode} selected={detailHospital} />
                  <NetworkGapChart result={result} selected={detailHospital} />
                </div>
                <div className="section-gap" />
                <HospitalTable
                  result={result}
                  mode={shownMode}
                  detailHospital={detailHospital}
                  onPick={(h) => setDetailHospital(h)}
                />
              </div>
            </Reveal>
          </>
        )}

        <div className="section-gap" />
        <Reveal delay={240}>
          <Methodology stats={stats} traffic={traffic} mode={shownMode} />
        </Reveal>
      </main>

      <footer className="page footer">
        <div className="footer__grid">
          <p>
            <strong>Arrival</strong> compares each emergency department&apos;s published
            wait with its usual range at this hour, adds the 1-in-20 long wait, and adds
            travel time. Source: Hong Kong&apos;s public A&amp;E feed. Independent of the
            Hospital Authority.
          </p>
          <p>
            <strong>Not medical advice.</strong> If a condition may be life-threatening,
            call <a href="tel:999" style={{ color: '#a02b2b', fontWeight: 650 }}>999</a>{' '}
            immediately rather than travelling.
          </p>
        </div>
      </footer>
    </>
  )
}
