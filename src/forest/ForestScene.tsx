import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Box } from 'lucide-react'
import { useForestData } from './forestData'
import { getForestView, hasWebGL, type ForestMode, type ForestView } from './view'

/** Mounts the shared Forest Scene canvas into this panel. */
export function ForestScene({ mode, onView, children }: { mode: ForestMode; onView?(v: ForestView | null): void; children?: ReactNode }) {
  const host = useRef<HTMLDivElement>(null)
  const model = useForestData((s) => s.model)
  const error = useForestData((s) => s.error)
  const [webgl] = useState(hasWebGL)
  const [ready, setReady] = useState(false)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (!model || !host.current || !webgl) return
    const el = host.current
    let view: ForestView | null = null
    // Give the page one frame to paint before the first (heavier) scene build.
    const raf = requestAnimationFrame(() => {
      try {
        view = getForestView(model)
        view.setMode(mode)
        view.attach(el)
        setReady(true)
        onView?.(view)
      } catch {
        setFailed(true)
      }
    })
    return () => {
      cancelAnimationFrame(raf)
      if (view) {
        view.detach(el)
        onView?.(null)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model, mode, webgl])

  const message = !webgl || failed ? '3D view unavailable on this device' : error
  return (
    <>
      <div className="forest-host" ref={host} />
      {message ? (
        <div className="forest-loading" role="alert"><div><Box size={28} />{message}</div></div>
      ) : !ready ? (
        <div className="forest-loading" aria-live="polite"><div><span>Growing the 3D forest…</span><span className="grow" /></div></div>
      ) : null}
      {ready && children}
    </>
  )
}
