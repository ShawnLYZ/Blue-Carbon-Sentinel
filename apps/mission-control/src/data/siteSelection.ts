// The selected site of the Command Center, shared by the globe markers and the Sites panel (the card host).
import { create } from 'zustand'

export const useSiteSelection = create<{ selected: string | null; mapMounted: boolean }>()(() => ({ selected: null, mapMounted: false }))

export const selectSite = (id: string | null) => useSiteSelection.setState({ selected: id })
export const setMapMounted = (mapMounted: boolean) => useSiteSelection.setState({ mapMounted })

/** Toggle: clicking the open site closes its card. */
export function toggleSite(id: string): void {
  useSiteSelection.setState((s) => ({ selected: s.selected === id ? null : id }))
}

/**
 * The data-testid of a site's marker: the globe marker carries `site-marker-{id}` when the map is mounted,
 * the panel list carries it only without a map (otherwise `site-list-{id}`), so it is never duplicated.
 */
export function markerTestId(id: string, el: 'globe' | 'list', mapMounted: boolean): string {
  return el === 'globe' || !mapMounted ? `site-marker-${id}` : `site-list-${id}`
}
