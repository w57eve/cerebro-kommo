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
  * { box-sizing: border-box; }
  body { font-family: system-ui, sans-serif; max-width: 640px; margin: 24px auto;
         padding: 0 16px; line-height: 1.5; }
  h1 { font-size: 1.25rem; margin-bottom: 4px; }
  .muted { color: #888; font-size: .9rem; margin-top: 0; }
  .fila { display: flex; gap: 8px; margin-top: 14px; }
  #msg { flex: 1; padding: 12px; font-size: 1rem; border-radius: 8px;
         border: 2px solid #d81b60; background: #fff; color: #111; }
  #enviar { padding: 12px 20px; font-size: 1rem; border: 0; border-radius: 8px;
            background: #d81b60; color: #fff; cursor: pointer; }
  #resp { white-space: pre-wrap; background: rgba(127,127,127,.14); padding: 14px;
          border-radius: 8px; margin-top: 16px; min-height: 44px; }
  .chips { margin-top: 12px; }
  .chips button { background:#eee; color:#222; margin:4px 6px 0 0; padding:8px 12px;
                  font-size:.9rem; border:1px solid #ccc; border-radius:20px; cursor:pointer; }
  a { color:#d81b60; }
</style></head><body>
<h1>🧠 Probar el agente</h1>
<p class="muted">Modo prueba: no toca Kommo ni clientes reales. Escribí como si fueras
un cliente y mirá qué respondería.</p>

<div class="fila">
  <input id="msg" type="text" autofocus autocomplete="off"
         placeholder="Escribí un mensaje y apretá Enter...">
  <button id="enviar" type="button">Enviar</button>
</div>

<div class="chips">
  <button type="button" data-t="Hola, buenas">Hola</button>
  <button type="button" data-t="¿Hacen envíos?">Envíos</button>
  <button type="button" data-t="¿Tienen precio mayorista?">Mayorista</button>
  <button type="button" data-t="¿A qué hora abren los domingos?">Horarios</button>
  <button type="button" data-t="Quiero hablar con un vendedor">Vendedor</button>
</div>

<div id="resp"></div>

<script>
  var inp = document.getElementById('msg');
  var box = document.getElementById('resp');

  async function enviar(texto){
    var msg = (texto !== undefined) ? texto : inp.value;
    msg = (msg || '').trim();
    if(texto !== undefined){ inp.value = texto; }
    if(!msg){ box.textContent = 'Escribí algo primero.'; inp.focus(); return; }
    box.textContent = 'Pensando...';
    try{
      var r = await fetch('/probar', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({mensaje: msg})
      });
      var d = await r.json();
      box.textContent = (d.derivar ? '↪️ (deriva a vendedor)\\n\\n' : '') + (d.texto || JSON.stringify(d));
    }catch(e){ box.textContent = 'Error de conexión: ' + e; }
  }

  document.getElementById('enviar').addEventListener('click', function(){ enviar(); });
  inp.addEventListener('keydown', function(e){ if(e.key === 'Enter'){ e.preventDefault(); enviar(); } });
  var chips = document.querySelectorAll('.chips button');
  for(var i=0;i<chips.length;i++){
    chips[i].addEventListener('click', function(){ enviar(this.getAttribute('data-t')); });
  }
  inp.focus();
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
