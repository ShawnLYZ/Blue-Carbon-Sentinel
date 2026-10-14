import { useEffect, useState } from 'react'
import { Slider } from '@bcs/ui'
import { api } from '../data/client'
import { useAppStore } from '../data/store'

export const EXAGGERATION_MIN = 0.25
export const EXAGGERATION_MAX = 3
export const PERSIST_DEBOUNCE_MS = 400

/** The PATCH call; openapi-fetch resolves with `error` on HTTP failures instead of rejecting. */
export type PatchExaggeration = (value: number) => Promise<{ error?: unknown }>

const patchSettings: PatchExaggeration = (value) =>
  api.PATCH('/api/v1/system/settings', { body: { vertical_exaggeration: value } })

/** Why a save failed, readable for the operator. */
export function saveErrorText(error: unknown): string {
  if (error && typeof error === 'object') {
    const e = error as { error?: { message?: string }; detail?: unknown; message?: string }
    if (typeof e.error?.message === 'string') return e.error.message
    if (typeof e.message === 'string') return e.message
    if (typeof e.detail === 'string') return e.detail
  }
  return 'the Ground Station did not accept the value'
}

export interface ExaggerationSaver {
  /** Queue `value`; it is sent after the debounce, replacing any unsent value. */
  schedule: (value: number) => void
  /** Send the unsent value now (if any). */
  flush: () => void
}

/**
 * Debounced persistence of the exaggeration (US 42). HTTP errors (openapi-fetch `error`) and
 * network failures both reach `onError`; a successful save reports `onSaved`.
 */
export function createExaggerationSaver(opts: {
  patch?: PatchExaggeration
  delayMs?: number
  onError: (message: string) => void
  onSaved?: () => void
}): ExaggerationSaver {
  const patch = opts.patch ?? patchSettings
  const delay = opts.delayMs ?? PERSIST_DEBOUNCE_MS
  let timer: ReturnType<typeof setTimeout> | undefined
  let pending: number | null = null

  const send = () => {
    if (timer !== undefined) clearTimeout(timer)
    timer = undefined
    if (pending === null) return
    const value = pending
    pending = null
    patch(value).then(
      (res) => {
        if (res.error !== undefined && res.error !== null) opts.onError(saveErrorText(res.error))
        else opts.onSaved?.()
      },
      (e: unknown) => opts.onError(e instanceof Error ? e.message : 'network error'),
    )
  }

  return {
    schedule: (value) => {
      pending = value
      if (timer !== undefined) clearTimeout(timer)
      timer = setTimeout(send, delay)
    },
    flush: send,
  }
}

/**
 * Vertical exaggeration (US 42). The surface uniform follows the store at once; the value is saved
 * with PATCH /system/settings after the slider rests, and a pending save is flushed (not dropped)
 * when the control unmounts. A failed save is shown under the slider and logged.
 */
export function ExaggerationControl() {
  const value = useAppStore((s) => s.twin.exaggeration)
  const setExaggeration = useAppStore((s) => s.setExaggeration)
  const [error, setError] = useState<string | null>(null)
  const [saver] = useState(() =>
    createExaggerationSaver({
      onError: (msg) => {
        console.warn('vertical exaggeration not saved:', msg)
        setError(msg)
      },
      onSaved: () => setError(null),
    }),
  )

  useEffect(() => () => saver.flush(), [saver])

  const onChange = (v: number) => {
    const next = Math.min(EXAGGERATION_MAX, Math.max(EXAGGERATION_MIN, v))
    setExaggeration(next)
    saver.schedule(next)
  }

  return (
    <div className="exaggeration-control">
      <Slider
        label="Vertical exaggeration"
        unit="×"
        value={value}
        min={EXAGGERATION_MIN}
        max={EXAGGERATION_MAX}
        step={0.05}
        onChange={onChange}
      />
      {error && (
        <span className="exaggeration-control__error" role="status">
          Not saved: {error}
        </span>
      )}
    </div>
  )
}
