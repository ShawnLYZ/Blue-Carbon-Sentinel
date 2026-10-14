import { useEffect, useState, type MouseEvent } from 'react'
import { Button } from '@bcs/ui'
import type { CalibrationResult } from '@bcs/api-types'
import { api } from '../../data/client'
import { apiErrorCode, apiErrorText, networkErrorText } from '../../data/apiError'
import { useAppStore } from '../../data/store'
import { setBaselineNow } from './BaselineControls'
import { edgesOf, sortClockwise, toImagePoint, type Pt } from './cornerGeometry'

const FRAME_URL = '/api/v1/calibration/frame.jpg'

type FrameState =
  | { kind: 'loading' }
  | { kind: 'ready'; url: string }
  | { kind: 'unavailable'; message: string }

/** Fetches one raw camera frame (409 camera_offline when the camera has never sent one). */
function useCalibrationFrame(): FrameState {
  const [state, setState] = useState<FrameState>({ kind: 'loading' })
  useEffect(() => {
    let live = true
    let url: string | null = null
    fetch(FRAME_URL, { cache: 'no-store' }).then(
      async (r) => {
        if (!live) return
        if (r.ok) {
          url = URL.createObjectURL(await r.blob())
          if (live) setState({ kind: 'ready', url })
          else URL.revokeObjectURL(url)
        } else {
          const body: unknown = await r.json().catch(() => null)
          const offline = apiErrorCode(body) === 'camera_offline'
          setState({
            kind: 'unavailable',
            message: offline ? 'No camera frame: the camera is offline.' : apiErrorText(body, 'The camera frame could not be loaded.'),
          })
        }
      },
      (e: unknown) => {
        if (live) setState({ kind: 'unavailable', message: networkErrorText(e) })
      },
    )
    return () => {
      live = false
      if (url) URL.revokeObjectURL(url)
    }
  }, [])
  return state
}

function RecalibrationPrompts({ result, onClose }: { result: CalibrationResult; onClose: () => void }) {
  const [baselineMsg, setBaselineMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const setNow = async () => {
    setBusy(true)
    const err = await setBaselineNow()
    setBusy(false)
    setBaselineMsg(err ?? 'Baseline set from the latest evidence-grade capture.')
  }
  return (
    <div className="corner-picker__done" role="status">
      <p>
        <strong>Four-corner calibration is active.</strong>
      </p>
      {result.recommend.reset_baseline && (
        <div className="prompt">
          <strong>Reset baseline?</strong>
          <p className="hint">
            The old baseline was taken under the previous calibration and is no longer compared. The next evidence-grade
            capture under this calibration becomes the baseline automatically, or set one now.
          </p>
          <Button onClick={setNow} disabled={busy}>
            Set baseline now
          </Button>
          {baselineMsg && <p className="hint">{baselineMsg}</p>}
        </div>
      )}
      {result.recommend.recommission && (
        <div className="prompt">
          <strong>Re-run commissioning?</strong>
          <p className="hint">Node positions were commissioned under the previous calibration.</p>
          <Button disabled title="available in M3">
            Re-run commissioning
          </Button>
          <span className="hint"> available in M3</span>
        </div>
      )}
      <div className="row-actions">
        <Button variant="primary" onClick={onClose}>
          Done
        </Button>
      </div>
    </div>
  )
}

/**
 * Four-corner calibration (addendum F4): click four corners of the site on a raw camera frame, pick
 * the north edge (edge k runs from corner k to k+1 after clockwise sorting), submit.
 */
export function CornerPicker({ onClose, onCalibrated }: { onClose: () => void; onCalibrated: (r: CalibrationResult) => void }) {
  const online = useAppStore((s) => s.camera.status?.online ?? false)
  const frame = useCalibrationFrame()
  const [natural, setNatural] = useState<{ width: number; height: number } | null>(null)
  const [clicks, setClicks] = useState<Pt[]>([])
  const [north, setNorth] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<CalibrationResult | null>(null)

  const sorted = clicks.length === 4 ? sortClockwise(clicks) : null
  const shown = sorted ?? clicks
  const edges = sorted ? edgesOf(sorted) : []

  if (result) return <RecalibrationPrompts result={result} onClose={onClose} />

  const onFrameClick = (e: MouseEvent<HTMLDivElement>) => {
    if (!online || !natural || clicks.length >= 4) return
    const img = e.currentTarget.querySelector('img')
    if (!img) return
    const rect = img.getBoundingClientRect()
    const p = toImagePoint({ x: e.clientX - rect.left, y: e.clientY - rect.top }, rect, natural)
    setClicks((c) => [...c, p])
    setError(null)
  }

  const reset = () => {
    setClicks([])
    setNorth(null)
    setError(null)
  }

  const submit = async () => {
    if (!online || !sorted || north === null) return
    setBusy(true)
    setError(null)
    try {
      const r = await api.POST('/api/v1/calibration/four-corner', { body: { corners_px: sorted, north_edge: north } })
      if (r.data) {
        setResult(r.data)
        onCalibrated(r.data)
      } else setError(apiErrorText(r.error, 'The calibration was rejected.'))
    } catch (e) {
      setError(networkErrorText(e))
    }
    setBusy(false)
  }

  const stroke = natural ? Math.max(2, natural.width / 250) : 2

  return (
    <div className="corner-picker">
      {!online && <p className="form-error">The camera is offline; four-corner calibration needs a live frame.</p>}
      <p className="hint">
        {clicks.length < 4
          ? `Click the four site corners in any order (${clicks.length}/4). Set flip and mirror first so the image matches the scene from above.`
          : north === null
            ? 'Now click the north edge (or pick it below).'
            : `North edge: ${north + 1}. Submit to activate.`}
      </p>
      {frame.kind === 'loading' && <span className="media-missing corner-picker__frame">loading camera frame…</span>}
      {frame.kind === 'unavailable' && (
        <span className="media-missing corner-picker__frame" role="alert">
          {frame.message}
        </span>
      )}
      {frame.kind === 'ready' && (
        <div className="corner-picker__frame" data-disabled={!online} onClick={onFrameClick} data-testid="corner-picker-frame">
          <img
            src={frame.url}
            alt="Raw camera frame"
            draggable={false}
            onLoad={(e) => setNatural({ width: e.currentTarget.naturalWidth, height: e.currentTarget.naturalHeight })}
          />
          {natural && (
            <svg viewBox={`0 0 ${natural.width} ${natural.height}`} preserveAspectRatio="none">
              {sorted && <polygon points={sorted.map((p) => p.join(',')).join(' ')} className="corner-picker__poly" />}
              {edges.map((edge) => (
                <line
                  key={edge.index}
                  className={`corner-picker__edge${north === edge.index ? ' is-north' : ''}`}
                  x1={edge.from[0]}
                  y1={edge.from[1]}
                  x2={edge.to[0]}
                  y2={edge.to[1]}
                  strokeWidth={stroke * (north === edge.index ? 3 : 2)}
                  onClick={(ev) => {
                    ev.stopPropagation()
                    if (online) setNorth(edge.index)
                  }}
                />
              ))}
              {edges.map((edge) => (
                <text
                  key={`t${edge.index}`}
                  className="corner-picker__label"
                  x={(edge.from[0] + edge.to[0]) / 2}
                  y={(edge.from[1] + edge.to[1]) / 2}
                  fontSize={stroke * 8}
                >
                  {north === edge.index ? 'N' : `edge ${edge.index + 1}`}
                </text>
              ))}
              {shown.map((p, i) => (
                <g key={`${p[0]},${p[1]},${i}`}>
                  <circle cx={p[0]} cy={p[1]} r={stroke * 3} className="corner-picker__dot" />
                  {sorted && (
                    <text x={p[0] + stroke * 4} y={p[1] - stroke * 4} className="corner-picker__label" fontSize={stroke * 7}>
                      {i + 1}
                    </text>
                  )}
                </g>
              ))}
            </svg>
          )}
        </div>
      )}
      {sorted && (
        <div className="corner-picker__edges" role="radiogroup" aria-label="North edge">
          {edges.map((edge) => (
            <label key={edge.index} className="corner-picker__edge-choice">
              <input
                type="radio"
                name="north-edge"
                disabled={!online}
                checked={north === edge.index}
                onChange={() => setNorth(edge.index)}
              />
              Edge {edge.index + 1} (corner {edge.index + 1} → {((edge.index + 1) % 4) + 1}) is north
            </label>
          ))}
        </div>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <div className="row-actions">
        <Button
          onClick={() => {
            setClicks((c) => c.slice(0, -1))
            setNorth(null)
          }}
          disabled={clicks.length === 0 || busy}>
          Undo
        </Button>
        <Button onClick={reset} disabled={clicks.length === 0 || busy}>
          Clear
        </Button>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" onClick={submit} disabled={!online || !sorted || north === null || busy || frame.kind !== 'ready'}>
          {busy ? 'Calibrating…' : 'Apply calibration'}
        </Button>
      </div>
    </div>
  )
}
