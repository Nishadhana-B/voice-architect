"""Tiny local web page that shows the design as you speak: diagram, risks, cost and transcript.

stdlib only. Open http://127.0.0.1:8765 in a browser while talking."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAGE = """<!doctype html><meta charset=utf-8><title>Voice Architect</title>
<style>
:root{color-scheme:dark}*{box-sizing:border-box}
body{margin:0;background:#0b1220;color:#e2e8f0;font:14px/1.45 -apple-system,Helvetica,Arial,sans-serif}
header{padding:12px 20px;border-bottom:1px solid #1e293b;display:flex;gap:16px;align-items:baseline}
h1{font-size:17px;margin:0}.sub{color:#94a3b8}.dot{width:9px;height:9px;border-radius:50%;background:#22c55e;display:inline-block;margin-right:6px}
main{display:grid;grid-template-columns:minmax(0,1.7fr) minmax(320px,1fr);gap:14px;padding:14px 20px}
.card{background:#111a2e;border:1px solid #1e293b;border-radius:10px;padding:12px 14px;margin-bottom:14px}
.card h2{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#94a3b8;margin:0 0 8px}
#diagram{overflow:auto}#diagram img{max-width:100%}
.f{border-left:4px solid;padding:6px 10px;margin:6px 0;background:#0f172a;border-radius:0 6px 6px 0}
.high{border-color:#ef4444}.medium{border-color:#f59e0b}.low{border-color:#3b82f6}
.tag{font-size:11px;color:#94a3b8}.fix{color:#86efac;font-size:13px}
.cost{font-size:30px;font-weight:700}.row{display:flex;justify-content:space-between;color:#cbd5e1;font-size:13px;padding:2px 0}
.me{color:#7dd3fc}.ai{color:#fdba74}.line{margin:4px 0}#tr{max-height:240px;overflow:auto}
</style>
<header><h1><span class=dot></span>Voice Architect</h1><span class=sub id=meta>waiting for the conversation</span></header>
<main><section>
<div class=card id=diagram><h2>Architecture</h2><img id=svg alt="diagram"></div>
<div class=card><h2>Conversation</h2><div id=tr></div></div></section>
<aside><div class=card><h2>Risks</h2><div id=risks></div></div>
<div class=card><h2>Estimated monthly cost</h2><div class=cost id=total>$0</div><div id=rows></div>
<div class=tag id=basis style="margin-top:8px"></div></div></aside></main>
<script>
let last=-1;const E=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function tick(){try{const s=await (await fetch('/state.json',{cache:'no-store'})).json();
document.getElementById('meta').textContent=s.components+' components, '+s.connections+' connections, '+s.findings.length+' risks';
if(s.version!==last){last=s.version;document.getElementById('svg').src='/design.svg?v='+s.version;}
document.getElementById('risks').innerHTML=s.findings.length?s.findings.map(f=>`<div class="f ${f.severity}"><b>${E(f.severity.toUpperCase())}</b> ${E(f.pillar)}<br>${E(f.message)}<div class=fix>Fix: ${E(f.fix)}</div><div class=tag>${f.confidence==='stated'?'stated by you':'not stated, to confirm'}</div></div>`).join(''):'<span class=tag>No risks flagged yet.</span>';
document.getElementById('total').textContent='$'+Math.round(s.cost.monthly_total_usd).toLocaleString()+' / month';
document.getElementById('rows').innerHTML=s.cost.breakdown.map(r=>`<div class=row><span>${E(r.component)}</span><span>$${r.monthly_usd.toFixed(0)}</span></div>`).join('');
document.getElementById('basis').textContent='Approximate: '+s.cost.price_basis;
const tr=document.getElementById('tr'),stick=tr.scrollTop+tr.clientHeight>=tr.scrollHeight-8;
tr.innerHTML=s.transcript.map(t=>`<div class=line><span class="${t.role==='user'?'me':'ai'}">${t.role==='user'?'You':'Architect'}:</span> ${E(t.text)}</div>`).join('');
if(stick)tr.scrollTop=tr.scrollHeight;}catch(e){}}
setInterval(tick,700);tick();
</script>"""


class LiveView:
    def __init__(self, get_state, get_svg, port: int = 8765):
        self.get_state, self.get_svg, self.port = get_state, get_svg, port
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

            def do_GET(self):
                path = self.path.split("?")[0]
                try:
                    if path == "/":
                        self._send(PAGE.encode(), "text/html; charset=utf-8")
                    elif path == "/state.json":
                        self._send(json.dumps(outer.get_state()).encode(), "application/json")
                    elif path == "/design.svg":
                        self._send(outer.get_svg().encode(), "image/svg+xml")
                    else:
                        self._send(b"not found", "text/plain", 404)
                except Exception as e:  # noqa: BLE001 - the page must never crash the voice session
                    self._send(str(e).encode(), "text/plain", 500)

        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), H)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.port}"

    def stop(self):
        if self._server:
            self._server.shutdown()
