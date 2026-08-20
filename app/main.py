# -*- coding: utf-8 -*-
"""
Servidor del cerebro (FastAPI).

Endpoints:
- GET  /            -> página simple para PROBAR el agente desde el navegador
- GET  /health      -> healthcheck para Render
- POST /webhook     -> lo llama Kommo (Salesbot widget_request)
- POST /probar      -> prueba por API: {"mensaje": "...", "ad_id": ""}
- GET  /probar?mensaje=...  -> prueba rápida escribiendo una URL en el navegador

Clave del webhook: contestamos 200 en menos de 2 segundos (solo el ACK) y el
trabajo real (pensar la respuesta + contestarle a Kommo) se hace en segundo plano.
"""

from fastapi import BackgroundTasks, Request
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from . import agente, kommo
from .config import cfg

app = FastAPI(title="Cerebro de ventas — Shopping Asia")

# CORS abierto: permite probar desde una página externa si hiciera falta. No
# expone nada sensible (este servicio no guarda datos de clientes).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


PAGINA_PRUEBA = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Probar el cerebro — Shopping Asia</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, sans-serif; max-width: 640px; margin: 30px auto;
         padding: 0 16px; line-height: 1.5; }
  h1 { font-size: 1.3rem; }
  textarea { width: 100%; padding: 10px; font-size: 1rem; border-radius: 8px;
             border: 1px solid #999; box-sizing: border-box; }
  button { margin-top: 10px; padding: 10px 18px; font-size: 1rem; border: 0;
           border-radius: 8px; background: #d81b60; color: #fff; cursor: pointer; }
  #resp { white-space: pre-wrap; background: rgba(127,127,127,.12); padding: 14px;
          border-radius: 8px; margin-top: 16px; min-height: 40px; }
  .muted { color: #888; font-size: .9rem; }
  .chips button { background:#eee; color:#333; margin:4px 4px 0 0; padding:6px 10px;
                  font-size:.85rem; }
</style></head><body>
<h1>🧠 Probar el agente (modo prueba)</h1>
<p class="muted">Esto es 100% seguro: no toca Kommo ni ningún cliente real.
Escribí un mensaje como si fueras un cliente y mirá qué respondería.</p>
<div class="chips">
  <button onclick="poner('Hola, buenas')">Hola</button>
  <button onclick="poner('¿Hacen envíos?')">Envíos</button>
  <button onclick="poner('¿Tienen precio mayorista?')">Mayorista</button>
  <button onclick="poner('¿A qué hora abren los domingos?')">Horarios</button>
  <button onclick="poner('Quiero hablar con un vendedor')">Vendedor</button>
</div>
<p><textarea id="msg" rows="3" placeholder="Escribí un mensaje de cliente..."></textarea></p>
<button onclick="probar()">Enviar</button>
<div id="resp"></div>
<script>
function poner(t){ document.getElementById('msg').value = t; }
async function probar(){
  const msg = document.getElementById('msg').value.trim();
  const box = document.getElementById('resp');
  if(!msg){ box.textContent = 'Escribí algo primero.'; return; }
  box.textContent = 'Pensando...';
  try{
    const r = await fetch('/probar', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({mensaje: msg})});
    const d = await r.json();
    box.textContent = (d.derivar ? '↪️ (deriva a vendedor)\\n\\n' : '') + (d.texto || JSON.stringify(d));
  }catch(e){ box.textContent = 'Error: ' + e; }
}
</script>
</body></html>"""


@app.get("/", response_class=HTMLResponse)
async def raiz():
    return PAGINA_PRUEBA


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "ia": "on" if cfg.ANTHROPIC_API_KEY else "off (falta ANTHROPIC_API_KEY)",
        "kommo_validacion": "on" if cfg.KOMMO_SECRET_KEY else "off",
    }


@app.post("/webhook")
async def webhook(request: Request, bg: BackgroundTasks):
    """Lo llama Kommo. Respondemos 200 ya mismo y procesamos en segundo plano."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    token = body.get("token", "")
    data = body.get("data") or {}
    return_url = body.get("return_url", "")

    if kommo.verificar_token(token) is None:
        return {"status": "ignored", "reason": "token invalido"}

    mensaje = ""
    if isinstance(data, dict):
        mensaje = data.get("message") or data.get("text") or ""

    if return_url and mensaje:
        bg.add_task(agente.procesar_y_responder, mensaje, return_url, data)

    return {"status": "ok"}


@app.post("/probar")
async def probar(request: Request):
    body = await request.json()
    mensaje = body.get("mensaje", "")
    ad_id = body.get("ad_id", "")
    res = await agente.procesar(mensaje, ad_id=ad_id)
    return res


@app.get("/probar")
async def probar_get(mensaje: str = "", ad_id: str = ""):
    """Prueba rápida desde el navegador: /probar?mensaje=hacen%20envios"""
    if not mensaje:
        return JSONResponse({"error": "pasá ?mensaje=tu%20mensaje"})
    res = await agente.procesar(mensaje, ad_id=ad_id)
    return res
