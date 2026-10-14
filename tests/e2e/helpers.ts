/** Parses a computed `rgb()/rgba()` colour into 0-255 channels (alpha ignored: callers compare solid colours). */
function parseRgb(css: string): [number, number, number] {
  const m = css.match(/rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)/)
  if (!m) throw new Error(`cannot parse colour: ${css}`)
  return [Number(m[1]), Number(m[2]), Number(m[3])]
}

function luminance([r, g, b]: [number, number, number]): number {
  const lin = (v: number) => {
    const c = v / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}

/** WCAG 2.x contrast ratio (1-21) between two computed CSS colours. */
export function contrastRatio(fg: string, bg: string): number {
  const a = luminance(parseRgb(fg))
  const b = luminance(parseRgb(bg))
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
}
