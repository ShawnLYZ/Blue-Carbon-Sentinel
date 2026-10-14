// Globe markers of the sites (design §7, §26), shown on the Command Center: Kuala Selangor live, the others planned.
import { useEffect } from 'react'
import { Marker } from 'react-map-gl/mapbox'
import { useAppStore } from '../data/store'
import { markerTestId, setMapMounted, toggleSite, useSiteSelection } from '../data/siteSelection'

export function PlannedSiteMarkers() {
  const site = useAppStore((s) => s.site.site)
  const page = useAppStore((s) => s.ui.page)
  const selected = useSiteSelection((s) => s.selected)
  useEffect(() => {
    setMapMounted(true)
    return () => setMapMounted(false)
  }, [])
  if (page !== 'command' || !site) return null
  const items = [
    { id: 'KSL', name: site.name, lng: site.centre.lng, lat: site.centre.lat, live: true },
    ...(site.planned_sites ?? []).map((p) => ({ id: p.id, name: p.name, lng: p.centre.lng, lat: p.centre.lat, live: false })),
  ]
  return (
    <>
      {items.map((i) => (
        <Marker key={i.id} longitude={i.lng} latitude={i.lat} anchor="center">
          <button
            type="button"
            className={`globe-marker${i.live ? ' globe-marker--live' : ''}`}
            data-testid={markerTestId(i.id, 'globe', true)}
            aria-pressed={i.id === selected}
            title={i.live ? `${i.name}: live` : `${i.name}: planned — not yet monitored`}
            onClick={() => toggleSite(i.id)}
          />
        </Marker>
      ))}
    </>
  )
}
