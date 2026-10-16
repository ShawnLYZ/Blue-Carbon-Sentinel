import { useState } from 'react'
import type { Report } from './model'
import { relevantSales, type LocalSale } from './sales'
const fmt = (v: number) => v.toLocaleString('en-MY', { maximumFractionDigits: 2 })
export function SellCredits({ report, sales, onSell, onUndo }: { report: Report | null; sales: LocalSale[]; onSell: (amount: number) => void; onUndo: (id: string) => void }) {
  const [amount, setAmount] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const available = report?.totals.available ?? 0
  const numeric = Number(amount)
  const valid = !!report && amount.trim() !== '' && Number.isFinite(numeric) && numeric > 0 && numeric <= available && Math.abs(numeric * 100 - Math.round(numeric * 100)) < 1e-7
  const relevant = report ? relevantSales(report, sales) : []
  return <div className="cl-sell"><label htmlFor="credit-sale-amount">Amount to sell <span>tCO₂e</span></label><div className="cl-sell-row"><input id="credit-sale-amount" aria-label="Credits to sell" type="number" min="0.01" max={available} step="0.01" value={amount} placeholder="0.00" onChange={e => { setAmount(e.target.value); setError(''); setNotice('') }} /><button disabled={!report || available < .01} onClick={() => { setAmount(String(Math.floor(available * 100) / 100)); setNotice(''); setError('') }}>Max</button><button className="cl-sell-button" disabled={!valid} onClick={() => { try { onSell(numeric); setAmount(''); setError(''); setNotice(`${fmt(numeric)} tCO₂e recorded as a local sale. Balance updated.`) } catch (e) { setError(e instanceof Error ? e.message : 'Sale could not be saved.') } }}>Sell</button></div>
    {amount !== '' && !valid && <p className="cl-warning">Use 0.01–{fmt(Math.floor(available * 100) / 100)} tCO₂e, up to 2 decimals.</p>}
    <p className="cl-sell-note">Local sale record only · no marketplace transfer or payment.</p>
    {error && <p role="alert" className="cl-error">{error}</p>}{notice && <p role="status">{notice}</p>}
    {!!relevant.length && <details><summary>{relevant.length} local sale{relevant.length === 1 ? '' : 's'} · {fmt(relevant.reduce((n, s) => n + s.amount, 0))} tCO₂e</summary>{relevant.map(s => <div className="cl-sale-record" key={s.id}><span>{fmt(s.amount)} tCO₂e<small>{new Date(s.created).toLocaleString('en-MY', { timeZone: 'Asia/Kuala_Lumpur' })} · {s.id.slice(0, 8)}</small></span><button onClick={() => { try { onUndo(s.id); setNotice('Local sale reversed. Balance restored.'); setError('') } catch { setError('Could not reverse the local sale.') } }}>Undo</button></div>)}<p>Allocated across sections in order. Overlapping report periods also reserve these amounts.</p></details>}
  </div>
}
