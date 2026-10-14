// The Sentinel Network map layers, mounted inside TwinScene on the pages that show the network.
import { CoverageRings } from './CoverageRings'
import { NodePins } from './NodePins'
import { TaskingPulses } from './TaskingPulses'

export function NetworkLayers() {
  return (
    <>
      <CoverageRings />
      <NodePins />
      <TaskingPulses />
    </>
  )
}
