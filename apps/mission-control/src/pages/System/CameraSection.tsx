import { useState } from 'react'
import { Button, formatMYTDateTime, Panel, StatusDot, Toggle } from '@bcs/ui'
import type { CameraSettings, CameraSettingsPatch, CameraStatus } from '@bcs/api-types'
import { api } from '../../data/client'
import { apiErrorText, networkErrorText } from '../../data/apiError'
import { useAppStore } from '../../data/store'

const FRAME_SIZES: CameraSettings['frame_size'][] = ['VGA', 'SVGA', 'XGA', 'HD', 'SXGA']

type Result = { data?: CameraStatus; error?: unknown }

function deviceField(device: CameraStatus['device'], key: string): string | null {
  const v = device?.[key]
  return v === undefined || v === null ? null : String(v)
}

/** Camera status, exposure/white-balance lock, desired settings and reconnect (design §26 System). */
export function CameraSection() {
  const status = useAppStore((s) => s.camera.status)
  const setCameraStatus = useAppStore((s) => s.setCameraStatus)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)

  const run = async (what: string, call: () => Promise<Result>, done?: string) => {
    setBusy(what)
    setError(null)
    setNote(null)
    try {
      const r = await call()
      if (r.data) setCameraStatus(r.data)
      if (r.error) setError(apiErrorText(r.error))
      else if (done) setNote(done)
    } catch (e) {
      setError(networkErrorText(e))
    }
    setBusy(null)
  }

  const patch = (body: CameraSettingsPatch) => run('settings', () => api.PATCH('/api/v1/camera/settings', { body }))
  const setLock = (locked: boolean) => run('lock', () => api.POST('/api/v1/camera/lock', { body: { locked } }))
  const reconnect = () =>
    run('reconnect', async () => {
      const r = await api.POST('/api/v1/camera/reconnect')
      return { error: r.error }
    }, 'Reconnect requested.')

  if (!status) {
    return (
      <Panel title="Camera">
        <p className="page__blurb">Loading camera status…</p>
      </Panel>
    )
  }

  const d = status.desired
  const fw = deviceField(status.device, 'fw_version')
  const rssi = deviceField(status.device, 'rssi_dbm')
  const disabled = busy !== null

  return (
    <Panel title="Camera">
      <dl className="kv-list" data-testid="camera-status">
        <dt>State</dt>
        <dd>
          <StatusDot status={status.online ? 'ok' : 'fail'} label={status.online ? 'online' : 'offline'} />{' '}
          {status.online ? 'online' : 'offline'}
        </dd>
        <dt>Since</dt>
        <dd className="bcs-mono">{formatMYTDateTime(status.since, { seconds: true })}</dd>
        <dt>Host</dt>
        <dd className="bcs-mono">{status.host}</dd>
        <dt>Resolved IP</dt>
        <dd className="bcs-mono">{status.resolved_ip ?? '—'}</dd>
        <dt>Last frame</dt>
        <dd className="bcs-mono">{status.last_frame_at ? formatMYTDateTime(status.last_frame_at, { seconds: true }) : 'never'}</dd>
        <dt>Frames in</dt>
        <dd className="bcs-mono">{status.fps_in.toFixed(1)} fps</dd>
        <dt>Exposure / WB</dt>
        <dd>{status.locked ? 'locked (confirmed by the camera)' : 'not locked'}</dd>
        {fw && (
          <>
            <dt>Firmware</dt>
            <dd className="bcs-mono">{fw}</dd>
          </>
        )}
        {rssi && (
          <>
            <dt>Wi-Fi RSSI</dt>
            <dd className="bcs-mono">{rssi} dBm</dd>
          </>
        )}
      </dl>

      <div className="settings-grid">
        <Toggle checked={status.locked} onChange={setLock} disabled={disabled} label="Lock exposure and white balance" />
        <label className="field">
          <span>Frame size</span>
          <select
            value={d.frame_size}
            disabled={disabled}
            onChange={(e) => patch({ frame_size: e.target.value as CameraSettings['frame_size'] })}
          >
            {FRAME_SIZES.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>JPEG quality (lower is better)</span>
          <input
            type="number"
            min={4}
            max={63}
            defaultValue={d.jpeg_quality}
            key={d.jpeg_quality}
            disabled={disabled}
            onBlur={(e) => {
              const v = Number(e.target.value)
              if (Number.isFinite(v) && v !== d.jpeg_quality) void patch({ jpeg_quality: v })
            }}
          />
        </label>
        <Toggle checked={d.vflip} onChange={(v) => patch({ vflip: v })} disabled={disabled} label="Flip (vertical)" />
        <Toggle checked={d.hmirror} onChange={(v) => patch({ hmirror: v })} disabled={disabled} label="Mirror (horizontal)" />
      </div>
      <p className="hint">Settings are kept while the camera is offline and re-applied when it reconnects.</p>
      <div className="row-actions">
        <Button onClick={reconnect} disabled={disabled}>
          Reconnect
        </Button>
        {busy && <span className="hint">Working…</span>}
        {note && <span className="hint">{note}</span>}
      </div>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </Panel>
  )
}
