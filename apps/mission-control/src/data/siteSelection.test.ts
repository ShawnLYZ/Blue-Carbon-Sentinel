import { beforeEach, describe, expect, test } from 'vitest'
import { markerTestId, selectSite, setMapMounted, toggleSite, useSiteSelection } from './siteSelection'

beforeEach(() => {
  selectSite(null)
  setMapMounted(false)
})

describe('site selection', () => {
  test('toggle opens and closes a site', () => {
    toggleSite('KKP')
    expect(useSiteSelection.getState().selected).toBe('KKP')
    toggleSite('KCH')
    expect(useSiteSelection.getState().selected).toBe('KCH')
    toggleSite('KCH')
    expect(useSiteSelection.getState().selected).toBeNull()
  })
  test('the marker testid is carried by exactly one element', () => {
    expect(markerTestId('KKP', 'list', false)).toBe('site-marker-KKP')
    expect(markerTestId('KKP', 'list', true)).toBe('site-list-KKP')
    expect(markerTestId('KKP', 'globe', true)).toBe('site-marker-KKP')
  })
})
