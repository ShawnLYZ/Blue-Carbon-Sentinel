/** Sliders send their value 150 ms after the last change (Task 13). */
export const SLIDER_DEBOUNCE_MS = 150

export interface Debounced<A extends unknown[]> {
  (...args: A): void
  cancel(): void
}

/** Trailing-edge debounce: only the last call within `ms` runs. */
export function debounce<A extends unknown[]>(fn: (...args: A) => void, ms = SLIDER_DEBOUNCE_MS): Debounced<A> {
  let timer: ReturnType<typeof setTimeout> | undefined
  const d = ((...args: A) => {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      timer = undefined
      fn(...args)
    }, ms)
  }) as Debounced<A>
  d.cancel = () => {
    if (timer) clearTimeout(timer)
    timer = undefined
  }
  return d
}
