import type { Raster } from './satellite'

export interface Environment { layout: 'forest' | 'farm'; salinity: number; inundation: number; age: number; spacing: number }
export interface ModelTree { x: number; z: number; height: number; crown: number; stress: number; rotation: number }
export const DEFAULT_ENV: Environment = { layout: 'forest', salinity: 20, inundation: 35, age: 15, spacing: 12 }

// A deterministic visual scenario, not a calibrated growth or species model.
export function environmentShape(e: Environment) {
  const stress = Math.min(0.85, Math.max(0, e.salinity - 25) / 40 + Math.max(0, e.inundation - 55) / 90)
  const height = (1.5 + 15 * (1 - Math.exp(-e.age / 12))) * (1 - stress * 0.55)
  return { stress, height, crown: Math.max(0.8, height * 0.31 * (1 - stress * 0.35)) }
}

export function buildTrees(raster: Raster | null, e: Environment, size = 500): ModelTree[] {
  const trees: ModelTree[] = []
  const shape = environmentShape(e)
  let seed = 2519
  const rand = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296 }
  const step = Math.max(5, e.spacing)
  for (let z = step / 2; z < size; z += step) for (let x = step / 2; x < size; x += step) {
    const px = e.layout === 'forest' ? rand() * size : Math.max(0.5, Math.min(size - 0.5, x + Math.sin(z / 90) * 8 + (rand() - 0.5) * step * 0.3))
    const pz = e.layout === 'forest' ? rand() * size : Math.max(0.5, Math.min(size - 0.5, z + (rand() - 0.5) * step * 0.3))
    let vigour = 0.7
    if (raster) {
      const i = Math.min(raster.height - 1, Math.floor(pz / size * raster.height)) * raster.width + Math.min(raster.width - 1, Math.floor(px / size * raster.width))
      if (!raster.valid[i] || raster.ndvi[i]! < 0.35) continue
      vigour = Math.min(1, Math.max(0.25, raster.ndvi[i]!))
    } else if (e.layout === 'forest' && (px < size * 0.13 + Math.sin(pz / 70) * 18 || rand() < 0.12)) continue
    const variation = 0.7 + rand() * 0.6
    trees.push({ x: px - size / 2, z: pz - size / 2, height: shape.height * variation * (0.6 + vigour * 0.6), crown: shape.crown * variation, stress: shape.stress, rotation: rand() * Math.PI * 2 })
  }
  return trees
}
