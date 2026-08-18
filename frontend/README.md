# Arrival — front end

A single-page React client for the A&E forecast API. Light, clinical, and built
around one editorial rule: **a wait is never shown as a single number.**

## Run it

```bash
npm install
npm run dev      # Vite dev server, proxies /api to http://127.0.0.1:8094
npm run build    # emits dist/, which the API server hosts at /
npm run lint
```

## The rules the UI enforces

These are product constraints, not style preferences. Breaking one is a bug.

1. **Intervals only.** Every wait renders as a p25–p75 range (`lib/format.js`).
   A median appears only with the word "Median" beside it. If an interval cannot
   be built, the UI prints no figure and says why.
2. **The gap is the headline.** The published Hospital Authority figure measures
   patients who have *already* been seen. Every screen that shows a forecast also
   shows how far the published figure sits from it, in plain language
   (`lib/verdict.js`) and to scale (the strip in `components/AnswerCard.jsx`).
3. **Refusal is a designed state.** A 503 from the API renders
   `RefusalCard` — a considered answer, not an error toast.
4. **Pooled data is never passed off as hour-specific.** `pooled: true` puts a
   badge on the answer and a full explanation under it. The narrower
   `basis: "hour_window"` case gets its own, softer note.
5. **Nothing is invented when a field is missing.** `lib/api.js` normalises every
   response field to a value or `null`; the UI degrades to a stated limitation
   rather than rendering `NaN`. A hospital with no honest travel estimate is
   excluded from the total-time ranking and shown apart with the reason — it is
   never counted as a free journey.
6. **Persistent medical-safety framing.** A `tel:999` control sits in the sticky
   header on every screen size, with a full disclaimer in the answer card and the
   footer.

## Layout

- `src/lib/` — `api.js` (fetch + normalise), `format.js` (the interval rules),
  `verdict.js` (the published-vs-reality copy), `hospitals.js`, `hooks.js`, `ui.jsx`.
- `src/components/` — `TopBar`, `Planner`, `AnswerCard`, `RecoCard`, `charts.jsx`,
  `HospitalTable`, `States` (refusal / error / loading), `Methodology`.

Charts are Recharts. The palette is validated for colour-vision deficiency; blue
carries the modelled wait, green the travel leg, and the diverging red/blue pair
is reserved for the direction of the published-figure error. Every chart has a
table twin so no value is reachable by colour alone.
