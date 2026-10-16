import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@bcs/ui'
import './styles.css'
import { App } from './App'
if (new URLSearchParams(location.search).has('mangrove-preview') && !location.hash) {
  history.replaceState(null, '', `${location.pathname}${location.search}#/satellite`)
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
