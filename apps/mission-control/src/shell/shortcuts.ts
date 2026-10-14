import { useEffect } from 'react'
import { navigate, pageForKey } from './router'

export type ShortcutMap = Record<string, () => void>

function isTyping(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null
  if (!el) return false
  return el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)
}

/** Registers single-key shortcuts on the window (keys are case-insensitive); returns an unregister function. */
export function registerShortcuts(map: ShortcutMap): () => void {
  const lower = Object.fromEntries(Object.entries(map).map(([k, v]) => [k.toLowerCase(), v]))
  const onKey = (e: KeyboardEvent) => {
    if (e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target)) return
    const fn = lower[e.key.toLowerCase()]
    if (fn) {
      e.preventDefault()
      fn()
    }
  }
  window.addEventListener('keydown', onKey)
  return () => window.removeEventListener('keydown', onKey)
}

/** Keys 0-7 navigate (I6) and D toggles the Demo Director. */
export function useGlobalShortcuts(toggleDirector: () => void): void {
  useEffect(() => {
    const map: ShortcutMap = { d: toggleDirector }
    for (const k of '01234567') {
      const page = pageForKey(k)
      if (page) map[k] = () => navigate(page)
    }
    return registerShortcuts(map)
  }, [toggleDirector])
}
