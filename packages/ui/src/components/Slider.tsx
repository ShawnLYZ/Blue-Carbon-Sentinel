export interface SliderProps {
  value: number
  min: number
  max: number
  step?: number
  onChange: (value: number) => void
  label?: string
  unit?: string
  disabled?: boolean
}

export function Slider({ value, min, max, step = 1, onChange, label, unit = '', disabled }: SliderProps) {
  return (
    <label className="bcs-slider">
      {label && (
        <span style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span>{label}</span>
          <span className="bcs-mono">
            {value}
            {unit && ` ${unit}`}
          </span>
        </span>
      )}
      <input
        type="range"
        value={value}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  )
}
