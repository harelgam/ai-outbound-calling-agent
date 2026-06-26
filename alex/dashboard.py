"""Operator dashboard for Alex (separate from the public webhook server).

A small local web UI to view customers, place calls, read transcripts/summaries,
add/delete customers, and reset a single customer for a re-demo. Run it on a port
that is NOT tunnelled by ngrok, so customer data and the Call button stay private:

    uvicorn alex.dashboard:app --port 8001
    # open http://localhost:8001

Placing a call still requires the public webhook server (alex.server on :8000) +
ngrok to be running, since Vapi calls back to it for tools and the end-of-call
summary. The two apps share the same CRM file.
"""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import config, crm
from .brief import brief
from .vapi_client import place_call

app = FastAPI(title="Alex Operator Dashboard")


class NewLead(BaseModel):
    name: str
    email: str = ""
    phone: str = ""
    title: str = ""
    company: str = ""
    industry: str = ""
    employees: int = 0
    signal: str = ""


class EditLead(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None
    industry: Optional[str] = None
    employees: Optional[int] = None
    signal: Optional[str] = None


@app.get("/api/leads")
def api_leads():
    return sorted(crm.list_leads(), key=lambda l: l["lead_id"])


@app.get("/api/leads/{lead_id}")
def api_lead(lead_id: str):
    lead = crm.get_lead(lead_id)
    if not lead:
        raise HTTPException(404, "no such lead")
    return lead


@app.post("/api/leads")
def api_add(lead: NewLead):
    return crm.add_lead(**lead.model_dump())


@app.put("/api/leads/{lead_id}")
def api_edit(lead_id: str, patch: EditLead):
    if not crm.get_lead(lead_id):
        raise HTTPException(404, "no such lead")
    fields = {k: v for k, v in patch.model_dump().items() if v is not None}
    if "email" in fields:
        fields["email"] = (fields["email"] or "").strip() or None
    if "phone" in fields:
        fields["phone"] = (fields["phone"] or "").strip() or None
    if "employees" in fields:
        fields["employees"] = int(fields["employees"] or 0)
    return crm.update_lead(lead_id, **fields)


@app.delete("/api/leads/{lead_id}")
def api_delete(lead_id: str):
    if not crm.delete_lead(lead_id):
        raise HTTPException(404, "no such lead")
    return {"deleted": lead_id}


@app.post("/api/leads/{lead_id}/reset")
def api_reset(lead_id: str):
    lead = crm.reset_lead(lead_id)
    if not lead:
        raise HTTPException(404, "no such lead")
    return lead


@app.post("/api/leads/{lead_id}/call")
def api_call(lead_id: str):
    lead = crm.get_lead(lead_id)
    if not lead:
        raise HTTPException(404, "no such lead")
    if not lead.get("phone"):
        raise HTTPException(400, "This customer has no phone number.")
    if not config.PUBLIC_WEBHOOK_URL or "example" in config.PUBLIC_WEBHOOK_URL:
        raise HTTPException(400, "PUBLIC_WEBHOOK_URL not set — start the webhook server + ngrok.")
    call = place_call(lead, brief(lead), lead["phone"])  # sync def -> runs in threadpool
    return {"call_id": call.get("id"), "status": call.get("status"), "to": lead["phone"]}


@app.get("/", response_class=HTMLResponse)
def index():
    return _HTML


_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Alex — Operator Dashboard</title>
<style>
  :root { --bg:#0f1115; --card:#181b22; --line:#262b35; --txt:#e7e9ee; --mut:#9aa3b2; --accent:#4f8cff; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--txt); font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif; }
  header { padding:18px 24px; border-bottom:1px solid var(--line); display:flex; align-items:center; gap:12px; }
  header h1 { font-size:18px; margin:0; } header .sub { color:var(--mut); font-size:12px; }
  main { padding:20px 24px; max-width:1200px; margin:0 auto; }
  .bar { display:flex; gap:10px; align-items:center; margin-bottom:14px; }
  button { background:var(--card); color:var(--txt); border:1px solid var(--line); border-radius:7px; padding:6px 11px; cursor:pointer; font-size:13px; }
  button:hover { border-color:var(--accent); }
  button.primary { background:var(--accent); border-color:var(--accent); color:#fff; }
  button.danger:hover { border-color:#e5484d; color:#ff8086; }
  table { width:100%; border-collapse:collapse; }
  th,td { text-align:left; padding:9px 10px; border-bottom:1px solid var(--line); vertical-align:top; }
  th { color:var(--mut); font-weight:600; font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
  .badge { padding:2px 8px; border-radius:20px; font-size:12px; white-space:nowrap; }
  .b-new{background:#2a2f3a;color:#aab3c2} .b-sent{background:#13371f;color:#5be08a}
  .b-pending{background:#13243f;color:#79a8ff} .b-failed,.b-opt{background:#3a1416;color:#ff8086}
  .b-callback{background:#3a2c12;color:#f0c267} .b-ni{background:#2a2f3a;color:#aab3c2}
  .muted{color:var(--mut)} a{color:var(--accent)} .row-actions{display:flex;gap:6px;flex-wrap:wrap}
  td.signal{max-width:240px;color:var(--mut);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.6);display:none;align-items:center;justify-content:center;padding:20px}
  .modal{background:var(--card);border:1px solid var(--line);border-radius:12px;max-width:760px;width:100%;max-height:85vh;overflow:auto;padding:22px}
  .modal h2{margin:0 0 4px} pre{white-space:pre-wrap;background:#0c0e12;border:1px solid var(--line);border-radius:8px;padding:12px;font-size:13px}
  form.add{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin-bottom:16px}
  form.add input{background:#0c0e12;border:1px solid var(--line);color:var(--txt);border-radius:6px;padding:7px}
  form.add .full{grid-column:1/-1}
  #toast{position:fixed;bottom:20px;right:20px;background:var(--card);border:1px solid var(--accent);border-radius:8px;padding:10px 14px;display:none}
  .kv{display:grid;grid-template-columns:130px 1fr;gap:6px 12px;margin:10px 0}
  .kv div:nth-child(odd){color:var(--mut)}
  .editgrid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px}
  .editgrid label{display:flex;flex-direction:column;gap:3px;font-size:12px;color:var(--mut)}
  .modal input{background:#0c0e12;border:1px solid var(--line);color:var(--txt);border-radius:6px;padding:7px;width:100%}
</style></head>
<body>
<header><h1>📞 Alex — Operator Dashboard</h1><span class="sub">AI outbound calling agent · Harel's</span></header>
<main>
  <div class="bar">
    <button class="primary" onclick="toggleAdd()">+ Add customer</button>
    <button onclick="load()">↻ Refresh</button>
    <span id="status" class="muted"></span>
  </div>

  <form class="add" id="addForm" style="display:none" onsubmit="return addLead(event)">
    <input name="name" placeholder="Name *" required>
    <input name="title" placeholder="Title">
    <input name="company" placeholder="Company">
    <input name="industry" placeholder="Industry">
    <input name="email" placeholder="Email" type="email">
    <input name="phone" placeholder="Phone (+972...)">
    <input name="employees" placeholder="Employees" type="number">
    <input name="signal" class="full" placeholder="Signal / why we're calling">
    <div class="full"><button class="primary" type="submit">Save customer</button></div>
  </form>

  <table><thead><tr>
    <th>ID</th><th>Name</th><th>Company</th><th>Signal</th><th>Phone</th><th>Status</th><th>Meeting</th><th>Actions</th>
  </tr></thead><tbody id="rows"></tbody></table>
</main>

<div class="modal-bg" id="modalBg" onclick="if(event.target.id==='modalBg')closeModal()">
  <div class="modal" id="modal"></div>
</div>
<div id="toast"></div>

<script>
const BADGE = {
  new:'b-new', calendar_invite_sent:'b-sent', reserved_pending_calendar_invite:'b-pending',
  calendar_invite_failed:'b-failed', opt_out:'b-opt', callback:'b-callback',
  not_interested:'b-ni', voicemail:'b-callback', wrong_person:'b-ni'
};
function esc(s){return (s==null?'':String(s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function toast(m){const t=document.getElementById('toast');t.textContent=m;t.style.display='block';setTimeout(()=>t.style.display='none',3500);}
function toggleAdd(){const f=document.getElementById('addForm');f.style.display=f.style.display==='none'?'grid':'none';}

async function load(){
  const r = await fetch('/api/leads'); const leads = await r.json();
  const called = leads.filter(l=>l.status!=='new').length;
  document.getElementById('status').textContent = `${leads.length} customers · ${called} called`;
  document.getElementById('rows').innerHTML = leads.map(l=>{
    const m = l.meeting||{};
    const meet = m.label ? `${esc(m.label)}${m.meet_link?` · <a href="${esc(m.meet_link)}" target="_blank">Meet</a>`:''}` : '<span class="muted">—</span>';
    const canCall = !!l.phone;
    return `<tr>
      <td class="muted">${l.lead_id}</td>
      <td>${esc(l.name)}<div class="muted">${esc(l.email||'')}</div></td>
      <td>${esc(l.company||'')}</td>
      <td class="signal" title="${esc(l.signal||'')}">${esc(l.signal||'—')}</td>
      <td>${esc(l.phone||'<span class=muted>none</span>')}</td>
      <td><span class="badge ${BADGE[l.status]||'b-new'}">${esc(l.status)}</span></td>
      <td>${meet}</td>
      <td><div class="row-actions">
        <button class="primary" ${canCall?'':'disabled'} onclick="callLead('${l.lead_id}','${esc(l.name)}','${esc(l.phone||'')}')">Call</button>
        <button onclick="viewLead('${l.lead_id}')">View</button>
        <button onclick="editLead('${l.lead_id}')">Edit</button>
        <button onclick="resetLead('${l.lead_id}','${esc(l.name)}')">Reset</button>
        <button class="danger" onclick="delLead('${l.lead_id}','${esc(l.name)}')">Delete</button>
      </div></td></tr>`;
  }).join('');
}

async function addLead(e){
  e.preventDefault();
  const fd = Object.fromEntries(new FormData(e.target).entries());
  const r = await fetch('/api/leads',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(fd)});
  if(r.ok){ toast('Customer added'); e.target.reset(); toggleAdd(); load(); } else { toast('Add failed'); }
  return false;
}
async function callLead(id,name,phone){
  if(!confirm(`Place a REAL call to ${name} at ${phone}?`)) return;
  toast('Dialing '+name+'…');
  const r = await fetch('/api/leads/'+id+'/call',{method:'POST'});
  const j = await r.json();
  toast(r.ok ? `Call ${j.status} → ${j.to}` : ('Call failed: '+(j.detail||'')));
}
async function resetLead(id,name){
  if(!confirm(`Reset ${name}'s call data back to 'new'? (frees their booked slot)`)) return;
  await fetch('/api/leads/'+id+'/reset',{method:'POST'}); toast(name+' reset'); load();
}
async function delLead(id,name){
  if(!confirm(`Delete ${name}? This cannot be undone.`)) return;
  await fetch('/api/leads/'+id,{method:'DELETE'}); toast(name+' deleted'); load();
}
async function viewLead(id){
  const l = await (await fetch('/api/leads/'+id)).json();
  const m = l.meeting||{};
  document.getElementById('modal').innerHTML = `
    <h2>${esc(l.name)} <span class="muted">· ${esc(l.title||'')} ${l.company?'@ '+esc(l.company):''}</span></h2>
    <div class="kv">
      <div>Status</div><div><span class="badge ${BADGE[l.status]||'b-new'}">${esc(l.status)}</span></div>
      <div>Email</div><div>${esc(l.email||'—')}</div>
      <div>Phone</div><div>${esc(l.phone||'—')}</div>
      <div>Meeting</div><div>${m.label?esc(m.label):'—'} ${m.meet_link?`· <a href="${esc(m.meet_link)}" target="_blank">Meet link</a>`:''} ${m.event_link?`· <a href="${esc(m.event_link)}" target="_blank">Calendar</a>`:''}</div>
      <div>Qualification</div><div>${esc(l.qualification||'—')}</div>
      <div>Next action</div><div>${esc(l.next_action||'—')}</div>
    </div>
    <h3>Summary</h3><pre>${esc(l.notes||'(no summary yet — call this customer first)')}</pre>
    <h3>Transcript</h3><pre>${esc(l.transcript||'(no transcript yet)')}</pre>
    <div style="margin-top:14px;text-align:right"><button onclick="closeModal()">Close</button></div>`;
  document.getElementById('modalBg').style.display='flex';
}
function closeModal(){document.getElementById('modalBg').style.display='none';}

async function editLead(id){
  const l = await (await fetch('/api/leads/'+id)).json();
  const fld = (k,v,extra='')=>`<label>${k}<input name="${k}" value="${esc(v==null?'':v)}" ${extra}></label>`;
  document.getElementById('modal').innerHTML = `
    <h2>Edit customer</h2>
    <form onsubmit="return saveEdit(event,'${id}')">
      <div class="editgrid">
        ${fld('name', l.name)}
        ${fld('title', l.title)}
        ${fld('company', l.company)}
        ${fld('industry', l.industry)}
        ${fld('email', l.email)}
        ${fld('phone', l.phone)}
        ${fld('employees', l.employees, 'type="number"')}
        ${fld('signal', l.signal)}
      </div>
      <div style="margin-top:16px;text-align:right">
        <button type="button" onclick="closeModal()">Cancel</button>
        <button class="primary" type="submit">Save changes</button>
      </div>
    </form>`;
  document.getElementById('modalBg').style.display='flex';
}
async function saveEdit(e,id){
  e.preventDefault();
  const fd = Object.fromEntries(new FormData(e.target).entries());
  const r = await fetch('/api/leads/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(fd)});
  if(r.ok){ toast('Customer updated'); closeModal(); load(); } else { toast('Update failed'); }
  return false;
}

load();
setInterval(load, 4000);  // auto-refresh so call results appear as they complete
</script>
</body></html>"""
