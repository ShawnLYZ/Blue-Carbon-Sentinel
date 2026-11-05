// The Forest Scene (PRD decision 21): one renderer, two modes (Natural and Twin).
// Built once per session and moved between the Satellite Intelligence and Digital Twin pages.

import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { Sky } from 'three/examples/jsm/objects/Sky.js'
import { GRID, heightAt, N, ROOT_STRIDE, TREE_STRIDE, WATER_LEVEL, type ForestModel } from './model'
import { breathingRoot, buildVariants, REF_HEIGHT, type TreeVariant } from './trees'
import { canopyTexture, dashTexture, leafTexture, mudTextures, waterNormalTexture } from './textures'
import { REPLANT_PATCHES, SENSOR_POSTS, type PatchId } from '../site/catalogue'

export type ForestMode = 'natural' | 'twin'

export interface PickHit {
  x: number
  y: number
  z: number
}

const SKIRT_BOTTOM = -7
const NEAR_LOD_M = 150
const SUN_ELEVATION = 45
const SUN_AZIMUTH = 118 // degrees clockwise from north: late-morning sun in the east-south-east

const shared = { uTime: { value: 0 } }

function windChunk(strength: number) {
  return /* glsl */ `
    #include <begin_vertex>
    #ifdef USE_INSTANCING
      vec3 ip = vec3(instanceMatrix[3][0], instanceMatrix[3][1], instanceMatrix[3][2]);
    #else
      vec3 ip = vec3(0.0);
    #endif
    float hh = clamp(position.y / ${REF_HEIGHT.toFixed(1)}, 0.0, 1.4);
    float ph = ip.x * 0.071 + ip.z * 0.053;
    float sway = sin(uTime * 1.05 + ph) * 0.65 + sin(uTime * 2.2 + ph * 1.7) * 0.25;
    transformed.x += sway * ${(0.09 * strength).toFixed(3)} * hh * hh * 12.0 / 12.0;
    transformed.z += cos(uTime * 0.85 + ph * 1.3) * ${(0.06 * strength).toFixed(3)} * hh * hh;
    transformed += objectNormal * sin(uTime * 3.6 + position.x * 2.7 + position.z * 2.1 + ph) * ${(0.035 * strength).toFixed(3)} * hh;
  `
}

/** Adds wind sway and an instanced tint (rgb + mix) to a standard material. */
function foliageMaterial(params: THREE.MeshStandardMaterialParameters, strength: number, keepNormals: boolean) {
  const m = new THREE.MeshStandardMaterial(params)
  m.onBeforeCompile = (shader) => {
    shader.uniforms.uTime = shared.uTime
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nuniform float uTime;\nattribute vec4 instTint;\nvarying vec4 vTint;')
      .replace('#include <begin_vertex>', windChunk(strength) + '\nvTint = instTint;')
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', '#include <common>\nvarying vec4 vTint;')
      .replace('#include <color_fragment>', '#include <color_fragment>\ndiffuseColor.rgb = mix(diffuseColor.rgb, vTint.rgb * 0.82, vTint.a);')
    if (keepNormals) {
      // Foliage normals stay spherical on both faces of a leaf card.
      shader.fragmentShader = shader.fragmentShader.replace(
        '#include <normal_fragment_begin>',
        THREE.ShaderChunk.normal_fragment_begin.replace('normal *= faceDirection;', ''),
      )
    }
  }
  return m
}

function foliageDepthMaterial(map: THREE.Texture | null, strength: number) {
  const m = new THREE.MeshDepthMaterial({ depthPacking: THREE.RGBADepthPacking, map, alphaTest: map ? 0.45 : 0 })
  m.onBeforeCompile = (shader) => {
    shader.uniforms.uTime = shared.uTime
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nuniform float uTime;')
      .replace('#include <begin_vertex>', windChunk(strength).replace(/objectNormal/g, 'vec3(0.0, 1.0, 0.0)'))
  }
  return m
}

interface LodSet {
  near: { bark: THREE.InstancedMesh; leaves: THREE.InstancedMesh; core: THREE.InstancedMesh }[]
  far: { crown: THREE.InstancedMesh }[]
}

export class ForestView {
  readonly renderer: THREE.WebGLRenderer
  readonly scene = new THREE.Scene()
  readonly camera = new THREE.PerspectiveCamera(40, 1, 1, 16000)
  readonly controls: OrbitControls
  private model: ForestModel
  private container: HTMLElement | null = null
  private resizeObs: ResizeObserver | null = null
  private timer = new THREE.Timer()
  private sun = new THREE.DirectionalLight(0xfff0d8, 3.6)
  private sunDir = new THREE.Vector3()
  private variants: TreeVariant[]
  private lod: LodSet = { near: [], far: [] }
  private treeMatrices: Float32Array
  private treeNatural: Float32Array
  private treeTint: Float32Array
  private treeVariant: Uint8Array
  private byVariant: number[][] = [[], [], [], []]
  private rootsMesh: THREE.InstancedMesh
  private rootMatrices: Float32Array
  private lastLodPos = new THREE.Vector3(1e9, 0, 0)
  private lastLodQuat = new THREE.Quaternion()
  private frustum = new THREE.Frustum()
  private projScreen = new THREE.Matrix4()
  private sphere = new THREE.Sphere()
  private lodDistance = NEAR_LOD_M
  private overlayTex: THREE.DataTexture
  private overlayMix = { value: 0 }
  mode: ForestMode = 'natural'
  private twinGroup = new THREE.Group()
  private patchGroup = new THREE.Group()
  private dash = dashTexture()
  private anchors = new Map<HTMLElement, THREE.Vector3>()
  private frameHooks = new Set<() => void>()
  private quality = 0
  private fpsFrames = 0
  private fpsStart = 0
  private lowWindows = 0
  private focusAnim: {
    from: THREE.Vector3; to: THREE.Vector3; camFrom: THREE.Vector3; camTo: THREE.Vector3; t0: number
    ms?: number; smooth?: boolean; done?: () => void
  } | null = null
  private running = false
  private disposed = false

  constructor(model: ForestModel) {
    this.model = model
    this.renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5))
    this.renderer.outputColorSpace = THREE.SRGBColorSpace
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping
    this.renderer.toneMappingExposure = 0.52
    this.renderer.shadowMap.enabled = true
    this.renderer.shadowMap.type = THREE.PCFShadowMap
    this.renderer.domElement.className = 'forest-canvas'

    this.controls = new OrbitControls(this.camera, this.renderer.domElement)
    this.controls.enableDamping = true
    this.controls.dampingFactor = 0.08
    this.controls.minDistance = 20
    this.controls.maxDistance = 1200
    this.controls.maxPolarAngle = 1.47
    this.controls.minPolarAngle = 0.08
    this.controls.zoomToCursor = true
    this.controls.screenSpacePanning = false
    this.controls.zoomSpeed = 0.9
    this.controls.rotateSpeed = 0.55

    this.buildAtmosphere()
    this.variants = buildVariants()
    const count = model.trees.length / TREE_STRIDE
    this.treeMatrices = new Float32Array(count * 16)
    this.treeNatural = new Float32Array(count * 3)
    this.treeTint = new Float32Array(count * 4)
    this.treeVariant = new Uint8Array(count)
    this.buildTrees()
    const roots = this.buildRoots()
    this.rootsMesh = roots.mesh
    this.rootMatrices = roots.matrices
    this.overlayTex = new THREE.DataTexture(new Uint8Array(N * N * 4), N, N, THREE.RGBAFormat)
    this.overlayTex.magFilter = THREE.LinearFilter
    this.overlayTex.minFilter = THREE.LinearFilter
    this.overlayTex.colorSpace = THREE.SRGBColorSpace
    this.overlayTex.needsUpdate = true
    this.buildTerrain()
    this.buildWater()
    this.buildSkirt()
    this.buildPosts()
    this.scene.add(this.twinGroup)
    this.twinGroup.add(this.patchGroup)
    this.twinGroup.visible = false

    this.renderer.domElement.addEventListener('dblclick', this.onDoubleClick)
  }

  // ---------------------------------------------------------------- building

  private buildAtmosphere() {
    const sky = new Sky()
    sky.scale.setScalar(10000)
    const u = sky.material.uniforms
    u.turbidity.value = 5.5
    u.rayleigh.value = 1.35
    u.mieCoefficient.value = 0.0045
    u.mieDirectionalG.value = 0.82
    const phi = THREE.MathUtils.degToRad(90 - SUN_ELEVATION)
    const theta = THREE.MathUtils.degToRad(SUN_AZIMUTH)
    // three.js: x east, z south. Azimuth measured clockwise from north (-z).
    this.sunDir.setFromSphericalCoords(1, phi, Math.PI - theta)
    u.sunPosition.value.copy(this.sunDir)

    const pmrem = new THREE.PMREMGenerator(this.renderer)
    const envScene = new THREE.Scene()
    envScene.add(sky)
    this.scene.environment = pmrem.fromScene(envScene, 0, 0.1, 20000).texture
    this.scene.environmentIntensity = 0.42
    pmrem.dispose()
    this.scene.add(sky)

    const haze = new THREE.Color('#cfdbe0')
    this.scene.fog = new THREE.FogExp2(haze, 0.00038)

    const hemi = new THREE.HemisphereLight(0xcfe3f2, 0x5b4a36, 0.3)
    this.scene.add(hemi)

    this.sun.castShadow = true
    this.sun.shadow.mapSize.set(2048, 2048)
    const sc = this.sun.shadow.camera
    sc.left = -170; sc.right = 170; sc.top = 170; sc.bottom = -170
    sc.near = 10; sc.far = 1400
    sc.updateProjectionMatrix()
    this.sun.shadow.bias = -0.00035
    this.sun.shadow.normalBias = 0.45
    this.sun.shadow.radius = 3
    this.scene.add(this.sun, this.sun.target)

    // A soft plain under the tile, fading into the haze.
    const plain = new THREE.Mesh(
      new THREE.CircleGeometry(9000, 64).rotateX(-Math.PI / 2),
      new THREE.MeshStandardMaterial({ color: '#aebcb1', roughness: 1, metalness: 0 }),
    )
    plain.position.y = SKIRT_BOTTOM - 0.05
    plain.receiveShadow = true
    this.scene.add(plain)

    // A soft contact shadow so the tile sits on the plain.
    const cv = document.createElement('canvas')
    cv.width = cv.height = 256
    const g = cv.getContext('2d')!
    g.filter = 'blur(18px)'
    g.fillStyle = 'rgba(30, 40, 34, 0.55)'
    g.fillRect(52, 52, 152, 152)
    const contact = new THREE.Mesh(
      new THREE.PlaneGeometry(860, 860).rotateX(-Math.PI / 2),
      new THREE.MeshBasicMaterial({
        map: new THREE.CanvasTexture(cv), transparent: true, depthWrite: false,
        polygonOffset: true, polygonOffsetFactor: -4, polygonOffsetUnits: -4,
      }),
    )
    contact.position.y = SKIRT_BOTTOM + 0.3
    contact.renderOrder = 1
    this.scene.add(contact)
  }

  private infoAt(x: number, z: number, ch: number): number {
    const i = Math.min(N - 1, Math.max(0, Math.floor(x + 250)))
    const j = Math.min(N - 1, Math.max(0, Math.floor(z + 250)))
    return this.model.info[(j * N + i) * 4 + ch] / 255
  }

  private buildTerrain() {
    const { heights } = this.model
    const pos = new Float32Array(GRID * GRID * 3)
    const uv = new Float32Array(GRID * GRID * 2)
    const col = new Float32Array(GRID * GRID * 3)
    const wet = new Float32Array(GRID * GRID)
    // Colours are written in sRGB (hex) and converted to linear by three.js.
    const cMud = new THREE.Color('#6a5b45')
    const cShade = new THREE.Color('#3d3325')
    const cDry = new THREE.Color('#8a7f60')
    const cGrass = new THREE.Color('#717650')
    const cWet = new THREE.Color('#3b3225')
    const cUnder = new THREE.Color('#2e281e')
    const c = new THREE.Color()
    for (let j = 0; j < GRID; j++) {
      for (let i = 0; i < GRID; i++) {
        const k = j * GRID + i
        const x = i * 2 - 250, z = j * 2 - 250
        const h = heights[k]
        pos[k * 3] = x; pos[k * 3 + 1] = h; pos[k * 3 + 2] = z
        uv[k * 2] = (x + 250) / 500; uv[k * 2 + 1] = (z + 250) / 500
        const w = this.infoAt(x, z, 0), shade = this.infoAt(x, z, 1), dry = this.infoAt(x, z, 3)
        const grass = 0.5 + 0.5 * Math.sin(x * 0.05 + Math.cos(z * 0.043) * 2.1)
        c.copy(cMud).lerp(c.clone().copy(cDry).lerp(cGrass, grass * 0.6), dry * 0.85)
        c.lerp(cShade, shade * 0.85)
        c.lerp(cWet, Math.min(1, w * 1.1))
        if (h < WATER_LEVEL) c.lerp(cUnder, Math.min(1, (WATER_LEVEL - h) * 2))
        col[k * 3] = c.r; col[k * 3 + 1] = c.g; col[k * 3 + 2] = c.b
        wet[k] = Math.min(1, w * 1.3 + (h < WATER_LEVEL + 0.15 ? 0.5 : 0))
      }
    }
    const idx: number[] = []
    for (let j = 0; j < GRID - 1; j++) {
      for (let i = 0; i < GRID - 1; i++) {
        const a = j * GRID + i, b = a + 1, d = a + GRID, e = d + 1
        idx.push(a, d, b, b, d, e)
      }
    }
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3))
    g.setAttribute('uv', new THREE.BufferAttribute(uv, 2))
    g.setAttribute('color', new THREE.BufferAttribute(col, 3))
    g.setAttribute('wet', new THREE.BufferAttribute(wet, 1))
    g.setIndex(idx)
    g.computeVertexNormals()

    const mud = mudTextures()
    mud.map.repeat.set(70, 70)
    mud.normal.repeat.set(70, 70)
    const mat = new THREE.MeshStandardMaterial({
      vertexColors: true, map: mud.map, normalMap: mud.normal, normalScale: new THREE.Vector2(0.9, 0.9),
      roughness: 0.94, metalness: 0,
    })
    const overlayTex = this.overlayTex, overlayMix = this.overlayMix
    mat.onBeforeCompile = (shader) => {
      shader.uniforms.uOverlay = { value: overlayTex }
      shader.uniforms.uOverlayMix = overlayMix
      shader.vertexShader = shader.vertexShader
        .replace('#include <common>', '#include <common>\nattribute float wet;\nvarying float vWet;\nvarying vec2 vInfoUv;')
        .replace('#include <begin_vertex>', '#include <begin_vertex>\nvWet = wet;\nvInfoUv = uv;')
      shader.fragmentShader = shader.fragmentShader
        .replace('#include <common>', '#include <common>\nuniform sampler2D uOverlay;\nuniform float uOverlayMix;\nvarying float vWet;\nvarying vec2 vInfoUv;')
        .replace('#include <color_fragment>', `#include <color_fragment>
          vec4 ov = texture2D(uOverlay, vInfoUv);
          diffuseColor.rgb = mix(diffuseColor.rgb, ov.rgb * 0.92, ov.a * uOverlayMix);`)
        .replace('#include <roughnessmap_fragment>', '#include <roughnessmap_fragment>\nroughnessFactor = mix(roughnessFactor, 0.32, vWet);')
    }
    const terrain = new THREE.Mesh(g, mat)
    terrain.receiveShadow = true
    terrain.name = 'terrain'
    this.scene.add(terrain)
  }

  private buildWater() {
    const g = new THREE.PlaneGeometry(500, 500, 1, 1).rotateX(-Math.PI / 2)
    g.translate(0, WATER_LEVEL, 0)
    // PlaneGeometry uv.y runs north-up after rotation; flip it to match the info texture rows (north = row 0).
    const uv = g.getAttribute('uv') as THREE.BufferAttribute
    for (let i = 0; i < uv.count; i++) uv.setY(i, 1 - uv.getY(i))
    const info = new THREE.DataTexture(this.model.info, N, N, THREE.RGBAFormat)
    info.magFilter = THREE.LinearFilter
    info.minFilter = THREE.LinearFilter
    info.needsUpdate = true
    const ripple = waterNormalTexture()
    const mat = new THREE.MeshStandardMaterial({
      color: '#3d4a3c', roughness: 0.16, metalness: 0, transparent: true, depthWrite: false, envMapIntensity: 0.6,
    })
    const overlayTex = this.overlayTex, overlayMix = this.overlayMix
    mat.onBeforeCompile = (shader) => {
      shader.uniforms.uTime = shared.uTime
      shader.uniforms.uInfo = { value: info }
      shader.uniforms.uRipple = { value: ripple }
      shader.uniforms.uOverlay = { value: overlayTex }
      shader.uniforms.uOverlayMix = overlayMix
      shader.uniforms.uSkyTint = { value: new THREE.Color('#8fb6cc') }
      shader.vertexShader = shader.vertexShader
        .replace('#include <common>', '#include <common>\nvarying vec2 vInfoUv;\nvarying vec2 vWorldXZ;')
        .replace('#include <begin_vertex>', '#include <begin_vertex>\nvInfoUv = uv;\nvWorldXZ = (modelMatrix * vec4(position, 1.0)).xz;')
      shader.fragmentShader = shader.fragmentShader
        .replace('#include <common>', `#include <common>
          uniform float uTime; uniform sampler2D uInfo; uniform sampler2D uRipple; uniform sampler2D uOverlay; uniform float uOverlayMix; uniform vec3 uSkyTint;
          varying vec2 vInfoUv; varying vec2 vWorldXZ;`)
        .replace('#include <color_fragment>', `#include <color_fragment>
          vec4 inf = texture2D(uInfo, vInfoUv);
          float presence = smoothstep(0.12, 0.5, inf.b);
          if (presence < 0.01) discard;
          float deep = smoothstep(0.5, 1.0, inf.r);
          float shallow = 1.0 - smoothstep(0.3, 0.8, inf.b);
          diffuseColor.rgb = mix(diffuseColor.rgb * 1.1, diffuseColor.rgb * 0.62, deep);
          diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.2, 0.17, 0.1), shallow * 0.55);
          vec4 ov = texture2D(uOverlay, vInfoUv);
          diffuseColor.rgb = mix(diffuseColor.rgb, ov.rgb * 0.8, ov.a * uOverlayMix * 0.85);
          diffuseColor.a = mix(0.85, 0.98, deep) * presence;`)
        .replace('#include <normal_fragment_maps>', `
          vec2 q = vWorldXZ;
          vec3 n1 = texture2D(uRipple, q * 0.035 + vec2(uTime * 0.010, uTime * 0.006)).xyz * 2.0 - 1.0;
          vec3 n2 = texture2D(uRipple, q * 0.09 + vec2(-uTime * 0.008, uTime * 0.011)).xyz * 2.0 - 1.0;
          vec3 n3 = texture2D(uRipple, q * 0.011 + vec2(uTime * 0.004, -uTime * 0.003)).xyz * 2.0 - 1.0;
          float fade = clamp(1.0 - length(vViewPosition) / 1400.0, 0.55, 1.0);
          vec3 wn = normalize(vec3((n1.x + n2.x) * 0.26 * fade + n3.x * 0.5, 1.0, (n1.y + n2.y) * 0.26 * fade + n3.y * 0.5));
          normal = normalize((viewMatrix * vec4(wn, 0.0)).xyz);`)
        // A sky sheen that grows towards grazing angles, so the river reads as water from the air.
        .replace('#include <opaque_fragment>', `
          float facing = clamp(dot(normal, normalize(vViewPosition)), 0.0, 1.0);
          float streak = 0.75 + 0.5 * clamp(n3.x * 0.9 + n3.y * 0.6, -1.0, 1.0);
          float sheen = (0.2 + 0.65 * pow(1.0 - facing, 2.0)) * streak * (1.0 - ov.a * uOverlayMix);
          outgoingLight = mix(outgoingLight, uSkyTint * 0.62, clamp(sheen, 0.0, 0.85));
          // A pale wet line where the water meets the mud.
          float waterline = smoothstep(0.12, 0.22, inf.b) * (1.0 - smoothstep(0.22, 0.38, inf.b));
          outgoingLight = mix(outgoingLight, vec3(0.42, 0.4, 0.33) * 0.55, waterline * 0.7);
          #include <opaque_fragment>`)
    }
    const water = new THREE.Mesh(g, mat)
    water.receiveShadow = true
    water.renderOrder = 2
    this.scene.add(water)
  }

  /** The tile's cut edges: layered mud, with the water's cross-section where a channel meets the edge. */
  private buildSkirt() {
    const { heights } = this.model
    const pos: number[] = [], col: number[] = [], idx: number[] = []
    const layers = [-0.5, -1.6, -2.9, -4.4, SKIRT_BOTTOM]
    const soil = ['#3a2e21', '#5a4a37', '#4b3e30', '#66573f', '#544838'].map((h) => new THREE.Color(h))
    const waterCol = new THREE.Color('#2f4548')
    const edge = (fx: (t: number) => [number, number, number], outward: THREE.Vector3) => {
      const cols = GRID
      const rows = 2 + layers.length
      const base = pos.length / 3
      for (let i = 0; i < cols; i++) {
        const [x, z, h] = fx(i)
        const top = Math.max(h, WATER_LEVEL)
        const ys = [top, Math.min(h, top), ...layers.map((l) => Math.min(l, h - 0.05))]
        for (let r = 0; r < rows; r++) {
          pos.push(x, ys[r], z)
          const c = r === 0 && h < WATER_LEVEL ? waterCol : r <= 1 ? (h < WATER_LEVEL ? waterCol : soil[0]) : soil[Math.min(soil.length - 1, r - 2)]
          col.push(c.r, c.g, c.b)
        }
      }
      for (let i = 0; i < cols - 1; i++) {
        for (let r = 0; r < rows - 1; r++) {
          const a = base + i * rows + r, b = a + rows
          if (outward.x + outward.z > 0) idx.push(a, a + 1, b, b, a + 1, b + 1)
          else idx.push(a, b, a + 1, b, b + 1, a + 1)
        }
      }
    }
    const H = (i: number, j: number) => heights[j * GRID + i]
    edge((i) => [i * 2 - 250, -250, H(i, 0)], new THREE.Vector3(0, 0, -1))
    edge((i) => [i * 2 - 250, 250, H(i, GRID - 1)], new THREE.Vector3(0, 0, 1))
    edge((i) => [-250, i * 2 - 250, H(0, i)], new THREE.Vector3(-1, 0, 0))
    edge((i) => [250, i * 2 - 250, H(GRID - 1, i)], new THREE.Vector3(1, 0, 0))
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
    g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3))
    g.setIndex(idx)
    g.computeVertexNormals()
    const skirt = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.96, side: THREE.DoubleSide }))
    skirt.receiveShadow = true
    skirt.castShadow = true
    this.scene.add(skirt)
  }

  private buildTrees() {
    const t = this.model.trees
    const count = t.length / TREE_STRIDE
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), e = new THREE.Euler(), p = new THREE.Vector3(), s = new THREE.Vector3()
    const natural = new THREE.Color()
    for (let k = 0; k < count; k++) {
      const o = k * TREE_STRIDE
      const x = t[o], z = t[o + 1], h = t[o + 2], cs = t[o + 3], rot = t[o + 4], v = t[o + 5], tint = t[o + 6], lean = t[o + 7]
      const scale = h / REF_HEIGHT
      p.set(x, heightAt(this.model.heights, x, z) - 0.05, z)
      e.set(lean, rot, lean * 0.6)
      q.setFromEuler(e)
      s.set(scale * cs, scale, scale * cs)
      m.compose(p, q, s)
      m.toArray(this.treeMatrices, k * 16)
      // Per-tree variation: most crowns deep green, some lighter, a few yellowing.
      const lum = 0.72 + tint * 0.42
      natural.setRGB(lum * (0.9 + tint * 0.1), lum * (0.98 + tint * 0.04), lum * (0.82 - tint * 0.1))
      if (tint > 0.94) natural.setRGB(1.1, 1.0, 0.62)
      natural.toArray(this.treeNatural, k * 3)
      this.treeVariant[k] = v
      this.byVariant[v].push(k)
    }
    const leaf = leafTexture()
    const canopy = canopyTexture()
    const barkMat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.92, metalness: 0, envMapIntensity: 0.45 })
    const leafMat = foliageMaterial({
      map: leaf, alphaTest: 0.45, side: THREE.DoubleSide, vertexColors: true, roughness: 0.8, metalness: 0, envMapIntensity: 0.6,
    }, 1, true)
    const leafDepth = foliageDepthMaterial(leaf, 1)
    const farMat = foliageMaterial({ map: canopy, vertexColors: true, roughness: 0.8, metalness: 0 }, 0.6, false)
    const farDepth = foliageDepthMaterial(null, 0.6)

    for (let v = 0; v < 4; v++) {
      const cap = Math.max(1, this.byVariant[v].length)
      const variant = this.variants[v]
      const mk = (geo: THREE.BufferGeometry, mat: THREE.Material, tinted: boolean, depth?: THREE.Material) => {
        const mesh = new THREE.InstancedMesh(geo, mat, cap)
        mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage)
        mesh.frustumCulled = false
        mesh.castShadow = true
        mesh.receiveShadow = true
        mesh.count = 0
        if (depth) mesh.customDepthMaterial = depth
        mesh.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(cap * 3), 3)
        mesh.instanceColor.setUsage(THREE.DynamicDrawUsage)
        if (tinted) {
          const attr = new THREE.InstancedBufferAttribute(new Float32Array(cap * 4), 4)
          attr.setUsage(THREE.DynamicDrawUsage)
          geo.setAttribute('instTint', attr)
        }
        this.scene.add(mesh)
        return mesh
      }
      const leavesGeo = variant.leaves
      const farGeo = variant.far
      this.lod.near.push({
        bark: mk(variant.bark, barkMat, false),
        leaves: mk(leavesGeo, leafMat, true, leafDepth),
        core: mk(variant.core, farMat, true, farDepth),
      })
      this.lod.far.push({ crown: mk(farGeo, farMat, true, farDepth) })
    }
  }

  private buildRoots() {
    const r = this.model.roots
    const count = r.length / ROOT_STRIDE
    const matrices = new Float32Array(count * 16)
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), e = new THREE.Euler(), p = new THREE.Vector3(), s = new THREE.Vector3()
    for (let k = 0; k < count; k++) {
      const o = k * ROOT_STRIDE
      p.set(r[o], heightAt(this.model.heights, r[o], r[o + 1]) - 0.03, r[o + 1])
      e.set(Math.sin(r[o + 3]) * 0.12, 0, Math.cos(r[o + 3]) * 0.12)
      q.setFromEuler(e)
      s.set(1, r[o + 2], 1)
      m.compose(p, q, s).toArray(matrices, k * 16)
    }
    const mesh = new THREE.InstancedMesh(breathingRoot(), new THREE.MeshStandardMaterial({ color: '#5b4b3b', roughness: 0.9 }), Math.min(count, 14000))
    mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage)
    mesh.frustumCulled = false
    mesh.count = 0
    mesh.castShadow = false
    mesh.receiveShadow = true
    this.scene.add(mesh)
    return { mesh, matrices }
  }

  /** A pole with a sensor box and solar panel at every sensor post; only the Sentinel Station carries the camera. */
  private buildPosts() {
    const white = new THREE.MeshStandardMaterial({ color: '#f4f6f5', roughness: 0.5 })
    const dark = new THREE.MeshStandardMaterial({ color: '#1f2b33', roughness: 0.35, metalness: 0.3 })
    const teal = new THREE.MeshStandardMaterial({ color: '#0F766E', roughness: 0.5 })
    const grey = new THREE.MeshStandardMaterial({ color: '#8E9A95', roughness: 0.5 })
    const poleGeo = new THREE.CylinderGeometry(0.07, 0.09, 4.4, 10)
    const boxGeo = new THREE.BoxGeometry(0.55, 0.42, 0.32)
    const stripeGeo = new THREE.BoxGeometry(0.56, 0.06, 0.33)
    const panelGeo = new THREE.BoxGeometry(0.9, 0.04, 0.6)
    const camGeo = new THREE.CylinderGeometry(0.07, 0.07, 0.22, 12).rotateX(Math.PI / 2)
    for (const post of SENSOR_POSTS) {
      const g = new THREE.Group()
      const pole = new THREE.Mesh(poleGeo, white)
      pole.position.y = 2.2
      const box = new THREE.Mesh(boxGeo, white)
      box.position.set(0, 2.5, 0.2)
      const stripe = new THREE.Mesh(stripeGeo, post.live ? teal : grey)
      stripe.position.set(0, 2.62, 0.2)
      const panel = new THREE.Mesh(panelGeo, dark)
      panel.position.set(0, 4.45, 0)
      panel.rotation.x = -0.35
      g.add(pole, box, stripe, panel)
      if (post.live) {
        const cam = new THREE.Mesh(camGeo, dark)
        cam.position.set(0, 3.4, 0.2)
        g.add(cam)
      }
      g.children.forEach((c) => { c.castShadow = true })
      g.position.set(post.x, heightAt(this.model.heights, post.x, post.z), post.z)
      g.rotation.y = -0.6
      this.scene.add(g)
    }
  }

  // ---------------------------------------------------------------- public API

  attach(container: HTMLElement) {
    if (this.disposed) return
    this.container = container
    container.appendChild(this.renderer.domElement)
    this.resizeObs?.disconnect()
    this.resizeObs = new ResizeObserver(() => this.resize())
    this.resizeObs.observe(container)
    this.resize()
    // Every page starts from its own good aerial view (the panels have different shapes).
    this.focusAnim = null
    this.controls.enabled = true
    this.frameAll()
    this.start()
  }

  detach(container: HTMLElement) {
    if (this.container !== container) return
    this.stop()
    this.resizeObs?.disconnect()
    this.resizeObs = null
    if (this.renderer.domElement.parentElement === container) container.removeChild(this.renderer.domElement)
    this.container = null
  }

  setMode(mode: ForestMode) {
    this.mode = mode
    this.twinGroup.visible = mode === 'twin'
    this.overlayMix.value = mode === 'twin' ? this.overlayMix.value : 0
    if (mode === 'natural') this.applyTint(null)
  }

  /** Paints the Digital Twin layer: ground and water get the overlay, crowns are tinted from it. */
  setOverlay(rgba: Uint8Array | null, mix: number) {
    if (!rgba) {
      this.overlayMix.value = 0
      this.applyTint(null)
      return
    }
    ;(this.overlayTex.image.data as Uint8Array).set(rgba)
    this.overlayTex.needsUpdate = true
    this.overlayMix.value = mix
    this.applyTint(rgba, mix)
  }

  setPlantings(ids: PatchId[]) {
    this.patchGroup.clear()
    const mat = new THREE.MeshBasicMaterial({ color: '#ffffff', alphaMap: this.dash, alphaTest: 0.5, side: THREE.DoubleSide })
    for (const p of REPLANT_PATCHES) {
      if (!ids.includes(p.id)) continue
      const ring = p.ring
      const n = ring.length / 2
      const pos: number[] = [], uv: number[] = [], idx: number[] = []
      let along = 0
      for (let i = 0; i <= n; i++) {
        const a = i % n, b = (i + 1) % n, prev = (i - 1 + n) % n
        const x = ring[a * 2], z = ring[a * 2 + 1]
        const dx = ring[b * 2] - ring[prev * 2], dz = ring[b * 2 + 1] - ring[prev * 2 + 1]
        const len = Math.hypot(dx, dz) || 1
        const nx = -dz / len, nz = dx / len
        if (i > 0) along += Math.hypot(x - ring[prev * 2], z - ring[prev * 2 + 1])
        const y = Math.max(heightAt(this.model.heights, x, z), WATER_LEVEL) + 0.35
        pos.push(x + nx * 0.5, y, z + nz * 0.5, x - nx * 0.5, y, z - nz * 0.5)
        uv.push(along / 7, 0, along / 7, 1)
        if (i < n) {
          const k = i * 2
          idx.push(k, k + 1, k + 2, k + 1, k + 3, k + 2)
        }
      }
      const g = new THREE.BufferGeometry()
      g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
      g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2))
      g.setIndex(idx)
      this.patchGroup.add(new THREE.Mesh(g, mat))
    }
  }

  addAnchor(el: HTMLElement, x: number, y: number | null, z: number) {
    const yy = y ?? heightAt(this.model.heights, x, z)
    this.anchors.set(el, new THREE.Vector3(x, yy, z))
  }

  moveAnchor(el: HTMLElement, x: number, y: number | null, z: number) {
    this.addAnchor(el, x, y, z)
  }

  removeAnchor(el: HTMLElement) {
    this.anchors.delete(el)
  }

  onFrame(fn: () => void) {
    this.frameHooks.add(fn)
    return () => this.frameHooks.delete(fn)
  }

  groundHeight(x: number, z: number) {
    return heightAt(this.model.heights, x, z)
  }

  /** Finds the point under the pointer: tree crowns first, then the ground or water. Null outside the forest. */
  pick(clientX: number, clientY: number): PickHit | null {
    const el = this.renderer.domElement
    const rect = el.getBoundingClientRect()
    const ndc = new THREE.Vector2(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1)
    const ray = new THREE.Raycaster()
    ray.setFromCamera(ndc, this.camera)
    const o = ray.ray.origin, d = ray.ray.direction
    // Ground: march along the ray, then refine.
    let tHit = Infinity
    let prev = 0
    const step = 1.5
    for (let t = 0; t < 4000; t += step) {
      const x = o.x + d.x * t, y = o.y + d.y * t, z = o.z + d.z * t
      if (y < SKIRT_BOTTOM - 1) break
      if (Math.abs(x) > 250 || Math.abs(z) > 250) { prev = t; continue }
      const g = Math.max(heightAt(this.model.heights, x, z), WATER_LEVEL)
      if (y <= g) {
        let lo = prev, hi = t
        for (let k = 0; k < 18; k++) {
          const mid = (lo + hi) / 2
          const mx = o.x + d.x * mid, mz = o.z + d.z * mid
          if (o.y + d.y * mid <= Math.max(heightAt(this.model.heights, mx, mz), WATER_LEVEL)) hi = mid
          else lo = mid
        }
        tHit = hi
        break
      }
      prev = t
    }
    // Crowns: nearest sphere hit closer than the ground.
    const tr = this.model.trees
    const count = tr.length / TREE_STRIDE
    for (let k = 0; k < count; k++) {
      const off = k * TREE_STRIDE
      const v = this.variants[tr[off + 5]]
      const sc = tr[off + 2] / REF_HEIGHT
      const cx = tr[off], cz = tr[off + 1]
      const cy = heightAt(this.model.heights, cx, cz) + v.crownY * sc
      const r = v.crownR * sc * tr[off + 3] * 0.85
      const lx = o.x - cx, ly = o.y - cy, lz = o.z - cz
      const b = lx * d.x + ly * d.y + lz * d.z
      const c = lx * lx + ly * ly + lz * lz - r * r
      const disc = b * b - c
      if (disc < 0) continue
      const t = -b - Math.sqrt(disc)
      if (t > 0 && t < tHit) tHit = t
    }
    if (!Number.isFinite(tHit)) return null
    const x = o.x + d.x * tHit, y = o.y + d.y * tHit, z = o.z + d.z * tHit
    if (Math.abs(x) > 250 || Math.abs(z) > 250) return null
    return { x, y, z }
  }

  /** The default aerial view: about 35-40 degrees down, from the south, showing the whole Footprint. */
  frameAll(animate = false) {
    const aspect = this.camera.aspect || 1
    const pitch = THREE.MathUtils.degToRad(39)
    const target = new THREE.Vector3(0, 2, 18)
    const corners = [
      [-250, 0, -250], [250, 0, -250], [250, 0, 250], [-250, 0, 250],
      [-250, 16, -250], [250, 16, -250],
    ].map(([x, y, z]) => new THREE.Vector3(x, y, z))
    let dist = 300
    const tmp = new THREE.PerspectiveCamera(this.camera.fov, aspect, 0.5, 16000)
    for (; dist < 1200; dist += 15) {
      tmp.position.set(target.x, target.y + Math.sin(pitch) * dist, target.z + Math.cos(pitch) * dist)
      tmp.lookAt(target)
      tmp.updateMatrixWorld()
      const fits = corners.every((c) => {
        const p = c.clone().project(tmp)
        return Math.abs(p.x) < 0.96 && p.y < 0.88 && p.y > -0.94
      })
      if (fits) break
    }
    const pos = new THREE.Vector3(target.x, target.y + Math.sin(pitch) * dist, target.z + Math.cos(pitch) * dist)
    if (animate) {
      this.focusAnim = { from: this.controls.target.clone(), to: target, camFrom: this.camera.position.clone(), camTo: pos, t0: performance.now() }
    } else {
      this.controls.target.copy(target)
      this.camera.position.copy(pos)
      this.controls.update()
    }
  }

  /**
   * Swoops the camera down to a close look at a point (the Sentinel Station hand-over to Sentinel Network).
   * Comes in from the west, over the river, so the trees do not hide the post. Resolves when the flight ends.
   */
  diveTo(x: number, z: number, ms = 2400): Promise<void> {
    const to = new THREE.Vector3(x, heightAt(this.model.heights, x, z) + 2.6, z)
    const camTo = to.clone().add(new THREE.Vector3(-17, 11, 13))
    this.controls.enabled = false
    return new Promise((resolve) => {
      this.focusAnim = { from: this.controls.target.clone(), to, camFrom: this.camera.position.clone(), camTo, t0: performance.now(), ms, smooth: true, done: () => { this.controls.enabled = true; resolve() } }
    })
  }

  dispose() {
    this.disposed = true
    this.stop()
    this.renderer.domElement.removeEventListener('dblclick', this.onDoubleClick)
    this.renderer.dispose()
  }

  // ---------------------------------------------------------------- internals

  private applyTint(rgba: Uint8Array | null, mix = 0) {
    const count = this.treeVariant.length
    const tr = this.model.trees
    for (let k = 0; k < count; k++) {
      const o = k * 4
      if (!rgba) {
        this.treeTint[o + 3] = 0
        continue
      }
      const x = tr[k * TREE_STRIDE], z = tr[k * TREE_STRIDE + 1]
      const i = Math.min(N - 1, Math.max(0, Math.floor(x + 250)))
      const j = Math.min(N - 1, Math.max(0, Math.floor(z + 250)))
      const p = (j * N + i) * 4
      this.treeTint[o] = (rgba[p] / 255) ** 2.2
      this.treeTint[o + 1] = (rgba[p + 1] / 255) ** 2.2
      this.treeTint[o + 2] = (rgba[p + 2] / 255) ** 2.2
      this.treeTint[o + 3] = (rgba[p + 3] / 255) * mix * 0.78
    }
    this.lastLodPos.set(1e9, 0, 0)
  }

  private resize() {
    if (!this.container) return
    const w = this.container.clientWidth, h = this.container.clientHeight
    if (w === 0 || h === 0) return
    this.renderer.setSize(w, h, false)
    this.renderer.domElement.style.width = '100%'
    this.renderer.domElement.style.height = '100%'
    this.camera.aspect = w / h
    this.camera.updateProjectionMatrix()
  }

  private start() {
    if (this.running) return
    this.running = true
    // Measure only after a 3 s warm-up, so shader compiling never counts as a slow frame rate.
    this.fpsStart = performance.now() + 3000
    this.fpsFrames = 0
    this.lowWindows = 0
    this.renderer.setAnimationLoop(this.loop)
  }

  private stop() {
    this.running = false
    this.renderer.setAnimationLoop(null)
  }

  private onDoubleClick = (e: MouseEvent) => {
    const hit = this.pick(e.clientX, e.clientY)
    if (!hit) return
    const to = new THREE.Vector3(hit.x, hit.y, hit.z)
    const dir = this.camera.position.clone().sub(this.controls.target).normalize()
    const dist = Math.max(45, Math.min(110, this.camera.position.distanceTo(this.controls.target) * 0.35))
    this.focusAnim = { from: this.controls.target.clone(), to, camFrom: this.camera.position.clone(), camTo: to.clone().addScaledVector(dir, dist), t0: performance.now() }
  }

  private updateLod(force = false) {
    const cam = this.camera.position
    const turned = this.camera.quaternion.angleTo(this.lastLodQuat) > 0.015
    if (!force && !turned && cam.distanceToSquared(this.lastLodPos) < 2.25) return
    this.lastLodPos.copy(cam)
    this.lastLodQuat.copy(this.camera.quaternion)
    // Only trees in (or just beside) the view are drawn; the margin keeps their shadows.
    this.camera.updateMatrixWorld()
    this.projScreen.multiplyMatrices(this.camera.projectionMatrix, this.camera.matrixWorldInverse)
    this.frustum.setFromProjectionMatrix(this.projScreen)
    const sph = this.sphere
    sph.radius = 26
    const d2 = this.lodDistance * this.lodDistance
    const tr = this.model.trees
    for (let v = 0; v < 4; v++) {
      const near = this.lod.near[v], far = this.lod.far[v]
      const nb = near.bark.instanceMatrix.array as Float32Array
      const nl = near.leaves.instanceMatrix.array as Float32Array
      const fc = far.crown.instanceMatrix.array as Float32Array
      const nlTint = near.leaves.geometry.getAttribute('instTint') as THREE.InstancedBufferAttribute
      const fcTint = far.crown.geometry.getAttribute('instTint') as THREE.InstancedBufferAttribute
      const nc = near.core.instanceMatrix.array as Float32Array
      const ncTint = near.core.geometry.getAttribute('instTint') as THREE.InstancedBufferAttribute
      const ncCol = near.core.instanceColor!.array as Float32Array
      const nlCol = near.leaves.instanceColor!.array as Float32Array
      const fcCol = far.crown.instanceColor!.array as Float32Array
      const nbCol = near.bark.instanceColor!.array as Float32Array
      let n = 0, f = 0
      for (const k of this.byVariant[v]) {
        sph.center.set(tr[k * TREE_STRIDE], 8, tr[k * TREE_STRIDE + 1])
        if (!this.frustum.intersectsSphere(sph)) continue
        const dx = tr[k * TREE_STRIDE] - cam.x, dz = tr[k * TREE_STRIDE + 1] - cam.z, dy = cam.y
        const src = this.treeMatrices.subarray(k * 16, k * 16 + 16)
        const nat = this.treeNatural.subarray(k * 3, k * 3 + 3)
        const tint = this.treeTint.subarray(k * 4, k * 4 + 4)
        if (dx * dx + dz * dz + dy * dy * 0.6 < d2) {
          nb.set(src, n * 16); nl.set(src, n * 16); nc.set(src, n * 16)
          nlCol.set(nat, n * 3); ncCol.set(nat, n * 3); nbCol[n * 3] = 1; nbCol[n * 3 + 1] = 1; nbCol[n * 3 + 2] = 1
          ;(nlTint.array as Float32Array).set(tint, n * 4)
          ;(ncTint.array as Float32Array).set(tint, n * 4)
          n++
        } else {
          fc.set(src, f * 16)
          fcCol.set(nat, f * 3)
          ;(fcTint.array as Float32Array).set(tint, f * 4)
          f++
        }
      }
      near.bark.count = n; near.leaves.count = n; near.core.count = n; far.crown.count = f
      near.core.instanceMatrix.needsUpdate = true
      near.core.instanceColor!.needsUpdate = true
      ncTint.needsUpdate = true
      near.bark.instanceMatrix.needsUpdate = true
      near.leaves.instanceMatrix.needsUpdate = true
      far.crown.instanceMatrix.needsUpdate = true
      near.leaves.instanceColor!.needsUpdate = true
      near.bark.instanceColor!.needsUpdate = true
      far.crown.instanceColor!.needsUpdate = true
      nlTint.needsUpdate = true
      fcTint.needsUpdate = true
    }
    // Breathing roots only near the camera.
    const rr = this.model.roots
    const rm = this.rootsMesh.instanceMatrix.array as Float32Array
    const cap = this.rootsMesh.instanceMatrix.count
    let c = 0
    const rd2 = Math.min(d2, 120 * 120)
    if (cam.y < 260) {
      for (let k = 0; k < rr.length / ROOT_STRIDE && c < cap; k++) {
        const dx = rr[k * ROOT_STRIDE] - cam.x, dz = rr[k * ROOT_STRIDE + 1] - cam.z
        if (dx * dx + dz * dz + cam.y * cam.y * 0.6 < rd2) {
          sph.center.set(rr[k * ROOT_STRIDE], 0, rr[k * ROOT_STRIDE + 1])
          sph.radius = 2
          if (!this.frustum.intersectsSphere(sph)) continue
          rm.set(this.rootMatrices.subarray(k * 16, k * 16 + 16), c * 16)
          c++
        }
      }
    }
    this.rootsMesh.count = c
    this.rootsMesh.instanceMatrix.needsUpdate = true
  }

  private placeShadowCamera() {
    const target = this.controls.target
    const texel = 340 / 2048
    const cx = Math.round(target.x / texel) * texel
    const cz = Math.round(target.z / texel) * texel
    const dist = this.camera.position.distanceTo(target)
    const half = Math.min(170, Math.max(60, dist * 0.42))
    const sc = this.sun.shadow.camera
    if (sc.right !== half) {
      sc.left = -half; sc.right = half; sc.top = half; sc.bottom = -half
      sc.updateProjectionMatrix()
    }
    this.sun.target.position.set(cx, 0, cz)
    this.sun.position.set(cx, 0, cz).addScaledVector(this.sunDir, 650)
    this.sun.target.updateMatrixWorld()
  }

  private adapt(now: number) {
    if (now < this.fpsStart) return
    this.fpsFrames++
    const span = now - this.fpsStart
    if (span < 2000) return
    const fps = (this.fpsFrames * 1000) / span
    this.fpsFrames = 0
    this.fpsStart = now
    if (document.hidden || fps >= 30) { this.lowWindows = 0; return }
    if (++this.lowWindows < 2 || this.quality >= 3) return
    this.lowWindows = 0
    this.quality++
    if (this.quality === 1) this.sun.castShadow = false
    if (this.quality === 2) { this.renderer.setPixelRatio(1); this.resize() }
    if (this.quality === 3) { this.lodDistance = 90; this.updateLod(true) }
  }

  private loop = () => {
    const now = performance.now()
    this.timer.update()
    shared.uTime.value = this.timer.getElapsed()
    if (this.focusAnim) {
      const a = this.focusAnim
      const t = Math.min(1, (now - a.t0) / (a.ms ?? 900))
      const e = a.smooth ? (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2) : 1 - Math.pow(1 - t, 3)
      this.controls.target.lerpVectors(a.from, a.to, e)
      this.camera.position.lerpVectors(a.camFrom, a.camTo, e)
      if (t >= 1) {
        this.focusAnim = null
        a.done?.()
      }
    }
    this.controls.update()
    // Keep the view over the forest and never below the ground.
    const tg = this.controls.target
    tg.x = THREE.MathUtils.clamp(tg.x, -300, 300)
    tg.z = THREE.MathUtils.clamp(tg.z, -300, 300)
    tg.y = THREE.MathUtils.clamp(tg.y, -1, 20)
    const cp = this.camera.position
    const floor = (Math.abs(cp.x) <= 250 && Math.abs(cp.z) <= 250 ? Math.max(heightAt(this.model.heights, cp.x, cp.z), WATER_LEVEL) : SKIRT_BOTTOM) + 2
    if (cp.y < floor) cp.y = floor
    this.updateLod()
    this.placeShadowCamera()
    this.renderer.render(this.scene, this.camera)
    this.updateAnchors()
    for (const fn of this.frameHooks) fn()
    this.adapt(now)
  }

  private updateAnchors() {
    if (!this.container || this.anchors.size === 0) return
    const w = this.container.clientWidth, h = this.container.clientHeight
    const v = new THREE.Vector3()
    for (const [el, p] of this.anchors) {
      v.copy(p).project(this.camera)
      const visible = v.z < 1 && Math.abs(v.x) < 1.2 && Math.abs(v.y) < 1.2
      el.style.visibility = visible ? 'visible' : 'hidden'
      el.style.transform = `translate3d(${((v.x + 1) / 2) * w}px, ${((1 - v.y) / 2) * h}px, 0)`
    }
  }
}

let instance: ForestView | null = null

export function getForestView(model: ForestModel): ForestView {
  if (!instance) {
    instance = new ForestView(model)
    if (import.meta.env.DEV) (window as unknown as { __forest: ForestView }).__forest = instance
  }
  return instance
}

export function hasWebGL(): boolean {
  try {
    const c = document.createElement('canvas')
    return !!(c.getContext('webgl2') || c.getContext('webgl'))
  } catch {
    return false
  }
}
