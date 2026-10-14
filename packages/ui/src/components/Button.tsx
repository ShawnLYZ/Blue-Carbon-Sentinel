import type { ButtonHTMLAttributes } from 'react'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'default' | 'primary' | 'danger'
}

export function Button({ variant = 'default', className = '', type = 'button', ...rest }: ButtonProps) {
  const v = variant === 'default' ? '' : ` bcs-btn--${variant}`
  return <button type={type} className={`bcs-btn${v} ${className}`.trim()} {...rest} />
}
