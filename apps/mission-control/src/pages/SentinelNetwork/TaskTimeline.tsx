import { useState } from 'react'
import { Button, Panel, formatMYT } from '@bcs/ui'
import type { Task } from '@bcs/api-types'
import { api } from '../../data/client'
import { apiErrorText, networkErrorText } from '../../data/apiError'
import { useAppStore } from '../../data/store'
import { isOpenTask } from '../../data/network'

const GRID = 5
const COLS = 'ABCDE'
/** Zone labels row by row: A1 … E1, A2 … E5 (addendum F4: columns west to east, rows north to south). */
export const ZONE_GRID: string[] = Array.from({ length: GRID * GRID }, (_, i) => `${COLS[i % GRID]}${Math.floor(i / GRID) + 1}`)
const TIMELINE_SHOWN = 6
const TASKS_SHOWN = 12

const ACK_TEXT: Record<string, string> = {
  pending: 'pending',
  accepted: 'acknowledged',
  completed: 'completed',
  rejected: 'rejected',
  expired: 'expired',
  no_ack: 'no ack',
  released: 'released',
}

type Result = { data?: Task; error?: unknown }

/** One task: status, zone, trigger, per-node acknowledgements with Release, Cancel, and its timeline. */
export function TaskCard({ task, zoneLabel }: { task: Task; zoneLabel: (id: string) => string }) {
  const upsertTask = useAppStore((s) => s.upsertTask)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const open = isOpenTask(task)

  const act = async (call: () => Promise<Result>) => {
    setBusy(true)
    setError(null)
    try {
      const r = await call()
      if (r.data) upsertTask(r.data)
      else setError(apiErrorText(r.error))
    } catch (e) {
      setError(networkErrorText(e))
    }
    setBusy(false)
  }
  const cancel = () => act(() => api.POST('/api/v1/tasks/{task_id}/cancel', { params: { path: { task_id: task.id } } }))
  const release = (node_id: string) =>
    act(() => api.POST('/api/v1/tasks/{task_id}/release', { params: { path: { task_id: task.id } }, body: { node_id } }))

  const timeline = task.timeline.slice(-TIMELINE_SHOWN).reverse()
  return (
    <li className="task-card" data-testid="task-card" data-task-id={task.id} data-status={task.status}>
      <header className="task-card__head">
        <span className={`badge task-status task-status--${task.status}`} data-testid="task-status">
          {task.status}
        </span>
        <strong>{task.zone_id ? zoneLabel(task.zone_id) : task.node_ids.join(', ')}</strong>
        <span className="hint">{task.trigger}</span>
        {open && (
          <Button className="panel-action task-card__cancel" variant="danger" onClick={cancel} disabled={busy}>
            Cancel
          </Button>
        )}
      </header>
      <p className="task-card__reason">{task.reason}</p>
      <p className="hint bcs-mono">
        {formatMYT(task.created_at, { seconds: true })}
        {open ? ` · until ${formatMYT(task.expires_at, { seconds: true })}` : ` · ended ${formatMYT(task.updated_at, { seconds: true })}`}
        {task.cancelled_by ? ` · by ${task.cancelled_by}` : ''}
      </p>
      <ul className="task-card__nodes">
        {task.commands.map((c) => {
          const holds = open && c.ack_status !== 'released' && c.ack_status !== 'no_ack'
          return (
            <li key={c.id} data-ack={c.ack_status}>
              <span className="bcs-mono">{c.node_id}</span>
              <span className="hint">
                {ACK_TEXT[c.ack_status] ?? c.ack_status}
                {c.retries > 0 ? ` · retried ${c.retries}` : ''}
              </span>
              {holds && (
                <Button className="panel-action" onClick={() => release(c.node_id)} disabled={busy} aria-label={`Release ${c.node_id}`}>
                  Release
                </Button>
              )}
            </li>
          )
        })}
      </ul>
      <ol className="task-card__timeline">
        {timeline.map((e, i) => (
          <li key={`${e.at}-${i}`}>
            <span className="bcs-mono">{formatMYT(e.at, { seconds: true })}</span> {e.event.replaceAll('_', ' ')}
            {e.node_id ? ` ${e.node_id}` : ''}
          </li>
        ))}
      </ol>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </li>
  )
}

/** The 5 × 5 zone picker for a manual task; zones no WQ/SP node covers cannot be tasked. */
function ZonePicker({ onPick, busy }: { onPick: (label: string) => void; busy: boolean }) {
  const zones = useAppStore((s) => s.site.site?.zones)
  const coverage = useAppStore((s) => s.coverage.coverage)
  const idFor = (label: string) => zones?.find((z) => z.label === label)?.id ?? null
  const covered = (id: string) => !coverage || coverage.zones.find((z) => z.zone_id === id)?.covered !== false
  return (
    <div className="zone-picker" role="group" aria-label="Pick a zone to task">
      {ZONE_GRID.map((label) => {
        const id = idFor(label)
        // Until the site snapshot arrives there is no zone id to task: the cells stay disabled.
        const ok = id !== null && covered(id)
        return (
          <button
            key={label}
            type="button"
            className="zone-picker__cell"
            data-testid={`zone-${label}`}
            data-covered={ok}
            disabled={busy || !ok}
            title={!id ? 'Loading the site…' : ok ? `Task the nodes covering ${label}` : `No WQ or SP node covers ${label}`}
            onClick={() => onPick(label)}
          >
            {label}
          </button>
        )
      })}
    </div>
  )
}

/** Active and recent tasks, newest first, with Cancel, per-node Release and "Manual task" (design §15). */
export function TaskTimeline({ zoneLabel }: { zoneLabel: (id: string) => string }) {
  const tasks = useAppStore((s) => s.tasks.items)
  const zones = useAppStore((s) => s.site.site?.zones)
  const upsertTask = useAppStore((s) => s.upsertTask)
  const [picking, setPicking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const create = async (label: string) => {
    const zone_id = zones?.find((z) => z.label === label)?.id
    if (!zone_id) {
      setError('The site is still loading; try again in a moment.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const r = await api.POST('/api/v1/tasks', { body: { zone_id } })
      if (r.data) {
        upsertTask(r.data)
        setPicking(false)
      } else setError(apiErrorText(r.error, 'The task was not created.'))
    } catch (e) {
      setError(networkErrorText(e))
    }
    setBusy(false)
  }

  const openCount = tasks.filter(isOpenTask).length
  return (
    <Panel
      title={`Tasks${openCount ? ` · ${openCount} open` : ''}`}
      actions={
        <Button className="panel-action" variant="primary" aria-expanded={picking} onClick={() => (setError(null), setPicking((p) => !p))}>
          Manual task
        </Button>
      }
    >
      {picking && (
        <div className="manual-task">
          <p className="hint">Pick a zone: its covering nodes switch to investigation mode.</p>
          <ZonePicker onPick={create} busy={busy} />
        </div>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {tasks.length === 0 ? (
        <p className="hint">No tasks in the last 10 minutes.</p>
      ) : (
        <ul className="task-list">
          {tasks.slice(0, TASKS_SHOWN).map((t) => (
            <TaskCard key={t.id} task={t} zoneLabel={zoneLabel} />
          ))}
        </ul>
      )}
    </Panel>
  )
}
