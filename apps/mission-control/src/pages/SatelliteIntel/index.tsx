import { useMemo, useState } from 'react'
import { Chip, Modal } from '@bcs/ui'
import { calibrationLabel, useCalibration } from '../../data/hooks'
import { BaselineControls } from './BaselineControls'
import { CaptureTimeline } from './CaptureTimeline'
import { CompareSlider } from './CompareSlider'
import { CornerPicker } from './CornerPicker'
import { LiveView } from './LiveView'
import { NdviPanel } from './NdviPanel'
import { HistoryChart } from './HistoryChart'
import { Observations } from './Observations'
import { MODEL_SCALE_TEXT, useCaptureDetails, useCaptures, useZoneLabels } from './shared'

/**
 * Satellite Intelligence (design §26 pages): SentinelCam as a satellite over the nadir map preset.
 * Left column: header, live view, baseline, timeline. Right column: compare, NDVI-proxy and metrics.
 * The right column stops above the stage HUD corner (exaggeration control) so neither covers the other.
 */
export function SatelliteIntel() {
  const { list, error } = useCaptures()
  const cal = useCalibration()
  const zoneLabel = useZoneLabels()
  const [picked, setPicked] = useState<string | null>(null)
  const [pickerOpen, setPickerOpen] = useState(false)

  const captures = useMemo(() => list ?? [], [list])
  const selected = captures.find((c) => c.id === picked) ?? captures[0] ?? null
  const baseline = captures.find((c) => c.is_baseline) ?? null
  const detailIds = useMemo(() => {
    const ids = captures.filter((c) => c.flagged).map((c) => c.id)
    if (selected && !ids.includes(selected.id)) ids.push(selected.id)
    return ids
  }, [captures, selected])
  const { details, errors: detailErrors } = useCaptureDetails(detailIds)

  const before = baseline && selected && baseline.id !== selected.id ? baseline.id : (captures[1]?.id ?? null)
  const calText = calibrationLabel(cal.calibration, cal.error)

  return (
    <div className="sat-page">
      <div className="sat-page__col sat-page__left">
        <header className="sat-header">
          <h1 className="page__title">Satellite Intelligence</h1>
          <a href="?mangrove-preview" className="bcs-button">Preview open satellite + mangrove model ↗</a>
          <div className="sat-header__chips">
            <Chip>{MODEL_SCALE_TEXT}</Chip>
            <Chip title={cal.error ?? undefined}>{calText}</Chip>
          </div>
        </header>
        <LiveView onCalibrate={() => setPickerOpen(true)} />
        <BaselineControls captures={list} />
        <CaptureTimeline
          captures={list}
          error={error}
          details={details}
          selectedId={selected?.id ?? null}
          onSelect={setPicked}
          zoneLabel={zoneLabel}
        />
      </div>
      <div className="sat-page__col sat-page__right">
        <CompareSlider captures={captures} defaultBefore={before} defaultAfter={selected?.id ?? null} zoneLabel={zoneLabel} details={details} />
        <Observations />
        <HistoryChart />
        <NdviPanel
          capture={selected}
          detail={selected ? (details[selected.id] ?? null) : null}
          detailError={selected ? (detailErrors[selected.id] ?? null) : null}
          baseline={baseline}
          zoneLabel={zoneLabel}
        />
      </div>
      <Modal open={pickerOpen} title="Four-corner calibration" onClose={() => setPickerOpen(false)}>
        <CornerPicker onClose={() => setPickerOpen(false)} onCalibrated={(r) => cal.set(r.calibration)} />
      </Modal>
    </div>
  )
}
