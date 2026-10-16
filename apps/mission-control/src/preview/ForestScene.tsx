import { useEffect, useMemo, useRef, type ReactNode } from 'react'
import { Canvas, useThree } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import { CanvasTexture, Color, DoubleSide, Euler, LinearFilter, Matrix4, Quaternion, SRGBColorSpace, Vector3, type InstancedMesh } from 'three'
import { woodGeometry } from '../twin/Trees'
import { organicCrownGeometry } from '../twin/mangroveGeometry'
import { extentWeight, fluidRiskPixels } from './fluidSurface'
import type { Raster } from './satellite'
import type { Environment, ModelTree } from './model'
import { RISK_PALETTE, type RiskZone } from './scenarioRisk'

export interface ForestSceneProps {
  trees: ModelTree[]; raster: Raster | null; env: Environment
  zones?: RiskZone[]; selectedZone?: string | null; onSelectZone?: (id: string) => void
  hoveredZone?: string | null
  onHoverZone?: (id: string | null) => void
  showRisk?: boolean; showGrid?: boolean; opacity?: number; showWater?: boolean
  cameraScale?: number
  floorRaster?: Raster | null
  children?: ReactNode
}

function Forest({ trees, raster, floorRaster, env, zones, selectedZone, onSelectZone, showRisk = false, showGrid = true, opacity = 0.7, showWater = true, children, hoveredZone, onHoverZone }: ForestSceneProps) {
  const crowns = useRef<InstancedMesh>(null)
  const trunks = useRef<InstancedMesh>(null)
  const invalidate = useThree(s => s.invalidate)
  const wood = useMemo(woodGeometry, [])
  const crown = useMemo(organicCrownGeometry, [])
  const floor = floorRaster === undefined ? raster : floorRaster
  const texture = useMemo(() => {
    if (!floor) return null
    const canvas = document.createElement('canvas')
    canvas.width = floor.width; canvas.height = floor.height
    const pixels = new Uint8ClampedArray(floor.rgb)
    for (let y = 0; y < floor.height; y++) for (let x = 0; x < floor.width; x++) pixels[(y * floor.width + x) * 4 + 3] = Math.round(255 * extentWeight((x + 0.5) / floor.width * 500, (y + 0.5) / floor.height * 500))
    canvas.getContext('2d')!.putImageData(new ImageData(pixels, floor.width, floor.height), 0, 0)
    const result = new CanvasTexture(canvas)
    result.colorSpace = SRGBColorSpace
    result.magFilter = result.minFilter = LinearFilter
    return result
  }, [floor])
  const riskTexture = useMemo(() => {
    const canvas = document.createElement('canvas'); canvas.width = canvas.height = 128
    canvas.getContext('2d')!.putImageData(new ImageData(new Uint8ClampedArray(fluidRiskPixels(zones ?? [], raster, showGrid)), 128, 128), 0, 0)
    const result = new CanvasTexture(canvas); result.colorSpace = SRGBColorSpace
    result.magFilter = result.minFilter = LinearFilter
    return result
  }, [zones, raster, showGrid])
  useEffect(() => () => riskTexture.dispose(), [riskTexture])
  useEffect(() => () => { wood.dispose(); crown.dispose() }, [wood, crown])
  useEffect(() => () => texture?.dispose(), [texture])
  useEffect(() => { invalidate() }, [zones, selectedZone, hoveredZone, showRisk, showGrid, opacity, showWater, invalidate])
  useEffect(() => {
    if (!crowns.current || !trunks.current) return
    const m = new Matrix4(), p = new Vector3(), q = new Quaternion(), s = new Vector3()
    trees.forEach((t, i) => {
      q.setFromEuler(new Euler(Math.sin(i * 2.3) * 0.04, t.rotation, Math.cos(i * 1.7) * 0.04))
      m.compose(p.set(t.x, t.height * 0.76, t.z), q, s.set(t.crown, t.height * 0.28, t.crown))
      crowns.current!.setMatrixAt(i, m)
      crowns.current!.setColorAt(i, new Color().setHSL(0.28 + Math.sin(i * 1.73) * 0.025, 0.34 + Math.cos(i) * 0.06, 0.24 + Math.sin(i * 0.73) * 0.04).lerp(new Color('#9a7943'), t.stress))
      m.compose(p.set(t.x, 0, t.z), q, s.set(t.height / 10, t.height / 10, t.height / 10))
      trunks.current!.setMatrixAt(i, m)
    })
    crowns.current.instanceMatrix.needsUpdate = true
    if (crowns.current.instanceColor) crowns.current.instanceColor.needsUpdate = true
    trunks.current.instanceMatrix.needsUpdate = true
    invalidate()
  }, [trees, invalidate])
  return <>
    <ambientLight intensity={0.6} />
    <hemisphereLight args={['#b9d9df', '#4b4a2d', 1.1]} />
    <directionalLight position={[-150, 300, 80]} intensity={2} />
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -1, 0]}>
      <planeGeometry args={[500, 500, 1, 1]} />
      <meshStandardMaterial key={texture?.uuid ?? 'flat'} map={texture} color={texture ? '#c5c7a8' : '#3d5545'} roughness={1} transparent alphaTest={0.02} side={DoubleSide} />
    </mesh>
    {showWater && env.inundation > 0 && <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -1.2, 0]}>
      <circleGeometry args={[350, 96]} /><meshStandardMaterial color="#16464f" transparent opacity={0.16} roughness={0.25} metalness={0.25} depthWrite={false} />
    </mesh>}
    {!!zones?.length && <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.04, 0]} onClick={e => {
      e.stopPropagation()
      const col = Math.min(4, Math.max(0, Math.floor((e.point.x + 250) / 100)))
      const row = Math.min(4, Math.max(0, Math.floor((e.point.z + 250) / 100)))
      const z = zones.find(z => z.col === col && z.row === row); if (z) onSelectZone?.(z.id)
    }} onPointerMove={e => {
      e.stopPropagation()
      const col = Math.min(4, Math.max(0, Math.floor((e.point.x + 250) / 100)))
      const row = Math.min(4, Math.max(0, Math.floor((e.point.z + 250) / 100)))
      onHoverZone?.(zones.find(z => z.col === col && z.row === row)?.id ?? null)
    }} onPointerOut={() => onHoverZone?.(null)}>
      <planeGeometry args={[500, 500]} />
      <meshBasicMaterial map={riskTexture} transparent opacity={showRisk ? opacity : 0} depthWrite={false} toneMapped={false} side={DoubleSide} />
    </mesh>}
    {zones?.filter(z => z.id === (hoveredZone ?? selectedZone)).map(z => <mesh key={`selected-${z.id}`} rotation={[-Math.PI / 2, 0, 0]} position={[-200 + z.col * 100, 0.18, -200 + z.row * 100]}>
      <ringGeometry args={[43, 44, 64]} /><meshBasicMaterial color="#98e4cf" transparent opacity={0.55} depthWrite={false} toneMapped={false} side={DoubleSide} />
    </mesh>)}
    <instancedMesh key={`c${trees.length}`} ref={crowns} args={[crown, undefined, Math.max(1, trees.length)]} count={trees.length} frustumCulled={false}>
      <meshStandardMaterial vertexColors roughness={0.95} />
    </instancedMesh>
    <instancedMesh key={`w${trees.length}`} ref={trunks} args={[wood, undefined, Math.max(1, trees.length)]} count={trees.length} frustumCulled={false}>
      <meshStandardMaterial color="#806044" roughness={1} />
    </instancedMesh>
    <OrbitControls target={[0, 0, 0]} minDistance={30} maxDistance={1400} maxPolarAngle={Math.PI / 2.05} />
    {children}
  </>
}

export default function ForestScene(props: ForestSceneProps) {
  const k = props.cameraScale ?? 1
  return <Canvas frameloop="demand" camera={{ position: [350 * k, 270 * k, 370 * k], fov: 46, near: 1, far: 2500 }} dpr={[1, 1.5]}>
    <color attach="background" args={['#071a22']} />
    <Forest {...props} />
  </Canvas>
}
