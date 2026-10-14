// The live reality surface's shader material and the site <-> scene mapping it relies on.
//
// Frames (addendum F4 and react-three-map):
// - Site metres (e, s): east and south of the NW anchor, 0..500.
// - react-three-map scene: origin at the <Canvas> coordinates (the NW anchor), one unit = one metre,
//   +x east, +y up, +z SOUTH (its origin matrix is rotateX(-90 deg) * scale(1, -1, 1) in mercator,
//   where mercator y grows south). So site (e, s) at height h is scene (e, h, s).
// - The 500 x 500 m PlaneGeometry lies in its local XY plane. Rotated -90 deg about X it lies flat,
//   its local +y points north and its local +z (the displacement axis) points up. It is centred at
//   scene (250, base, 250), so its NW corner sits on the anchor.
// - Texture coordinates: PlaneGeometry's uv.y = 1 on its north edge. Both textures are uploaded with
//   row 0 / the top image row first and flipY = false, i.e. row 0 at t = 0. The shaders therefore
//   sample at (uv.x, 1 - uv.y), which puts height-map row 0 (north edge, J1) on the north edge.
//
// Height texture format: WebGL2 cannot filter or normalise R16UI (it samples as usampler2D), and
// R16 UNORM needs EXT_texture_norm16, which is not universal. The u16 heights are converted to
// Float32 0..1 and uploaded as R32F (RedFormat + FloatType). One plane vertex sits on each texel
// (255 segments -> 256 x 256 vertices), so NearestFilter is exact and needs no float-linear extension.
import {
  DataTexture,
  DoubleSide,
  FloatType,
  NearestFilter,
  NoColorSpace,
  RedFormat,
  RGBAFormat,
  ShaderMaterial,
  Texture,
  UnsignedByteType,
  LinearFilter,
  type IUniform,
} from 'three'
import { CLASS_PALETTE, FIELD_RAMP, NDVI_RAMP, NDVI_RANGE } from './layers'

export const SITE_SIZE_M = 500
export const HEIGHT_GRID = 256
export const MAX_RELIEF_M = 40
/** Plane segments per side: one vertex per height texel. */
export const SURFACE_SEGMENTS = HEIGHT_GRID - 1
export const SURFACE_ROTATION_X = -Math.PI / 2
export const SURFACE_POSITION: [number, number, number] = [SITE_SIZE_M / 2, 0, SITE_SIZE_M / 2]

/** Height in metres of one u16 sample: 0..65535 -> 0..maxRelief, times the exaggeration. */
export function heightMetres(u16: number, maxRelief: number, exaggeration: number): number {
  return (u16 / 65535) * maxRelief * exaggeration
}

/** Scene position (react-three-map frame: x east, y up, z south) of site point (e, s) at height `up`. */
export function siteToScene(e: number, s: number, up: number): [number, number, number] {
  return [e, up, s]
}

/** PlaneGeometry texture coordinate of site point (e, s). */
export function uvForSite(e: number, s: number): [number, number] {
  return [e / SITE_SIZE_M, 1 - s / SITE_SIZE_M]
}

/** Which height-map texel the vertex shader samples at plane uv (u, v): it reads (u, 1 - v). */
export function heightTexelForUv(u: number, v: number): { row: number; col: number } {
  const clamp = (x: number) => Math.min(HEIGHT_GRID - 1, Math.max(0, Math.floor(x * HEIGHT_GRID)))
  return { row: clamp(1 - v), col: clamp(u) }
}

/** Zone centre in site metres (F4): column c = A..E east, row r = 1..5 south. */
export function zoneCentreSite(col: number, row: number): [number, number] {
  return [100 * col + 50, 100 * row + 50]
}

/** u16 heights -> Float32 0..1 (into `out`). */
export function normaliseHeights(src: Uint16Array, out: Float32Array): void {
  for (let i = 0; i < src.length; i++) out[i] = src[i]! / 65535
}

/** Coverage rings drawn by the surface shader (a `#define` in GLSL, so a fixed uniform array size). */
export const MAX_RINGS = 16

/**
 * Coverage-ring overlay data. The typed arrays are handed to the shader as its uniform arrays (the
 * same objects), so writing them and bumping nothing else is enough: the next render uploads them.
 */
export interface RingBuffers {
  /** Site metres (e, s) per ring, flattened: [e0, s0, e1, s1, ...]. */
  centres: Float32Array
  /** Radius in metres per ring. */
  radii: Float32Array
  /** Linear RGB 0..1 per ring, flattened. */
  colours: Float32Array
  count: number
}

export interface Ring {
  e: number
  s: number
  radius: number
  /** CSS hex colour, e.g. "#1aa7ff". */
  colour: string
}

function hexToRgb(hex: string): [number, number, number] {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim())
  const v = m ? parseInt(m[1]!, 16) : 0xffffff
  return [((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255]
}

/** Writes up to MAX_RINGS rings into the buffers (extra rings are dropped). Returns the count written. */
export function packRings(buf: RingBuffers, rings: Ring[]): number {
  const n = Math.min(rings.length, MAX_RINGS)
  buf.centres.fill(0)
  buf.radii.fill(0)
  buf.colours.fill(0)
  for (let i = 0; i < n; i++) {
    const r = rings[i]!
    buf.centres[2 * i] = r.e
    buf.centres[2 * i + 1] = r.s
    buf.radii[i] = r.radius
    const [cr, cg, cb] = hexToRgb(r.colour)
    buf.colours[3 * i] = cr
    buf.colours[3 * i + 1] = cg
    buf.colours[3 * i + 2] = cb
  }
  buf.count = n
  return n
}

export function createRingBuffers(): RingBuffers {
  return {
    centres: new Float32Array(MAX_RINGS * 2),
    radii: new Float32Array(MAX_RINGS),
    colours: new Float32Array(MAX_RINGS * 3),
    count: 0,
  }
}

/** Overlay modes of the surface shader (`uOverlayMode`). */
export const OVERLAY_NONE = 0
export const OVERLAY_NDVI = 1
export const OVERLAY_CLASSES = 2
export const OVERLAY_FIELD = 3
export type OverlayMode = 0 | 1 | 2 | 3

/**
 * The one overlay texture the surface blends (Digital Twin layers). NDVI: R = VARI mapped from [-1, 1]
 * to 0..1. Classes: R = class code / 255 (NearestFilter). Field: R = value in the legend range 0..1,
 * A = 0 outside the mask. Owned by the layer that sets it.
 */
export interface SurfaceOverlay {
  mode: OverlayMode
  texture: Texture | null
  opacity: number
}

/** Mutable state shared between the surface and the labels; written in useFrame, never React state. */
export interface SurfaceState {
  heights: Float32Array
  hasHeights: boolean
  base: number
  exaggeration: number
  maxRelief: number
  rings: RingBuffers
  overlay: SurfaceOverlay
  /** Zone grid lines (100 m) on the surface. */
  grid: boolean
  /** The reality surface's own colour (the live raster); off leaves only overlays, grid and rings. */
  reality: boolean
}

export function createSurfaceState(): SurfaceState {
  return {
    heights: new Float32Array(HEIGHT_GRID * HEIGHT_GRID),
    hasHeights: false,
    base: 0.5,
    exaggeration: 1,
    maxRelief: MAX_RELIEF_M,
    rings: createRingBuffers(),
    overlay: { mode: OVERLAY_NONE, texture: null, opacity: 0 },
    grid: false,
    reality: true,
  }
}

/**
 * Whether the surface mesh draws at all: the live raster when a frame has arrived (and the reality
 * layer is on), or anything drawn over it (overlay, zone grid, coverage rings) even before the first
 * frame, so those layers never depend on a live camera frame.
 */
export function surfaceVisible(st: SurfaceState, hasColour: boolean): boolean {
  return (st.reality && hasColour && st.hasHeights) || st.overlay.mode !== OVERLAY_NONE || st.grid || st.rings.count > 0
}

/** Scene height (y) of the surface at site point (e, s). */
export function surfaceHeightAt(st: SurfaceState, e: number, s: number): number {
  const { row, col } = heightTexelForUv(...uvForSite(e, s))
  const h = st.hasHeights ? st.heights[row * HEIGHT_GRID + col]! : 0
  return st.base + h * st.maxRelief * st.exaggeration
}

const VERTEX = /* glsl */ `
uniform sampler2D uHeight;
uniform float uMaxRelief;
uniform float uExaggeration;
uniform float uBase;
varying vec2 vTex;
void main() {
  vTex = vec2(uv.x, 1.0 - uv.y);                      // row 0 = north edge
  float h = texture2D(uHeight, vTex).r;               // 0..1 (normalised u16)
  vec3 p = position; p.z += h * uMaxRelief * uExaggeration + uBase;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
}
`

function rampGlsl(name: string, stops: [number, number, number][]): string {
  const v = (c: [number, number, number]) => `vec3(${c.map((x) => x.toFixed(3)).join(', ')})`
  const n = stops.length - 1
  const lines = [`vec3 ${name}(float t) {`, `  t = clamp(t, 0.0, 1.0) * ${n.toFixed(1)};`]
  for (let i = 0; i < n; i++)
    lines.push(`  if (t <= ${(i + 1).toFixed(1)}) return mix(${v(stops[i]!)}, ${v(stops[i + 1]!)}, t - ${i.toFixed(1)});`)
  lines.push(`  return ${v(stops[n]!)};`, '}')
  return lines.join('\n')
}

const CLASS_GLSL = CLASS_PALETTE.map(
  (c) => `  if (k == ${c.code}) return vec3(${c.rgb.map((x) => (x / 255).toFixed(3)).join(', ')});`,
).join('\n')

export const FRAGMENT = /* glsl */ `
#define MAX_RINGS ${MAX_RINGS}
#define SITE_SIZE_M ${SITE_SIZE_M.toFixed(1)}
uniform sampler2D uColour;
uniform float uShowColour;          // 1 when the live raster is drawn (frame present, reality layer on)
// Digital Twin overlay: one texture at a time (0 none, 1 NDVI ramp, 2 classes palette, 3 field ramp).
uniform sampler2D uOverlayTex;
uniform int uOverlayMode;
uniform float uOverlayOpacity;
uniform float uGrid;                // zone grid lines (100 m) when 1
// Coverage rings (Sentinel Network): centre in site metres (e, s), radius in metres, colour.
uniform vec2 uRingCentres[MAX_RINGS];
uniform float uRingRadii[MAX_RINGS];
uniform vec3 uRingColours[MAX_RINGS];
uniform int uRingCount;
uniform float uRingOpacity;
varying vec2 vTex;
${rampGlsl('fieldRamp', FIELD_RAMP)}
${rampGlsl('ndviRamp', NDVI_RAMP)}
vec3 classColour(int k) {
${CLASS_GLSL}
  return vec3(0.0);
}
void main() {
  vec4 c = vec4(texture2D(uColour, vTex).rgb, uShowColour);
  if (uOverlayMode > 0) {
    vec4 o = texture2D(uOverlayTex, vTex);
    vec3 oc;
    float a = o.a;
    if (uOverlayMode == 1) {
      float vari = o.r * 2.0 - 1.0;
      oc = ndviRamp((vari - (${NDVI_RANGE[0].toFixed(3)})) / ${(NDVI_RANGE[1] - NDVI_RANGE[0]).toFixed(3)});
    } else if (uOverlayMode == 2) {
      int k = int(o.r * 255.0 + 0.5);
      oc = classColour(k);
      a *= k > 0 ? 1.0 : 0.0;
    } else {
      oc = fieldRamp(o.r);
    }
    float w = clamp(uOverlayOpacity * a, 0.0, 1.0);
    c.rgb = mix(c.rgb, oc, c.a > 0.0 ? w : 1.0);
    c.a = max(c.a, w);
  }
  // vTex = (e, s) / 500: row 0 is the north edge, so this is the site-metre position of the fragment.
  vec2 p = vTex * SITE_SIZE_M;
  if (uGrid > 0.5) {
    vec2 g = abs(fract(p / 100.0 + 0.5) - 0.5) * 100.0;   // metres to the nearest grid line
    float line = 1.0 - smoothstep(0.6, 1.8, min(g.x, g.y));
    c.rgb = mix(c.rgb, vec3(0.25, 0.88, 0.82), c.a > 0.0 ? line * 0.75 : 1.0);
    c.a = max(c.a, line * 0.75);
  }
  for (int i = 0; i < MAX_RINGS; i++) {
    if (i >= uRingCount) break;
    float d = distance(p, uRingCentres[i]);
    float r = uRingRadii[i];
    float edge = 1.0 - smoothstep(0.6, 2.2, abs(d - r));   // a ~3 m line on the circle
    float fill = d < r ? 0.07 : 0.0;                        // faint tint inside the coverage
    float w = clamp(max(edge * 0.9, fill) * uRingOpacity, 0.0, 1.0);
    c.rgb = mix(c.rgb, uRingColours[i], c.a > 0.0 ? w : 1.0);
    c.a = max(c.a, w);
  }
  if (c.a <= 0.002) discard;
  gl_FragColor = c;
}
`

export interface SurfaceUniforms {
  [name: string]: IUniform
  uHeight: IUniform<DataTexture>
  uColour: IUniform<Texture>
  uShowColour: IUniform<number>
  uOverlayTex: IUniform<Texture>
  uOverlayMode: IUniform<number>
  uOverlayOpacity: IUniform<number>
  uGrid: IUniform<number>
  uExaggeration: IUniform<number>
  uMaxRelief: IUniform<number>
  uBase: IUniform<number>
  uRingCentres: IUniform<Float32Array>
  uRingRadii: IUniform<Float32Array>
  uRingColours: IUniform<Float32Array>
  uRingCount: IUniform<number>
  uRingOpacity: IUniform<number>
}

export interface SurfaceResources {
  material: ShaderMaterial & { uniforms: SurfaceUniforms }
  heightTexture: DataTexture
  colourTexture: Texture
  /** The 1 x 1 transparent texture bound while no overlay is set. */
  emptyOverlay: Texture
  dispose: () => void
}

export function createSurfaceMaterial(heights: Float32Array, rings: RingBuffers = createRingBuffers()): SurfaceResources {
  const heightTexture = new DataTexture(heights, HEIGHT_GRID, HEIGHT_GRID, RedFormat, FloatType)
  heightTexture.minFilter = NearestFilter
  heightTexture.magFilter = NearestFilter
  heightTexture.generateMipmaps = false
  heightTexture.flipY = false
  heightTexture.needsUpdate = true

  // The JPEG arrives as an ImageBitmap (decoded top row first); its sRGB bytes go straight to the
  // sRGB framebuffer Mapbox draws into, so no colour-space conversion either way.
  const colourTexture = new Texture()
  colourTexture.flipY = false
  colourTexture.colorSpace = NoColorSpace
  colourTexture.minFilter = LinearFilter
  colourTexture.magFilter = LinearFilter
  colourTexture.generateMipmaps = false

  const overlay = new DataTexture(new Uint8Array(4), 1, 1, RGBAFormat, UnsignedByteType)
  overlay.needsUpdate = true

  const uniforms: SurfaceUniforms = {
    uHeight: { value: heightTexture },
    uColour: { value: colourTexture },
    uShowColour: { value: 0 },
    uOverlayTex: { value: overlay },
    uOverlayMode: { value: OVERLAY_NONE },
    uOverlayOpacity: { value: 0 },
    uGrid: { value: 0 },
    uExaggeration: { value: 1 },
    uMaxRelief: { value: MAX_RELIEF_M },
    uBase: { value: 0.5 },
    // The ring arrays are the shared buffers themselves; uRingCount is copied per frame.
    uRingCentres: { value: rings.centres },
    uRingRadii: { value: rings.radii },
    uRingColours: { value: rings.colours },
    uRingCount: { value: rings.count },
    uRingOpacity: { value: 1 },
  }
  const material = new ShaderMaterial({
    uniforms,
    vertexShader: VERTEX,
    fragmentShader: FRAGMENT,
    // react-three-map folds a mirror (scale y = -1) into the projection, which flips winding.
    side: DoubleSide,
    // Before the first frame (or with the reality layer off) only the overlays, grid and rings draw.
    transparent: true,
  }) as ShaderMaterial & { uniforms: SurfaceUniforms }
  return {
    material,
    heightTexture,
    colourTexture,
    emptyOverlay: overlay,
    dispose: () => {
      material.dispose()
      heightTexture.dispose()
      colourTexture.dispose()
      overlay.dispose()
    },
  }
}
