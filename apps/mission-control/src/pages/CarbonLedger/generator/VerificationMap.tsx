import { useState } from 'react'
import type { VerificationRequest, VerifierResponse } from './verification'
export function VerificationMap({ image, request, response, selected, onSelect }: { image: string; request: VerificationRequest | null; response: VerifierResponse | null; selected: string; onSelect: (id: string) => void }) {
  const [overlay, setOverlay] = useState(true)
  return <div className="cl-land-overview"><div className="cl-land-tools"><span>500 × 500 m · eligibility coverage</span><button aria-pressed={overlay} onClick={() => setOverlay(v => !v)}>Coverage {overlay ? 'on' : 'off'}</button></div><svg viewBox="0 0 500 500" role="group" aria-label="Verifier section eligibility map"><defs><pattern id="verification-ineligible" width="8" height="8" patternUnits="userSpaceOnUse"><rect width="8" height="8" fill="#25333fcc" /><path d="M-2 2L2 -2M0 8L8 0M6 10L10 6" stroke="#b5c3c8" strokeWidth="1.5" /></pattern></defs><rect width="500" height="500" fill="#0b202a" />{image && <image href={image} width="500" height="500" />}
    {Array.from({ length: 25 }, (_, i) => {
      const id = `${'ABCDE'[i % 5]}${Math.floor(i / 5) + 1}`, x = i % 5 * 100, y = Math.floor(i / 5) * 100
      const decision = response?.sections.find(s => s.id === id), pending = request?.sections.includes(id)
      const status = decision ? 'report received' : pending ? 'pending verification' : 'not requested'
      let yes = '', no = '', claimed = ''
      decision?.mask.forEach((row, ry) => [...row].forEach((v, rx) => { const path = `M${x + rx * 10} ${y + ry * 10}h10v10h-10z`; if (v === '1') yes += path; else if (v === '2') claimed += path; else no += path }))
      return <g key={id} role="button" tabIndex={0} className="cl-land-section" data-selected={selected === id} aria-pressed={selected === id} aria-label={`Section ${id}: ${status}`} onClick={() => onSelect(id)} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(id) } }}>
        {overlay && (decision ? <><path d={yes} fill="#24cd8b" fillOpacity=".5" /><path d={claimed} fill="#efbb54" fillOpacity=".65" /><path d={no} fill="url(#verification-ineligible)" /></> : <rect x={x} y={y} width="100" height="100" fill={pending ? '#8c86ca' : '#273b47'} fillOpacity={pending ? .45 : .35} />)}
        <rect className="cl-land-hit" x={x + 1} y={y + 1} width="98" height="98" fill="transparent" /><title>{id}: {status}{decision ? ` · ${decision.reason}` : ''}</title>
      </g>
    })}<g pointerEvents="none"><path d="M466 42L474 18L482 42L474 35Z" fill="white" stroke="#06201d" /><text x="474" y="58" textAnchor="middle" fill="white" fontSize="13">N</text><path d="M27 468V477H127V468" stroke="white" fill="none" strokeWidth="2" /><text x="77" y="470" textAnchor="middle" fill="white" fontSize="11">100 m</text></g></svg><div className="cl-land-key"><span><i style={{ background: '#24cd8b' }} />Unclaimed creditable</span><span><i style={{ background: '#efbb54' }} />Already claimed</span><span><i className="cl-ineligible-swatch" />Not creditable</span><span><i style={{ background: '#8c86ca' }} />Pending</span><span><i style={{ background: '#273b47' }} />Not requested</span></div><p>Coverage comes from the received section masks. Pending areas earn no credits. Crediting does not transfer land ownership.</p></div>
}
