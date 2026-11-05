// The Command Center -> Satellite Intelligence hand-over: the last globe frame and its view,
// so the satellite panel can start exactly where the flight ended.

export interface Handover {
  image: string
  center: [number, number]
  zoom: number
  width: number
  height: number
}

let pending: Handover | null = null

export function setHandover(h: Handover | null) {
  pending = h
}

export function takeHandover(): Handover | null {
  const h = pending
  pending = null
  return h
}
