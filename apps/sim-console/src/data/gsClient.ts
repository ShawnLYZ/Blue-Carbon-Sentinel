import type { Coverage, PublicConfig } from '@bcs/api-types'

type Fetch = typeof fetch
const defaultFetch: Fetch = (...a) => fetch(...a)

/** PublicConfig from the Ground Station (same origin; Vite proxies /api in dev). */
export async function loadPublicConfig(fetchImpl: Fetch = defaultFetch): Promise<PublicConfig> {
  const res = await fetchImpl('/api/v1/system/config')
  if (!res.ok) throw new Error(`GET /api/v1/system/config -> ${res.status}`)
  return (await res.json()) as PublicConfig
}

/** Zone coverage and gap suggestions (GET /api/v1/coverage). */
export async function loadCoverage(fetchImpl: Fetch = defaultFetch): Promise<Coverage> {
  const res = await fetchImpl('/api/v1/coverage')
  if (!res.ok) throw new Error(`GET /api/v1/coverage -> ${res.status}`)
  return (await res.json()) as Coverage
}

/** The latest live site raster, or null when the Ground Station has none (404). */
export async function loadLiveFrame(fetchImpl: Fetch = defaultFetch): Promise<Blob | null> {
  const res = await fetchImpl('/api/v1/media/live/latest.jpg', { cache: 'no-store' })
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`GET /api/v1/media/live/latest.jpg -> ${res.status}`)
  return await res.blob()
}
