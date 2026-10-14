import { SourceChip } from '@bcs/ui'
import { useAppStore } from '../../data/store'

/** Markers for the located trees, in the 512 x 512 raster space of the live view's SVG overlay. */
export function TreeMarkers() {
  const trees = useAppStore((s) => s.trees.points)
  const points = trees?.points ?? []
  return (
    <g data-testid="tree-markers" data-count={points.length}>
      {points.map((p, i) => (
        <g key={i} className="tree-marker" transform={`translate(${p.u_px} ${p.v_px})`}>
          <circle r={5} />
          <title>{`${p.label} · ${p.zone_id}`}</title>
        </g>
      ))}
    </g>
  )
}

/** "N trees" with the answering tier's chip; "0 trees" until the TreeLocator has run. */
export function TreeCount() {
  const trees = useAppStore((s) => s.trees.points)
  const n = trees?.points.length ?? 0
  return (
    <span className="tree-count" data-testid="tree-count" data-count={n}>
      <span>{n === 1 ? '1 tree' : `${n} trees`}</span>
      {trees && <SourceChip tier={trees.source.tier} model={trees.source.model} cached={trees.source.cached} />}
    </span>
  )
}
