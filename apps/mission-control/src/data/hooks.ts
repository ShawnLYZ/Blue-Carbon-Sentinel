import { useCallback, useEffect, useState } from 'react'
import type { Calibration } from '@bcs/api-types'
import { apiErrorText, networkErrorText } from './apiError'
import { api } from './client'
import { useAppStore } from './store'

/** Coalesces the burst of events one capture produces into a single refetch. */
export const REV_SETTLE_MS = 120

/** The `rev` counter of `kind`, updated at most once per settle window. */
export function useSettledRev(kind: 'captures' | 'calibration' | 'history' | 'ai'): number {
  const rev = useAppStore((s) => s.rev[kind])
  const [settled, setSettled] = useState(rev)
  useEffect(() => {
    if (rev === settled) return
    const t = setTimeout(() => setSettled(rev), REV_SETTLE_MS)
    return () => clearTimeout(t)
  }, [rev, settled])
  return settled
}

export interface CalibrationState {
  /** The active calibration; `null` until loaded. */
  calibration: Calibration | null
  /** Why the last fetch failed; retried on the next calibration event or resync. */
  error: string | null
  set: (c: Calibration) => void
}

/** The active calibration, refetched on `calibration.updated` and on every resync. */
export function useCalibration(): CalibrationState {
  const rev = useSettledRev('calibration')
  const [calibration, setCal] = useState<Calibration | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    api.GET('/api/v1/calibration').then(
      (r) => {
        if (!live) return
        if (r.data) {
          setCal(r.data)
          setError(null)
        } else setError(apiErrorText(r.error, 'Could not load the calibration.'))
      },
      (e: unknown) => {
        if (live) setError(networkErrorText(e))
      },
    )
    return () => {
      live = false
    }
  }, [rev])
  const set = useCallback((c: Calibration) => {
    setCal(c)
    setError(null)
  }, [])
  return { calibration, error, set }
}

export function calibrationLabel(cal: Pick<Calibration, 'mode'> | null, error: string | null = null): string {
  if (!cal) return error ? 'Calibration unavailable' : 'Calibration loading…'
  return cal.mode === 'four_corner' ? 'Four-corner calibration' : 'Default calibration'
}
