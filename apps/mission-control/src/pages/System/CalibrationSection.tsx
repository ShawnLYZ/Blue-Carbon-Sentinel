import { useState } from 'react'
import { Button, formatMYTDateTime, Modal, Panel } from '@bcs/ui'
import { api } from '../../data/client'
import { apiErrorText, networkErrorText } from '../../data/apiError'
import { calibrationLabel, useCalibration } from '../../data/hooks'

/** The active calibration and "Reset to default" (design §26 System, addendum F4). */
export function CalibrationSection() {
  const { calibration: cal, error: loadError, set: setCal } = useCalibration()
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reset = async () => {
    setBusy(true)
    setError(null)
    try {
      const r = await api.POST('/api/v1/calibration/reset')
      if (r.data) setCal(r.data.calibration)
      else setError(apiErrorText(r.error))
    } catch (e) {
      setError(networkErrorText(e))
    }
    setBusy(false)
    setConfirm(false)
  }

  return (
    <Panel title="Calibration">
      <dl className="kv-list" data-testid="calibration-status">
        <dt>Mode</dt>
        <dd>{calibrationLabel(cal, loadError)}</dd>
        <dt>Since</dt>
        <dd className="bcs-mono">{cal ? formatMYTDateTime(cal.created_at, { seconds: true }) : '—'}</dd>
        <dt>Frame</dt>
        <dd className="bcs-mono">{cal ? `${cal.frame_w} × ${cal.frame_h} px` : '—'}</dd>
        {cal?.corners_px && (
          <>
            <dt>Corners (px)</dt>
            <dd className="bcs-mono">{cal.corners_px.map((p, i) => `${i + 1}: (${p[0]}, ${p[1]})`).join('  ')}</dd>
            <dt>North edge</dt>
            <dd className="bcs-mono">
              {cal.north_edge !== null && cal.north_edge !== undefined
                ? `edge ${cal.north_edge + 1} (corner ${cal.north_edge + 1} → ${((cal.north_edge + 1) % 4) + 1})`
                : '—'}
            </dd>
          </>
        )}
      </dl>
      {loadError && (
        <p className="form-error" role="alert">
          {loadError} It is retried on the next calibration event.
        </p>
      )}
      <p className="hint">Set a four-corner calibration on the Satellite Intelligence page.</p>
      <div className="row-actions">
        <Button variant="danger" onClick={() => setConfirm(true)} disabled={busy}>
          Reset to default
        </Button>
      </div>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <Modal open={confirm} title="Reset calibration?" onClose={() => setConfirm(false)}>
        <p className="page__blurb">
          Reset to the default calibration (centred square, top = north)? The current baseline was taken under the active
          calibration and will no longer be compared.
        </p>
        <div className="row-actions">
          <Button onClick={() => setConfirm(false)}>Cancel</Button>
          <Button variant="danger" onClick={reset} disabled={busy}>
            {busy ? 'Resetting…' : 'Reset to default'}
          </Button>
        </div>
      </Modal>
    </Panel>
  )
}
