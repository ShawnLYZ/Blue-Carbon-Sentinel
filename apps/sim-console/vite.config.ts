import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The Ground Station serves the built app at /console/ (addendum I5); in dev, /api is proxied to it.
// The simulator itself is called cross-origin at PublicConfig.sim_url (CORS, addendum K3).
export default defineConfig({
  base: '/console/',
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      '/api': 'http://127.0.0.1:8700',
      '/ws': { target: 'ws://127.0.0.1:8700', ws: true },
    },
  },
})
