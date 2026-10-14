export const CHALLENGE_TITLE =
  'KUL06 — Blue Carbon Sentinel: Autonomous Swarm-to-Satellite Edge AI Mangrove Restoration Network'
export const HARDWARE_STATEMENT = 'Fixed, anchored edge nodes — no drones, no swarm robotics.'
export const PITCH_LINES = [
  ['The satellite tells us', 'WHERE'],
  ['The nearest sentinels tell us', 'WHY'],
  ['AI tells us', 'WHAT WILL HAPPEN'],
  ['The Digital Twin tells us', 'WHAT TO DO'],
  ['The Carbon Ledger tells us', 'WHAT IT IS WORTH'],
] as const

export function AboutCover() {
  return (
    <div className="about">
      <div className="about__inner">
        <p className="about__eyebrow">Ocean Hackathon 2026 · Kuala Lumpur</p>
        <h1 className="about__name">Blue Carbon Sentinel</h1>
        <p className="about__challenge">{CHALLENGE_TITLE}</p>
        <p className="about__hardware">{HARDWARE_STATEMENT}</p>
        <ol className="about__pitch" aria-label="Pitch narrative">
          {PITCH_LINES.map(([lead, key]) => (
            <li key={key}>
              {lead} <strong>{key}.</strong>
            </li>
          ))}
        </ol>
        <p className="about__team">
          <span>Team</span> Blue Carbon Sentinel team · GitHub ShawnLYZ
        </p>
      </div>
    </div>
  )
}
