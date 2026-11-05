import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { CircleAlert, CircleCheck, TriangleAlert, X } from 'lucide-react'
import type { Band } from '../sim/ranges'
import { usePrefersReducedMotion } from './hooks'

export const BAND_WORD: Record<Band, string> = { healthy: 'Healthy', warning: 'Warning', danger: 'Danger' }

export function BandIcon({ band, size = 18 }: { band: Band; size?: number }) {
  const props = { size, strokeWidth: 2.25, 'aria-hidden': true as const }
  if (band === 'healthy') return <CircleCheck {...props} />
  if (band === 'warning') return <CircleAlert {...props} />
  return <TriangleAlert {...props} />
}

/** Status always shows a word and an icon as well as colour. */
export function StatusChip({ band, size = 'md' }: { band: Band; size?: 'sm' | 'md' | 'lg' }) {
  const icon = size === 'lg' ? 22 : size === 'sm' ? 15 : 18
  return (
    <span className={`chip ${band} ${size === 'md' ? '' : `chip-${size}`}`}>
      <BandIcon band={band} size={icon} />
      {BAND_WORD[band]}
    </span>
  )
}

/** A number that glides to its new value, so the readings visibly move. */
export function AnimatedNumber({ value, decimals, duration = 1300 }: { value: number; decimals: number; duration?: number }) {
  const reduced = usePrefersReducedMotion()
  const [shown, setShown] = useState(value)
  const from = useRef(value)
  const raf = useRef(0)
  useEffect(() => {
    cancelAnimationFrame(raf.current)
    const start = from.current
    if (reduced || !Number.isFinite(start)) {
      from.current = value
      setShown(value)
      return
    }
    const t0 = performance.now()
    const step = (now: number) => {
      const p = Math.min(1, (now - t0) / duration)
      const e = 1 - Math.pow(1 - p, 3)
      const v = start + (value - start) * e
      from.current = v
      setShown(v)
      if (p < 1) raf.current = requestAnimationFrame(step)
    }
    raf.current = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf.current)
  }, [value, duration, reduced])
  const f = 10 ** decimals
  const rounded = Math.round(shown * f) / f
  return <>{rounded.toLocaleString('en-MY', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}</>
}

interface SparklineProps {
  values: number[]
  healthy: [number | null, number | null]
  minSpan: number
  band: Band
  format: (v: number) => string
  stepSeconds: number
  label: string
}

const BAND_COLOR: Record<Band, string> = { healthy: 'var(--healthy)', warning: 'var(--warning)', danger: 'var(--danger)' }

/** The last five minutes as a thin line, the healthy range shaded behind it. Hover for any point. */
export function Sparkline({ values, healthy, minSpan, band, format, stepSeconds, label }: SparklineProps) {
  const [hover, setHover] = useState<number | null>(null)
  const ref = useRef<HTMLDivElement>(null)
  const clip = useId()
  const W = 300, H = 46, PAD = 5
  if (values.length < 2) return <div className="spark" />
  let lo = Math.min(...values), hi = Math.max(...values)
  if (hi - lo < minSpan) {
    const mid = (hi + lo) / 2
    lo = mid - minSpan / 2
    hi = mid + minSpan / 2
  }
  const padV = (hi - lo) * 0.12
  lo -= padV
  hi += padV
  const x = (i: number) => (i / (values.length - 1)) * W
  const y = (v: number) => PAD + (1 - (v - lo) / (hi - lo)) * (H - PAD * 2)
  const d = values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join('')
  const bandTop = healthy[1] == null ? -10 : Math.max(-10, y(healthy[1]))
  const bandBottom = healthy[0] == null ? H + 10 : Math.min(H + 10, y(healthy[0]))
  // Shade the healthy range only when one of its edges is inside the chart, so it means something.
  const edgeVisible = (healthy[1] != null && healthy[1] > lo && healthy[1] < hi) || (healthy[0] != null && healthy[0] > lo && healthy[0] < hi)
  const last = values.length - 1
  const hi2 = hover ?? last
  const ago = (last - hi2) * stepSeconds
  const agoText = ago === 0 ? 'now' : ago < 60 ? `${ago} s ago` : `${Math.round(ago / 60)} min ago`
  return (
    <div
      className="spark"
      ref={ref}
      onPointerMove={(e) => {
        const r = ref.current!.getBoundingClientRect()
        setHover(Math.max(0, Math.min(last, Math.round(((e.clientX - r.left) / r.width) * last))))
      }}
      onPointerLeave={() => setHover(null)}
      role="img"
      aria-label={`${label}: trend over the last 5 minutes, now ${format(values[last])}`}
    >
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
        <defs>
          <clipPath id={clip}><rect x="0" y="0" width={W} height={H} /></clipPath>
        </defs>
        {edgeVisible && bandBottom > bandTop && (
          <rect x="0" y={bandTop} width={W} height={bandBottom - bandTop} fill="rgb(47 158 68 / 0.1)" clipPath={`url(#${clip})`} />
        )}
        <path d={d} fill="none" stroke="#6B7A73" strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round" />
        {hover != null && <line x1={x(hover)} x2={x(hover)} y1="0" y2={H} stroke="#14211C" strokeOpacity="0.35" vectorEffect="non-scaling-stroke" />}
      </svg>
      <span
        style={{
          position: 'absolute', left: `${(hi2 / last) * 100}%`, top: y(values[hi2]) * (46 / H), width: 10, height: 10,
          marginLeft: -5, marginTop: -5, borderRadius: '50%', background: BAND_COLOR[band], boxShadow: '0 0 0 2px var(--surface)',
          transition: hover == null ? 'top 600ms cubic-bezier(0.16,1,0.3,1)' : 'none',
        }}
      />
      {hover != null && (
        <span className="spark-tip num" style={{ left: `${Math.min(84, Math.max(16, (hover / last) * 100))}%` }}>
          {format(values[hover])} · {agoText}
        </span>
      )}
    </div>
  )
}

export function Modal({ open, onClose, children, label }: { open: boolean; onClose(): void; children: ReactNode; label: string }) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (open && !d.open) d.showModal()
    if (!open && d.open) d.close()
  }, [open])
  return (
    <dialog
      ref={ref}
      className="modal"
      aria-label={label}
      onCancel={(e) => { e.preventDefault(); onClose() }}
      onClick={(e) => { if (e.target === ref.current) onClose() }}
    >
      {open && children}
    </dialog>
  )
}

export function Lightbox({ src, alt, caption, credit, onClose }: { src: string | null; alt: string; caption?: ReactNode; credit?: string | null; onClose(): void }) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (src && !d.open) d.showModal()
    if (!src && d.open) d.close()
  }, [src])
  return (
    <dialog
      ref={ref}
      className="lightbox"
      aria-label="Photo, full size"
      onCancel={(e) => { e.preventDefault(); onClose() }}
      onClick={(e) => { if (e.target === ref.current) onClose() }}
    >
      {src && (
        <div className="lb">
          <button className="icon-btn lb-x" onClick={onClose} aria-label="Close photo"><X size={22} /></button>
          <img src={src} alt={alt} />
          <div className="lb-cap">
            <span>{caption}</span>
            {credit && <span className="credit">Photo: {credit}</span>}
          </div>
        </div>
      )}
    </dialog>
  )
}

export function BrandMark() {
  return <img className="brand-mark" src="/brand/rhizolah-mark.png" alt="" />
}

export function Toast({ children, onDone }: { children: ReactNode; onDone(): void }) {
  useEffect(() => {
    const t = setTimeout(onDone, 3200)
    return () => clearTimeout(t)
  }, [onDone])
  return <div className="toast" role="status">{children}</div>
}
