// One year slider (2026 -> 2035) drives both maps and every number (US 140). It moves continuously;
// numbers interpolate linearly between the yearly keyframes. Changing it never fetches anything.
import { FIRST_YEAR, KEYFRAMES, LAST_YEAR } from '../../lib/interp'

export const YEAR_STEP = 0.1

/** "2030" on whole years, else one decimal ("2030.5"). */
export function formatYear(year: number): string {
  const r = Math.round(year)
  return Math.abs(year - r) < 1e-6 ? String(r) : year.toFixed(1)
}

export function YearSlider({ year, onChange }: { year: number; onChange: (year: number) => void }) {
  return (
    <div className="tt-year">
      <label className="tt-year__label" htmlFor="tt-year">
        Year
      </label>
      <div className="tt-year__track">
        <input
          id="tt-year"
          type="range"
          aria-label="Year"
          min={FIRST_YEAR}
          max={LAST_YEAR}
          step={YEAR_STEP}
          value={year}
          onChange={(e) => onChange(Number(e.target.value))}
        />
        <div className="tt-year__ticks" aria-hidden="true">
          {Array.from({ length: LAST_YEAR - FIRST_YEAR + 1 }, (_, i) => FIRST_YEAR + i).map((y) => (
            <span key={y} className={(KEYFRAMES as readonly number[]).includes(y) ? 'tt-year__tick tt-year__tick--key' : 'tt-year__tick'}>
              {y}
            </span>
          ))}
        </div>
      </div>
      <output className="tt-year__value bcs-mono" htmlFor="tt-year">
        {formatYear(year)}
      </output>
    </div>
  )
}
