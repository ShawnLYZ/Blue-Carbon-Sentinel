import createClient from 'openapi-fetch'
import type { paths } from '@bcs/api-types'

/** Typed REST client for the Ground Station; same-origin (Vite proxies /api to 8700 in dev). */
export const api = createClient<paths>({ baseUrl: '' })
