import { useEffect } from 'react'
import { TopBar } from './TopBar'
import { startRouter, useRoute } from './router'
import { startSimulation } from '../state/store'
import { ensureForestModel } from '../forest/forestData'
import { CommandPage } from '../pages/command/CommandPage'
import { SatellitePage } from '../pages/satellite/SatellitePage'
import { NetworkPage } from '../pages/network/NetworkPage'
import { TwinPage } from '../pages/twin/TwinPage'
import { ROUTE_INFO } from './router'

let booted = false

export function App() {
  const route = useRoute((s) => s.route)
  useEffect(() => {
    if (booted) return
    booted = true
    startSimulation()
    startRouter()
    ensureForestModel()
  }, [])
  useEffect(() => {
    document.title = `${ROUTE_INFO[route].title} · RhizoLah!`
  }, [route])

  return (
    <div className="app">
      <TopBar />
      <main className="page" aria-label={ROUTE_INFO[route].title}>
        {route === 'command' && <CommandPage />}
        {route === 'satellite' && <SatellitePage />}
        {route === 'network' && <NetworkPage />}
        {route === 'twin' && <TwinPage />}
      </main>
    </div>
  )
}
