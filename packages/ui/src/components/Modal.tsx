import { useEffect, type ReactNode } from 'react'
import { Panel } from './Panel'

export interface ModalProps {
  open: boolean
  title?: string
  onClose: () => void
  children: ReactNode
}

export function Modal({ open, title, onClose, children }: ModalProps) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="bcs-modal-backdrop" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <Panel title={title} className="bcs-modal">
          {children}
        </Panel>
      </div>
    </div>
  )
}
