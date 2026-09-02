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

# ── Anti-scraping (31/08): un navegador humano no hace cientos de
# pedidos por minuto; un aspirador de catálogos sí. Límite por IP con
# ventana de 60s. Kommo y healthchecks quedan exentos.
_ritmo = {}


@app.middleware("http")
async def _limite_ritmo(request, call_next):
    import time as _t
    ruta = request.url.path
    if ruta.startswith(("/c/", "/cat/", "/l/", "/tienda", "/buscar")):
        ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
              or (request.client.host if request.client else "?"))
        ahora = int(_t.time() // 60)
        clave = (ip, ahora)
        _ritmo[clave] = _ritmo.get(clave, 0) + 1
        if len(_ritmo) > 5000:
            _ritmo.clear()
        if _ritmo[clave] > 240:   # 240 páginas/min por IP: nadie humano
            from fastapi.responses import PlainTextResponse
            return PlainTextResponse("Demasiadas consultas, probá en un "
                                     "minuto.", status_code=429)
    return await call_next(request)


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
      var r = await fetch('/probar' + location.search, {
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
async def raiz(request: Request):
    # 01/09: la portada SIEMPRE es la tienda (en cualquier dominio).
    # La página de prueba solo se ve con la clave: /?clave=... — así desde
    # otra PC nadie llega al probador ni gasta la IA.
    if (_CLAVE_PANEL
            and request.query_params.get("clave", "") == _CLAVE_PANEL):
        return PAGINA_PRUEBA
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/tienda", status_code=302)


@app.get("/sw.js")
async def sw_matador():
    """El catálogo chico (flyers) era una PWA con service worker cache-first
    en catalogo.shoppingasia.com.py. Al migrar el dominio a la tienda, los
    navegadores que lo visitaron siguen sirviendo la app VIEJA desde caché
    (se ve vacía/rota). Este SW se instala encima, borra los cachés, se
    desregistra y recarga la página del cliente (01/09)."""
    from fastapi.responses import Response
    js = (
        "self.addEventListener('install',e=>self.skipWaiting());"
        "self.addEventListener('activate',e=>{e.waitUntil((async()=>{"
        "try{const ks=await caches.keys();"
        "await Promise.all(ks.map(k=>caches.delete(k)));}catch(_){}"
        "await self.registration.unregister();"
        "const cs=await self.clients.matchAll({type:'window'});"
        "cs.forEach(c=>{try{c.navigate(c.url);}catch(_){}});"
        "})());});")
    return Response(js, media_type="application/javascript",
                    headers={"Cache-Control": "no-cache, max-age=0"})


@app.get("/robots.txt")
async def robots():
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(
        "User-agent: *\n"
        "Allow: /tienda\nAllow: /cat/\nAllow: /c/\nAllow: /foto/\n"
        "Disallow: /probar\nDisallow: /diag\nDisallow: /aprendizaje\n"
        "Disallow: /ultimos-webhooks\nDisallow: /webhook\n")


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
# clave SOLO para las páginas del dueño (probador, /aprendizaje, etc.).
# Es SEPARADA de WEBHOOK_CLAVE a propósito: Kommo llama a /webhook-mensajes
# sin clave, así que activar WEBHOOK_CLAVE cortaría el bot (01/09).
_CLAVE_PANEL = ((_os.getenv("CLAVE_PRUEBA", "") or "").strip()
                or _WEBHOOK_CLAVE)

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
    # IDENTIFICACIÓN DE PAUTA POR UTM (soporte Kommo 31/08): si el webhook no
    # trajo el anuncio, la ficha del lead puede tener los UTM del link del
    # anuncio (utm_campaign=<producto>). Un GET barato y sabemos QUÉ pauta es.
    if not ch.get("ad_id"):
        try:
            from . import conocimiento as _cono2
            _utms = await kommo_api.utms_de_lead(lead_id)
            if _utms:
                # OFERTA FLASH (01/09): utm con flash_<SKU> -> producto exacto
                _skuf = _cono2.sku_por_utm(_utms)
                if _skuf:
                    ch["ad_id"] = f"flash:{_skuf}"
                    ch["pauta"] = True
                    print(f"[UTM] lead={lead_id} OFERTA FLASH sku={_skuf} "
                          f"({_utms})", flush=True)
                _ad2 = "" if _skuf else _cono2.ad_por_utm(_utms)
                if _ad2:
                    ch["ad_id"] = _ad2
                    ch["pauta"] = True
                    print(f"[UTM] lead={lead_id} anuncio por UTM: {_ad2!r} "
                          f"({_utms})", flush=True)
                else:
                    ch["pauta"] = True   # vino de anuncio, aunque sin mapear
                    print(f"[UTM] lead={lead_id} utms sin mapa: {_utms}",
                          flush=True)
        except Exception as _e:
            print(f"[UTM] lead={lead_id}: {_e}", flush=True)
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
_storage_caido = {"ts": 0.0}   # último fallo del storage de la web


@app.get("/foto/{sku}.jpg")
async def foto_sku(sku: str, i: int = 0):
    from fastapi.responses import Response
    from . import productos as _prod

    import time as _time
    sku = "".join(c for c in sku if c.isalnum())[:20]
    i = max(0, min(int(i or 0), 8))
    _clave = sku if i == 0 else f"{sku}:{i}"
    v = _fotos_cache.get(_clave)
    if isinstance(v, bytes):
        return Response(content=v, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"})
    if isinstance(v, float):          # caché NEGATIVO: falló hace poco
        if _time.time() - v < 600:    # (sin esto, cada intento re-esperaba
            return JSONResponse({"error": "sin foto"}, status_code=404)
    it = await _prod.por_sku(sku)
    _imgs = (it or {}).get("imagenes") or []
    url = _imgs[i] if i < len(_imgs) else (_imgs[0] if _imgs and i == 0 else "")
    # OJO (31/08): NO cortar acá si la web no tiene la i-ésima — el ESPEJO es
    # multi-foto (sku_2.jpg...). Este guard viejo hacía que las 4 fotos de
    # los IRUN estuvieran publicadas pero nunca se sirvieran.
    from . import espejo_fotos as _esp0
    if i > 0 and not url and (await _esp0.cantidad(sku)) <= i:
        return JSONResponse({"error": "sin foto"}, status_code=404)
    # Fuentes en orden: storage de la web y, si falla (30/08: el VPS de la
    # web se cayó entero), los espejos en GitHub Pages (no dependen de ese
    # VPS): fotos del depósito en precios.* y el espejo COMPLETO del repo
    # "fotos" (~24.500 miniaturas, se publica con respaldo-fotos-github).
    # Los espejos también cubren SKUs que en la web no tienen foto.
    from . import catalogo_chico as _chico
    from . import espejo_fotos as _esp
    # CORTOCIRCUITO (31/08): si el storage de la web viene fallando (VPS
    # caído), no gastar 6s por foto en él — el espejo pasa PRIMERO.
    _storage_ok = _time.time() - _storage_caido.get("ts", 0) > 300
    fuentes = [u for u in (
        url if _storage_ok else "",
        # el espejo "fotos" es MULTI-FOTO (sku.jpg, sku_2.jpg, ...)
        _esp.url_foto(sku, i),
        (await _chico.foto_de(sku)) if i == 0 else "",
        f"https://precios.shoppingasia.com.py/fotos_sku/{sku}.jpg" if i == 0 else "",
        url if not _storage_ok else "") if u]
    import io

    import httpx as _httpx
    from PIL import Image
    for fuente in fuentes:
        try:
            # timeout corto: con la web caída, 25s x fuente dejaba la página
            # /l "colgada" con huecos blancos (30/08)
            async with _httpx.AsyncClient(timeout=6) as cli:
                r = await cli.get(fuente, headers={"User-Agent": "cerebro"})
                r.raise_for_status()
            img = Image.open(io.BytesIO(r.content)).convert("RGB")
            img.thumbnail((600, 600))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=72, optimize=True)
            data = buf.getvalue()
            if "shoppingasia.com.py/storage" in fuente:
                _esp.storage_ok["v"] = True
            if len(_fotos_cache) > 800:
                _fotos_cache.clear()
            _fotos_cache[_clave] = data
            return Response(content=data, media_type="image/jpeg",
                            headers={"Cache-Control": "public, max-age=86400"})
        except Exception as e:
            if "shoppingasia.com.py/storage" in fuente:
                _storage_caido["ts"] = _time.time()   # 5 min sin insistir
                _esp.storage_ok["v"] = False
            print(f"[FOTO] {fuente[:60]} sku={sku}: {e}", flush=True)
    import time as _t2
    if len(_fotos_cache) > 800:
        _fotos_cache.clear()
    _fotos_cache[_clave] = _t2.time()    # caché negativo 10 min
    return JSONResponse({"error": "sin foto"}, status_code=404)


# ── Catálogo dinámico (un solo link, diseño premium) ────────────────────────
# /l/<sku,sku,...>  candidatos exactos que el agente eligió (máx 8)
# /c/<término>      TODOS los resultados de una búsqueda (máx 200)
# Ambos: tarjetas con fotos deslizables por SKU y botón "Hacer pedido" que
# vuelve al chat con el SKU (mismo formato que el catálogo chico: el webhook
# ya lo reconoce y concreta).
WA_PEDIDOS = "595976915333"   # línea del negocio (la misma del catálogo chico)


def _opciones_cat(actual=""):
    import html as _h
    from . import tienda as _td
    return "".join(
        f'<option value="{_h.escape(c)}"'
        f'{" selected" if c == actual else ""}>{_h.escape(c)}</option>'
        for c in _td.CATEGORIAS)


async def _pagina_catalogo(items, titulo, nota, query="", cat="",
                           extra_abajo=""):
    import html as _html
    from urllib.parse import quote as _q

    from . import espejo_fotos as _esp
    from . import productos as _prod

    tarjetas = []
    for it in items:
        sku = str(it.get("sku"))
        nombre = it.get("nombre") or ""
        precio = _prod.precio_texto(it)
        # cantidad real de fotos: las de la web o las del espejo multi-foto
        n_fotos = max(1, len(it.get("imagenes") or []),
                      await _esp.cantidad(sku))
        fotos = "".join(
            f'<img src="/foto/{sku}.jpg{("?i=%d" % j) if j else ""}" '
            f'loading="lazy" alt="" '
            f'onerror="this.remove();window.__rm&&window.__rm(this)">'
            for j in range(min(n_fotos, 4)))
        puntos = ("<div class='dots'>" + "<i></i>" * min(n_fotos, 4) + "</div>"
                  if n_fotos > 1 else "")
        wa = ("/pedido-wa?skus=" + sku + "&texto=" + _q(
            "Quiero hacer un pedido 🛒\n"
            f"Producto (SKU): {sku}\n"
            f"Artículo: {nombre} — {precio}"))
        _cls_fs = "fs multi" if n_fotos > 1 else "fs"
        _nav = ('<button class="nav prev" aria-label="anterior">&#8249;</button>'
                '<button class="nav next" aria-label="siguiente">&#8250;</button>'
                f'<span class="cnt">1/{min(n_fotos, 4)}</span>'
                if n_fotos > 1 else "")
        _dj = _html.escape(nombre).replace("'", "&#39;")
        tarjetas.append(
            f'<div class="c" data-sku="{sku}" data-nombre="{_dj}" '
            f'data-precio="{it.get("precio") or 0}">'
            f'<div class="fw"><div class="{_cls_fs}">{fotos}'
            f'</div>{_nav}</div>{puntos}'
            f'<div class="tx"><div class="n">{_html.escape(nombre)}</div>'
            f'<div class="p">{precio}</div>'
            f'<div class="s">SKU {sku}</div></div>'
            f'<button class="btn agregar" type="button">➕ Agregar</button>'
            f'<a class="btn" href="{wa}">🛒 Hacer pedido</a></div>')
    pagina = f"""<!doctype html><html lang='es'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Shopping Asia — {_html.escape(titulo) if titulo else "Tienda"}</title>
<link rel='preconnect' href='https://fonts.googleapis.com'>
<link href='https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500;600;700&family=Jost:wght@300;400;500;600&display=swap' rel='stylesheet'>
<style>
:root{{color-scheme:light dark;--marca:#b3134f;--verde:#0a7a38;--fondo:#faf8f5;
--tarjeta:#ffffff;--texto:#191714;--suave:#8d8880;--linea:#e8e3db;
--serif:'Cormorant Garamond',Georgia,serif;--sans:'Jost',system-ui,sans-serif}}
@media(prefers-color-scheme:dark){{:root{{--fondo:#141210;--tarjeta:#1d1a17;
--texto:#f0ece6;--suave:#9b958c;--linea:#2c2823}}}}
*{{box-sizing:border-box;margin:0}}
body{{font-family:var(--sans);font-weight:300;background:var(--fondo);
color:var(--texto);padding-bottom:40px;letter-spacing:.01em}}
header{{position:sticky;top:0;z-index:5;background:var(--fondo);
border-bottom:1px solid var(--linea);padding:18px 20px 14px}}
header h1{{font-family:var(--serif);font-size:1.55rem;font-weight:600;
letter-spacing:.04em;color:var(--texto)}}
header a h1{{color:var(--texto)}}
header .sub{{font-size:.72rem;color:var(--suave);margin-top:2px;
text-transform:uppercase;letter-spacing:.22em}}
.bsc{{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}}
.bsc input{{flex:2 1 160px;min-width:0;padding:10px 14px;font-family:var(--sans);
border:1px solid var(--linea);border-radius:0;font-size:.92rem;
background:var(--tarjeta);color:var(--texto)}}
.bsc input:focus{{outline:1px solid var(--marca)}}
.bsc select{{flex:1 1 130px;min-width:0;padding:10px 8px;font-family:var(--sans);
border:1px solid var(--linea);border-radius:0;font-size:.8rem;
background:var(--tarjeta);color:var(--texto)}}
.bsc button{{padding:10px 22px;border:1px solid var(--texto);border-radius:0;
font-family:var(--sans);font-weight:500;background:var(--texto);
color:var(--fondo);cursor:pointer;font-size:.8rem;text-transform:uppercase;
letter-spacing:.14em}}
.ayuda{{display:inline-flex;align-items:center;gap:7px;margin-top:11px;
font-size:.72rem;color:#fff;background:var(--marca);text-decoration:none;
text-transform:uppercase;letter-spacing:.16em;font-weight:500;
padding:8px 16px;border-radius:999px;box-shadow:0 3px 12px rgba(179,19,79,.28)}}
.ayuda:hover{{background:var(--texto)}}
.nota{{padding:16px 20px 2px;color:var(--suave);font-size:.83rem;
max-width:70ch;line-height:1.55}}
.g{{display:grid;grid-template-columns:repeat(auto-fill,minmax(178px,1fr));
gap:22px 16px;padding:18px 20px 26px}}
.c{{background:var(--tarjeta);border:1px solid var(--linea);border-radius:0;
overflow:hidden;display:flex;flex-direction:column;
transition:box-shadow .25s,transform .25s}}
.c:hover{{box-shadow:0 12px 34px rgba(25,23,20,.10);transform:translateY(-2px)}}
.fs{{display:flex;overflow-x:auto;scroll-snap-type:x mandatory;
scrollbar-width:none;background:#fff;aspect-ratio:1}}
.fs::-webkit-scrollbar{{display:none}}
.fs img{{flex:0 0 100%;width:100%;object-fit:contain;scroll-snap-align:center;
background:#fff;padding:8%}}
.dots{{display:flex;gap:6px;justify-content:center;padding:8px 0 0}}
.dots i{{width:5px;height:5px;border-radius:50%;background:var(--suave);
opacity:.4;cursor:pointer;transition:all .2s}}
.dots i.on{{opacity:1;background:var(--marca);width:16px;border-radius:3px}}
.fs.multi img{{cursor:pointer}}
.fw{{position:relative}}
.nav{{position:absolute;top:50%;transform:translateY(-50%);width:30px;
height:30px;border-radius:50%;border:1px solid var(--linea);
background:rgba(255,255,255,.94);color:#333;font-size:17px;line-height:1;
display:flex;align-items:center;justify-content:center;cursor:pointer;
z-index:2;opacity:0;transition:opacity .15s}}
.prev{{left:8px}}.next{{right:8px}}
.fw:hover .nav{{opacity:1}}
@media(pointer:coarse){{.nav{{opacity:.65;width:27px;height:27px}}}}
.cnt{{position:absolute;top:8px;right:8px;background:rgba(25,23,20,.55);
color:#fff;font-size:.62rem;font-weight:500;padding:2px 8px;
letter-spacing:.08em;z-index:2}}
.tx{{padding:12px 13px 4px;flex:1}}
.n{{font-family:var(--serif);font-size:1.02rem;line-height:1.22;
font-weight:600;min-height:2.4em}}
.p{{font-size:.95rem;font-weight:500;color:var(--texto);margin-top:6px;
letter-spacing:.03em}}
.p::after{{content:"";display:block;width:26px;height:2px;
background:var(--marca);margin-top:6px}}
.s{{font-size:.62rem;color:var(--suave);margin-top:5px;letter-spacing:.08em}}
.btn{{display:block;text-align:center;text-decoration:none;font-weight:500;
font-size:.76rem;text-transform:uppercase;letter-spacing:.16em;color:var(--fondo);
background:var(--texto);margin:10px 13px 13px;padding:11px 0;border:0;
cursor:pointer;transition:background .2s}}
.btn:hover{{background:var(--marca)}}
.btn:active{{transform:scale(.98)}}
.btn.agregar{{background:transparent;color:var(--texto);
border:1px solid var(--texto);margin-bottom:0;padding:9px 0}}
.btn.agregar:hover{{border-color:var(--marca);color:var(--marca)}}
#cfab{{position:fixed;right:14px;top:50%;transform:translateY(-50%);
z-index:50;width:56px;height:56px;
border-radius:50%;border:1px solid var(--linea);background:var(--texto);
color:var(--fondo);font-size:23px;box-shadow:0 8px 26px rgba(0,0,0,.28);
cursor:pointer;display:none}}
#cfab b{{position:absolute;top:-5px;right:-5px;background:var(--marca);
color:#fff;font-size:.7rem;min-width:22px;height:22px;border-radius:11px;
display:flex;align-items:center;justify-content:center;padding:0 4px}}
#cpanel{{position:fixed;right:80px;top:50%;transform:translateY(-50%);
z-index:50;width:min(340px,86vw);
max-height:62vh;overflow-y:auto;background:var(--tarjeta);
border:1px solid var(--linea);box-shadow:0 18px 48px rgba(0,0,0,.25);
display:none;padding:16px}}
#cpanel h3{{font-family:var(--serif);font-size:1.15rem;font-weight:600;
margin-bottom:10px}}
.citem{{display:flex;gap:10px;align-items:center;padding:8px 0;
border-bottom:1px solid var(--linea)}}
.citem img{{width:48px;height:48px;object-fit:contain;background:#fff;
border:1px solid var(--linea);flex:0 0 48px}}
.citem .ci{{flex:1;min-width:0}}
.citem .cn{{font-size:.78rem;line-height:1.25;overflow:hidden;
display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}}
.citem .cp{{font-size:.82rem;font-weight:600;margin-top:2px}}
.citem .cx{{border:0;background:none;color:var(--suave);font-size:1rem;
cursor:pointer;padding:4px}}
.citem .cx:hover{{color:var(--marca)}}
#ctot{{display:flex;justify-content:space-between;font-weight:600;
padding:12px 2px 4px;font-size:.95rem}}
#cwa{{display:block;text-align:center;text-decoration:none;font-weight:500;
font-size:.78rem;text-transform:uppercase;letter-spacing:.14em;color:#fff;
background:var(--verde);padding:12px 0;margin-top:8px}}
</style></head><body>
<header><a href='/tienda' style='text-decoration:none'><h1>Shopping Asia 🛍️</h1></a><div class='sub'>{_html.escape(titulo)} · {len(items)} resultado{"s" if len(items) != 1 else ""}</div>
<form class='bsc' action='/buscar' method='get'>
<input name='q' type='search' placeholder='Buscá un producto...' value='{_html.escape(query)}'>
<select name='cat'><option value=''>Todas las categorías</option>{_opciones_cat(cat)}</select>
<button type='submit'>Buscar</button></form>
<a class='ayuda' href='/vendedor'>💬 ¿Necesitás ayuda? Hablá con un vendedor</a></header>
<div class='nota'>{_html.escape(nota)} Si un modelo tiene varias fotos, deslizá sobre la imagen.</div>
<div class='g'>{"".join(tarjetas)}</div>{extra_abajo}
<button id='cfab' type='button'>🛒<b id='cnum'>0</b></button>
<div id='cpanel'><h3>Tu pedido 🛒</h3><div id='clista'></div>
<div id='ctot'><span>Total</span><span id='ctotv'></span></div>
<a id='cwa' href='#'>Enviar pedido por WhatsApp</a></div>
<script>
window.__marcas=[];
window.__rm=function(){{window.__marcas.forEach(function(f){{f();}});}};
document.querySelectorAll('.c').forEach(function(c){{
var fs=c.querySelector('.fs'), dots=c.querySelectorAll('.dots i'),
cnt=c.querySelector('.cnt');
if(!fs)return;
function nImgs(){{return fs.querySelectorAll('img').length;}}
function idx(){{return Math.round(fs.scrollLeft/fs.clientWidth);}}
function marca(){{
var i=idx(), n=nImgs();
dots.forEach(function(d,j){{
d.classList.toggle('on',j===i);
d.style.display=(j<n)?'':'none';   // si una foto falló, su punto se va
}});
if(cnt){{cnt.textContent=(i+1)+'/'+n;cnt.style.display=(n>1)?'':'none';}}
var pv=c.querySelector('.prev'),nx=c.querySelector('.next');
if(pv)pv.style.display=(n>1)?'':'none';
if(nx)nx.style.display=(n>1)?'':'none';
}}
function go(i){{
var n=nImgs(); if(n<1)return;
i=(i+n)%n;
fs.scrollTo({{left:i*fs.clientWidth,behavior:'smooth'}});
setTimeout(marca,350);
}}
marca();
window.__marcas.push(marca);
fs.addEventListener('scroll',function(){{requestAnimationFrame(marca);}});
var pv=c.querySelector('.prev'), nx=c.querySelector('.next');
if(pv)pv.addEventListener('click',function(e){{e.preventDefault();go(idx()-1);}});
if(nx)nx.addEventListener('click',function(e){{e.preventDefault();go(idx()+1);}});
var x0=null, drag=false;
fs.addEventListener('pointerdown',function(e){{x0=e.clientX;drag=false;}});
fs.addEventListener('pointermove',function(e){{
if(x0!==null&&Math.abs(e.clientX-x0)>12)drag=true;
}});
fs.addEventListener('pointerup',function(e){{
var n=nImgs();
if(n<2){{x0=null;return;}}
var dx=e.clientX-(x0===null?e.clientX:x0);
if(drag&&Math.abs(dx)>35){{go(idx()+(dx<0?1:-1));}}
else if(!drag){{go(idx()+1);}}
x0=null;drag=false;
}});
dots.forEach(function(d,j){{
d.addEventListener('click',function(){{go(j);}});
}});
}});
(function(){{
var K='carrito_sa', mem=[];
function leer(){{
try{{var v=JSON.parse(localStorage.getItem(K));if(v)return v;}}catch(e){{}}
return mem;
}}
function guardar(c){{
mem=c;
try{{localStorage.setItem(K,JSON.stringify(c))}}catch(e){{}}
}}
var fab=document.getElementById('cfab'),pan=document.getElementById('cpanel'),
num=document.getElementById('cnum'),lista=document.getElementById('clista'),
totv=document.getElementById('ctotv'),cwa=document.getElementById('cwa');
if(!fab)return;
function gs(n){{return (n||0).toLocaleString('es-PY')+' gs';}}
function pintar(){{
var c=leer();
num.textContent=c.length;
fab.style.display=c.length?'block':'none';
if(!c.length){{pan.style.display='none';}}
lista.innerHTML=c.map(function(it,i){{
return "<div class='citem'><img src='/foto/"+it.sku+".jpg'>"+
"<div class='ci'><div class='cn'>"+it.nombre+"</div>"+
"<div class='cp'>"+gs(it.precio)+"</div></div>"+
"<button class='cx' data-i='"+i+"' aria-label='quitar'>✕</button></div>";
}}).join('');
lista.querySelectorAll('img').forEach(function(im){{
im.onerror=function(){{im.style.visibility='hidden';}};
}});
var tot=c.reduce(function(s,x){{return s+(x.precio||0)}},0);
totv.textContent=gs(tot);
var txt='Quiero hacer un pedido 🛒\\n'+c.map(function(x){{
return 'Producto (SKU): '+x.sku+'\\n  '+x.nombre+' — '+gs(x.precio);
}}).join('\\n')+'\\nTOTAL: '+gs(tot);
var skus=c.map(function(x){{return x.sku}}).join(',');
cwa.href='/pedido-wa?skus='+skus+'&texto='+encodeURIComponent(txt);
lista.querySelectorAll('.cx').forEach(function(b){{
b.addEventListener('click',function(){{
var c2=leer();c2.splice(parseInt(b.getAttribute('data-i')),1);
guardar(c2);pintar();
}});
}});
}}
document.querySelectorAll('.agregar').forEach(function(b){{
b.addEventListener('click',function(){{
var c0=b.closest('.c'),c=leer();
c.push({{sku:c0.getAttribute('data-sku'),
nombre:c0.getAttribute('data-nombre'),
precio:parseInt(c0.getAttribute('data-precio'))||0}});
guardar(c);pintar();
b.textContent='✓ Agregado';
setTimeout(function(){{b.textContent='➕ Agregar';}},900);
}});
}});
fab.addEventListener('click',function(){{
pan.style.display=(pan.style.display==='block')?'none':'block';
}});
pintar();
}})();
</script></body></html>"""
    return HTMLResponse(pagina, headers={"Cache-Control": "public, max-age=600"})


@app.get("/l/{skus}")
async def lista_resultados(skus: str):
    from . import productos as _prod
    vistos, items = set(), []
    for s in skus.split(",")[:8]:
        s = "".join(c for c in s if c.isalnum())[:20]
        if not s or s in vistos:
            continue
        vistos.add(s)
        it = await _prod.por_sku(s)
        if it:
            items.append(it)
    if not items:
        return HTMLResponse("<h3>No encontramos esos productos.</h3>",
                            status_code=404)
    return await _pagina_catalogo(
        items, "opciones para vos",
        "Tocá \"Hacer pedido\" en el que te guste y volvés al chat con "
        "todos los datos, o decime por WhatsApp el nombre o SKU.")


@app.get("/c/{termino}")
async def catalogo_dinamico(termino: str, cat: str = ""):
    from . import productos as _prod
    from . import tienda as _td
    import re as _re2
    termino = _re2.sub(r"[^\w\sáéíóúñü-]", " ", termino)[:60].strip()
    if not termino:
        return HTMLResponse("<h3>Búsqueda vacía.</h3>", status_code=404)
    items = await _prod.buscar(termino, limite=200)
    if cat:
        items = _td.filtrar(_prod.indice_actual(), items, cat)
    # prioridad del dueño (31/08): pasar SOLO los que tienen foto (si casi
    # ninguno tiene, se muestran todos para no dejar la página vacía)
    from . import espejo_fotos as _esp2
    await _esp2._asegurar()
    from . import busqueda as _bq2
    _con_foto = [x for x in items if _bq2.it_foto(x)]
    if len(_con_foto) >= 2:
        items = _con_foto
    _tit = f"“{termino}”" + (f" en {cat}" if cat else "")
    if not items:
        # 01/09: antes devolvía un <h3> pelado (la "página se borraba").
        # Ahora queda la tienda entera con un aviso elegante bajo el buscador.
        import html as _h2
        return await _pagina_catalogo(
            [], _tit,
            f"No encontramos resultados para “{_h2.escape(termino)}”"
            + (f" en {_h2.escape(cat)}" if cat else "") + ". "
            "Probá con otra palabra (o revisá si hay algún error de "
            "tipeo), buscá sin filtro de categoría, o navegá por "
            "secciones desde la portada.",
            query=termino, cat=cat,
            extra_abajo=("<div style='text-align:center;padding:26px 20px "
                         "60px'><a class='ayuda' href='/tienda'>🛍️ Ver "
                         "todas las categorías</a></div>"))
    return await _pagina_catalogo(
        items, _tit,
        "Tocá \"➕ Agregar\" para juntar varios productos (el carrito te "
        "sigue a la derecha) o \"Hacer pedido\" si querés uno solo.",
        query=termino, cat=cat)


# ── TIENDA PROVISORIA (31/08: la página oficial está caída; esta es la
# "página" que se pasa a los clientes: catálogo completo + categorías +
# buscador propio con filtro opcional) ──────────────────────────────────────
@app.get("/tienda")
async def tienda_portada():
    import html as _h

    from . import productos as _prod
    from . import tienda as _td
    from . import espejo_fotos as _esp5
    await _esp5._asegurar()
    idx = _prod.indice_actual()
    if not idx:
        return HTMLResponse("<h3>Catálogo cargando, probá en unos segundos."
                            "</h3>", status_code=503)
    # DESTACADOS: productos con 3-4 fotos (los mejor presentados); rotan
    # cada día para que la portada se sienta viva
    import random as _rnd
    import time as _tt
    from . import espejo_fotos as _esp6
    _cands_dest = [it for it in idx.items
                   if _esp6.n_sync(it.get("sku")) >= 3]
    _rnd.Random(int(_tt.time() // 86400)).shuffle(_cands_dest)
    destacados = _cands_dest[:8]
    cts = {c: len(_td.items_de(idx, c)) for c in _td.CATEGORIAS}
    fichas = "".join(
        f'<a class="catf" href="/cat/{_h.escape(c)}"><b>{_h.escape(c)}</b>'
        f'<span>{n} productos</span></a>'
        for c, n in cts.items() if n)
    pagina = await _pagina_catalogo(
        destacados, "piezas destacadas", "")
    # portada: sin tarjetas; inyectamos las categorías en lugar de la grilla
    cuerpo = (f"<div class='nota'>Bienvenido/a a nuestra tienda. Buscá "
              f"arriba lo que necesités o navegá por secciones:</div>"
              f"<div class='cats'>{fichas}</div>"
              f"<div class='nota' style='text-transform:uppercase;"
              f"letter-spacing:.2em;font-size:.72rem'>— Piezas destacadas</div>")
    h = pagina.body.decode("utf-8")
    import re as _re3
    h = _re3.sub(r"<div class='nota'>.*?</div>", "", h, count=1, flags=_re3.S)
    h = h.replace("<div class='g'>", cuerpo + "<div class='g'>", 1)
    h = h.replace(" · 8 resultados", "").replace(" · 0 resultados", "")
    h = h.replace("</style>", """
.cats{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));
gap:10px;padding:12px}
.catf{background:var(--tarjeta);border-radius:14px;padding:16px 14px;
text-decoration:none;color:var(--texto);box-shadow:0 1px 6px rgba(0,0,0,.09);
display:flex;flex-direction:column;gap:4px}
.catf b{font-size:.95rem}
.catf span{font-size:.75rem;color:var(--suave)}
</style>""")
    return HTMLResponse(h, headers={"Cache-Control": "public, max-age=600"})


@app.get("/cat/{categoria}")
async def tienda_categoria(categoria: str, p: int = 1):
    import html as _h

    from . import productos as _prod
    from . import tienda as _td
    from . import espejo_fotos as _esp4
    await _esp4._asegurar()   # sin esto, en frío el orden con-foto fallaba
    idx = _prod.indice_actual()
    if not idx or categoria not in _td.CATEGORIAS:
        return HTMLResponse("<h3>Categoría no encontrada. "
                            "<a href='/tienda'>Volver a la tienda</a></h3>",
                            status_code=404)
    items = _td.items_de(idx, categoria)
    POR_PAG = 60
    total = len(items)
    p = max(1, int(p or 1))
    pag = items[(p - 1) * POR_PAG: p * POR_PAG]
    nav = "<div class='pgn'>"
    if p > 1:
        nav += f"<a href='/cat/{_h.escape(categoria)}?p={p-1}'>&#8249; Anteriores</a>"
    if p * POR_PAG < total:
        nav += f"<a href='/cat/{_h.escape(categoria)}?p={p+1}'>Ver más &#8250;</a>"
    nav += "</div><style>.pgn{display:flex;gap:10px;justify-content:center;padding:6px 0 20px}.pgn a{background:var(--marca);color:#fff;text-decoration:none;padding:10px 18px;border-radius:12px;font-weight:700;font-size:.9rem}</style>"
    r = await _pagina_catalogo(
        pag, f"{categoria} ({total})",
        "Tocá \"➕ Agregar\" para juntar varios (el carrito te sigue a la "
        "derecha) o \"Hacer pedido\" si querés uno solo.", cat=categoria, extra_abajo=nav)
    return r


@app.get("/vendedor")
async def tienda_vendedor(consulta: str = ""):
    """Derivación DIRECTA desde el catálogo: usa la misma rotación equitativa
    de vendedoras que el bot y redirige al WhatsApp personal (31/08)."""
    from urllib.parse import quote as _q

    from fastapi.responses import RedirectResponse

    from . import vendedores as _vend
    v = _vend.siguiente()
    if not v:
        from fastapi.responses import RedirectResponse as _RR
        return _RR("/tienda", status_code=302)
    nombre, numero = v
    txt = (f"Hola {nombre}, vengo del catálogo de Shopping Asia y quiero "
           "que me ayudes con mi compra."
           + (f" Consulta: {consulta[:150]}" if consulta else ""))
    return RedirectResponse(f"https://wa.me/{numero}?text={_q(txt)}",
                            status_code=302)


@app.get("/pedido-wa")
async def pedido_wa(texto: str = "", skus: str = ""):
    """Pedidos del catálogo DIRECTO a la vendedora de turno (31/08: pedido
    del dueño). El texto lleva SKUs+precios+TOTAL y un link /l con las FOTOS
    de lo elegido (la vista previa de WhatsApp la muestra en miniatura)."""
    from urllib.parse import quote as _q

    from fastapi.responses import RedirectResponse

    from . import vendedores as _vend
    v = _vend.siguiente()
    if not v:
        return RedirectResponse("/tienda", status_code=302)
    nombre, numero = v
    cuerpo = (texto or "").strip()[:1200]
    if skus:
        _sk = ",".join("".join(ch for ch in s if ch.isalnum())[:20]
                       for s in skus.split(",")[:8] if s.strip())
        if _sk:
            cuerpo += ("\n📷 Fotos del pedido: "
                       f"https://catalogo.shoppingasia.com.py/l/{_sk}")
    msj = (f"Hola {nombre}, vengo del catálogo de Shopping Asia 🛍️\n"
           + (cuerpo or "Quiero hacer un pedido."))
    return RedirectResponse(f"https://wa.me/{numero}?text={_q(msj)}",
                            status_code=302)


@app.get("/buscar")
async def tienda_buscar(q: str = "", cat: str = ""):
    from urllib.parse import quote as _q

    from fastapi.responses import RedirectResponse
    q = (q or "").strip()[:60]
    cat = (cat or "").strip()
    if q:
        url = f"/c/{_q(q)}" + (f"?cat={_q(cat)}" if cat else "")
    elif cat:
        url = f"/cat/{_q(cat)}"
    else:
        url = "/tienda"
    return RedirectResponse(url, status_code=302)


@app.get("/ultimos-webhooks")
async def ver_ultimos_webhooks(request: Request):
    """Últimos webhooks CRUDOS: para descubrir en qué campo llega la
    referencia del anuncio de Meta y sumarla al mapa de pautas."""
    if _CLAVE_PANEL and request.query_params.get("clave", "") != _CLAVE_PANEL:
        return JSONResponse({"error": "clave"}, status_code=403)
    return {"webhooks": _ultimos_raw}


@app.get("/aprendizaje")
async def ver_aprendizaje(request: Request):
    """Resumen del registro de aprendizaje: tasas de error y consultas sin
    respuesta útil (materia prima para reglas y sinónimos nuevos)."""
    if _CLAVE_PANEL and request.query_params.get("clave", "") != _CLAVE_PANEL:
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
    if _CLAVE_PANEL and request.query_params.get("clave", "") != _CLAVE_PANEL:
        return JSONResponse({"error": "clave requerida"}, status_code=403)
    body = await request.json()
    mensaje = body.get("mensaje", "")
    ad_id = body.get("ad_id", "")
    nombre = body.get("nombre", "")
    res = await agente.procesar(mensaje, ad_id=ad_id, nombre=nombre)
    return res


@app.get("/probar")
async def probar_get(mensaje: str = "", ad_id: str = "", nombre: str = "",
                     clave: str = ""):
    # 31/08: sin clave, cualquiera que descubra la URL gasta la IA
    if _CLAVE_PANEL and clave != _CLAVE_PANEL:
        return JSONResponse({"error": "clave requerida: agregá "
                             "?clave=... a la URL"}, status_code=403)
    """Prueba rápida desde el navegador: /probar?mensaje=hacen%20envios"""
    if not mensaje:
        return JSONResponse({"error": "pasá ?mensaje=tu%20mensaje"})
    res = await agente.procesar(mensaje, ad_id=ad_id, nombre=nombre)
    return res
