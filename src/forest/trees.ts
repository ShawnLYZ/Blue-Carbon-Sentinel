// Procedural Rhizophora-like mangrove trees, built in code (PRD decision 21).
// Geometry is authored for a 12 m tree; each instance is scaled to its own height.

import * as THREE from 'three'
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js'
import { rng } from '../sim/noise'

export const REF_HEIGHT = 12

export interface TreeVariant {
  bark: THREE.BufferGeometry
  leaves: THREE.BufferGeometry
  /** A darker inner leaf mass inside the near crown, so gaps show foliage rather than the ground. */
  core: THREE.BufferGeometry
  far: THREE.BufferGeometry
  /** Crown centre height and radius at the reference height, for picking. */
  crownY: number
  crownR: number
}

// sRGB colours, converted to linear by three.js.
const MUD = new THREE.Color('#2e251b')
const BARK = new THREE.Color('#5e4f41')
const BARK_DARK = new THREE.Color('#43372b')

/** A tube along a smooth curve with a radius that tapers from r0 to r1. */
function taperedTube(points: THREE.Vector3[], segments: number, radial: number, r0: number, r1: number, tint: number) {
  const curve = new THREE.CatmullRomCurve3(points, false, 'centripetal')
  const frames = curve.computeFrenetFrames(segments, false)
  const pos: number[] = [], nor: number[] = [], uv: number[] = [], col: number[] = [], idx: number[] = []
  const p = new THREE.Vector3(), n = new THREE.Vector3(), c = new THREE.Color()
  for (let i = 0; i <= segments; i++) {
    const t = i / segments
    curve.getPointAt(t, p)
    const r = r0 + (r1 - r0) * t
    const N = frames.normals[i], B = frames.binormals[i]
    for (let j = 0; j <= radial; j++) {
      const a = (j / radial) * Math.PI * 2
      n.set(0, 0, 0).addScaledVector(N, Math.cos(a)).addScaledVector(B, Math.sin(a)).normalize()
      pos.push(p.x + n.x * r, p.y + n.y * r, p.z + n.z * r)
      nor.push(n.x, n.y, n.z)
      uv.push(j / radial, t)
      const muddy = THREE.MathUtils.smoothstep(p.y, 0.1, 0.9)
      c.copy(MUD).lerp(BARK, muddy).lerp(BARK_DARK, tint)
      col.push(c.r, c.g, c.b)
    }
  }
  for (let i = 0; i < segments; i++) {
    for (let j = 0; j < radial; j++) {
      const a = i * (radial + 1) + j, b = a + radial + 1
      idx.push(a, b, a + 1, b, b + 1, a + 1)
    }
  }
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3))
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2))
  g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3))
  g.setIndex(idx)
  return g
}

function leafCards(clusters: THREE.Vector3[], crownCentre: THREE.Vector3, crownR: number, seed: number) {
  const r = rng(seed)
  const pos: number[] = [], nor: number[] = [], uv: number[] = [], col: number[] = [], idx: number[] = []
  const q = new THREE.Quaternion(), e = new THREE.Euler()
  const corner = new THREE.Vector3(), cardN = new THREE.Vector3(), sph = new THREE.Vector3(), n = new THREE.Vector3()
  const up = new THREE.Vector3(0, 1, 0)
  for (const cc of clusters) {
    const cards = 11
    for (let k = 0; k < cards; k++) {
      const size = 1.5 + r() * 0.7
      const centre = new THREE.Vector3((r() - 0.5) * 1.1, (r() - 0.35) * 0.8, (r() - 0.5) * 1.1).add(cc)
      // Face cards mostly up and outward so the crown reads full from above.
      const out = centre.clone().sub(crownCentre).setY(0).normalize()
      cardN.set(r() - 0.5, r() * 0.6, r() - 0.5).add(up.clone().multiplyScalar(0.9)).addScaledVector(out, 0.45).normalize()
      q.setFromUnitVectors(new THREE.Vector3(0, 0, 1), cardN)
      e.set(0, 0, (r() - 0.5) * Math.PI * 2)
      q.multiply(new THREE.Quaternion().setFromEuler(e))
      const base = pos.length / 3
      const shade = 0.62 + 0.38 * THREE.MathUtils.clamp((centre.y - (crownCentre.y - 1.4)) / 2.6, 0, 1)
      for (const [u, v] of [[0, 0], [1, 0], [1, 1], [0, 1]]) {
        corner.set((u - 0.5) * size, (v - 0.15) * size, 0).applyQuaternion(q).add(centre)
        pos.push(corner.x, corner.y, corner.z)
        sph.copy(corner).sub(crownCentre).multiply(new THREE.Vector3(1 / crownR, 1 / (crownR * 0.6), 1 / crownR)).normalize()
        n.copy(sph).multiplyScalar(0.72).addScaledVector(cardN, 0.28).normalize()
        nor.push(n.x, n.y, n.z)
        uv.push(u, v)
        const dist = corner.distanceTo(crownCentre) / crownR
        const s = shade * (0.78 + 0.22 * Math.min(1, dist))
        col.push(s, s, s)
      }
      idx.push(base, base + 1, base + 2, base, base + 2, base + 3)
    }
  }
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3))
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2))
  g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3))
  g.setIndex(idx)
  return g
}

function farCrown(crownY: number, crownR: number, seed: number) {
  const r = rng(seed)
  const g = new THREE.IcosahedronGeometry(1, 1)
  const pos = g.getAttribute('position') as THREE.BufferAttribute
  const nor: number[] = [], uv: number[] = [], col: number[] = []
  const v = new THREE.Vector3()
  const bumps = Array.from({ length: 6 }, () => new THREE.Vector3(r() - 0.5, r() * 0.8, r() - 0.5).normalize())
  for (let i = 0; i < pos.count; i++) {
    v.fromBufferAttribute(pos, i)
    let k = 0.92
    for (const b of bumps) k += Math.max(0, v.dot(b) - 0.55) * 0.5
    const flat = v.y < 0 ? 0.45 : 0.62
    const x = v.x * crownR * k, y = v.y * crownR * flat * k + crownY, z = v.z * crownR * k
    pos.setXYZ(i, x, y, z)
    nor.push(v.x, v.y * 1.2 + 0.25, v.z)
    uv.push(x / 3.2 + v.y * 0.15, z / 3.2 + v.y * 0.15)
    const s = 0.55 + 0.45 * (v.y * 0.5 + 0.5)
    col.push(s, s, s)
  }
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3))
  g.normalizeNormals()
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2))
  g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3))
  return g
}

function darken(g: THREE.BufferGeometry, k: number) {
  const c = g.getAttribute('color') as THREE.BufferAttribute
  for (let i = 0; i < c.count; i++) c.setXYZ(i, c.getX(i) * k, c.getY(i) * k, c.getZ(i) * k)
  return g
}

function buildVariant(seed: number): TreeVariant {
  const r = rng(seed)
  const H = REF_HEIGHT
  const bark: THREE.BufferGeometry[] = []

  // Trunk: slightly bent, from just above the mud to the crown.
  const lean = new THREE.Vector3((r() - 0.5) * 0.5, 0, (r() - 0.5) * 0.5)
  const trunkTop = new THREE.Vector3(lean.x, H * 0.74, lean.z)
  const trunkPts = [
    new THREE.Vector3(0, 0.9, 0),
    new THREE.Vector3(lean.x * 0.25, H * 0.3, lean.z * 0.25),
    new THREE.Vector3(lean.x * 0.65, H * 0.55, lean.z * 0.65),
    trunkTop,
  ]
  bark.push(taperedTube(trunkPts, 6, 6, 0.19, 0.09, 0.1))
  const trunkCurve = new THREE.CatmullRomCurve3(trunkPts, false, 'centripetal')

  // Stilt roots: 6 to 10 arching roots from about a third of the trunk down into the mud.
  const roots = 6 + Math.floor(r() * 5)
  const a0 = r() * Math.PI * 2
  for (let i = 0; i < roots; i++) {
    const ang = a0 + (i / roots) * Math.PI * 2 + (r() - 0.5) * 0.5
    const u = new THREE.Vector3(Math.cos(ang), 0, Math.sin(ang))
    const y0 = H * (0.18 + r() * 0.16)
    const d = 1.6 + r() * 1.6
    const start = trunkCurve.getPointAt(Math.min(1, (y0 - 0.9) / (H * 0.74 - 0.9))).addScaledVector(u, 0.12)
    const pts = [
      start,
      start.clone().addScaledVector(u, d * 0.42).setY(y0 + 0.15 + r() * 0.3),
      new THREE.Vector3().addScaledVector(u, d * 0.86).setY(y0 * (0.42 + r() * 0.2)),
      new THREE.Vector3().addScaledVector(u, d).setY(-0.35),
    ]
    bark.push(taperedTube(pts, 7, 4, 0.075, 0.05, r() * 0.25))
    if (r() < 0.45) {
      const mid = new THREE.CatmullRomCurve3(pts, false, 'centripetal').getPointAt(0.42 + r() * 0.15)
      const u2 = u.clone().applyAxisAngle(new THREE.Vector3(0, 1, 0), (r() - 0.5) * 0.9)
      const far = d + 0.7 + r() * 0.8
      bark.push(taperedTube([
        mid,
        mid.clone().addScaledVector(u2, 0.5).setY(mid.y * 0.8),
        new THREE.Vector3().addScaledVector(u2, far).setY(-0.3),
      ], 5, 3, 0.045, 0.034, r() * 0.25))
    }
  }

  // Branches: from the upper trunk out to the leaf clusters.
  const crownCentre = new THREE.Vector3(lean.x, H * 0.82, lean.z)
  const crownR = 2.9 + r() * 0.5
  const clusters: THREE.Vector3[] = [new THREE.Vector3(lean.x, H * 0.9, lean.z)]
  const branches = 5 + Math.floor(r() * 3)
  for (let i = 0; i < branches; i++) {
    const ang = (i / branches) * Math.PI * 2 + r() * 0.6
    const u = new THREE.Vector3(Math.cos(ang), 0, Math.sin(ang))
    const rho = crownR * (0.45 + r() * 0.45)
    const end = crownCentre.clone().addScaledVector(u, rho)
    end.y = H * 0.8 + (1 - (rho / crownR) ** 2) * 1.2 + (r() - 0.5) * 0.4
    const startY = H * (0.56 + r() * 0.16)
    const start = trunkCurve.getPointAt(Math.min(1, (startY - 0.9) / (H * 0.74 - 0.9)))
    bark.push(taperedTube([start, start.clone().lerp(end, 0.5).setY((start.y + end.y) / 2 + 0.35), end], 5, 4, 0.065, 0.03, 0.05))
    clusters.push(end)
    if (r() < 0.6) {
      const extra = end.clone().addScaledVector(u.clone().applyAxisAngle(new THREE.Vector3(0, 1, 0), 1.2), crownR * 0.35)
      extra.y -= 0.3
      clusters.push(extra)
    }
    // Some branches drop a thin aerial root straight down into the mud.
    if (r() < 0.22) {
      const drop = start.clone().lerp(end, 0.55)
      bark.push(taperedTube([drop, drop.clone().setY(drop.y * 0.5).add(new THREE.Vector3(0.05, 0, 0.05)), drop.clone().setY(-0.3)], 6, 4, 0.03, 0.025, 0.2))
    }
  }
  const barkGeo = mergeGeometries(bark)!
  bark.forEach((g) => g.dispose())

  return {
    bark: barkGeo,
    leaves: leafCards(clusters, crownCentre, crownR, seed + 1),
    core: darken(farCrown(H * 0.83, crownR * 0.7, seed + 2), 0.45),
    far: farCrown(H * 0.86, crownR * 1.05, seed + 2),
    crownY: H * 0.85,
    crownR: crownR * 1.05,
  }
}

export function buildVariants(): TreeVariant[] {
  return [101, 202, 303, 404].map(buildVariant)
}

/** A small pencil-like breathing root (pneumatophore), 1 m tall at reference scale. */
export function breathingRoot(): THREE.BufferGeometry {
  const g = new THREE.ConeGeometry(0.035, 1, 5, 1, true)
  g.translate(0, 0.5, 0)
  return g
}
