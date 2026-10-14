import { describe, expect, it } from 'vitest'
import type { DirectorState } from '@bcs/api-types'
import { actionHint, blockedHint, isComplete, shouldOpenTimeTravel } from './directorView'

const state = (current: DirectorState['current'], active = true): DirectorState => ({ active, branch: 'main', current, started_at: null, steps: [] })

describe('actionHint', () => {
  it('maps the physical, console and time-travel steps', () => {
    expect(actionHint({ key: 'predict', action: 'Opens Time Travel' })).toBe('Run forecast, then scrub to 2035')
    expect(actionHint({ key: 'detect', action: 'x' })).toBe('Physical action on the model')
    expect(actionHint({ key: 'restore', action: 'x' })).toBe('Physical action on the model')
    expect(actionHint({ key: 'measure', action: 'x' })).toContain('Switch to the Simulator Console window')
    expect(actionHint({ key: 'measure', action: 'x' })).toContain('Alt+Tab')
  })
  it('falls back to the server action', () => {
    expect(actionHint({ key: 'task', action: null })).toBeNull()
    expect(actionHint({ key: 'verify', action: 'Generate Projected record' })).toBe('Generate Projected record')
  })
})

describe('blockedHint', () => {
  it('hints only for the camera reason', () => {
    expect(blockedHint('Camera offline — step requires live captures')).toMatch(/camera power and Wi-Fi/i)
    expect(blockedHint('something else')).toBeNull()
    expect(blockedHint(null)).toBeNull()
  })
})

describe('isComplete / shouldOpenTimeTravel', () => {
  it('complete means active with no current step', () => {
    expect(isComplete(state(null))).toBe(true)
    expect(isComplete(state(null, false))).toBe(false)
    expect(isComplete(state('detect'))).toBe(false)
    expect(isComplete(null)).toBe(false)
  })
  it('opens once on the transition into predict', () => {
    expect(shouldOpenTimeTravel(state('fuse'), state('predict'))).toBe(true)
    expect(shouldOpenTimeTravel(null, state('predict'))).toBe(true)
    expect(shouldOpenTimeTravel(state('predict'), state('predict'))).toBe(false)
    expect(shouldOpenTimeTravel(state('predict'), state('restore'))).toBe(false)
  })
})
