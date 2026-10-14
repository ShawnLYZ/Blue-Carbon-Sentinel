export interface ToggleProps {
  checked: boolean
  onChange: (checked: boolean) => void
  label?: string
  disabled?: boolean
}

export function Toggle({ checked, onChange, label, disabled }: ToggleProps) {
  return (
    <label className="bcs-toggle">
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        style={{ position: 'absolute', opacity: 0, width: 34, height: 18, margin: 0 }}
      />
      <span className="bcs-toggle__track" data-on={checked}>
        <span className="bcs-toggle__thumb" />
      </span>
      {label && <span>{label}</span>}
    </label>
  )
}
