/** The 5 x 5 zone grid (addendum F): columns A–E run west to east, rows 1–5 north to south. */
export const GRID = 5
const COLS = 'ABCDE'

/** `labelForCell(1, 2)` is `"B3"`: column index (0 = A) and row index (0 = row 1). */
export function labelForCell(col: number, row: number): string {
  if (!Number.isInteger(col) || !Number.isInteger(row) || col < 0 || row < 0 || col >= GRID || row >= GRID) {
    throw new RangeError(`cell (${col}, ${row}) is outside the ${GRID} x ${GRID} grid`)
  }
  return `${COLS[col]}${row + 1}`
}

/** The cell of a zone label (`B3` or `KSL-B3`), or null when it is not on the grid. */
export function cellForLabel(label: string): { col: number; row: number } | null {
  const m = /^(?:[A-Z]+-)?([A-E])([1-5])$/.exec(label.trim().toUpperCase())
  if (!m) return null
  return { col: COLS.indexOf(m[1]), row: Number(m[2]) - 1 }
}

/** Every label, row by row (A1, B1, … E1, A2, …). */
export const ZONE_LABELS: readonly string[] = Array.from({ length: GRID * GRID }, (_, i) =>
  labelForCell(i % GRID, Math.floor(i / GRID)),
)
