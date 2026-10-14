// Time Travel's future surface (design §21): the same 500 x 500 m plane as the live reality surface
// (twin/surfaceMaterial.ts frames and conventions), coloured by two textures and displaced by two height
// maps of the selected year, mixed in the shader: `uBlend` for colour, `uHeightBlend` for height (see
// lib/interp.ts frameSources). All textures come from the page's preload (pages/TimeTravel/futuresMedia),
// so a year change only swaps uniforms. A texture not rendered yet falls back to the real capture.
import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import {
  DataTexture,
  DoubleSide,
  FloatType,
  LinearFilter,
  NearestFilter,
  NoColorSpace,
  RedFormat,
  ShaderMaterial,
  Texture,
  type IUniform,
  type Mesh,
} from 'three'
import type { ColourSource, FrameSources, Scenario } from '../lib/interp'
import { FIRST_YEAR } from '../lib/interp'
import type { FuturesMedia } from '../pages/TimeTravel/futuresMedia'
import {
  HEIGHT_GRID,
  SITE_SIZE_M,
  SURFACE_POSITION,
  SURFACE_ROTATION_X,
  SURFACE_SEGMENTS,
  type SurfaceState,
} from './surfaceMaterial'

const VERTEX = /* glsl */ `
uniform sampler2D uHeightA;
uniform sampler2D uHeightB;
uniform float uHeightBlend;
uniform float uMaxRelief;
uniform float uExaggeration;
uniform float uBase;
varying vec2 vTex;
void main() {
  vTex = vec2(uv.x, 1.0 - uv.y);                      // row 0 = north edge
  float h = mix(texture2D(uHeightA, vTex).r, texture2D(uHeightB, vTex).r, uHeightBlend);
  vec3 p = position; p.z += h * uMaxRelief * uExaggeration + uBase;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
}
`

const FRAGMENT = /* glsl */ `
uniform sampler2D uColourA;
uniform sampler2D uColourB;
uniform float uBlend;
varying vec2 vTex;
void main() {
  gl_FragColor = vec4(mix(texture2D(uColourA, vTex).rgb, texture2D(uColourB, vTex).rgb, uBlend), 1.0);
}
`

interface FutureUniforms {
  [name: string]: IUniform
  uHeightA: IUniform<Texture>
  uHeightB: IUniform<Texture>
  uHeightBlend: IUniform<number>
  uColourA: IUniform<Texture>
  uColourB: IUniform<Texture>
  uBlend: IUniform<number>
  uMaxRelief: IUniform<number>
  uExaggeration: IUniform<number>
  uBase: IUniform<number>
}

function colourTexture(bmp: ImageBitmap): Texture {
  // Same as the live surface: top row first, flipY false, sRGB bytes straight through.
  const t = new Texture(bmp)
  t.flipY = false
  t.colorSpace = NoColorSpace
  t.minFilter = LinearFilter
  t.magFilter = LinearFilter
  t.generateMipmaps = false
  t.needsUpdate = true
  return t
}

function heightTexture(h: Float32Array): DataTexture {
  const t = new DataTexture(h, HEIGHT_GRID, HEIGHT_GRID, RedFormat, FloatType)
  t.minFilter = NearestFilter
  t.magFilter = NearestFilter
  t.generateMipmaps = false
  t.flipY = false
  t.needsUpdate = true
  return t
}

/** The bitmap of a colour source; a missing repaint or illustration falls back to the real capture. */
export function colourBitmap(media: FuturesMedia, scenario: Scenario, src: ColourSource): { key: string; bmp: ImageBitmap } | null {
  if (src.kind === 'illustration') {
    const bmp = media.illustrations.get(`${scenario}:${src.year}`)
    if (bmp) return { key: `i:${src.year}`, bmp }
  } else if (src.kind === 'repaint') {
    const bmp = media.textures[scenario][src.year - FIRST_YEAR]
    if (bmp) return { key: `r:${src.year}`, bmp }
  }
  return media.capture ? { key: 'capture', bmp: media.capture } : null
}

/** The height map of a year; a missing one falls back to the real capture's. */
export function heightData(media: FuturesMedia, scenario: Scenario, year: number): { key: string; data: Float32Array } | null {
  const h = media.heights[scenario][year - FIRST_YEAR]
  if (h) return { key: `h:${year}`, data: h }
  return media.captureHeight ? { key: 'capture', data: media.captureHeight } : null
}

export interface FutureSurfaceProps {
  state: SurfaceState
  media: FuturesMedia | null
  /** Bumps when `media` gained files. */
  version: number
  scenario: Scenario
  frame: FrameSources
}

export function FutureSurface({ state, media, version, scenario, frame }: FutureSurfaceProps) {
  const invalidate = useThree((s) => s.invalidate)
  const gl = useThree((s) => s.gl)
  const mesh = useRef<Mesh>(null)
  const res = useMemo(() => {
    const empty = new DataTexture(new Float32Array(1), 1, 1, RedFormat, FloatType)
    empty.needsUpdate = true
    const uniforms: FutureUniforms = {
      uHeightA: { value: empty },
      uHeightB: { value: empty },
      uHeightBlend: { value: 0 },
      uColourA: { value: empty },
      uColourB: { value: empty },
      uBlend: { value: 0 },
      uMaxRelief: { value: state.maxRelief },
      uExaggeration: { value: state.exaggeration },
      uBase: { value: state.base },
    }
    const material = new ShaderMaterial({ uniforms, vertexShader: VERTEX, fragmentShader: FRAGMENT, side: DoubleSide })
    return { material: material as ShaderMaterial & { uniforms: FutureUniforms }, empty }
  }, [state])

  // GPU textures per source, made once per bitmap (cleared when the forecast's media changes).
  const textures = useRef(new Map<string, Texture>())
  useEffect(() => {
    const cache = textures.current
    return () => {
      for (const t of cache.values()) t.dispose()
      cache.clear()
    }
  }, [media])
  useEffect(
    () => () => {
      res.material.dispose()
      res.empty.dispose()
    },
    [res],
  )

  const texFor = (key: string, make: () => Texture): Texture => {
    let t = textures.current.get(key)
    if (!t) {
      t = make()
      textures.current.set(key, t)
    }
    return t
  }

  // Upload every loaded texture up front, so the first scrub to a year does not stall on an upload.
  useEffect(() => {
    if (!media) return
    const all: Texture[] = []
    if (media.capture) all.push(texFor('capture', () => colourTexture(media.capture!)))
    media.textures[scenario].forEach((b, i) => b && all.push(texFor(`r:${FIRST_YEAR + i}`, () => colourTexture(b))))
    for (const [k, b] of media.illustrations) if (k.startsWith(`${scenario}:`)) all.push(texFor(`i:${k.split(':')[1]}`, () => colourTexture(b)))
    media.heights[scenario].forEach((h, i) => h && all.push(texFor(`h:${FIRST_YEAR + i}`, () => heightTexture(h))))
    if (media.captureHeight) all.push(texFor('hcapture', () => heightTexture(media.captureHeight!)))
    for (const t of all) {
      try {
        gl.initTexture(t)
      } catch {
        // uploaded on first use instead
      }
    }
    invalidate()
  }, [media, version, scenario, gl, invalidate])

  // Bind this year's sources; blend the CPU copy of the heights for trees and zone hits.
  useEffect(() => {
    const u = res.material.uniforms
    let visible = false
    if (media) {
      const a = colourBitmap(media, scenario, frame.colour.from)
      const b = colourBitmap(media, scenario, frame.colour.to)
      if (a && b) {
        u.uColourA.value = texFor(a.key, () => colourTexture(a.bmp))
        u.uColourB.value = texFor(b.key, () => colourTexture(b.bmp))
        u.uBlend.value = frame.colour.t
        visible = true
      }
      const ha = heightData(media, scenario, frame.height.from)
      const hb = heightData(media, scenario, frame.height.to)
      if (ha && hb) {
        const hk = (k: string) => (k === 'capture' ? 'hcapture' : k)
        u.uHeightA.value = texFor(hk(ha.key), () => heightTexture(ha.data))
        u.uHeightB.value = texFor(hk(hb.key), () => heightTexture(hb.data))
        u.uHeightBlend.value = frame.height.t
        const t = frame.height.t
        const out = state.heights
        for (let i = 0; i < out.length; i++) out[i] = ha.data[i]! + (hb.data[i]! - ha.data[i]!) * t
        state.hasHeights = true
      } else {
        u.uHeightA.value = res.empty
        u.uHeightB.value = res.empty
        state.hasHeights = false
      }
    }
    if (mesh.current) mesh.current.visible = visible
    invalidate()
  }, [media, version, scenario, frame, res, state, invalidate])

  useFrame(() => {
    const u = res.material.uniforms
    u.uBase.value = state.base
    u.uExaggeration.value = state.exaggeration
    u.uMaxRelief.value = state.maxRelief
  })

  return (
    <mesh ref={mesh} position={SURFACE_POSITION} rotation-x={SURFACE_ROTATION_X} visible={false} frustumCulled={false}>
      <planeGeometry args={[SITE_SIZE_M, SITE_SIZE_M, SURFACE_SEGMENTS, SURFACE_SEGMENTS]} />
      <primitive object={res.material} attach="material" />
    </mesh>
  )
}
