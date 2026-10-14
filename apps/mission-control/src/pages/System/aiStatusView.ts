/** Seconds of cooldown left at `nowMs`, rounded up; 0 when over or not cooling. */
export function cooldownLeftS(cooldownUntil: string | null | undefined, nowMs: number): number {
  if (!cooldownUntil) return 0
  const left = Date.parse(cooldownUntil) - nowMs
  return Number.isFinite(left) && left > 0 ? Math.ceil(left / 1000) : 0
}

/** "ok", or "cooldown 1:05" while a key and model are cooling. */
export function keyStateText(state: 'ok' | 'cooldown', cooldownUntil: string | null | undefined, nowMs: number): string {
  if (state === 'ok') return 'ok'
  const s = cooldownLeftS(cooldownUntil, nowMs)
  if (s <= 0) return 'ok'
  return `cooldown ${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}
