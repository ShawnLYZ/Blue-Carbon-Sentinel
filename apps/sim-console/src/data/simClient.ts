import type {
  ConfirmBody, FaultBody, HealthBody, InstallBody, MoveBody, NaturePatch, OverrideBody, RecordingStartBody,
  ScenarioApplied, ScenarioApply, ScenarioCatalogue, ScenarioRunBody, SessionList, SimNature, SimNode,
  SimRecording, SimReplay, SimState,
} from './types'

export class SimError extends Error {
  readonly status: number
  readonly code: string | null
  constructor(status: number, message: string, code: string | null = null) {
    super(message)
    this.status = status
    this.code = code
  }
}

/** The I1 envelope's message when there is one, else "<method> <path> -> <status>". */
async function errorFrom(res: Response, method: string, path: string): Promise<SimError> {
  try {
    const body = (await res.json()) as { error?: { code?: string; message?: string } }
    if (body?.error?.message) return new SimError(res.status, body.error.message, body.error.code ?? null)
  } catch {
    // not JSON
  }
  return new SimError(res.status, `${method} ${path} -> ${res.status}`)
}

/** Typed fetch wrapper over the simulator control API (K1). Pass PublicConfig.sim_url as `baseUrl`. */
export function createSimClient(baseUrl: string, fetchImpl: typeof fetch = (...a) => fetch(...a)) {
  const root = `${baseUrl.replace(/\/+$/, '')}/api/v1`
  async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
    const res = await fetchImpl(`${root}${path}`, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    if (!res.ok) throw await errorFrom(res, method, path)
    return (res.status === 204 ? undefined : await res.json()) as T
  }
  const zone = (z: string) => `/zones/${encodeURIComponent(z)}/scenario`
  const node = (n: string) => `/nodes/${encodeURIComponent(n)}`
  return {
    state: () => call<SimState>('GET', '/state'),
    scenarios: () => call<ScenarioCatalogue>('GET', '/scenarios'),
    applyScenario: (z: string, b: ScenarioApply) => call<ScenarioApplied>('POST', zone(z), b),
    clearScenario: (z: string) => call<unknown>('DELETE', zone(z)),
    setOverride: (n: string, b: OverrideBody) => call<SimNode>('POST', `${node(n)}/overrides`, b),
    clearOverride: (n: string, p: string) => call<SimNode>('DELETE', `${node(n)}/overrides/${encodeURIComponent(p)}`),
    setHealth: (n: string, b: HealthBody) => call<SimNode>('POST', `${node(n)}/health`, b),
    injectFault: (n: string, b: FaultBody) => call<SimNode>('POST', `${node(n)}/faults`, b),
    clearFault: (n: string, kind: string) => call<SimNode>('DELETE', `${node(n)}/faults/${encodeURIComponent(kind)}`),
    patchNature: (b: NaturePatch) => call<{ nature: SimNature; fast_forward: number }>('PATCH', '/nature', b),
    install: (b: InstallBody) => call<unknown>('POST', '/lifecycle/install', b),
    move: (n: string, b: MoveBody) => call<unknown>('POST', `/lifecycle/${encodeURIComponent(n)}/move`, b),
    remove: (n: string, b: ConfirmBody) => call<unknown>('POST', `/lifecycle/${encodeURIComponent(n)}/remove`, b),
    startRecording: (b: RecordingStartBody) => call<SimRecording>('POST', '/recording/start', b),
    stopRecording: () => call<unknown>('POST', '/recording/stop'),
    sessions: () => call<SessionList>('GET', '/sessions'),
    replay: (id: string) => call<{ replay: SimReplay | null }>('POST', `/sessions/${encodeURIComponent(id)}/replay`),
    stopReplay: () => call<unknown>('POST', '/replay/stop'),
    runScenario: (b: ScenarioRunBody) => call<unknown>('POST', '/scenario-runs', b),
    scenarioRun: (id: string) => call<unknown>('GET', `/scenario-runs/${encodeURIComponent(id)}`),
  }
}

export type SimClient = ReturnType<typeof createSimClient>
