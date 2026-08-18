import { useEffect, useRef, useState } from 'react'

/* ------------------------------------------------------------------ hooks */

export function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(() =>
    typeof matchMedia === 'function'
      ? matchMedia('(prefers-reduced-motion: reduce)').matches
      : false,
  )
  useEffect(() => {
    if (typeof matchMedia !== 'function') return undefined
    const mq = matchMedia('(prefers-reduced-motion: reduce)')
    const on = () => setReduced(mq.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return reduced
}

export function useMediaQuery(query) {
  const [match, setMatch] = useState(() =>
    typeof matchMedia === 'function' ? matchMedia(query).matches : false,
  )
  useEffect(() => {
    if (typeof matchMedia !== 'function') return undefined
    const mq = matchMedia(query)
    const on = () => setMatch(mq.matches)
    on()
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [query])
  return match
}

/**
 * Animates a numeric target. Motion here serves comprehension: the digits
 * settling makes it read as a measurement rather than a printed constant.
 */
export function useCountUp(target, { duration = 750, decimals = 0 } = {}) {
  const reduced = usePrefersReducedMotion()
  const valid = typeof target === 'number' && Number.isFinite(target)
  // Start from zero so the first run reads as a measurement settling, unless
  // motion is reduced, where the figure must be present with no animation.
  const start = valid && !reduced ? 0 : valid ? target : 0
  const [v, setV] = useState(start)
  const fromRef = useRef(start)

  useEffect(() => {
    if (!valid) return undefined
    if (reduced || duration <= 0) {
      fromRef.current = target
      setV(target)
      return undefined
    }
    const from = fromRef.current
    if (from === target) return undefined
    const t0 = performance.now()
    let raf = 0
    const tick = (t) => {
      const p = Math.min(1, (t - t0) / duration)
      const e = 1 - Math.pow(1 - p, 3)
      const next = from + (target - from) * e
      setV(next)
      if (p < 1) raf = requestAnimationFrame(tick)
      else fromRef.current = target
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [target, duration, reduced, valid])

  if (!valid) return null
  const f = Math.pow(10, decimals)
  return Math.round(v * f) / f
}
