import type { ReactNode } from 'react'

export interface ChipProps {
  children: ReactNode
  color?: string
  title?: string
}

export function Chip({ children, color, title }: ChipProps) {
  return (
    <span className="bcs-chip" title={title} style={color ? { borderColor: color, color } : undefined}>
      {children}
    </span>
  )
}
