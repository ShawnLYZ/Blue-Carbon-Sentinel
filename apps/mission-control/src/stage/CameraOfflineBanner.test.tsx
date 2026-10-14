import { renderToStaticMarkup } from 'react-dom/server'
import { expect, test } from 'vitest'
import { CameraOfflineBannerView, offlineBannerText } from './CameraOfflineBanner'

test('banner time is MYT (UTC+8), 24 h, with seconds', () => {
  expect(offlineBannerText('2026-10-16T02:03:04.567Z')).toBe('CAMERA OFFLINE since 10:03:04 (MYT)')
  expect(offlineBannerText('2026-10-16T15:59:59.000Z')).toBe('CAMERA OFFLINE since 23:59:59 (MYT)')
  expect(offlineBannerText('2026-10-16T16:00:00.000Z')).toBe('CAMERA OFFLINE since 00:00:00 (MYT)')
})

test('banner shows only while the camera is offline', () => {
  const off = renderToStaticMarkup(<CameraOfflineBannerView status={{ online: false, since: '2026-10-16T02:03:04.000Z' }} />)
  expect(off).toContain('CAMERA OFFLINE since 10:03:04 (MYT)')
  expect(off).toContain('role="alert"')
  expect(renderToStaticMarkup(<CameraOfflineBannerView status={{ online: true, since: '2026-10-16T02:03:04.000Z' }} />)).toBe('')
  expect(renderToStaticMarkup(<CameraOfflineBannerView status={null} />)).toBe('')
})
