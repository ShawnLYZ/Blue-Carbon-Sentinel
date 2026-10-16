import { useEffect, useState } from 'react'
import { useAppStore } from '../data/store'
import { useCarbonSummary } from '../data/carbon'
import { api } from '../data/client'
import { heldNodes, isOpenTask } from '../data/network'
import { pinsFromNodes } from '../twin/NodePins'
import { alertMarkers } from '../twin/AlertMarkers'
import { latestRasters, type CaptureRasters } from '../twin/captureRasters'
import type { Region } from './satellite'

export interface PreviewPin { id: string; e: number; s: number; colour: string; radius: number; source: string }
export interface PreviewAlert { id: string; e: number; s: number; title: string; critical: boolean }
export interface ExtraData { pins: PreviewPin[]; alerts: PreviewAlert[]; pulsing: string[]; carbon: Record<string, number>; examples: boolean }

export function registeredSiteMatches(region: Region, centre?: { lat: number; lng: number } | null): boolean {
  return !!centre && Math.abs(region.lat - centre.lat) < 0.0002 && Math.abs(region.lng - centre.lng) < 0.0002 && region.size === 500
}
export function exampleLayerData(): ExtraData {
  return {
    examples: true,
    pins: [
      { id: 'EX-WQ1', e: 125, s: 150, colour: '#1aa7ff', radius: 150, source: 'EXAMPLE' },
      { id: 'EX-SP1', e: 350, s: 325, colour: '#d09cfa', radius: 100, source: 'EXAMPLE' },
      { id: 'EX-WQ2', e: 350, s: 120, colour: '#1aa7ff', radius: 150, source: 'EXAMPLE' },
    ],
    pulsing: ['EX-WQ1'],
    alerts: [{ id: 'EX-alert', e: 250, s: 250, title: 'Example alert marker — not an environmental observation', critical: true }],
    carbon: Object.fromEntries(Array.from({ length: 25 }, (_, i) => [`${'ABCDE'[i % 5]}${Math.floor(i / 5) + 1}`, 10 + (i * 17 % 65)])),
  }
}

export function useLayerData(region: Region, examples: boolean) {
  const site = useAppStore(s => s.site.site)
  const nodes = useAppStore(s => s.nodes.items)
  const tasks = useAppStore(s => s.tasks.items)
  const alerts = useAppStore(s => s.alerts.items)
  const connection = useAppStore(s => s.system.connection)
  const rev = useAppStore(s => s.rev.captures)
  const carbon = useCarbonSummary(s => s.summary?.per_zone)
  const [captures, setCaptures] = useState<CaptureRasters | null>(null)
  const matches = registeredSiteMatches(region, site?.centre)
  useEffect(() => {
    setCaptures(null)
    if (!matches || connection !== 'open') return
    let alive = true
    api.GET('/api/v1/captures', { params: { query: { limit: 5 } } }).then(async r => {
      if (!r.data) return
      const result = await latestRasters(r.data.map(c => c.id))
      if (alive) setCaptures(result)
    }).catch(() => undefined)
    return () => { alive = false }
  }, [matches, connection, rev])
  const registeredZones = matches ? site?.zones ?? [] : []
  const data: ExtraData = examples ? exampleLayerData() : {
    examples: false,
    pins: matches ? pinsFromNodes(nodes).map(p => ({ ...p, radius: p.type === 'water_quality' ? 150 : p.type === 'soil_probe' ? 100 : 0, source: p.source.toUpperCase() })) : [],
    pulsing: matches ? tasks.filter(isOpenTask).flatMap(heldNodes) : [],
    alerts: matches ? alertMarkers(alerts, registeredZones, nodes).map(a => ({ id: a.key, e: a.e, s: a.s, title: a.title, critical: a.severity === 'critical' })) : [],
    carbon: matches ? Object.fromEntries(registeredZones.flatMap(z => carbon?.[z.id] === undefined ? [] : [[z.label, carbon[z.id]!]])) : {},
  }
  return { data, matches, captures, connection, nodes: matches ? nodes : [] }
}
