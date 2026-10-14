// The carbon summary (GET /carbon/summary) shared by the Command Center tiles and the Digital Twin carbon columns.
import { useEffect } from 'react'
import { create } from 'zustand'
import type { CarbonSummary } from '@bcs/api-types'
import { api } from './client'
import { onLiveEvent } from './live'
import { useSettledRev } from './hooks'

export const useCarbonSummary = create<{ summary: CarbonSummary | null }>()(() => ({ summary: null }))

export async function refreshCarbon(): Promise<void> {
  const r = await api.GET('/api/v1/carbon/summary')
  if (r.data) useCarbonSummary.setState({ summary: r.data })
}

/** Keeps the summary fresh: on mount, after captures settle and on ledger events. */
export function useCarbonRefresh(): void {
  const rev = useSettledRev('captures')
  useEffect(() => {
    refreshCarbon().catch(() => undefined)
  }, [rev])
  useEffect(
    () =>
      onLiveEvent((e) => {
        if (e.type === 'ledger.appended' || e.type === 'ledger.verified') refreshCarbon().catch(() => undefined)
      }),
    [],
  )
}
