import { expect, test } from 'vitest'
import { edgesOf, sortClockwise, toImagePoint } from './cornerGeometry'

test('corner picker sorts clicks clockwise and labels edges', () => {
  const sorted = sortClockwise([[480, 500], [100, 100], [90, 470], [500, 120]])
  expect(sorted).toEqual([[100, 100], [500, 120], [480, 500], [90, 470]])
})

test('the start corner is the smallest x+y, ties broken by the smaller y', () => {
  // A diamond: (300,100) and (100,300) both have x+y = 400; the smaller y wins.
  const sorted = sortClockwise([[100, 300], [300, 500], [500, 300], [300, 100]])
  expect(sorted[0]).toEqual([300, 100])
  expect(sorted).toEqual([[300, 100], [500, 300], [300, 500], [100, 300]])
})

test('edge k runs from corner k to corner k+1, wrapping at the end', () => {
  const pts: [number, number][] = [[0, 0], [10, 0], [10, 10], [0, 10]]
  const edges = edgesOf(pts)
  expect(edges.map((e) => e.index)).toEqual([0, 1, 2, 3])
  expect(edges[0]).toMatchObject({ from: [0, 0], to: [10, 0] })
  expect(edges[3]).toMatchObject({ from: [0, 10], to: [0, 0] })
})

test('clicks on the scaled image map to native frame pixels', () => {
  // 800 x 600 frame shown at 400 x 300.
  expect(toImagePoint({ x: 200, y: 150 }, { width: 400, height: 300 }, { width: 800, height: 600 })).toEqual([400, 300])
})
