"""Front-end assets for the surveillance dashboard (dependency-free, inline)."""
from __future__ import annotations

from string import Template

LOGIN_HTML = Template("""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>trade_v2 · sign in</title>
<style>
:root{color-scheme:dark;--bg:#0b0e14;--panel:#121722;--panel2:#171d2a;--line:#242c3b;--text:#e6eaf2;--muted:#8791a5;--accent:#4c8dff;--red:#ff6b6b;--green:#3ddc97}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:radial-gradient(1200px 600px at 50% -10%,#16233b,#0b0e14 60%);color:var(--text);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{width:min(92vw,400px);background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:32px;box-shadow:0 24px 60px #0006}
.brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:19px;letter-spacing:.3px}
.dot{width:10px;height:10px;border-radius:50%;background:var(--accent);box-shadow:0 0 14px var(--accent)}
p{color:var(--muted);font-size:13px;margin:14px 0 26px}
label{display:block;font-size:13px;font-weight:600;margin-bottom:8px}
input{width:100%;padding:12px 13px;border-radius:8px;border:1px solid var(--line);background:#0b0e14;color:var(--text);font:inherit}
input:focus{outline:2px solid var(--accent);outline-offset:1px;border-color:transparent}
button{width:100%;margin-top:18px;padding:12px;border:0;border-radius:8px;background:var(--accent);color:#fff;font:600 14px inherit;cursor:pointer}
button:hover{filter:brightness(1.1)}
.err{margin-top:16px;padding:11px 13px;border-radius:8px;background:#3a1d22;color:#ff9a9a;font-size:13px}
.foot{margin-top:22px;font-size:11px;color:#5d6678;text-align:center}
</style></head>
<body><main>
<div class="brand"><span class="dot"></span> trade_v2 <span style="color:var(--muted);font-weight:400">surveillance</span></div>
<p>Enter the dashboard token configured on this server to continue.</p>
<form method="post" action="/login">
<label for="token">Dashboard token</label>
<input id="token" name="token" type="password" required autofocus autocomplete="current-password" spellcheck="false">
$error
<button type="submit">Sign in</button>
</form>
<div class="foot">Sessions expire after 12 hours · the token is never stored in your browser</div>
</main></body></html>""")


INDEX_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>trade_v2 · surveillance</title>
<style>
:root{color-scheme:dark;--bg:#0b0e14;--panel:#121722;--panel2:#171d2a;--panel3:#1c2331;--line:#242c3b;--line2:#2e384a;--text:#e6eaf2;--muted:#8791a5;--dim:#5d6678;--accent:#4c8dff;--green:#3ddc97;--red:#ff6b6b;--amber:#ffb454}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;-webkit-font-smoothing:antialiased}
a{color:var(--accent);text-decoration:none}
.wrap{max-width:1500px;margin:0 auto;padding:0 24px 60px}
header{position:sticky;top:0;z-index:20;background:#0b0e14e8;backdrop-filter:blur(12px);border-bottom:1px solid var(--line)}
.hbar{max-width:1500px;margin:0 auto;padding:14px 24px;display:flex;align-items:center;gap:18px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:17px;white-space:nowrap}
.dot{width:9px;height:9px;border-radius:50%;background:var(--accent);box-shadow:0 0 12px var(--accent)}
.brand small{color:var(--muted);font-weight:400;font-size:12px}
.spacer{flex:1}
.badge{display:inline-flex;align-items:center;gap:6px;padding:5px 10px;border-radius:999px;font-size:11px;font-weight:700;letter-spacing:.4px;border:1px solid var(--line2);background:var(--panel)}
.badge .p{width:6px;height:6px;border-radius:50%;background:currentColor}
.b-live{color:var(--red)}.b-paper{color:var(--green)}.b-halt{color:var(--amber)}.b-ok{color:var(--green)}.b-off{color:var(--muted)}
.clock{color:var(--muted);font-variant-numeric:tabular-nums;font-size:12px}
button.btn{padding:7px 12px;border-radius:7px;border:1px solid var(--line2);background:var(--panel2);color:var(--text);font:600 12px inherit;cursor:pointer}
button.btn:hover{border-color:var(--accent)}button.btn.danger{color:var(--red)}button.btn.ghost{background:transparent}
section{margin-top:24px}
.sh{display:flex;align-items:baseline;gap:12px;margin:0 0 12px}
h2{font-size:13px;letter-spacing:1.2px;text-transform:uppercase;color:var(--muted);margin:0;font-weight:700}
.sh .hint{font-size:11px;color:var(--dim)}
.grid{display:grid;gap:14px}.kpis{grid-template-columns:repeat(auto-fit,minmax(180px,1fr))}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px}
.kpi .label{font-size:11px;letter-spacing:.7px;text-transform:uppercase;color:var(--muted)}
.kpi .value{font-size:26px;font-weight:700;margin-top:6px;font-variant-numeric:tabular-nums;letter-spacing:-.5px}
.kpi .sub{font-size:11px;color:var(--dim);margin-top:3px}
.pos{color:var(--green)}.neg{color:var(--red)}.neutral{color:var(--text)}
.main-grid{grid-template-columns:minmax(0,1.9fr) minmax(320px,1fr)}
@media(max-width:1050px){.main-grid{grid-template-columns:1fr}}
.card-h{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:12px}
.card-h h3{margin:0;font-size:14px;font-weight:650}
.tabs{display:flex;gap:5px;flex-wrap:wrap}
.tab{padding:5px 11px;border-radius:7px;border:1px solid var(--line);background:transparent;color:var(--muted);font:600 12px inherit;cursor:pointer}
.tab:hover{color:var(--text)}.tab.active{background:var(--accent);border-color:var(--accent);color:#fff}
.chart-wrap{position:relative;height:330px}
#chart{width:100%;height:100%;display:block}
.chart-legend{display:flex;gap:16px;font-size:11px;color:var(--muted);margin-top:8px;flex-wrap:wrap}
.chart-legend b{color:var(--text)}
.market-row{display:flex;align-items:center;gap:10px;padding:10px 8px;border-radius:8px;cursor:pointer;border:1px solid transparent}
.market-row:hover{background:var(--panel2)}.market-row.active{border-color:var(--accent);background:#16223a}
.coin{width:30px;height:30px;border-radius:50%;display:grid;place-items:center;font-size:11px;font-weight:800;color:#0b0e14;flex:none}
.market-row .sym{font-weight:650}.market-row .name{font-size:11px;color:var(--dim)}
.market-row .px{margin-left:auto;text-align:right;font-variant-numeric:tabular-nums}
.market-row .px b{display:block;font-size:13px}.market-row .px span{font-size:11px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;font-size:10px;letter-spacing:.7px;text-transform:uppercase;color:var(--muted);font-weight:700;padding:8px 10px;border-bottom:1px solid var(--line)}
td{padding:10px;border-bottom:1px solid #1b2230;font-variant-numeric:tabular-nums}
tr:last-child td{border-bottom:0}
.empty{padding:26px 12px;text-align:center;color:var(--dim);font-size:13px}
.two-col{grid-template-columns:1fr 1fr}@media(max-width:900px){.two-col{grid-template-columns:1fr}}
.kv{display:flex;justify-content:space-between;gap:12px;padding:7px 0;border-bottom:1px solid #1b2230;font-size:12px}
.kv:last-child{border-bottom:0}.kv .k{color:var(--muted)}.kv .v{font-weight:600;text-align:right}
.pill{display:inline-block;padding:2px 8px;border-radius:999px;font-size:10px;font-weight:700;letter-spacing:.4px}
.p-ok{background:#12332a;color:var(--green)}.p-warn{background:#3a2b14;color:var(--amber)}.p-bad{background:#3a1d22;color:var(--red)}.p-idle{background:var(--panel3);color:var(--muted)}
.activity{display:flex;gap:10px;padding:9px 4px;border-bottom:1px solid #1b2230;font-size:12px}
.activity:last-child{border-bottom:0}.activity .t{color:var(--dim);white-space:nowrap;font-variant-numeric:tabular-nums}
.activity .e{color:var(--accent);font-weight:650;min-width:140px}
.controls{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
.note{font-size:11px;color:var(--dim);margin-top:8px}
.loading{color:var(--dim);padding:20px;text-align:center}
.err-bar{background:#3a1d22;border:1px solid #63303a;color:#ff9a9a;padding:10px 14px;border-radius:8px;font-size:12px;margin-top:12px;display:none}
footer{margin-top:36px;padding-top:16px;border-top:1px solid var(--line);color:var(--dim);font-size:11px;display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px}
</style></head>
<body>
<header><div class="hbar">
<div class="brand"><span class="dot"></span>trade_v2 <small>surveillance console</small></div>
<span id="modeBadge" class="badge b-paper"><span class="p"></span>PAPER</span>
<span id="stateBadge" class="badge b-ok"><span class="p"></span>ACTIVE</span>
<span class="clock" id="clock">—</span>
<span class="spacer"></span>
<form method="post" action="/logout" style="margin:0"><button class="btn" type="submit">Sign out</button></form>
</div></header>

<div class="wrap">
<div id="errorBar" class="err-bar"></div>

<section class="grid kpis" id="kpis">
<div class="card kpi"><div class="label">Portfolio equity</div><div class="value" id="kEquity">—</div><div class="sub" id="kEquitySub"></div></div>
<div class="card kpi"><div class="label">Realized P&amp;L</div><div class="value" id="kPnl">—</div><div class="sub" id="kPnlSub"></div></div>
<div class="card kpi"><div class="label">Profit factor</div><div class="value" id="kPf">—</div><div class="sub" id="kPfSub"></div></div>
<div class="card kpi"><div class="label">Win rate</div><div class="value" id="kWin">—</div><div class="sub" id="kWinSub"></div></div>
<div class="card kpi"><div class="label">Open positions</div><div class="value" id="kPos">—</div><div class="sub" id="kPosSub"></div></div>
</section>

<section class="grid main-grid">
<div class="card">
<div class="card-h"><h3>Market · price chart</h3><div class="tabs" id="chartTabs"></div></div>
<div class="chart-wrap"><canvas id="chart"></canvas></div>
<div class="chart-legend"><span><b id="legSym">—</b> · <span id="legTf">1h</span> candles (UTC)</span><span id="legRange">—</span><span id="legSrc"></span></div>
</div>
<div class="card">
<div class="card-h"><h3>Tracked markets</h3><span class="hint" id="marketCount"></span></div>
<div id="marketList"><div class="loading">Loading quotes…</div></div>
<div class="note">Live public spot data · prices update every 30s</div>
</div>
</section>

<section class="grid two-col">
<div class="card"><div class="card-h"><h3>Open positions</h3><span class="hint" id="posCount"></span></div><div id="positions"></div></div>
<div class="card"><div class="card-h"><h3>Risk &amp; safety</h3><span id="riskPill"></span></div><div id="risk"></div>
<div class="controls"><button class="btn danger" onclick="post('/api/emergency-stop','Emergency stop? This halts all new entries.')">Emergency stop</button>
<button class="btn" onclick="post('/api/resume','Resume trading? Requires a flat, reconciled account.')">Resume</button></div>
<div class="note">Resume is refused unless the account is flat and reconciled.</div></div>
</section>

<section class="grid two-col">
<div class="card"><div class="card-h"><h3>Strategy configuration</h3></div><div id="config"></div></div>
<div class="card"><div class="card-h"><h3>Recent activity</h3><span class="hint">audit log</span></div><div id="activity"></div></div>
</section>

<footer><span>trade_v2 · surveillance · data: public spot feed + local state store</span><span id="updated"></span></footer>
</div>

<script>
const $=(id)=>document.getElementById(id);
const fmt=(n,d=2)=>n==null||!isFinite(n)?'—':Number(n).toLocaleString(undefined,{minimumFractionDigits:d,maximumFractionDigits:d});
const money=(n)=>n==null?'—':(n>=0?'+':'-')+'$'+fmt(Math.abs(n),2);
const cls=(n)=>n==null?'neutral':n>0?'pos':n<0?'neg':'neutral';
let selectedSymbol=null, candles={}, quotes={}, statusData=null;

function showError(msg){const e=$('errorBar');if(msg){e.textContent=msg;e.style.display='block'}else e.style.display='none'}

function renderKpis(s,p){
  let eq=s.equity||p.daily_starting_equity||(s.config&&s.config.initial_balance)||null;
  $('kEquity').textContent=eq==null?'—':'$'+fmt(eq,0);
  $('kEquitySub').textContent=s.paper_trading?'Paper account':'Live account';
  $('kPnl').textContent=money(p.total_pnl??s.daily_pnl);
  $('kPnl').className='value '+cls(p.total_pnl??s.daily_pnl);
  $('kPnlSub').textContent=p.total_trades?`across ${p.total_trades} closed trades`:'no closed trades yet';
  $('kPf').textContent=p.profit_factor==null?'—':fmt(p.profit_factor,2);
  $('kPf').className='value '+(!p.profit_factor?'neutral':p.profit_factor>=1.5?'pos':'neg');
  $('kPfSub').textContent=p.profit_factor==null?'needs 2+ trades':p.profit_factor>=1.5?'above 1.5 target':'below 1.5 target';
  $('kWin').textContent=p.win_rate==null?'—':fmt(p.win_rate,1)+'%';
  $('kWinSub').textContent=p.winners!=null?`${p.winners}W / ${p.losers}L`:'—';
  $('kPos').textContent=s.open_positions;
  $('kPosSub').textContent=s.entry_mode||'ACTIVE';
  $('modeBadge').textContent=s.paper_trading?'PAPER':'LIVE';
  $('modeBadge').className='badge '+(s.paper_trading?'b-paper':'b-live');
  $('stateBadge').textContent=s.halted?'HALTED':(s.entry_mode==='EXIT_ONLY'?'EXIT ONLY':'ACTIVE');
  $('stateBadge').className='badge '+(s.halted?'b-halt':'b-ok');
  $('riskPill').innerHTML=`<span class="pill ${s.halted?'p-bad':'p-ok'}">${s.halted?'HALTED':'NOMINAL'}</span>`;
}
function renderConfig(c){
  if(!c){$('config').innerHTML='<div class="empty">Configuration unavailable</div>';return}
  const rows=[['Environment',c.environment],['Exchange',c.exchange],['Trading pairs',(c.pairs||[]).join(', ')],['Timeframe',c.timeframe],['Model',c.model_type],['Confidence threshold',c.confidence_threshold!=null?fmt(c.confidence_threshold,2):null],['Prediction horizon',c.horizon_bars!=null?c.horizon_bars+' bars':null],['Max risk / trade',c.max_risk_per_trade!=null?fmt(c.max_risk_per_trade,1)+'%':null],['Max daily loss',c.max_daily_loss_pct!=null?fmt(c.max_daily_loss_pct,1)+'%':null],['Initial balance',c.initial_balance!=null?'$'+fmt(c.initial_balance,0):null]];
  $('config').innerHTML=rows.map(([k,v])=>`<div class="kv"><span class="k">${k}</span><span class="v">${v??'—'}</span></div>`).join('');
}
function renderRisk(s,r){
  const g=(k,d)=>r&&r[k]!=null?r[k]:d;
  const halt=s.halt_reason?`<div class="kv"><span class="k">Halt reason</span><span class="v neg">${escapeHtml(s.halt_reason)}</span></div>`:'';
  const routes=Object.keys(s.route_halts||{});
  $('risk').innerHTML=
   `<div class="kv"><span class="k">Daily P&amp;L</span><span class="v ${cls(g('daily_loss'))}">${money(g('daily_loss'))}</span></div>`+
   `<div class="kv"><span class="k">Daily start equity</span><span class="v">${g('daily_starting_equity')!=null?'$'+fmt(g('daily_starting_equity'),0):'—'}</span></div>`+
   `<div class="kv"><span class="k">Rolling peak equity</span><span class="v">${g('rolling_peak_equity')!=null?'$'+fmt(g('rolling_peak_equity'),0):'—'}</span></div>`+
   `<div class="kv"><span class="k">Consecutive losses</span><span class="v">${g('consecutive_losses',0)} / ${g('max_consecutive_losses','—')}</span></div>`+
   `<div class="kv"><span class="k">Winning streak state</span><span class="v">${routes.length?'<span class="pill p-warn">'+routes.length+' route halt(s)</span>':'<span class="pill p-ok">No route halts</span>'}</span></div>`+halt+
   (routes.length?`<div class="note">${routes.map(x=>escapeHtml(x)+': '+escapeHtml(s.route_halts[x])).join('<br>')}</div>`:'');
}
function renderPositions(s){
  const pos=Object.values(s.positions||{});
  $('posCount').textContent=pos.length+' open';
  if(!pos.length){$('positions').innerHTML='<div class="empty">No open positions — the bot is flat.</div>';return}
  const px=(sym)=>quotes[sym]?.last;
  $('positions').innerHTML=`<table><thead><tr><th>Symbol</th><th>Amount</th><th>Entry</th><th>Mark</th><th>Unrealized</th><th>Stop</th></tr></thead><tbody>`+pos.map(p=>{
    const last=px(p.symbol),up=last!=null&&p.entry_price>0?((last-p.entry_price)/p.entry_price*100*(p.side==='short'?-1:1)):null;
    const u=last!=null?((last-p.entry_price)*p.amount*(p.side==='short'?-1:1)):null;
    return `<tr><td><b>${escapeHtml(p.symbol)}</b><br><span class="pill p-idle">${escapeHtml(p.route||'—')}</span></td><td>${fmt(p.amount,4)}</td><td>${fmt(p.entry_price)}</td><td>${last!=null?fmt(last):'—'}</td><td class="${cls(u)}">${u!=null?money(u)+'<br><small>'+fmt(up,2)+'%</small>':'—'}</td><td>${p.stop_loss_price!=null?fmt(p.stop_loss_price):'—'}</td></tr>`;
  }).join('')+'</tbody></table>';
}
function renderActivity(list){
  if(!list||!list.length){$('activity').innerHTML='<div class="empty">No audit events recorded yet.</div>';return}
  $('activity').innerHTML=list.slice(0,10).map(e=>{
    const d=e.details||{};const parts=Object.entries(d).slice(0,2).map(([k,v])=>k+'='+escapeHtml(String(v))).join(' · ');
    return `<div class="activity"><span class="t">${escapeHtml((e.created_at||'').replace('T',' ').slice(0,19))}</span><span class="e">${escapeHtml(e.event_type)}</span><span>${parts}</span></div>`;
  }).join('');
}
function coinColor(sym){const h=[...sym].reduce((a,c)=>a*31+c.charCodeAt(0),7);const hue=h%360;return `hsl(${hue} 70% 62%)`}
function renderMarkets(){
  const syms=Object.keys(quotes).length?Object.keys(quotes):(candles?Object.keys(candles):[]);
  const cfgPairs=(statusData&&statusData.pairs)||syms;
  const list=cfgPairs.length?cfgPairs:syms;
  $('marketCount').textContent=list.length+' symbols';
  if(!list.length){$('marketList').innerHTML='<div class="empty">Market data unavailable.</div>';return}
  $('marketList').innerHTML=list.map(sym=>{
    const q=quotes[sym];const ch=q?.change_pct;
    return `<div class="market-row ${sym===selectedSymbol?'active':''}" onclick="selectSymbol('${sym}')">
      <span class="coin" style="background:${coinColor(sym)}">${escapeHtml(sym.split('/')[0].slice(0,3))}</span>
      <span><span class="sym">${escapeHtml(sym)}</span><br><span class="name">spot · ${escapeHtml(sym.split('/')[1]||'')}</span></span>
      <span class="px"><b>${q?.last!=null?fmt(q.last):'—'}</b><span class="${cls(ch)}">${ch!=null?(ch>=0?'+':'')+fmt(ch,2)+'%':'—'}</span></span>
    </div>`;
  }).join('');
}
function renderTabs(){
  const syms=Object.keys(candles);
  if(!selectedSymbol||!syms.includes(selectedSymbol))selectedSymbol=syms[0]||null;
  $('chartTabs').innerHTML=syms.map(s=>`<button class="tab ${s===selectedSymbol?'active':''}" onclick="selectSymbol('${s}')">${escapeHtml(s.split('/')[0])}</button>`).join('');
  $('legSym').textContent=selectedSymbol||'—';
}
function selectSymbol(s){selectedSymbol=s;renderTabs();renderMarkets();drawChart()}

function drawChart(){
  const cv=$('chart');const ctx=cv.getContext('2d');const dpr=window.devicePixelRatio||1;
  const w=cv.clientWidth,h=cv.clientHeight;if(!w||!h)return;
  cv.width=w*dpr;cv.height=h*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
  const rows=candles[selectedSymbol]||[];
  if(!rows.length){ctx.fillStyle='#5d6678';ctx.font='13px system-ui';ctx.textAlign='center';ctx.fillText('No candle data available',w/2,h/2);$('legRange').textContent='';return}
  const pad={l:8,r:64,t:10,b:22};const iw=w-pad.l-pad.r,ih=h-pad.t-pad.b;
  const hi=Math.max(...rows.map(r=>r[2])),lo=Math.min(...rows.map(r=>r[3]));const range=(hi-lo)||1;const y=v=>pad.t+(hi-v)/range*ih;
  const step=iw/rows.length,cw=Math.max(1,Math.min(10,step*0.62));
  rows.forEach((r,i)=>{const x=pad.l+i*step+step/2;const up=r[4]>=r[1];const col=up?'#3ddc97':'#ff6b6b';
    ctx.strokeStyle=col;ctx.fillStyle=col;ctx.globalAlpha=.85;
    ctx.beginPath();ctx.moveTo(x,y(r[2]));ctx.lineTo(x,y(r[3]));ctx.stroke();
    const yt=y(Math.max(r[1],r[4])),yb=y(Math.min(r[1],r[4]));ctx.fillRect(x-cw/2,yt,cw,Math.max(1,yb-yt));});
  ctx.globalAlpha=1;ctx.font='10px system-ui';ctx.textAlign='left';ctx.fillStyle='#5d6678';
  for(let i=0;i<=4;i++){const val=hi-range*i/4,yy=pad.t+ih*i/4;ctx.fillText(fmt(val,val<10?3:0),w-pad.r+8,yy+3);
    ctx.strokeStyle='#1b2230';ctx.beginPath();ctx.moveTo(pad.l,yy);ctx.lineTo(w-pad.r,yy);ctx.stroke();}
  const first=new Date(rows[0][0]),last=new Date(rows[rows.length-1][0]);
  ctx.fillText(first.toISOString().slice(5,10),pad.l,h-6);ctx.textAlign='right';ctx.fillText(last.toISOString().slice(5,10),w-pad.r,h-6);
  const lastClose=rows[rows.length-1][4],firstClose=rows[0][1];const ch=(lastClose-firstClose)/firstClose*100;
  $('legRange').innerHTML=`O ${fmt(firstClose)} · C ${fmt(lastClose)} · <span class="${cls(ch)}">${ch>=0?'+':''}${fmt(ch,2)}%</span>`;
}
function escapeHtml(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function post(path,msg){if(msg&&!confirm(msg))return;const r=await fetch(path,{method:'POST'});if(r.status===401){location='/login';return}if(!r.ok){let detail='';try{const b=await r.json();detail=b.error?': '+b.error:''}catch(e){}showError('Action failed ('+r.status+')'+detail)}else{showError('');await refresh()}}

async function refresh(){
  try{
    const [sr,mr,ar]=await Promise.all([
      fetch('/api/status'),fetch('/api/market'),fetch('/api/activity')]);
    if(sr.status===401||mr.status===401){location='/login';return}
    if(!sr.ok)throw new Error('status '+sr.status);
    const s=await sr.json();statusData=s;
    const m=mr.ok?await mr.json():{quotes:{},candles:{}};
    const a=ar.ok?await ar.json():{events:[]};
    quotes=m.quotes||{};candles=m.candles||{};
    $('legTf').textContent=m.timeframe||s.timeframe||'1h';
    $('legSrc').textContent=m.source==='live'?'public spot feed':m.source==='unavailable'?'feed offline':'';
    if(m.error)showError(m.error);else showError('');
    renderKpis(s,s.risk||{});
    renderConfig(s.config);renderRisk(s,s.risk||{});renderPositions(s);
    renderActivity(a.events);renderTabs();renderMarkets();drawChart();
    $('updated').textContent='Updated '+new Date().toLocaleTimeString();
  }catch(e){showError('Could not refresh dashboard data: '+e.message)}
}
setInterval(()=>{$('clock').textContent=new Date().toISOString().slice(11,19)+' UTC'},1000);
window.addEventListener('resize',drawChart);
refresh();setInterval(refresh,30000);
</script></body></html>"""
