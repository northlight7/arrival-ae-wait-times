// oxlint-disable react/only-export-components -- shared primitives module:
// the Icon map and the small components below belong together.
import { useEffect, useState } from 'react'
import { usePrefersReducedMotion } from './hooks.js'

/* ------------------------------------------------------------------ icons */

const S = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.7, strokeLinecap: 'round', strokeLinejoin: 'round' }

export const Icon = {
  Check: (p) => (
    <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden {...p}>
      <path d="M3 8.5 6.3 12 13 4.5" {...S} />
    </svg>
  ),
  Alert: (p) => (
    <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden {...p}>
      <path d="M8 1.8 15 14H1L8 1.8Z" {...S} />
      <path d="M8 6.4v3.1" {...S} />
      <circle cx="8" cy="11.6" r=".85" fill="currentColor" stroke="none" />
    </svg>
  ),
  Info: (p) => (
    <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden {...p}>
      <circle cx="8" cy="8" r="6.6" {...S} />
      <path d="M8 7.3v4" {...S} />
      <circle cx="8" cy="4.9" r=".85" fill="currentColor" stroke="none" />
    </svg>
  ),
  Ban: (p) => (
    <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden {...p}>
      <circle cx="8" cy="8" r="6.6" {...S} />
      <path d="M3.6 12.4 12.4 3.6" {...S} />
    </svg>
  ),
  Car: (p) => (
    <svg width="15" height="15" viewBox="0 0 18 16" aria-hidden {...p}>
      <path d="M2.4 10.6h13.2M3.6 10.6 5 6.2a1.4 1.4 0 0 1 1.3-1h5.4a1.4 1.4 0 0 1 1.3 1l1.4 4.4" {...S} />
      <path d="M2.4 10.6v2.2M15.6 10.6v2.2" {...S} />
      <circle cx="5.4" cy="10.6" r="1.2" {...S} />
      <circle cx="12.6" cy="10.6" r="1.2" {...S} />
    </svg>
  ),
  Transit: (p) => (
    <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden {...p}>
      <rect x="3.4" y="2.2" width="9.2" height="9.4" rx="2.2" {...S} />
      <path d="M3.4 8.2h9.2M5.4 14 6.8 11.8M10.6 14 9.2 11.8" {...S} />
      <circle cx="5.9" cy="9.9" r=".75" fill="currentColor" stroke="none" />
      <circle cx="10.1" cy="9.9" r=".75" fill="currentColor" stroke="none" />
    </svg>
  ),
  Pin: (p) => (
    <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden {...p}>
      <path d="M8 14.4s5-4.3 5-8a5 5 0 0 0-10 0c0 3.7 5 8 5 8Z" {...S} />
      <circle cx="8" cy="6.3" r="1.9" {...S} />
    </svg>
  ),
  Clock: (p) => (
    <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden {...p}>
      <circle cx="8" cy="8" r="6.4" {...S} />
      <path d="M8 4.4V8l2.4 1.6" {...S} />
    </svg>
  ),
  Layers: (p) => (
    <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden {...p}>
      <path d="M8 1.9 14.4 5 8 8.1 1.6 5 8 1.9Z" {...S} />
      <path d="m1.6 8.5 6.4 3.1 6.4-3.1" {...S} />
      <path d="m1.6 11.9 6.4 3.1 6.4-3.1" {...S} />
    </svg>
  ),
  Cross: (p) => (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden {...p}>
      <path d="M6.4 1.8h3.2v4.6h4.6v3.2H9.6v4.6H6.4V9.6H1.8V6.4h4.6V1.8Z" fill="currentColor" />
    </svg>
  ),
  Arrow: (p) => (
    <svg width="13" height="13" viewBox="0 0 16 16" aria-hidden {...p}>
      <path d="M3 8h10M9 4l4 4-4 4" {...S} />
    </svg>
  ),
}

/* ----------------------------------------------------------------- pieces */

export function Badge({ tone = 'neutral', icon, children }) {
  return (
    <span className={`badge badge--${tone}`}>
      {icon}
      {children}
    </span>
  )
}

/** A reveal that runs once per key change. CSS-driven so it never blocks paint. */
export function Reveal({ delay = 0, children, className = '', style }) {
  const reduced = usePrefersReducedMotion()
  const [on, setOn] = useState(reduced)
  useEffect(() => {
    if (reduced) { setOn(true); return undefined }
    const t = setTimeout(() => setOn(true), delay)
    return () => clearTimeout(t)
  }, [delay, reduced])
  return (
    <div
      className={className}
      style={{
        ...style,
        opacity: on ? 1 : 0,
        transform: on ? 'none' : 'translateY(18px)',
        transition: reduced ? 'none' : 'opacity .48s cubic-bezier(0,0,0.2,1), transform .48s cubic-bezier(0,0,0.2,1)',
      }}
    >
      {children}
    </div>
  )
}
