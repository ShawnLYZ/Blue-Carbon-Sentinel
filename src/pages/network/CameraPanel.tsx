import { useMemo, useState } from 'react'
import { Camera, CameraOff, CircleCheck, Clock, LoaderCircle, RefreshCw, Send, Sparkles } from 'lucide-react'
import { cameraOnline, lastHeard, latestRequest, pendingRequest, PHOTO_COUNT, useApp, type Photo } from '../../state/store'
import { dangerSummary } from '../../sim/insights'
import { sendNotice } from '../../state/notifications'
import { Lightbox } from '../../ui/components'
import { formatMYT, formatMYTDateTime, timeAgo } from '../../ui/time'

/** Sample photos stand in for the camera; they are never described as taken at the station. */
function photoAlt(photo: Photo) {
  return photo.source === 'own'
    ? 'Photo from the ESP32-CAM, shown when the readings reached Danger'
    : 'Sample mangrove photo standing in for the camera in this demo'
}

function PhotoBadge({ photo }: { photo: Photo }) {
  return photo.source === 'own'
    ? <span className="badge badge-own">ESP32-CAM photo</span>
    : <span className="badge badge-sample">Sample photo</span>
}

export function CameraPanel() {
  const online = useApp(cameraOnline)
  const heard = useApp(lastHeard)
  const now = useApp((s) => s.now)
  const photos = useApp((s) => s.photos)
  const events = useApp((s) => s.events)
  const req = useApp(latestRequest)
  const pending = useApp((s) => !!pendingRequest(s))
  const [open, setOpen] = useState<Photo | null>(null)
  const reading = useApp((s) => s.reading)
  const restoring = useApp((s) => s.ramp.mode === 'restoring')
  // Hidden while Save Lah! (or Restore healthy) glides the readings back.
  const summary = useMemo(() => (restoring ? null : dangerSummary(reading)), [reading, restoring])

  const latest = photos.length ? photos[photos.length - 1] : null
  const strip = photos.slice(-6).reverse()
  const isNew = !!(latest && req && req.photoId === latest.id && now - latest.takenAt < 4000)

  let line: React.ReactNode
  if (req?.status === 'pending') {
    const secs = Math.max(0, Math.floor((now - req.createdAt) / 1000))
    line = (
      <div className="cam-line asking" aria-live="polite">
        <LoaderCircle size={20} className="spin" style={{ animation: 'spin 0.9s linear infinite', color: 'var(--primary)' }} />
        <span>{online ? 'Asking the camera to take a photo…' : 'Camera offline, waiting for it to come back'} <b className="num">{secs} s</b></span>
      </div>
    )
  } else if (req && (req.status === 'failed' || req.status === 'expired')) {
    line = (
      <div className="cam-line failed" role="alert">
        <CameraOff size={20} />
        <span>Camera offline, no new photo{latest ? (latest.source === 'own' ? '. Showing the last real photo.' : '. Showing the last photo.') : '.'}</span>
        <button className="btn btn-sm" disabled={pending || !events.length} onClick={() => useApp.getState().retryPhoto()}>
          <RefreshCw size={15} /> Try again
        </button>
      </div>
    )
  } else if (req?.status === 'done' && latest) {
    const took = Math.round(((req.completedAt ?? latest.takenAt) - req.createdAt) / 1000)
    line = (
      <div className="cam-line">
        <CircleCheck size={20} style={{ color: 'var(--healthy)' }} />
        <span>Photo received <span className="num">{timeAgo(latest.takenAt, now)}</span>, <span className="num">{took} s</span> after the request.</span>
      </div>
    )
  } else {
    line = (
      <div className="cam-line" style={{ color: 'var(--muted)' }}>
        <Clock size={20} />
        <span>Watching. When a reading reaches Danger, the camera takes a photo by itself.</span>
      </div>
    )
  }

  return (
    <section className="card cam" aria-label="Camera">
      <div className="card-head">
        <h2>Camera</h2>
        <span className="cam-status" title={`Last heard ${timeAgo(heard, now)}`}>
          <span className={`dot ${online ? 'dot-on' : ''}`} />
          <span className="num">{online ? 'Online' : 'Offline'} · last heard {timeAgo(heard, now)}</span>
        </span>
      </div>
      <div className="cam-body">
        {latest ? (
          <button className="photo" onClick={() => setOpen(latest)} aria-label="Open the latest photo full size">
            <img key={latest.id} src={latest.src} alt={photoAlt(latest)} className={isNew ? 'photo-new' : ''} />
            <PhotoBadge photo={latest} />
            <span className="photo-time num">Arrived {formatMYT(latest.takenAt, { seconds: true })}</span>
          </button>
        ) : (
          <div className="photo">
            <div className="photo-empty">
              <div>
                <Camera size={30} />
                <span>
                  {req?.status === 'pending'
                    ? 'Waiting for the camera’s photo…'
                    : PHOTO_COUNT === 0
                      ? 'No photos are available for the camera yet.'
                      : 'No photo yet. The first one is taken the moment a reading reaches Danger.'}
                </span>
              </div>
            </div>
          </div>
        )}
        {line}
        {summary && (
          <div className={`ai-note ai-${summary.band}`} aria-live="polite">
            <div className="ai-tag"><Sparkles size={15} /> AI Summary</div>
            {summary.lines.map((l, i) => <p key={i}>{l}</p>)}
            <p className="ai-advice">{summary.advice}</p>
            <button className="btn btn-primary ai-action" onClick={() => { useApp.getState().savePanel(); sendNotice('saving') }}>
              <Send size={17} /> Save Lah!
            </button>
          </div>
        )}
        <div>
          <div className="strip-head">Earlier danger photos</div>
          {strip.length ? (
            <div className="strip" style={{ marginTop: 6 }}>
              {strip.map((p) => (
                <button key={p.id} className="thumb" onClick={() => setOpen(p)} aria-label={`Photo that arrived ${formatMYTDateTime(p.takenAt)}`}>
                  <img src={p.src} alt="" loading="lazy" />
                  <span className="num">{formatMYT(p.takenAt).replace(' MYT', '')}</span>
                </button>
              ))}
            </div>
          ) : (
            <p className="strip-none" style={{ marginTop: 4 }}>None yet. Each danger episode adds one photo here.</p>
          )}
        </div>
      </div>
      <Lightbox
        src={open?.src ?? null}
        alt={open ? photoAlt(open) : ''}
        caption={open ? <span className="num">{open.source === 'own' ? 'ESP32-CAM photo' : 'Sample photo'} · arrived {formatMYTDateTime(open.takenAt)}</span> : null}
        credit={open?.credit}
        onClose={() => setOpen(null)}
      />
    </section>
  )
}
