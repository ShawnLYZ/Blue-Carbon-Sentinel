import { useState } from 'react'
import { Button, Modal, Panel, SimulatedBadge, StatusDot, formatMYT } from '@bcs/ui'
import type { Node } from '@bcs/api-types'
import { api } from '../../data/client'
import { apiErrorText, networkErrorText } from '../../data/apiError'
import { useAppStore } from '../../data/store'
import { TYPE_LABEL, sourceText } from '../../data/network'

/**
 * Where the regenerate-key flow is: confirming, done (with the key for a hardware node, shown once),
 * or failed. The key lives only in this component's state and is dropped when the dialog closes; it is
 * never written to the store or to browser storage.
 */
export type KeyFlow =
  | { stage: 'confirm'; node: Node }
  | { stage: 'busy'; node: Node }
  | { stage: 'key'; node: Node; key: string }
  | { stage: 'reprovisioned'; node: Node }
  | { stage: 'error'; node: Node; message: string }

export function KeyDialog({ flow, onClose, onConfirm }: { flow: KeyFlow | null; onClose: () => void; onConfirm: () => void }) {
  const [copied, setCopied] = useState<'yes' | 'failed' | null>(null)
  if (!flow) return null
  const close = () => {
    setCopied(null)
    onClose()
  }
  const copy = async (key: string) => {
    try {
      await navigator.clipboard.writeText(key)
      setCopied('yes')
    } catch {
      setCopied('failed')
    }
  }
  const id = flow.node.id
  const busy = flow.stage === 'busy'
  return (
    <Modal open title={`Regenerate key · ${id}`} onClose={busy ? () => undefined : close}>
      {(flow.stage === 'confirm' || flow.stage === 'busy') && (
        <>
          <p className="page__blurb">
            {flow.node.source === 'simulated'
              ? `Regenerate the broker key for ${id}? The simulator re-provisions the node with its new credentials.`
              : `Regenerate the broker key for ${id}? The current key stops working at once; the new key is shown once and must be flashed to the device.`}
          </p>
          <div className="row-actions">
            <Button onClick={close} disabled={busy}>
              Keep current key
            </Button>
            <Button variant="danger" onClick={onConfirm} disabled={busy}>
              {busy ? 'Regenerating…' : 'Regenerate'}
            </Button>
          </div>
        </>
      )}
      {flow.stage === 'key' && (
        <div className="key-once" data-testid="key-once">
          <p className="page__blurb">
            New key for {id}. It is shown <strong>once</strong> and is not stored in this browser: copy it now.
          </p>
          <code className="key-once__value bcs-mono" data-testid="key-value">
            {flow.key}
          </code>
          <div className="row-actions">
            <Button variant="primary" onClick={() => copy(flow.key)}>
              Copy
            </Button>
            {copied === 'yes' && <span className="hint">Copied.</span>}
            {copied === 'failed' && <span className="hint">Copy failed: select the key and copy it by hand.</span>}
            <Button onClick={close}>Done</Button>
          </div>
        </div>
      )}
      {flow.stage === 'reprovisioned' && (
        <div data-testid="key-reprovisioned">
          <p className="page__blurb">
            Reprovisioned by simulator: the broker identity of {id} was rotated and the Sentinel Simulator picked up the new
            credentials. No key is shown for simulated nodes.
          </p>
          <div className="row-actions">
            <Button onClick={close}>Done</Button>
          </div>
        </div>
      )}
      {flow.stage === 'error' && (
        <>
          <p className="form-error" role="alert">
            {flow.message}
          </p>
          <div className="row-actions">
            <Button onClick={close}>Close</Button>
          </div>
        </>
      )}
    </Modal>
  )
}

/** Every registered node and the camera, with "Regenerate key" per node (design §26 System). */
export function DeviceRegistrySection() {
  const all = useAppStore((s) => s.nodes.items)
  const camera = useAppStore((s) => s.camera.status)
  const [flow, setFlow] = useState<KeyFlow | null>(null)
  const nodes = all.filter((n) => n.status !== 'decommissioned')

  const regenerate = async () => {
    if (!flow || flow.stage !== 'confirm') return
    const node = flow.node
    setFlow({ stage: 'busy', node })
    try {
      const r = await api.POST('/api/v1/nodes/{node_id}/regenerate-key', { params: { path: { node_id: node.id } } })
      if (r.data?.key) setFlow({ stage: 'key', node, key: r.data.key })
      else if (r.data) setFlow({ stage: 'reprovisioned', node })
      else setFlow({ stage: 'error', node, message: apiErrorText(r.error, 'The key was not regenerated.') })
    } catch (e) {
      setFlow({ stage: 'error', node, message: networkErrorText(e) })
    }
  }

  const camFw = camera?.device?.['fw_version']
  return (
    <Panel title="Device registry">
      <div className="metrics-table__wrap">
        <table className="node-table registry-table">
          <thead>
            <tr>
              <th scope="col">Device</th>
              <th scope="col">Source</th>
              <th scope="col">Last seen (MYT)</th>
              <th scope="col">Key</th>
            </tr>
          </thead>
          <tbody>
            {nodes.map((n) => (
              <tr key={n.id} data-testid="registry-row" data-node-id={n.id} title={`${TYPE_LABEL[n.node_type]} · firmware ${n.fw_version ?? 'unknown'}`}>
                <th scope="row">
                  <StatusDot status={n.status === 'online' ? 'ok' : n.status === 'offline' ? 'fail' : 'off'} label={`${n.id} ${n.status}`} />{' '}
                  {n.id}
                </th>
                <td>{n.source === 'simulated' ? <SimulatedBadge /> : <span className="bcs-chip">{sourceText(n.source)}</span>}</td>
                <td className="bcs-mono">{n.last_seen_at ? formatMYT(n.last_seen_at, { seconds: true }).replace(' MYT', '') : 'never'}</td>
                <td>
                  <Button className="panel-action" onClick={() => setFlow({ stage: 'confirm', node: n })}>
                    Regenerate key
                  </Button>
                </td>
              </tr>
            ))}
            <tr data-testid="registry-camera" title={`Firmware ${camFw === undefined || camFw === null ? 'unknown' : String(camFw)}`}>
              <th scope="row">
                <StatusDot status={camera?.online ? 'ok' : 'fail'} label={`camera ${camera?.online ? 'online' : 'offline'}`} /> SentinelCam
              </th>
              <td>
                <span className="bcs-chip">HARDWARE</span>
              </td>
              <td className="bcs-mono">{camera?.last_frame_at ? formatMYT(camera.last_frame_at, { seconds: true }).replace(' MYT', '') : 'never'}</td>
              <td className="hint" title="The camera streams over HTTP on the local network; it has no broker identity.">
                no broker key
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      {nodes.length === 0 && <p className="hint">No nodes are registered yet.</p>}
      <KeyDialog flow={flow} onClose={() => setFlow(null)} onConfirm={regenerate} />
    </Panel>
  )
}
