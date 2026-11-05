/// <reference types="vite/client" />

declare module 'virtual:camera-photos' {
  const library: {
    source: 'sample' | 'own'
    photos: { src: string; credit: string | null }[]
  }
  export default library
}

interface ImportMetaEnv {
  readonly VITE_MAPBOX_TOKEN?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
