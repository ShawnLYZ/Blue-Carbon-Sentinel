import { useEffect } from 'react'
import { ConsoleShell } from './shell/ConsoleShell'
import { loadPublicConfig } from './data/gsClient'
import { connect } from './data/store'

export function App() {
  useEffect(() => {
    let stop: (() => void) | null = null
    let alive = true
    // Without PublicConfig the Console still talks to the default simulator URL.
    loadPublicConfig()
      .catch(() => null)
      .then((config) => {
        if (alive) stop = connect(config)
      })
    return () => {
      alive = false
      stop?.()
    }
  }, [])
  return <ConsoleShell />
}
