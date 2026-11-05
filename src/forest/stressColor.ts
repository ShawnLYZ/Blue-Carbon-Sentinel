// The continuous stress colour for Digital Twin layers: green (Healthy) through amber (Warning) to red (Danger).
// Stress 0 is ideal, 1 the healthy edge, 2 the danger edge, 3 deep danger. Interpolated in OKLab.

const STOPS: [number, string][] = [
  [0, '#2F9E44'],
  [0.85, '#8DC63F'],
  [1.2, '#F08C00'],
  [1.8, '#EE6A1B'],
  [2.15, '#E03131'],
  [3, '#A61B1B'],
]

const srgbToLin = (c: number) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4))
const linToSrgb = (c: number) => (c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055)

function hexToOklab(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16)
  const r = srgbToLin(((n >> 16) & 255) / 255), g = srgbToLin(((n >> 8) & 255) / 255), b = srgbToLin((n & 255) / 255)
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ]
}

function oklabToRgb([L, A, B]: [number, number, number]): [number, number, number] {
  const l = (L + 0.3963377774 * A + 0.2158037573 * B) ** 3
  const m = (L - 0.1055613458 * A - 0.0638541728 * B) ** 3
  const s = (L - 0.0894841775 * A - 1.291485548 * B) ** 3
  const r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
  const g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
  const b = -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s
  const to8 = (c: number) => Math.round(255 * Math.min(1, Math.max(0, linToSrgb(c))))
  return [to8(r), to8(g), to8(b)]
}

const LAB = STOPS.map(([s, hex]) => [s, hexToOklab(hex)] as const)
const LUT_SIZE = 256

/** 256 RGB entries covering stress 0..3. */
export const STRESS_LUT: Uint8Array = (() => {
  const lut = new Uint8Array(LUT_SIZE * 3)
  for (let i = 0; i < LUT_SIZE; i++) {
    const s = (i / (LUT_SIZE - 1)) * 3
    let k = 0
    while (k < LAB.length - 2 && s > LAB[k + 1][0]) k++
    const [s0, c0] = LAB[k]
    const [s1, c1] = LAB[k + 1]
    const t = Math.min(1, Math.max(0, (s - s0) / (s1 - s0)))
    const rgb = oklabToRgb([c0[0] + (c1[0] - c0[0]) * t, c0[1] + (c1[1] - c0[1]) * t, c0[2] + (c1[2] - c0[2]) * t])
    lut.set(rgb, i * 3)
  }
  return lut
})()

export function stressRgb(s: number): [number, number, number] {
  const i = Math.round((Math.min(3, Math.max(0, s)) / 3) * (LUT_SIZE - 1)) * 3
  return [STRESS_LUT[i], STRESS_LUT[i + 1], STRESS_LUT[i + 2]]
}

export function stressCss(s: number): string {
  const [r, g, b] = stressRgb(s)
  return `rgb(${r} ${g} ${b})`
}

/** CSS gradient for the legend. */
export function stressGradientCss(): string {
  const parts: string[] = []
  for (let k = 0; k <= 12; k++) parts.push(`${stressCss((k / 12) * 3)} ${((k / 12) * 100).toFixed(1)}%`)
  return `linear-gradient(90deg, ${parts.join(', ')})`
}
