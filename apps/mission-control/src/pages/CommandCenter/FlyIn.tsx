// "Fly to Kuala Selangor": the cinematic move from the globe to the site (design §26: 1.5-3 s).
import { Button } from '@bcs/ui'
import { flyToPreset } from '../../stage/MapStage'

export const FLY_IN_MS = 3000

export function FlyIn() {
  return (
    <Button variant="primary" data-testid="fly-in" onClick={() => flyToPreset('site-oblique', FLY_IN_MS)}>
      Fly to Kuala Selangor
    </Button>
  )
}
