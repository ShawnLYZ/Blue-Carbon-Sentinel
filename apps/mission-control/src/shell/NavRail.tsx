import { NAV_PAGES, PAGES, type PageKey } from './router'

const ICONS: Record<string, string> = {
  command: 'M3 11l9-8 9 8v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z',
  satellite: 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 4a6 6 0 1 1 0 12 6 6 0 0 1 0-12zm0 3a3 3 0 1 0 0 6 3 3 0 0 0 0-6z',
  network: 'M12 3a3 3 0 1 1 0 6 3 3 0 0 1 0-6zM5 15a3 3 0 1 1 0 6 3 3 0 0 1 0-6zm14 0a3 3 0 1 1 0 6 3 3 0 0 1 0-6zM11 9l-5 6m7-6l5 6',
  twin: 'M12 2l9 5v10l-9 5-9-5V7zm0 0v20M3 7l9 5 9-5',
  ledger: 'M4 4h12a4 4 0 0 1 4 4v12H8a4 4 0 0 1-4-4zM8 9h8M8 13h8',
  system: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM3 12h3m12 0h3M12 3v3m0 12v3',
}

export function NavRail({ page }: { page: PageKey }) {
  return (
    <nav className="navrail" aria-label="Pages">
      {NAV_PAGES.map((k) => (
        <a
          key={k}
          href={PAGES[k].hash}
          className="navrail__item"
          aria-current={page === k ? 'page' : undefined}
          title={`${PAGES[k].title} (${PAGES[k].key})`}
        >
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" aria-hidden="true">
            <path d={ICONS[k]} />
          </svg>
          <span className="navrail__label">{PAGES[k].title}</span>
          <kbd className="navrail__key">{PAGES[k].key}</kbd>
        </a>
      ))}
      <a href={PAGES.about.hash} className="navrail__item navrail__item--about" aria-current={page === 'about' ? 'page' : undefined} title="About (0)">
        <span className="navrail__label">About</span>
        <kbd className="navrail__key">0</kbd>
      </a>
    </nav>
  )
}
