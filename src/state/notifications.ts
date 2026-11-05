import { create } from 'zustand'

export type NoticeKind = 'saving' | 'replanting'

export interface Notice {
  id: number
  kind: NoticeKind
  text: string
  at: number
}

const AGENCY = 'Forestry Department of Peninsular Malaysia (FDPM)'

const TEXT: Record<NoticeKind, string> = {
  saving: `The Saving notification had sent to ${AGENCY}`,
  replanting: `The Replanting notification had sent to ${AGENCY}`,
}

/** Simulated messages to the forestry department. `ring` counts sends so the bell rings once per send. */
export const useNotices = create<{ items: Notice[]; unread: number; ring: number }>(() => ({ items: [], unread: 0, ring: 0 }))

let nextId = 1
export function sendNotice(kind: NoticeKind) {
  useNotices.setState((s) => ({
    items: [{ id: nextId++, kind, text: TEXT[kind], at: Date.now() }, ...s.items].slice(0, 20),
    unread: s.unread + 1,
    ring: s.ring + 1,
  }))
}

export const markNoticesRead = () => useNotices.setState({ unread: 0 })
