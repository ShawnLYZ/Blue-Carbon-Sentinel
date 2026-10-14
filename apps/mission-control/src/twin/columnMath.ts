// Carbon column arithmetic (design §26), free of three.js so it can be unit-tested.
export const COLUMN_MAX_M = 60

/** Metres of column per tCO₂e: the largest zone stock fills COLUMN_MAX_M (1 when nothing is stored yet). */
export function columnScale(stocks: number[]): number {
  const max = Math.max(0, ...stocks.filter(Number.isFinite))
  return max > 0 ? COLUMN_MAX_M / max : 1
}

/** Column height for a stock: proportional to tCO₂e (`metresPerTco2e`), never negative, capped at COLUMN_MAX_M. */
export function columnHeight(tco2e: number, metresPerTco2e: number): number {
  if (!Number.isFinite(tco2e) || tco2e <= 0) return 0
  return Math.min(COLUMN_MAX_M, tco2e * metresPerTco2e)
}
