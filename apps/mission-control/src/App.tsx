import { useEffect } from 'react'
import { AppShell } from './shell/AppShell'
import { fetchSnapshots, startLive } from './data/live'

export function App() {
  useEffect(() => {
    // The live client resyncs on every (re)connect; the first snapshot also covers a slow socket.
    fetchSnapshots().catch(() => undefined)
    return startLive()
  }, [])
  return <AppShell />
}
