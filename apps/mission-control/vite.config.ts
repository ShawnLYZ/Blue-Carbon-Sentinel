import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The Ground Station serves the built app at "/" (addendum I5); in dev, /api and /ws are proxied to it.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8700',
      '/ws': { target: 'ws://127.0.0.1:8700', ws: true },
    },
  },
  build: { chunkSizeWarningLimit: 2500 },
})
