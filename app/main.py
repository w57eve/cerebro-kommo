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

from . import agente, aprendizaje, kommo, kommo_api
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
_memoria = {}   # lead_id -> deque de intercambios {"cliente","agente"} (memoria)
_ultimos_raw = []   # últimos webhooks crudos (para descubrir campos de pautas)


@app.on_event("startup")
async def _arranque():
    # Crea/encuentra el campo "Respuesta bot" para poder elegirlo en el bot.
    await kommo_api.asegurar_campo()
    # Restaura la memoria de las charlas desde GitHub: un deploy ya no corta
    # el hilo de las conversaciones en curso (29/08).
    try:
        import asyncio as _aio
        from collections import deque as _dq
        _rest = await _aio.to_thread(aprendizaje.cargar_memoria)
        for _k, _v in _rest.items():
            _memoria[_k] = _dq(_v, maxlen=8)
        print(f"[ARRANQUE] memoria restaurada: {len(_rest)} charlas",
              flush=True)
    except Exception as _e:
        print(f"[ARRANQUE] memoria no restaurada: {_e}", flush=True)


@app.on_event("shutdown")
async def _cierre():
    # Deploy/reinicio: subir lo pendiente del aprendizaje antes de morir.
    try:
        import asyncio as _aio
        await _aio.to_thread(aprendizaje.subir_ahora)
    except Exception:
        pass


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
                "message_type": g("message_type"),
                "adjunto": body.get(f"{pref}[{i}][attachment][link]", ""),
                "author": {"type": body.get(f"{pref}[{i}][author][type]", "")},
            })
            i += 1
        if msgs:
            break
    return msgs


async def _analizar_foto(url: str):
    """Descarga la foto del cliente UNA vez y corre en paralelo:
    - VISIÓN (Claude): descripción en palabras.
    - MATCH VISUAL (CLIP/DINO): SKUs del catálogo más parecidos.
    Devuelve (descripcion, [(sku, similitud), ...])."""
    try:
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=15, follow_redirects=True) as cli:
            r = await cli.get(url)
        if r.status_code != 200 or not r.content:
            print(f"[VISION] descarga fallo HTTP {r.status_code}", flush=True)
            return "", []
        mt = (r.headers.get("content-type") or "image/jpeg").split(";")[0]
        if not mt.startswith("image"):
            return "", []
        from . import busqueda_imagen as _bi
        from . import llm as _llm
        t_desc = _asyncio.to_thread(_llm.describir_imagen, r.content, mt)
        t_match = _bi.buscar_por_imagen(r.content)
        desc, matches = await _asyncio.gather(t_desc, t_match)
        return desc or "", matches or []
    except Exception as e:
        print(f"[VISION] error: {e}", flush=True)
        return "", []


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
    # VISIÓN: si mandó foto(s), la IA la mira y su descripción entra al
    # mensaje -> la búsqueda y la memoria trabajan con lo que se VE.
    fotos = ch.pop("fotos", []) or []
    foto_matches = []
    if fotos:
        desc, foto_matches = await _analizar_foto(fotos[-1])
        if desc:
            texto = texto.replace("(el cliente mandó una foto)", "").strip()
            texto = (texto + f"\n(foto del cliente: {desc})").strip()
            print(f"[VISION] lead={lead_id} foto -> {desc[:100]!r}", flush=True)
    nombre = await kommo_api.nombre_contacto(ch.get("contact_id"))
    print(f"[CHAT] lead={lead_id} nombre={nombre!r} msgs={len(ch['textos'])} "
          f"texto={texto[:120]!r}", flush=True)
    try:
        from collections import deque as _deque
        hist = _memoria.setdefault(lead_id, _deque(maxlen=8))
        if not hist:
            _previa = await kommo_api.respuesta_previa(lead_id)
            if _previa:
                hist.append({"cliente": "(mensajes anteriores de esta charla,"
                                        " no disponibles)",
                             "agente": _previa[:250]})
        res = await agente.procesar(texto, nombre=nombre, historial=list(hist),
                                    lead_id=lead_id,
                                    ad_id=ch.get("ad_id", ""),
                                    origen=("pauta" if ch.get("pauta")
                                            else ch.get("origen", "")),
                                    foto_matches=foto_matches)
        ok = await kommo_api.entregar(lead_id, res["texto"])
        if ok:
            hist.append({"cliente": texto[:300], "agente": res["texto"][:300]})
        aprendizaje.registrar(lead_id, texto, res.get("texto", ""),
                              res.get("derivar", False), res.get("candidatos"))
        if len(_memoria) > 3000:   # limpieza gruesa de charlas viejas
            for k in list(_memoria.keys())[:1000]:
                _memoria.pop(k, None)
    except Exception as e:
        print(f"[CHAT] ERROR procesando lead={lead_id}: {e}", flush=True)


@app.get("/webhook-mensajes")
async def webhook_mensajes_get():
    """Kommo valida la URL del webhook con un GET antes de guardarla."""
    return {"status": "ok"}


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

    # PAUTAS: buscar un ID de anuncio conocido (mapa-anuncios.md) en el cuerpo
    # CRUDO del webhook, venga en el campo que venga. Si aparece, el agente
    # abre directo con ese producto/sección en vez de preguntar a ciegas.
    from . import conocimiento as _cono
    from urllib.parse import unquote_plus as _unq
    raw_str = raw.decode("utf-8", "replace") if raw else ""
    _ultimos_raw.append({"ts": int(_time.time()), "raw": raw_str[:1500]})
    del _ultimos_raw[:-20]
    # se busca en el raw DECODIFICADO: asi matchean tanto IDs numericos como
    # URLs de publicaciones (instagram.com/p/..., fb.com/...) del mapa.
    _raw_dec = _unq(raw_str)
    ad_id = next((k for k in _cono.ANUNCIOS
                  if k and (k in _raw_dec or k in raw_str)), "")
    if ad_id:
        print(f"[MENSAJES] pauta detectada: ad_id={ad_id} "
              f"({_cono.ANUNCIOS[ad_id].get('representa','')})", flush=True)
    else:
        # log de descubrimiento: para ver en Render qué campos manda Kommo
        # cuando el chat entra desde una pauta (y sumar IDs al mapa).
        print(f"[MENSAJES] raw={raw_str[:900]!r}", flush=True)

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
        # Foto/adjunto sin texto: NO ignorar (el hilo moria en silencio).
        tipo_msg = str(m.get("message_type") or "")
        if not texto and tipo_msg in ("voice", "audio", "ptt"):
            texto = "(el cliente mandó un audio)"
        elif not texto and (ad_id or tipo_msg in ("picture", "file", "video")):
            texto = "(el cliente mandó una foto)" if tipo_msg else "Hola"
        if not lead_id or not texto:
            continue
        # Plantilla de pauta click-to-WhatsApp: marca entrada desde publicidad
        # aunque el origen sea waba y Kommo no pase el ID del anuncio.
        _t = texto.lower()
        if ("quiero más información" in _t or "quiero mas informacion" in _t
                or "necesito más información" in _t
                or "necesito mas informacion" in _t):
            ch_pauta = True
        else:
            ch_pauta = False
        ch = _charlas.setdefault(lead_id, {"textos": [], "contact_id": "",
                                           "tarea": None, "ad_id": ""})
        ch["textos"].append(texto)
        ch["contact_id"] = str(m.get("contact_id") or ch["contact_id"])
        ch["ad_id"] = ad_id or ch.get("ad_id", "")
        ch["origen"] = str(m.get("origin") or ch.get("origen", ""))
        _adj = str(m.get("adjunto") or "")
        if _adj.startswith("http"):
            ch.setdefault("fotos", []).append(_adj)
            del ch["fotos"][:-2]   # solo las 2 más recientes
        if ch_pauta and not ch.get("ad_id"):
            ch["origen"] = ch["origen"] or "waba"
            ch["pauta"] = True
        if ch["tarea"] and not ch["tarea"].done():
            ch["tarea"].cancel()  # reinicia la espera: el cliente sigue escribiendo
        ch["tarea"] = _asyncio.create_task(_responder_charla(lead_id))
        n += 1
    print(f"[MENSAJES] webhook: {n} mensaje(s) encolado(s). keys={list(body.keys())[:8]}", flush=True)
    return {"status": "ok"}


# ── Fotos optimizadas ───────────────────────────────────────────────────────
# Las fotos del storage de la web son pesadas y la vista previa de WhatsApp
# tarda una barbaridad. Servimos una miniatura liviana (JPEG ~600px) desde acá:
# el bot manda https://cerebro-kommo.onrender.com/foto/<sku>.jpg y la preview
# carga al instante. Caché en memoria (las más pedidas quedan listas).
_fotos_cache = {}   # sku -> bytes jpeg


@app.get("/foto/{sku}.jpg")
async def foto_sku(sku: str):
    from fastapi.responses import Response
    from . import productos as _prod

    sku = "".join(c for c in sku if c.isalnum())[:20]
    if sku in _fotos_cache:
        return Response(content=_fotos_cache[sku], media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"})
    it = await _prod.por_sku(sku)
    url = (it or {}).get("imagenes") and it["imagenes"][0] or ""
    if not url:
        return JSONResponse({"error": "sin foto"}, status_code=404)
    try:
        import io

        import httpx as _httpx
        from PIL import Image
        async with _httpx.AsyncClient(timeout=25) as cli:
            r = await cli.get(url, headers={"User-Agent": "cerebro"})
            r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        img.thumbnail((600, 600))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=72, optimize=True)
        data = buf.getvalue()
        if len(_fotos_cache) > 800:
            _fotos_cache.clear()
        _fotos_cache[sku] = data
        return Response(content=data, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"})
    except Exception as e:
        print(f"[FOTO] error sku={sku}: {e}", flush=True)
        # último recurso: redirigir a la foto original
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url)


@app.get("/ultimos-webhooks")
async def ver_ultimos_webhooks(request: Request):
    """Últimos webhooks CRUDOS: para descubrir en qué campo llega la
    referencia del anuncio de Meta y sumarla al mapa de pautas."""
    if _WEBHOOK_CLAVE and request.query_params.get("clave", "") != _WEBHOOK_CLAVE:
        return JSONResponse({"error": "clave"}, status_code=403)
    return {"webhooks": _ultimos_raw}


@app.get("/aprendizaje")
async def ver_aprendizaje(request: Request):
    """Resumen del registro de aprendizaje: tasas de error y consultas sin
    respuesta útil (materia prima para reglas y sinónimos nuevos)."""
    if _WEBHOOK_CLAVE and request.query_params.get("clave", "") != _WEBHOOK_CLAVE:
        return JSONResponse({"error": "clave"}, status_code=403)
    return aprendizaje.resumen()


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
