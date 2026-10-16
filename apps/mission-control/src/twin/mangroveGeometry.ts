import { Float32BufferAttribute, SphereGeometry, type BufferGeometry } from 'three'
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js'

/** Reusable broadleaf crown. Geometry is illustrative; it does not imply a measured tree shape. */
export function organicCrownGeometry(): BufferGeometry {
  const lobes = [
    [0, 0.15, 0, 0.85, 0.8, 0.85], [-0.48, -0.15, 0.2, 0.7, 0.6, 0.65],
    [0.52, -0.05, 0.15, 0.65, 0.7, 0.7], [0.12, -0.22, -0.5, 0.7, 0.55, 0.68],
    [-0.22, 0.48, -0.05, 0.68, 0.6, 0.65], [0.15, -0.3, 0.55, 0.62, 0.52, 0.6],
  ]
  const parts = lobes.map(([x, y, z, sx, sy, sz], index) => {
    const g = new SphereGeometry(1, 8, 6)
    const p = g.getAttribute('position')
    const colours: number[] = []
    for (let i = 0; i < p.count; i++) {
      const px = p.getX(i), py = p.getY(i), pz = p.getZ(i)
      const flutter = 1 + 0.08 * Math.sin(px * 13 + pz * 9 + index * 2) * Math.cos(py * 11)
      p.setXYZ(i, px * flutter, py * flutter, pz * flutter)
      const shade = 0.65 + 0.25 * (py + 1) / 2 + 0.08 * Math.sin(i * 1.7 + index)
      colours.push(shade * 0.96, shade, shade * 0.9)
    }
    g.setAttribute('color', new Float32BufferAttribute(colours, 3))
    g.scale(sx!, sy!, sz!).translate(x!, y!, z!)
    g.computeVertexNormals()
    return g
  })
  const merged = mergeGeometries(parts)!
  parts.forEach(g => g.dispose())
  return merged
}
