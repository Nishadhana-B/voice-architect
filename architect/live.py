"""The page you look at while you talk: diagram, risks, cost, transcript, and the buttons around them.

Standard library only. Open http://127.0.0.1:8765 in a browser while the program runs."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Voice Architect</title>
<style>
:root{color-scheme:light;--bg:#f5f3ee;--card:#fff;--line:#e3dfd6;--ink:#1f2328;--muted:#6b7280;--accent:#1d4ed8;
--high:#d6342c;--medium:#d98a00;--low:#2f6fdd}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,"Segoe UI",Helvetica,Arial,sans-serif}
header{background:var(--card);border-bottom:1px solid var(--line);padding:10px 22px;display:flex;align-items:center;gap:18px;flex-wrap:wrap}
.brand{font-weight:600;font-size:15px;letter-spacing:.01em}
#title{font:inherit;font-weight:600;font-size:15px;border:1px solid transparent;border-radius:5px;padding:4px 8px;width:300px;background:transparent;color:var(--ink)}
#title:hover{border-color:var(--line)}#title:focus{outline:none;border-color:var(--accent);background:#fff}
.count{color:var(--muted);font-size:13px}
.tools{margin-left:auto;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
button,.btn{font:inherit;color:var(--ink);background:#fff;border:1px solid #d4d0c7;border-radius:6px;padding:5px 12px;cursor:pointer;text-decoration:none}
button:hover,.btn:hover{background:#f1efe9}
button.danger{border-color:var(--high);color:var(--high)}
.sep{width:1px;height:20px;background:var(--line);margin:0 6px}
.exp{color:var(--muted);font-size:13px;margin-right:2px}
.tools a.link{color:var(--accent);text-decoration:none;padding:3px 6px;border-radius:4px}.tools a.link:hover{background:#eef2ff}
main{display:grid;grid-template-columns:minmax(0,1.8fr) minmax(300px,1fr);gap:18px;padding:18px 22px;max-width:1500px;margin:0 auto}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px 16px;margin-bottom:18px}
.card h2{font-size:14px;font-weight:600;margin:0 0 2px}.sub{color:var(--muted);font-size:12.5px;margin:0 0 10px}
#canvas{overflow:auto;background:#faf9f6 radial-gradient(#dcd8cd 1px,transparent 1px) 0 0/18px 18px;border:1px solid var(--line);border-radius:6px;padding:14px;min-height:150px}
#canvas img{display:block;max-width:100%;height:auto}
#talk{max-height:300px;overflow:auto}
.line{margin:0 0 9px}.who{font-weight:600}.me .who{color:var(--accent)}
.empty{color:var(--muted);font-style:italic}
.say{display:flex;gap:8px;margin-top:10px}.say input{flex:1;font:inherit;border:1px solid #d4d0c7;border-radius:6px;padding:6px 10px}
.say input:focus{outline:none;border-color:var(--accent)}
ul.risks{list-style:none;margin:8px 0 0;padding:0}
.risk{border-left:3px solid var(--low);padding:2px 0 2px 12px;margin:0 0 14px}
.risk.high{border-color:var(--high)}.risk.medium{border-color:var(--medium)}
.risk .top{font-size:12px;color:var(--muted)}.risk .sev{font-weight:700;margin-right:6px}
.risk.high .sev{color:var(--high)}.risk.medium .sev{color:var(--medium)}.risk.low .sev{color:var(--low)}
.risk p{margin:2px 0}.risk .meta{color:var(--muted);font-size:12px}
.total{font-size:30px;font-weight:700;line-height:1.1}.total small{font-size:14px;font-weight:400;color:var(--muted)}
table{width:100%;border-collapse:collapse;margin-top:10px;font-size:13px}td{padding:3px 0;border-top:1px solid #f0ede6}td:last-child{text-align:right;font-variant-numeric:tabular-nums}
.note{color:var(--muted);font-size:12px;margin-top:10px}
@media(max-width:900px){main{grid-template-columns:1fr}#title{width:200px}}
</style></head><body>
<header>
  <span class="brand">Voice Architect</span>
  <input id="title" value="Untitled design" maxlength="80" aria-label="Design name" spellcheck="false">
  <span class="count" id="meta"></span>
  <div class="tools">
    <span id="newbox"><button id="new">New design</button></span>
    <span class="sep"></span><span class="exp">Export</span>
    <a class="link" href="/design.svg" download="architecture.svg">Diagram (SVG)</a>
    <a class="link" href="#" onclick="downloadPng();return false">Diagram (PNG)</a>
    <a class="link" href="/design.md" download="design.md">Document (Markdown)</a>
    <a class="link" href="/report.html" download="report.html">Report (HTML)</a>
  </div>
</header>
<main>
  <section>
    <div class="card"><h2>Diagram</h2>
      <p class="sub">Red outline means a high risk. A dashed arrow means asynchronous. <a href="/design.svg" target="_blank" style="color:var(--accent)">Open full size</a></p>
      <div id="canvas"><img id="svg" alt="Architecture diagram"></div></div>
    <div class="card"><h2>Conversation</h2><div id="talk"></div>
      <form class="say" id="sayform"><input id="saytext" placeholder="Or type a sentence instead of speaking" autocomplete="off"><button>Send</button></form></div>
  </section>
  <aside>
    <div class="card"><h2>Risks</h2><p class="sub" id="risksub"></p><ul class="risks" id="risks"></ul></div>
    <div class="card"><h2>Estimated monthly cost</h2><div class="total" id="total">$0 <small>a month</small></div>
      <table id="rows"></table><p class="note" id="basis"></p></div>
  </aside>
</main>
<script>
const $=id=>document.getElementById(id),E=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let version=-1,last='',components=0;
const post=(u,b)=>fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})}).then(r=>r.json());
async function tick(){try{
  const s=await (await fetch('/state.json',{cache:'no-store'})).json();components=s.components;
  const n=s.findings.length;$('meta').textContent=s.components?`${s.components} components · ${s.connections} links · ${n} risk${n===1?'':'s'}`:'';
  if(document.activeElement!==$('title')&&$('title').value!==s.title)$('title').value=s.title;
  if(s.version!==version){version=s.version;$('svg').src='/canvas.svg?v='+s.version}
  const key=JSON.stringify([s.findings,s.cost,s.transcript]);if(key===last)return;last=key;
  const hi=s.findings.filter(f=>f.severity==='high').length;
  $('risksub').textContent=n?`${hi} high, ${n-hi} other`:'';
  $('risks').innerHTML=n?s.findings.map(f=>`<li class="risk ${f.severity}"><div class="top"><span class="sev">${E(f.severity[0].toUpperCase()+f.severity.slice(1))}</span>${E(f.pillar)}</div><p>${E(f.message)}</p><p><b>Fix:</b> ${E(f.fix)}</p><p class="meta">${f.confidence==='stated'?'You said this.':'Not said yet, worth checking.'}</p></li>`).join(''):'<li class="empty">Nothing flagged yet.</li>';
  $('total').innerHTML='$'+Math.round(s.cost.monthly_total_usd).toLocaleString()+' <small>a month</small>';
  $('rows').innerHTML=s.cost.breakdown.map(r=>`<tr><td>${E(r.component)}</td><td>$${Math.round(r.monthly_usd).toLocaleString()}</td></tr>`).join('');
  $('basis').textContent='Rough list prices typed in by hand, not taken from AWS. Expect about 25% either way.';
  const t=$('talk'),stick=t.scrollTop+t.clientHeight>=t.scrollHeight-8;
  t.innerHTML=s.transcript.length?s.transcript.map(x=>`<p class="line ${x.role==='user'?'me':''}"><span class="who">${x.role==='user'?'You':'Architect'}:</span> ${E(x.text)}</p>`).join(''):'<p class="empty">Nothing said yet. Try: "Customers go through a load balancer to two web servers."</p>';
  if(stick)t.scrollTop=t.scrollHeight;
}catch(e){}}
$('title').addEventListener('change',()=>post('/api/title',{title:$('title').value}));
$('title').addEventListener('keydown',e=>{if(e.key==='Enter')e.target.blur()});
function wireNew(){$('new').onclick=askNew}
function resetNew(){$('newbox').innerHTML='<button id="new">New design</button>';wireNew()}
function askNew(){
  if(!components){post('/api/new').then(()=>{last='';tick()});return}
  $('newbox').innerHTML='Clear this design? <button class="danger" id="yes">Yes, clear it</button> <button id="no">Cancel</button>';
  $('yes').onclick=()=>post('/api/new').then(()=>{resetNew();last='';tick()});
  $('no').onclick=resetNew}
wireNew();
$('sayform').onsubmit=async e=>{e.preventDefault();const t=$('saytext').value.trim();if(!t)return;$('saytext').value='';
  const r=await post('/api/say',{text:t});if(!r.ok)alert(r.error||'Not connected to the voice session.')};
async function diagramPng(){const t=await (await fetch('/design.svg?'+Date.now())).text();
  return new Promise((ok,no)=>{const img=new Image();img.onload=()=>{const c=document.createElement('canvas'),k=2;c.width=img.width*k;c.height=img.height*k;
  const x=c.getContext('2d');x.scale(k,k);x.drawImage(img,0,0);ok(c.toDataURL('image/png'))};img.onerror=no;
  img.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(t)})}
async function downloadPng(){const a=document.createElement('a');a.href=await diagramPng();a.download=($('title').value||'architecture')+'.png';a.click()}
setInterval(tick,700);tick();
</script></body></html>"""


class LiveView:
    def __init__(self, get_state, get_svg, port: int = 8765, get_md=None, get_html=None, get_canvas=None,
                 actions: dict | None = None):
        self.get_state, self.get_svg, self.port = get_state, get_svg, port
        self.get_md, self.get_html, self.get_canvas = get_md, get_html, get_canvas
        self.actions = actions or {}
        self._server = None

    def start(self) -> str:
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silence request logging
                return

            def _send(self, body: bytes, ctype: str, status: int = 200):
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, obj: dict, status: int = 200):
                self._send(json.dumps(obj).encode(), "application/json", status)

            def do_GET(self):
                path = self.path.split("?")[0]
                try:
                    if path == "/":
                        self._send(PAGE.encode(), "text/html; charset=utf-8")
                    elif path == "/state.json":
                        self._json(outer.get_state())
                    elif path == "/design.svg":
                        self._send(outer.get_svg().encode(), "image/svg+xml")
                    elif path == "/canvas.svg":
                        self._send((outer.get_canvas or outer.get_svg)().encode(), "image/svg+xml")
                    elif path == "/design.md" and outer.get_md:
                        self._send(outer.get_md().encode(), "text/markdown; charset=utf-8")
                    elif path == "/report.html" and outer.get_html:
                        self._send(outer.get_html().encode(), "text/html; charset=utf-8")
                    else:
                        self._send(b"not found", "text/plain", 404)
                except Exception as e:  # noqa: BLE001 - the page must never crash the voice session
                    self._send(str(e).encode(), "text/plain", 500)

            def do_POST(self):
                path = self.path.split("?")[0]
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(n) or b"{}") if n else {}
                    name = {"/api/new": "new", "/api/title": "title", "/api/say": "say"}.get(path)
                    if not name or name not in outer.actions:
                        return self._json({"ok": False, "error": "not available"}, 404)
                    result = outer.actions[name](body)
                    self._json({"ok": True, **(result or {})})
                except ValueError as e:
                    self._json({"ok": False, "error": str(e)}, 400)
                except Exception as e:  # noqa: BLE001
                    self._json({"ok": False, "error": str(e)}, 500)

        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), H)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.port}"

    def stop(self):
        if self._server:
            self._server.shutdown()
