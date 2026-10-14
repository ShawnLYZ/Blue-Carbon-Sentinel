import type { ReactNode } from 'react'

/** Fade and slide (250 ms, see `.page-transition` in styles.css) each time `pageKey` changes; reduced motion turns it off. */
export function PageTransition({ pageKey, children }: { pageKey: string; children: ReactNode }) {
  return (
    <div key={pageKey} className="page-transition">
      {children}
    </div>
  )
}
