// Number formats of the carbon KPI tiles.
/** A tCO₂e quantity to 3 dp (the ledger's precision), or an em dash while unknown. */
export function fmtTco2e(v: number | null | undefined): string {
  return v === null || v === undefined || !Number.isFinite(v) ? '—' : v.toLocaleString('en-US', { minimumFractionDigits: 3, maximumFractionDigits: 3 })
}
