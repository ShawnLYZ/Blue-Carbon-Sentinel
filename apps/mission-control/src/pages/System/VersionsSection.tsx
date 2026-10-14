import { Panel } from '@bcs/ui'
import { useAppStore } from '../../data/store'
import { useAiStatus } from './AiSection'

/** Read-only versions: Ground Station, camera firmware, simulator, AI model ids and the demo-time scale. */
export function VersionsSection() {
  const status = useAppStore((s) => s.system.status)
  const config = useAppStore((s) => s.system.config)
  const device = useAppStore((s) => s.camera.status?.device)
  const { status: ai } = useAiStatus()
  const fw = device?.fw_version
  const models = ai ? [...new Set(ai.keys.map((k) => k.model))] : []
  if (ai?.ollama.model) models.push(ai.ollama.model)
  const demo = status?.demo_time_scale ?? config?.demo_time_scale
  return (
    <Panel title="Versions">
      <dl className="kv-list" data-testid="versions-section">
        <dt>Ground Station</dt>
        <dd className="bcs-mono" data-testid="version-gs">
          {status?.version ?? config?.version ?? 'unknown'}
        </dd>
        <dt>Camera firmware</dt>
        <dd className="bcs-mono" data-testid="version-fw">
          {fw === undefined || fw === null ? 'unknown (camera offline)' : String(fw)}
        </dd>
        <dt>Simulator</dt>
        <dd className="bcs-mono" data-testid="version-sim">
          not reported to the Ground Station
        </dd>
        <dt>AI models</dt>
        <dd className="bcs-mono" data-testid="version-models">
          {models.length ? models.join(', ') : 'none in use'}
        </dd>
        <dt>Demo-time scale</dt>
        <dd data-testid="version-demo">{demo === undefined ? 'unknown' : demo ? 'on' : 'off'}</dd>
      </dl>
    </Panel>
  )
}
