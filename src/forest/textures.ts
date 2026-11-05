// Textures generated at load into canvases (PRD decision 21, addendum A8). Nothing is downloaded.

import * as THREE from 'three'
import { rng } from '../sim/noise'

function canvas(w: number, h: number) {
  const c = document.createElement('canvas')
  c.width = w
  c.height = h
  return c
}

/** Periodic value noise in [0, 1] (tiles with the given period). */
function periodicNoise(size: number, period: number, seed: number): Float32Array {
  const r = rng(seed)
  const lattice = new Float32Array(period * period)
  for (let i = 0; i < lattice.length; i++) lattice[i] = r()
  const out = new Float32Array(size * size)
  const s = (t: number) => t * t * (3 - 2 * t)
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const fx = (x / size) * period, fy = (y / size) * period
      const i = Math.floor(fx), j = Math.floor(fy)
      const tx = s(fx - i), ty = s(fy - j)
      const i1 = (i + 1) % period, j1 = (j + 1) % period
      const a = lattice[j * period + i], b = lattice[j * period + i1]
      const c = lattice[j1 * period + i], d = lattice[j1 * period + i1]
      out[y * size + x] = (a + (b - a) * tx) * (1 - ty) + (c + (d - c) * tx) * ty
    }
  }
  return out
}

function fbmTile(size: number, base: number, octaves: number, seed: number): Float32Array {
  const out = new Float32Array(size * size)
  let amp = 1, norm = 0
  for (let o = 0; o < octaves; o++) {
    const n = periodicNoise(size, base << o, seed + o * 13)
    for (let i = 0; i < out.length; i++) out[i] += n[i] * amp
    norm += amp
    amp *= 0.5
  }
  for (let i = 0; i < out.length; i++) out[i] /= norm
  return out
}

function heightToNormal(h: Float32Array, size: number, strength: number): Uint8Array {
  const out = new Uint8Array(size * size * 4)
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const l = h[y * size + ((x - 1 + size) % size)], r = h[y * size + ((x + 1) % size)]
      const u = h[((y - 1 + size) % size) * size + x], d = h[((y + 1) % size) * size + x]
      let nx = (l - r) * strength, ny = (u - d) * strength
      const nz = 1
      const len = Math.hypot(nx, ny, nz)
      nx /= len; ny /= len
      const o = (y * size + x) * 4
      out[o] = Math.round((nx * 0.5 + 0.5) * 255)
      out[o + 1] = Math.round((ny * 0.5 + 0.5) * 255)
      out[o + 2] = Math.round((nz / len * 0.5 + 0.5) * 255)
      out[o + 3] = 255
    }
  }
  return out
}

function dataTexture(data: Uint8Array, size: number, srgb: boolean): THREE.DataTexture {
  const t = new THREE.DataTexture(data, size, size, THREE.RGBAFormat)
  t.wrapS = t.wrapT = THREE.RepeatWrapping
  t.magFilter = THREE.LinearFilter
  t.minFilter = THREE.LinearMipmapLinearFilter
  t.generateMipmaps = true
  t.anisotropy = 4
  if (srgb) t.colorSpace = THREE.SRGBColorSpace
  t.needsUpdate = true
  return t
}

/** A leafy Rhizophora spray: twigs with opposite pairs of glossy elliptical leaves and a rosette at each tip. */
export function leafTexture(): THREE.CanvasTexture {
  const S = 512
  const c = canvas(S, S)
  const g = c.getContext('2d')!
  const r = rng(4242)
  const leaf = (x: number, y: number, ang: number, len: number, wid: number) => {
    g.save()
    g.translate(x, y)
    g.rotate(ang)
    const hue = 96 + r() * 18
    const sat = 30 + r() * 16
    const lum = 13 + r() * 12
    const grad = g.createLinearGradient(0, -wid / 2, 0, wid / 2)
    grad.addColorStop(0, `hsl(${hue} ${sat}% ${lum + 11}%)`)
    grad.addColorStop(0.45, `hsl(${hue} ${sat}% ${lum + 4}%)`)
    grad.addColorStop(1, `hsl(${hue - 8} ${sat}% ${lum * 0.7}%)`)
    g.fillStyle = grad
    g.beginPath()
    g.moveTo(0, 0)
    g.bezierCurveTo(len * 0.25, -wid * 0.62, len * 0.8, -wid * 0.55, len, 0)
    g.bezierCurveTo(len * 0.8, wid * 0.55, len * 0.25, wid * 0.62, 0, 0)
    g.fill()
    g.strokeStyle = `hsl(${hue + 14} 34% ${lum + 16}% / 0.55)`
    g.lineWidth = 0.9
    g.beginPath()
    g.moveTo(1, 0)
    g.lineTo(len - 2, 0)
    g.stroke()
    g.restore()
  }
  const twigs = 11
  for (let t = 0; t < twigs; t++) {
    const ang = -Math.PI / 2 + (t / (twigs - 1) - 0.5) * 2.5 + (r() - 0.5) * 0.2
    const len = 150 + r() * 110
    const x0 = S / 2 + (r() - 0.5) * 60, y0 = S - 12
    const x1 = x0 + Math.cos(ang) * len, y1 = y0 + Math.sin(ang) * len
    g.strokeStyle = '#3f3122'
    g.lineWidth = 2.2
    g.beginPath()
    g.moveTo(x0, y0)
    g.quadraticCurveTo((x0 + x1) / 2 + (r() - 0.5) * 24, (y0 + y1) / 2, x1, y1)
    g.stroke()
    const pairs = 6
    for (let p = 1; p <= pairs; p++) {
      const f = 0.3 + (p / pairs) * 0.66
      const px = x0 + (x1 - x0) * f, py = y0 + (y1 - y0) * f
      const l = 24 + r() * 10, w = 10 + r() * 4
      // Leaves angle up towards the tip, as on Rhizophora shoots.
      leaf(px, py, ang + 0.6 + (r() - 0.5) * 0.35, l, w)
      leaf(px, py, ang - 0.6 + (r() - 0.5) * 0.35, l, w)
    }
    const n = 6 + Math.floor(r() * 3)
    for (let k = 0; k < n; k++) leaf(x1, y1, ang + (k / (n - 1) - 0.5) * 2.0, 28 + r() * 10, 11 + r() * 4)
  }
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 4
  return tex
}

/** Dense canopy blotches for far crowns (tileable). */
export function canopyTexture(): THREE.CanvasTexture {
  const S = 256
  const c = canvas(S, S)
  const g = c.getContext('2d')!
  g.fillStyle = 'hsl(104 38% 9%)'
  g.fillRect(0, 0, S, S)
  const r = rng(99)
  for (let i = 0; i < 1400; i++) {
    const x = r() * S, y = r() * S, rad = 2.5 + r() * 6
    const lum = 10 + r() * r() * 30
    g.fillStyle = `hsl(${92 + r() * 24} ${32 + r() * 18}% ${lum}%)`
    for (const [ox, oy] of [[0, 0], [S, 0], [-S, 0], [0, S], [0, -S]]) {
      g.beginPath()
      g.ellipse(x + ox, y + oy, rad * 1.4, rad, r() * Math.PI, 0, Math.PI * 2)
      g.fill()
    }
  }
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping
  return tex
}

/** Greyscale mud detail (multiplies the terrain's vertex colour) and its normal map. */
export function mudTextures(): { map: THREE.DataTexture; normal: THREE.DataTexture } {
  const S = 256
  const h = fbmTile(S, 8, 5, 31)
  const fine = fbmTile(S, 64, 2, 57)
  const map = new Uint8Array(S * S * 4)
  const height = new Float32Array(S * S)
  for (let i = 0; i < S * S; i++) {
    const v = 0.78 + 0.22 * h[i] + 0.1 * (fine[i] - 0.5)
    const b = Math.round(255 * Math.min(1, v))
    map[i * 4] = b; map[i * 4 + 1] = b; map[i * 4 + 2] = Math.round(b * 0.97); map[i * 4 + 3] = 255
    height[i] = h[i] * 0.7 + fine[i] * 0.3
  }
  return { map: dataTexture(map, S, true), normal: dataTexture(heightToNormal(height, S, 6), S, false) }
}

/** Gentle ripple normals for the water. */
export function waterNormalTexture(): THREE.DataTexture {
  const S = 256
  const h = fbmTile(S, 6, 5, 71)
  return dataTexture(heightToNormal(h, S, 9), S, false)
}

/** A short dash pattern for the Replant Patch outlines. */
export function dashTexture(): THREE.DataTexture {
  const data = new Uint8Array([255, 255, 255, 255, 255, 255, 255, 255, 0, 0, 0, 0, 0, 0, 0, 0])
  const t = new THREE.DataTexture(data, 4, 1, THREE.RGBAFormat)
  t.wrapS = THREE.RepeatWrapping
  t.magFilter = THREE.NearestFilter
  t.minFilter = THREE.NearestFilter
  t.needsUpdate = true
  return t
}
