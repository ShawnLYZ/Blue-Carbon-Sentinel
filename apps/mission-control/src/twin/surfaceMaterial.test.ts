import { describe, expect, test } from 'vitest'
import { Euler, Matrix4, Quaternion, Vector3 } from 'three'
import {
  SURFACE_POSITION,
  SURFACE_ROTATION_X,
  heightTexelForUv,
  normaliseHeights,
  siteToScene,
  uvForSite,
  zoneCentreSite,
} from './surfaceMaterial'

/**
 * react-three-map's origin matrix (core/coords-to-matrix) with one metre = one mercator unit:
 * compose(anchor, rotateX(-90 deg), scale(1, -1, 1)). Mercator x grows east, y grows SOUTH, z up.
 */
const r3mOrigin = new Matrix4().compose(
  new Vector3(0, 0, 0),
  new Quaternion().setFromEuler(new Euler(-Math.PI / 2, 0, 0)),
  new Vector3(1, -1, 1),
)
const meshMatrix = new Matrix4().compose(
  new Vector3(...SURFACE_POSITION),
  new Quaternion().setFromEuler(new Euler(SURFACE_ROTATION_X, 0, 0)),
  new Vector3(1, 1, 1),
)

/** A PlaneGeometry(500, 500) vertex at texture coordinate (u, v), displaced `up` along its normal. */
function mercatorOfPlaneUv(u: number, v: number, up = 0): Vector3 {
  return new Vector3(u * 500 - 250, v * 500 - 250, up).applyMatrix4(meshMatrix).applyMatrix4(r3mOrigin)
}

describe('surface orientation (F4: NW anchor, e east, s south)', () => {
  test('the plane NW corner sits on the anchor, NE is east and SW is south', () => {
    const nw = uvForSite(0, 0)
    expect(nw).toEqual([0, 1])
    const p = mercatorOfPlaneUv(...nw)
    expect(p.x).toBeCloseTo(0)
    expect(p.y).toBeCloseTo(0)
    const ne = mercatorOfPlaneUv(...uvForSite(500, 0))
    expect(ne.x).toBeCloseTo(500) // east
    expect(ne.y).toBeCloseTo(0)
    const sw = mercatorOfPlaneUv(...uvForSite(0, 500))
    expect(sw.x).toBeCloseTo(0)
    expect(sw.y).toBeCloseTo(500) // mercator y grows south
  })

  test('height displacement along the plane normal points up', () => {
    expect(mercatorOfPlaneUv(0.5, 0.5, 10).z).toBeCloseTo(10)
  })

  test('height-map row 0 (north edge) is sampled on the north edge of the plane', () => {
    expect(heightTexelForUv(...uvForSite(0, 0))).toEqual({ row: 0, col: 0 })
    expect(heightTexelForUv(...uvForSite(500, 500))).toEqual({ row: 255, col: 255 })
    expect(heightTexelForUv(...uvForSite(250, 1))).toEqual({ row: 0, col: 128 })
    // A 255-segment plane puts one vertex on each of the 256 texels, north row first.
    for (let i = 0; i < 256; i++) expect(heightTexelForUv(0, 1 - i / 255).row).toBe(i)
  })

  test('scene coordinates of a site point agree with the plane mapping', () => {
    const [x, y, z] = siteToScene(100, 400, 7)
    const viaScene = new Vector3(x, y, z).applyMatrix4(r3mOrigin)
    const viaPlane = mercatorOfPlaneUv(...uvForSite(100, 400), 7)
    expect(viaScene.x).toBeCloseTo(viaPlane.x)
    expect(viaScene.y).toBeCloseTo(viaPlane.y)
    expect(viaScene.z).toBeCloseTo(viaPlane.z)
  })

  test('zone centres follow F4: (100c+50, 100r+50)', () => {
    expect(zoneCentreSite(0, 0)).toEqual([50, 50])
    expect(zoneCentreSite(4, 4)).toEqual([450, 450])
    expect(zoneCentreSite(2, 1)).toEqual([250, 150])
  })
})

test('heights are normalised to 0..1 floats for a filterable float texture', () => {
  const out = new Float32Array(3)
  normaliseHeights(new Uint16Array([0, 32768, 65535]), out)
  expect(out[0]).toBe(0)
  expect(out[1]).toBeCloseTo(0.5, 4)
  expect(out[2]).toBe(1)
})
