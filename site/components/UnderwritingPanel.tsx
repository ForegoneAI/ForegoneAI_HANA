'use client';
import { useState } from 'react';

type Metric = {value: string | null; unit: string; formula: string; inputs: string[]; warning?: string};
type Result = {deal_id: string; scenarios: Record<string, {metrics: Record<string,Metric>; warnings: string[]}>};
type Field = {value: string | null; origin: 'source_fact'|'human_assumption'; source_field?: string; evidence_id?: string};
const keys=['purchase_price','annual_revenue','annual_operating_expenses','annual_noi','loan_amount','annual_interest_rate_pct','amortization_years','exit_cap_rate_pct','annual_noi_growth_pct','sale_cost_pct','upfront_costs'] as const;
const initial: Record<string,Field> = Object.fromEntries(keys.map(k=>[k,{value:null,origin:'human_assumption'}]));
export default function UnderwritingPanel({dealId, token, apiBase=''}:{dealId:string;token:string;apiBase?:string}) {
  const [fields,setFields]=useState<Record<string,Field>>(initial);
  const [holdYears,setHoldYears]=useState(5);
  const [interestOnly,setInterestOnly]=useState(false);
  const [active,setActive]=useState('base');
  const [data,setData]=useState<Result|null>(null);
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const [version,setVersion]=useState('');
  const req={deal_id:dealId,inputs:{...fields,hold_years:holdYears,interest_only:interestOnly},scenarios:{
    base:{},downside:{noi_pct:-10,exit_cap_rate_delta_pct:0.5},upside:{noi_pct:10,exit_cap_rate_delta_pct:-0.5}
  }};
  async function submit(save=false){
    setBusy(true);setError('');
    try{
      const res=await fetch(`${apiBase}/api/h9n/underwriting/${save?'save':'calculate'}`,{
        method:'POST',headers:{'Content-Type':'application/json',Authorization:`Bearer ${token}`},body:JSON.stringify(req)
      });
      const body=await res.json();
      if(!res.ok) throw new Error(typeof body.detail==='string'?body.detail:JSON.stringify(body.detail));
      if(save){setVersion(body.version_id);setData(body.result);} else setData(body);
    }catch(e){setError(e instanceof Error?e.message:String(e));}finally{setBusy(false)}
  }
  const scenario=data?.scenarios[active];
  return <section aria-label="First-pass underwriting" style={{maxWidth:1000,margin:'auto',padding:20}}>
    <h2>First-pass underwriting</h2><p>Source facts and assumptions remain separate. Missing inputs produce unavailable metrics.</p>
    <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(230px,1fr))',gap:12}}>
      {keys.map(key=><label key={key} style={{display:'grid',gap:5}}><strong>{key.replaceAll('_',' ')}</strong>
        <input aria-label={key} type="number" step="any" value={fields[key].value??''} onChange={e=>setFields(f=>({...f,[key]:{...f[key],value:e.target.value||null}}))}/>
        <select aria-label={`${key} origin`} value={fields[key].origin} onChange={e=>setFields(f=>({...f,[key]:{...f[key],origin:e.target.value as Field['origin']}}))}>
          <option value="human_assumption">Human assumption</option><option value="source_fact">Source fact</option>
        </select>
        {fields[key].origin==='source_fact'&&<input placeholder="Evidence ID" aria-label={`${key} evidence`} value={fields[key].evidence_id??''} onChange={e=>setFields(f=>({...f,[key]:{...f[key],evidence_id:e.target.value}}))}/>}
      </label>)}
    </div>
    <p><label>Hold years <input type="number" min={1} max={30} value={holdYears} onChange={e=>setHoldYears(Number(e.target.value))}/></label>{' '}
    <label><input type="checkbox" checked={interestOnly} onChange={e=>setInterestOnly(e.target.checked)}/> Interest-only loan</label></p>
    <button disabled={busy} onClick={()=>submit(false)}>Calculate scenarios</button>{' '}
    <button disabled={busy} onClick={()=>submit(true)}>Save approved-deal underwriting</button>
    {error&&<p role="alert">{error}</p>}{version&&<p>Saved version: {version}</p>}
    {data&&<><nav aria-label="Scenarios">{Object.keys(data.scenarios).map(s=><button key={s} aria-pressed={active===s} onClick={()=>setActive(s)}>{s}</button>)}</nav>
      {scenario&&<><table><thead><tr><th>Metric</th><th>Value</th><th>Formula</th></tr></thead><tbody>
      {Object.entries(scenario.metrics).map(([key,m])=><tr key={key}><td>{key.replaceAll('_',' ')}</td><td>{m.value??'Unavailable'} {m.value!==null?m.unit:''}</td><td>{m.formula}</td></tr>)}
      </tbody></table>{scenario.warnings.map((w,i)=><p role="status" key={i}>⚠ {w}</p>)}</>}
    </>}
  </section>;
}
