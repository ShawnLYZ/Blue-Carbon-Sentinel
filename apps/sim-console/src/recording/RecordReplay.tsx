import { useCallback, useEffect, useState } from 'react'
import { Button, formatMYTDateTime } from '@bcs/ui'
import { getState, refreshState, useConsole } from '../data/store'
import type { Session } from '../data/types'

/** A replay can finish within a second; the banner stays at least this long after it was started here. */
export const REPLAY_BANNER_MIN_MS = 4000

function stamp(d = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `console-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`
}

function elapsed(since: string, now: number): string {
  const s = Math.max(0, Math.floor((now - new Date(since).getTime()) / 1000))
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}

/** Header: record/stop, the session list, replay/stop. Replays are labelled "REPLAY · SIMULATED". */
export function RecordReplay() {
  const recWs = useConsole((s) => s.status?.recording)
  const recState = useConsole((s) => s.state?.recording)
  const replayWs = useConsole((s) => s.status?.replay)
  const replayState = useConsole((s) => s.state?.replay)
  const hasStatus = useConsole((s) => s.status !== null)
  const online = useConsole((s) => s.sim === 'online')
  const recording = hasStatus ? recWs : recState
  const replay = hasStatus ? replayWs : replayState
  const [sessions, setSessions] = useState<Session[]>([])
  const [listOpen, setListOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!recording && startedAt === null) return
    const t = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(t)
  }, [recording, startedAt])
  useEffect(() => {
    if (!error) return
    const t = setTimeout(() => setError(null), 5000)
    return () => clearTimeout(t)
  }, [error])

  const loadSessions = useCallback(async () => {
    const client = getState().client
    if (!client) return
    try {
      setSessions(await client.sessions())
    } catch (e) {
      setError((e as Error).message)
    }
  }, [])
  useEffect(() => {
    if (listOpen) void loadSessions()
  }, [listOpen, loadSessions])

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    try {
      await fn()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
      refreshState()
    }
  }

  const start = () => act(() => getState().client!.startRecording({ name: stamp() }))
  const stop = () =>
    act(async () => {
      await getState().client!.stopRecording()
      await loadSessions()
      setListOpen(true)
    })
  const replaySession = (id: string) =>
    act(async () => {
      await getState().client!.replay(id)
      setStartedAt(Date.now())
      setListOpen(false)
    })
  const stopReplay = () =>
    act(async () => {
      await getState().client!.stopReplay()
      setStartedAt(null)
    })

  const showBanner = !!replay || (startedAt !== null && now - startedAt < REPLAY_BANNER_MIN_MS)

  return (
    <div className="recrep" data-testid="record-replay-controls">
      {recording ? (
        <>
          <span className="recrep__rec bcs-mono" data-testid="recording-status">
            <span className="recrep__dot" aria-hidden="true" /> REC {elapsed(recording.started_at, now)} · {recording.messages} msgs
          </span>
          <Button variant="danger" disabled={busy} onClick={() => void stop()}>
            Stop
          </Button>
        </>
      ) : (
        <Button disabled={busy || !online} onClick={() => void start()}>
          <span className="recrep__dot" aria-hidden="true" /> Record
        </Button>
      )}
      <div className="recrep__sessions">
        <Button aria-expanded={listOpen} onClick={() => setListOpen((o) => !o)}>
          Sessions ▾
        </Button>
        {listOpen && (
          <div className="recrep__popover bcs-panel" role="dialog" aria-label="Sessions">
            {sessions.length === 0 && <div className="hint">No recorded sessions yet.</div>}
            {sessions.map((s) => (
              <div key={s.id} className="session-row" data-testid="session-row">
                <div className="session-row__main">
                  <div className="session-row__name">{s.name}</div>
                  <div className="hint bcs-mono">
                    {formatMYTDateTime(s.created_at, { seconds: true })} · {s.duration_s.toFixed(0)} s · {s.message_count} msgs
                    {s.uploaded ? ' · uploaded' : s.upload_error ? ' · upload failed' : ''}
                  </div>
                </div>
                <Button disabled={busy} onClick={() => void replaySession(s.id)}>
                  Replay
                </Button>
              </div>
            ))}
          </div>
        )}
      </div>
      {showBanner && (
        <>
          <span className="replay-banner" data-testid="replay-banner">REPLAY · SIMULATED</span>
          {replay && (
            <Button disabled={busy} onClick={() => void stopReplay()}>
              End replay ({replay.sent}/{replay.total})
            </Button>
          )}
        </>
      )}
      {error && <span className="recrep__error" role="alert">{error}</span>}
    </div>
  )
}
