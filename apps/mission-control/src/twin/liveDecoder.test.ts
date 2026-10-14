import { describe, expect, test } from 'vitest'
import { decodeLiveFrame, type LiveHeader } from './liveDecoder'
import { heightMetres } from './surfaceMaterial'

const HEIGHT_BYTES = 256 * 256 * 2

/** Test-only TypeScript mirror of `bcs_gs.live.codec.encode_frame` (addendum J1). */
function encodeForTest(header: Partial<LiveHeader>, jpeg: Uint8Array | null, heights: Uint16Array | null): ArrayBuffer {
  if (heights && heights.length !== 256 * 256) throw new Error('height map must be 256x256')
  const head = {
    ...header,
    raster_bytes: jpeg ? jpeg.length : 0,
    height_bytes: heights ? HEIGHT_BYTES : 0,
  }
  const raw = new TextEncoder().encode(JSON.stringify(head))
  const flags = (jpeg ? 1 : 0) | (heights ? 2 : 0)
  const total = 12 + raw.length + (jpeg ? jpeg.length : 0) + (heights ? HEIGHT_BYTES : 0)
  const buf = new ArrayBuffer(total)
  const u8 = new Uint8Array(buf)
  const dv = new DataView(buf)
  u8.set([0x42, 0x43, 0x53, 0x4c], 0) // "BCSL"
  dv.setUint16(4, 1, true)
  dv.setUint16(6, flags, true)
  dv.setUint32(8, raw.length, true)
  u8.set(raw, 12)
  let pos = 12 + raw.length
  if (jpeg) {
    u8.set(jpeg, pos)
    pos += jpeg.length
  }
  if (heights) {
    for (let i = 0; i < heights.length; i++) dv.setUint16(pos + 2 * i, heights[i]!, true)
  }
  return buf
}

test('decodes the BCSL frame layout', () => {
  const buf = encodeForTest({ seq: 9, mode: 'fallback' }, new Uint8Array([1, 2, 3]), new Uint16Array(256 * 256).fill(65535))
  const f = decodeLiveFrame(buf)
  expect(f.header.seq).toBe(9); expect(f.heights![0]).toBe(65535); expect(f.jpeg!.size).toBe(3)
})

test('height to metres uses max relief and exaggeration', () => {
  expect(heightMetres(65535, 40, 1)).toBeCloseTo(40); expect(heightMetres(32768, 40, 1.5)).toBeCloseTo(30, 0)
})

describe('decodeLiveFrame edge cases', () => {
  test('keeps row-major order with row 0 first (north edge)', () => {
    const h = new Uint16Array(256 * 256)
    h[0] = 7 // row 0, column 0: the NW texel
    h[256 * 255 + 255] = 9 // last row, last column: the SE texel
    const f = decodeLiveFrame(encodeForTest({ seq: 1, mode: 'depth' }, null, h))
    expect(f.jpeg).toBeNull()
    expect(f.heights![0]).toBe(7)
    expect(f.heights![256 * 256 - 1]).toBe(9)
    expect(f.header.mode).toBe('depth')
  })

  test('raster-only frames have no height map', () => {
    const f = decodeLiveFrame(encodeForTest({ seq: 2 }, new Uint8Array([9, 9]), null))
    expect(f.heights).toBeNull()
    expect(f.jpeg!.type).toBe('image/jpeg')
  })

  test('reads the height map at an odd byte offset (header length is arbitrary)', () => {
    const h = new Uint16Array(256 * 256).fill(1234)
    const f = decodeLiveFrame(encodeForTest({ seq: 3, calibration_id: 'x' }, new Uint8Array([1]), h))
    expect(f.heights![12345]).toBe(1234)
  })

  test.each([
    ['bad magic', (b: ArrayBuffer) => new Uint8Array(b).set([0x58], 0)],
    ['bad version', (b: ArrayBuffer) => new DataView(b).setUint16(4, 2, true)],
  ])('rejects %s', (_name, corrupt) => {
    const buf = encodeForTest({ seq: 1 }, new Uint8Array([1]), null)
    corrupt(buf)
    expect(() => decodeLiveFrame(buf)).toThrow()
  })

  test('rejects truncated and trailing bytes', () => {
    const buf = encodeForTest({ seq: 1 }, null, new Uint16Array(256 * 256))
    expect(() => decodeLiveFrame(buf.slice(0, buf.byteLength - 1))).toThrow()
    const longer = new Uint8Array(buf.byteLength + 1)
    longer.set(new Uint8Array(buf))
    expect(() => decodeLiveFrame(longer.buffer)).toThrow()
    expect(() => decodeLiveFrame(new ArrayBuffer(5))).toThrow()
  })
})
