import { useEffect, useSyncExternalStore } from 'react'
import { useAppStore } from '../data/store'

/** Addendum I6: hash routes, page keys and titles. */
export type PageKey = 'command' | 'satellite' | 'network' | 'twin' | 'time-travel' | 'ledger' | 'system' | 'about'

export const PAGES: Record<PageKey, { hash: string; key: string; title: string }> = {
  command: { hash: '#/command', key: '1', title: 'Command Center' },
  satellite: { hash: '#/satellite', key: '2', title: 'Satellite Intelligence' },
  network: { hash: '#/network', key: '3', title: 'Sentinel Network' },
  twin: { hash: '#/twin', key: '4', title: 'Digital Twin' },
  'time-travel': { hash: '#/time-travel', key: '5', title: 'Time Travel & Restoration' },
  ledger: { hash: '#/ledger', key: '6', title: 'Carbon Ledger' },
  system: { hash: '#/system', key: '7', title: 'System' },
  about: { hash: '#/about', key: '0', title: 'About' },
}

export const PAGE_KEYS = Object.keys(PAGES) as PageKey[]
export const NAV_PAGES = PAGE_KEYS.filter((k) => k !== 'about')

export function pageForHash(hash: string): PageKey {
  return PAGE_KEYS.find((k) => PAGES[k].hash === hash) ?? 'command'
}

export function pageForKey(key: string): PageKey | null {
  return PAGE_KEYS.find((k) => PAGES[k].key === key) ?? null
}

export function hashForPage(page: PageKey): string {
  return PAGES[page].hash
}

export function navigate(page: PageKey): void {
  if (window.location.hash !== PAGES[page].hash) window.location.hash = PAGES[page].hash
}

function subscribe(cb: () => void): () => void {
  window.addEventListener('hashchange', cb)
  return () => window.removeEventListener('hashchange', cb)
}

/** Current page from the URL hash; mirrors it into the store (ui.page). */
export function useHashRoute(): PageKey {
  const page = useSyncExternalStore(subscribe, () => pageForHash(window.location.hash))
  useEffect(() => {
    if (useAppStore.getState().ui.page !== page) useAppStore.getState().setPage(page)
  }, [page])
  return page
}
