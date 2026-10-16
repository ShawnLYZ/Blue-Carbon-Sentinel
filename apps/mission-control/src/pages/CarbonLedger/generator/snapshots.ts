export interface OverviewSnapshot {
  id: string; capturedAt: string; sceneId: string; acquiredAt: string; image: string
  width: number; height: number; lat: number; lng: number
}
function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const open = indexedDB.open('bcs-carbon-overview-snapshots', 1)
    open.onupgradeneeded = () => open.result.createObjectStore('snapshots', { keyPath: 'id' })
    open.onsuccess = () => resolve(open.result)
    open.onerror = () => reject(new Error('Snapshot storage is unavailable. Request was not submitted.'))
  })
}
export async function saveSnapshot(snapshot: OverviewSnapshot): Promise<void> {
  const db = await database()
  try { await new Promise<void>((resolve, reject) => {
    const tx = db.transaction('snapshots', 'readwrite')
    tx.objectStore('snapshots').add(snapshot) // add, never overwrite historical captures
    tx.oncomplete = () => resolve(); tx.onerror = tx.onabort = () => reject(new Error('Could not save the overview image. Request was not submitted.'))
  }) } finally { db.close() }
}
export async function getSnapshots(ids: string[]): Promise<OverviewSnapshot[]> {
  if (!ids.length) return []
  const db = await database()
  try { return await new Promise<OverviewSnapshot[]>((resolve, reject) => {
    const tx = db.transaction('snapshots', 'readonly'), result: OverviewSnapshot[] = []
    for (const id of ids) { const request = tx.objectStore('snapshots').get(id); request.onsuccess = () => { if (request.result) result.push(request.result as OverviewSnapshot) } }
    tx.oncomplete = () => resolve(result); tx.onerror = tx.onabort = () => reject(new Error('Stored overview images could not be loaded.'))
  }) } finally { db.close() }
}
export function conditionRevision(requests: { simulation?: boolean; snapshot?: { conditionRevision: number } }[]): number {
  return 1 + Math.max(0, ...requests.filter(r => r.simulation).map(r => r.snapshot?.conditionRevision ?? 0))
}
export function coverageChanges(previous: { id: string; mask: string[] }[], current: { id: string; mask: string[] }[]) {
  let gained = 0, lost = 0, compared = 0
  for (const next of current) {
    const before = previous.find(s => s.id === next.id)
    if (!before) continue
    const a = before.mask.join(''), b = next.mask.join('')
    for (let i = 0; i < Math.min(a.length, b.length); i++) {
      compared++
      if (a[i] !== '1' && b[i] === '1') gained++
      if (a[i] === '1' && b[i] !== '1') lost++
    }
  }
  return { gained, lost, compared, gainedPct: compared ? gained / compared * 100 : 0, lostPct: compared ? lost / compared * 100 : 0 }
}
