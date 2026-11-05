import { defineConfig, type Plugin, type ViteDevServer } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'node:fs'
import path from 'node:path'

const IMAGE = /\.(jpe?g|png|webp)$/i
const OWN_DIR = path.resolve(__dirname, 'camera-photos')
const SAMPLE_DIR = path.resolve(__dirname, 'public/sample-photos')
const VIRTUAL_ID = 'virtual:camera-photos'
const RESOLVED_ID = '\0' + VIRTUAL_ID

function listImages(dir: string): string[] {
  try {
    return fs.readdirSync(dir).filter((f) => IMAGE.test(f)).sort()
  } catch {
    return []
  }
}

function readCredits(): Record<string, string> {
  try {
    return JSON.parse(fs.readFileSync(path.join(SAMPLE_DIR, 'credits.json'), 'utf8'))
  } catch {
    return {}
  }
}

/**
 * Lists the photos the simulated camera can "take".
 * The owner's own ESP32-CAM photos in ./camera-photos win; otherwise the shipped samples are used.
 */
function cameraPhotos(): Plugin {
  return {
    name: 'camera-photos',
    resolveId(id) {
      return id === VIRTUAL_ID ? RESOLVED_ID : null
    },
    load(id) {
      if (id !== RESOLVED_ID) return null
      const own = listImages(OWN_DIR)
      if (own.length > 0) {
        const photos = own.map((f) => ({ src: `/camera-photos/${encodeURIComponent(f)}`, credit: null }))
        return `export default ${JSON.stringify({ source: 'own', photos })}`
      }
      const credits = readCredits()
      const photos = listImages(SAMPLE_DIR).map((f) => ({
        src: `/sample-photos/${encodeURIComponent(f)}`,
        credit: credits[f] ?? null,
      }))
      return `export default ${JSON.stringify({ source: 'sample', photos })}`
    },
    configureServer(server: ViteDevServer) {
      // Serve the owner's folder and reload the page when a photo is added or removed.
      server.middlewares.use('/camera-photos', (req, res, next) => {
        const name = decodeURIComponent((req.url ?? '/').split('?')[0].replace(/^\//, ''))
        const file = path.join(OWN_DIR, name)
        if (!file.startsWith(OWN_DIR) || !IMAGE.test(file) || !fs.existsSync(file)) return next()
        const ext = path.extname(file).toLowerCase()
        res.setHeader('Content-Type', ext === '.png' ? 'image/png' : ext === '.webp' ? 'image/webp' : 'image/jpeg')
        fs.createReadStream(file).pipe(res)
      })
      server.watcher.add(OWN_DIR)
      const refresh = (file: string) => {
        if (!file.startsWith(OWN_DIR) || !IMAGE.test(file)) return
        const mod = server.moduleGraph.getModuleById(RESOLVED_ID)
        if (mod) server.moduleGraph.invalidateModule(mod)
        server.ws.send({ type: 'full-reload' })
      }
      server.watcher.on('add', refresh)
      server.watcher.on('unlink', refresh)
    },
    generateBundle() {
      for (const f of listImages(OWN_DIR)) {
        this.emitFile({ type: 'asset', fileName: `camera-photos/${f}`, source: fs.readFileSync(path.join(OWN_DIR, f)) })
      }
    },
  }
}

export default defineConfig({
  plugins: [react(), cameraPhotos()],
  server: { port: 5173, strictPort: true },
  build: { chunkSizeWarningLimit: 3000, target: 'es2022' },
  worker: { format: 'es' },
})
