// Decoder for one /ws/live message (addendum J1); mirrors bcs_gs.live.codec.decode_frame.
//
// Layout: "BCSL" | version u16 LE (1) | flags u16 LE (bit 0 raster, bit 1 height) | header length
// u32 LE | header JSON (UTF-8) | raster JPEG | height map (256 x 256 u16 LE, row-major, row 0 north).

export interface LiveHeader {
  seq: number
  frame_seq: number
  captured_at: string
  processed_at: string
  latency_ms: number
  mode: 'depth' | 'fallback'
  quality: number
  raster_bytes: number
  height_bytes: number
  raster_w: number
  raster_h: number
  height_w: number
  height_h: number
  max_relief_m: number
  calibration_id: string
}

export interface LiveFrame {
  header: LiveHeader
  jpeg: Blob | null
  /** 256 x 256 normalised heights, row-major, row 0 = north edge. */
  heights: Uint16Array | null
}

export const HEIGHT_W = 256
export const HEIGHT_H = 256
const HEIGHT_BYTES = HEIGHT_W * HEIGHT_H * 2
const PREFIX = 12
const FLAG_RASTER = 0b01
const FLAG_HEIGHT = 0b10
const decoder = new TextDecoder('utf-8', { fatal: true })

/** Parses one message; throws on anything malformed (the caller drops the frame). */
export function decodeLiveFrame(buf: ArrayBuffer): LiveFrame {
  const u8 = new Uint8Array(buf)
  if (u8.length < PREFIX || u8[0] !== 0x42 || u8[1] !== 0x43 || u8[2] !== 0x53 || u8[3] !== 0x4c)
    throw new Error('not a BCSL frame')
  const dv = new DataView(buf)
  if (dv.getUint16(4, true) !== 1) throw new Error('unsupported BCSL version')
  const flags = dv.getUint16(6, true)
  const n = dv.getUint32(8, true)
  if (u8.length < PREFIX + n) throw new Error('truncated header')
  const header = JSON.parse(decoder.decode(u8.subarray(PREFIX, PREFIX + n))) as unknown
  if (!header || typeof header !== 'object' || Array.isArray(header)) throw new Error('header is not an object')
  const h = header as LiveHeader
  let pos = PREFIX + n
  let jpeg: Blob | null = null
  let heights: Uint16Array | null = null
  if (flags & FLAG_RASTER) {
    const r = Number(h.raster_bytes ?? -1)
    if (!(r >= 0) || pos + r > u8.length) throw new Error('truncated raster')
    jpeg = new Blob([u8.subarray(pos, pos + r)], { type: 'image/jpeg' })
    pos += r
  }
  if (flags & FLAG_HEIGHT) {
    if (Number(h.height_bytes) !== HEIGHT_BYTES || pos + HEIGHT_BYTES > u8.length) throw new Error('truncated height map')
    heights = new Uint16Array(HEIGHT_W * HEIGHT_H)
    // The offset after a JSON header is arbitrary (often odd), so read through the DataView.
    for (let i = 0; i < heights.length; i++) heights[i] = dv.getUint16(pos + 2 * i, true)
    pos += HEIGHT_BYTES
  }
  if (pos !== u8.length) throw new Error('trailing bytes')
  return { header: h, jpeg, heights }
}
