import { flushSync } from 'react-dom'
import { create } from 'zustand'
import { ROUTES, type Route } from '../state/store'
import { prefersReducedMotion } from '../ui/hooks'

export const ROUTE_INFO: Record<Route, { n: number; title: string; sub: string }> = {
  command: { n: 1, title: 'Command Center', sub: 'Overview of our mangrove sites' },
  satellite: { n: 2, title: 'Satellite Intelligence', sub: 'See the forest from space' },
  network: { n: 3, title: 'Sentinel Network', sub: 'Live forest health & camera' },
  twin: { n: 4, title: 'Digital Twin', sub: 'Read every sensor in the forest' },
}

function parseHash(): Route {
  const h = window.location.hash.replace(/^#\/?/, '')
  return (ROUTES as string[]).includes(h) ? (h as Route) : 'command'
}

export const useRoute = create<{ route: Route }>(() => ({ route: parseHash() }))

export type TransitionKind = 'fade' | 'handover' | 'dive' | 'slow-fade' | 'instant'

/** Changes page with a cross-fade (or the map hand-over), keeping the address bar in step. */
export function navigate(route: Route, kind: TransitionKind = 'fade') {
  if (useRoute.getState().route === route) return
  const apply = () => {
    flushSync(() => useRoute.setState({ route }))
    if (parseHash() !== route) history.replaceState(null, '', `#/${route}`)
  }
  const root = document.documentElement
  const canAnimate = typeof document.startViewTransition === 'function' && kind !== 'instant'
  if (!canAnimate || (prefersReducedMotion() && kind === 'fade')) {
    apply()
    return
  }
  const morph = (kind === 'handover' || kind === 'dive') && !prefersReducedMotion()
  const cls = morph ? kind : kind === 'slow-fade' || kind === 'handover' || kind === 'dive' ? 'slow-fade' : ''
  if (cls) root.classList.add(cls)
  const vt = document.startViewTransition(apply)
  vt.finished.finally(() => root.classList.remove('handover', 'dive', 'slow-fade'))
}

export function startRouter() {
  if (!window.location.hash || parseHash() !== window.location.hash.replace(/^#\/?/, '')) {
    history.replaceState(null, '', `#/${parseHash()}`)
  }
  window.addEventListener('hashchange', () => {
    const r = parseHash()
    if (r !== useRoute.getState().route) navigate(r)
  })
  window.addEventListener('keydown', (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return
    const t = e.target as HTMLElement | null
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
    if (document.querySelector('dialog[open]')) return
    const n = Number(e.key)
    if (n >= 1 && n <= 4) navigate(ROUTES[n - 1])
  })
}
