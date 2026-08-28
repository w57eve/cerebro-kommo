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

from . import agente, kommo, kommo_api
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
un cliente y mirá qué respondería. (En Kommo, el nombre del cliente lo toma solo.)</p>

<div class="fila">
  <input id="nom" type="text" autocomplete="off"
         placeholder="Nombre del cliente (opcional, ej. María)">
</div>
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
    var nom = (document.getElementById('nom').value || '').trim();
    try{
      var r = await fetch('/probar', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({mensaje: msg, nombre: nom})
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
    import json as _json
    from urllib.parse import parse_qs

    raw = await request.body()
    ctype = request.headers.get("content-type", "")
    print(f"[WEBHOOK] ct={ctype!r} len={len(raw)} raw={raw[:700]!r}", flush=True)

    body = {}
    if raw:
        try:
            body = _json.loads(raw)
        except Exception:
            try:
                q = parse_qs(raw.decode("utf-8", "replace"))
                body = {k: (v[0] if v else "") for k, v in q.items()}
            except Exception:
                body = {}
    if not isinstance(body, dict):
        body = {}

    token = body.get("token", "") or ""
    data = body.get("data")
    if not isinstance(data, dict):
        data = {}
    return_url = body.get("return_url", "") or ""

    mensaje = data.get("message") or data.get("text") or ""
    if not mensaje:
        mensaje = body.get("data[message]") or body.get("message") or body.get("text") or ""
    if not return_url:
        return_url = body.get("data[return_url]") or ""

    print(f"[WEBHOOK] parse | return_url={'si' if return_url else 'NO'} | "
          f"mensaje={mensaje!r} | keys={list(body.keys())}", flush=True)

    # NO bloqueamos por token: si no valida (secret/formato) avisamos y seguimos,
    # para no quedar mudos. Se puede endurecer una vez que ande.
    if kommo.verificar_token(token) is None:
        print("[WEBHOOK] aviso: el token NO valido (secret o formato). Proceso igual.", flush=True)

    if return_url and mensaje:
        bg.add_task(agente.procesar_y_responder, mensaje, return_url, data)
        print("[WEBHOOK] encolado para responder al return_url.", flush=True)
    else:
        print("[WEBHOOK] NO respondo: falta return_url o mensaje.", flush=True)

    return {"status": "ok"}


# ============================================================================
# ARQUITECTURA v2 — webhook general de mensajes entrantes (sin widget_request)
#
# Kommo manda un webhook por CADA mensaje entrante (evento "Incoming message
# received"). Nosotros: juntamos los mensajes seguidos del mismo lead unos
# segundos (la gente escribe en tandas), pensamos UNA respuesta y la entregamos
# via kommo_api (campo del lead + lanzar bot de 1 paso). Resultado: un solo
# mensaje natural, sin limite de 80, en TODOS los mensajes de la charla.
# ============================================================================

import asyncio as _asyncio
import os as _os
import time as _time

_ESPERA_AGRUPAR = float(_os.getenv("ESPERA_AGRUPAR_SEG", "6"))
_WEBHOOK_CLAVE = (_os.getenv("WEBHOOK_CLAVE", "") or "").strip()

_charlas = {}   # lead_id -> {"textos": [...], "contact_id": str, "tarea": Task}
_vistos = {}    # message_id -> timestamp (dedupe de reintentos del webhook)


@app.on_event("startup")
async def _arranque():
    # Crea/encuentra el campo "Respuesta bot" para poder elegirlo en el bot.
    await kommo_api.asegurar_campo()


def _extraer_mensajes(body: dict) -> list:
    """Del form-urlencoded aplanado (add[0][text], ...) o del JSON, saca la
    lista de mensajes entrantes."""
    msgs = []
    # JSON: {"add": [ {...} ]} o {"message": {"add": [...]}}
    add = body.get("add")
    if add is None and isinstance(body.get("message"), dict):
        add = body["message"].get("add")
    if isinstance(add, list):
        for m in add:
            if isinstance(m, dict):
                msgs.append(m)
        return msgs
    # Form aplanado: add[0][text], message[add][0][text], etc.
    for pref in ("add", "message[add]"):
        i = 0
        while f"{pref}[{i}][id]" in body or f"{pref}[{i}][text]" in body:
            g = lambda k, _i=i, _p=pref: body.get(f"{_p}[{_i}][{k}]", "")
            msgs.append({
                "id": g("id"), "text": g("text"), "type": g("type"),
                "entity_id": g("entity_id") or g("element_id"),
                "entity_type": g("entity_type"),
                "contact_id": g("contact_id"), "talk_id": g("talk_id"),
                "origin": g("origin"),
                "author": {"type": body.get(f"{pref}[{i}][author][type]", "")},
            })
            i += 1
        if msgs:
            break
    return msgs


async def _responder_charla(lead_id: str):
    """Espera unos segundos por si vienen mas mensajes seguidos y responde UNA vez."""
    try:
        await _asyncio.sleep(_ESPERA_AGRUPAR)
    except _asyncio.CancelledError:
        return  # llego otro mensaje: la tarea nueva se encarga
    ch = _charlas.pop(lead_id, None)
    if not ch or not ch["textos"]:
        return
    texto = "\n".join(ch["textos"])
    nombre = await kommo_api.nombre_contacto(ch.get("contact_id"))
    print(f"[CHAT] lead={lead_id} nombre={nombre!r} msgs={len(ch['textos'])} "
          f"texto={texto[:120]!r}", flush=True)
    try:
        res = await agente.procesar(texto, nombre=nombre)
        await kommo_api.entregar(lead_id, res["texto"])
    except Exception as e:
        print(f"[CHAT] ERROR procesando lead={lead_id}: {e}", flush=True)


@app.post("/webhook-mensajes")
async def webhook_mensajes(request: Request):
    """Webhook general de Kommo: evento 'Incoming message received'."""
    import json as _json
    from urllib.parse import parse_qs

    if _WEBHOOK_CLAVE and request.query_params.get("clave", "") != _WEBHOOK_CLAVE:
        return JSONResponse({"error": "clave"}, status_code=403)

    raw = await request.body()
    body = {}
    if raw:
        try:
            body = _json.loads(raw)
        except Exception:
            try:
                q = parse_qs(raw.decode("utf-8", "replace"))
                body = {k: (v[0] if v else "") for k, v in q.items()}
            except Exception:
                body = {}
    if not isinstance(body, dict):
        body = {}

    ahora = _time.time()
    # dedupe: limpiar ids viejos (>10 min)
    for k in [k for k, t in _vistos.items() if ahora - t > 600]:
        _vistos.pop(k, None)

    n = 0
    for m in _extraer_mensajes(body):
        if (m.get("type") or "").lower() not in ("", "incoming"):
            continue
        if (m.get("author") or {}).get("type") == "internal":
            continue  # lo escribio un usuario de Kommo o un bot, no el cliente
        mid = str(m.get("id") or "")
        if mid and mid in _vistos:
            continue
        if mid:
            _vistos[mid] = ahora
        lead_id = str(m.get("entity_id") or "")
        texto = (m.get("text") or "").strip()
        if not lead_id or not texto:
            continue
        ch = _charlas.setdefault(lead_id, {"textos": [], "contact_id": "", "tarea": None})
        ch["textos"].append(texto)
        ch["contact_id"] = str(m.get("contact_id") or ch["contact_id"])
        if ch["tarea"] and not ch["tarea"].done():
            ch["tarea"].cancel()  # reinicia la espera: el cliente sigue escribiendo
        ch["tarea"] = _asyncio.create_task(_responder_charla(lead_id))
        n += 1
    print(f"[MENSAJES] webhook: {n} mensaje(s) encolado(s). keys={list(body.keys())[:8]}", flush=True)
    return {"status": "ok"}


@app.get("/diag-kommo")
async def diag_kommo():
    """Diagnostico de la arquitectura v2: token, cuenta, campo y bot."""
    return await kommo_api.diagnostico()


@app.get("/diag")
async def diag():
    """Diagnostico: confirma si el catalogo carga y con que formato."""
    from . import productos
    info = {"catalogo_url": cfg.CATALOGO_JSON_URL}
    try:
        cand = await productos.buscar("championes", limite=3)
        info["productos_cargados"] = productos.cantidad()
        info["muestra_busqueda_champion"] = [
            {"sku": c["sku"], "nombre": c["nombre"], "precio": c["precio"],
             "foto": (c["imagenes"][0] if c.get("imagenes") else None)}
            for c in cand
        ]
        # fetch CRUDO del catalogo para ver el error real de descarga
        import httpx as _httpx
        try:
            async with _httpx.AsyncClient(timeout=30, headers={"User-Agent": "cerebro"}) as _cli:
                _r = await _cli.get(cfg.CATALOGO_JSON_URL)
            info["fetch_http"] = _r.status_code
            info["fetch_bytes"] = len(_r.content)
            info["fetch_muestra"] = _r.text[:180]
        except Exception as _e:
            info["fetch_error"] = f"{type(_e).__name__}: {_e}"

        items = productos._cache.get("items") or []
        if items:
            it0 = items[0]
            info["ejemplo_item"] = {"sku": it0["sku"], "nombre": it0["nombre"],
                                    "precio": it0["precio"],
                                    "foto": (it0["imagenes"][0] if it0.get("imagenes") else None)}
    except Exception as e:
        import traceback
        info["error"] = f"{type(e).__name__}: {e}"
        info["trace"] = traceback.format_exc()[-500:]
    return info


@app.post("/probar")
async def probar(request: Request):
    body = await request.json()
    mensaje = body.get("mensaje", "")
    ad_id = body.get("ad_id", "")
    nombre = body.get("nombre", "")
    res = await agente.procesar(mensaje, ad_id=ad_id, nombre=nombre)
    return res


@app.get("/probar")
async def probar_get(mensaje: str = "", ad_id: str = "", nombre: str = ""):
    """Prueba rápida desde el navegador: /probar?mensaje=hacen%20envios"""
    if not mensaje:
        return JSONResponse({"error": "pasá ?mensaje=tu%20mensaje"})
    res = await agente.procesar(mensaje, ad_id=ad_id, nombre=nombre)
    return res
