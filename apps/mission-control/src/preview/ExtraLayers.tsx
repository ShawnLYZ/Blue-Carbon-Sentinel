import { useEffect, useRef } from 'react'
import { Html } from '@react-three/drei'
import { useFrame, useThree } from '@react-three/fiber'
import { DoubleSide, type Mesh } from 'three'
import { usePulseDriver, pulsePhase, pulseRadius, pulseOpacity } from '../twin/TaskingPulses'
import { RealitySurface } from '../twin/RealitySurface'
import type { SurfaceState } from '../twin/surfaceMaterial'
import type { ExtraData } from './layerData'
import { RISK_PALETTE, type RiskZone } from './scenarioRisk'

export interface ExtraLayerFlags { reality: boolean; riskColumns: boolean; carbon: boolean; nodes: boolean; coverage: boolean; tasking: boolean; alerts: boolean }
export const EXTRA_DEFAULTS: ExtraLayerFlags = { reality: false, riskColumns: false, carbon: false, nodes: false, coverage: false, tasking: false, alerts: false }

function TaskPulse({ e, s, colour }: { e: number; s: number; colour: string }) {
  const mesh = useRef<Mesh>(null)
  const invalidate = useThree(s => s.invalidate)
  usePulseDriver(true, invalidate)
  useFrame(() => {
    if (!mesh.current) return
    const phase = pulsePhase(performance.now())
    mesh.current.scale.setScalar(pulseRadius(phase))
    const material = mesh.current.material as { opacity: number }
    material.opacity = pulseOpacity(phase)
  })
  return <mesh ref={mesh} position={[e - 250, 0.6, s - 250]} rotation-x={-Math.PI / 2}>
    <ringGeometry args={[0.85, 1, 48]} /><meshBasicMaterial color={colour} transparent depthWrite={false} side={DoubleSide} toneMapped={false} />
  </mesh>
}

export function ExtraLayers({ flags, data, zones, realityState, exaggeration, selectedZone, onSelectNode, onSelectZone }: { flags: ExtraLayerFlags; data: ExtraData; zones: RiskZone[]; realityState: SurfaceState; exaggeration: number; selectedZone?: string | null; onSelectNode?: (id: string) => void; onSelectZone?: (id: string) => void }) {
  const invalidate = useThree(s => s.invalidate)
  useEffect(() => { realityState.exaggeration = exaggeration; invalidate() }, [realityState, exaggeration, invalidate])
  useEffect(() => invalidate(), [flags, data, zones, invalidate])
  const maxCarbon = Math.max(1, ...Object.values(data.carbon))
  return <>
    {flags.reality && <group position={[-250, 0, -250]}><RealitySurface state={realityState} /></group>}
    {zones.map(z => {
      const x = z.col * 100 - 200, s = z.row * 100 - 200
      const h = (z.score ?? 0) * 0.65
      const carbon = data.carbon[z.id]
      const ch = (carbon ?? 0) / maxCarbon * 65
      return <group key={z.id}>
        {flags.riskColumns && z.score !== null && h > 0 && <mesh position={[x - 18, h / 2 + 0.2, s]} onClick={e => { e.stopPropagation(); onSelectZone?.(z.id) }}>
          <cylinderGeometry args={[13, 16, h, 24]} /><meshBasicMaterial color={RISK_PALETTE[z.risk]} transparent opacity={0.72} toneMapped={false} />
        </mesh>}
        {flags.carbon && carbon !== undefined && carbon > 0 && <group position={[x + 18, 0.2, s]}>
          <mesh position={[0, ch / 2, 0]}><cylinderGeometry args={[11, 14, ch, 24]} /><meshBasicMaterial color="#1fb6a6" transparent opacity={0.7} toneMapped={false} /></mesh>
          {selectedZone === z.id && <Html position={[0, ch + 8, 0]} center zIndexRange={[5, 0]}><span className="dt-scene-label">{data.examples ? 'EX ' : ''}{carbon.toFixed(1)} tCO₂e</span></Html>}
        </group>}
      </group>
    })}
    {data.pins.map(p => <group key={p.id}>
      {flags.coverage && p.radius > 0 && <mesh position={[p.e - 250, 0.45, p.s - 250]} rotation-x={-Math.PI / 2}>
        <ringGeometry args={[p.radius - 2, p.radius, 64]} /><meshBasicMaterial color={p.colour} transparent opacity={0.75} side={DoubleSide} depthWrite={false} toneMapped={false} />
      </mesh>}
      {flags.nodes && <group position={[p.e - 250, 24, p.s - 250]}>
        <mesh rotation-x={Math.PI}><coneGeometry args={[7, 22, 12]} /><meshBasicMaterial color={p.colour} toneMapped={false} /></mesh>
        <Html center position={[0, 20, 0]} zIndexRange={[5, 0]}><button className="dt-scene-label" onClick={() => onSelectNode?.(p.id)}>{p.id}<small>{p.source}</small></button></Html>
      </group>}
      {flags.tasking && data.pulsing.includes(p.id) && <TaskPulse e={p.e} s={p.s} colour={p.colour} />}
    </group>)}
    {flags.alerts && data.alerts.map(a => <group key={a.id} position={[a.e - 250, 65, a.s - 250]}>
      <Html center zIndexRange={[6, 0]}><span className="dt-alert-pin" style={{ background: a.critical ? '#bf263c' : '#9b6500' }} title={a.title}>!{data.examples ? ' EXAMPLE' : ''}</span></Html>
    </group>)}
  </>
}
