import { CalibrationSection } from './CalibrationSection'
import { CameraSection } from './CameraSection'
import { CommissioningSection } from './CommissioningSection'
import { DeviceRegistrySection } from './DeviceRegistrySection'
import { LiveStatsSection } from './LiveStatsSection'
import { AiSection } from './AiSection'
import { CloudSection } from './CloudSection'
import { VersionsSection } from './VersionsSection'

export function System() {
  return (
    <div className="page system-page">
      <h1 className="page__title">System</h1>
      <div className="system-page__col">
        <CameraSection />
        <LiveStatsSection />
        <CalibrationSection />
        <CommissioningSection />
        <DeviceRegistrySection />
        <AiSection />
        <CloudSection />
        <VersionsSection />
      </div>
    </div>
  )
}
