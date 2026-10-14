import type { ReactNode } from 'react'

export interface PanelProps {
  title?: string
  children?: ReactNode
  className?: string
  actions?: ReactNode
}

export function Panel({ title, children, className = '', actions }: PanelProps) {
  return (
    <section className={`bcs-panel ${className}`.trim()}>
      {(title || actions) && (
        <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h3 className="bcs-panel__title">{title}</h3>
          {actions}
        </header>
      )}
      <div className="bcs-panel__body">{children}</div>
    </section>
  )
}
