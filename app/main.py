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
    # IDENTIFICACIÓN DE PAUTA POR UTM (soporte Kommo 31/08): si el webhook no
    # trajo el anuncio, la ficha del lead puede tener los UTM del link del
    # anuncio (utm_campaign=<producto>). Un GET barato y sabemos QUÉ pauta es.
    if not ch.get("ad_id"):
        try:
            from . import conocimiento as _cono2
            _utms = await kommo_api.utms_de_lead(lead_id)
            if _utms:
                _ad2 = _cono2.ad_por_utm(_utms)
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
            if len(_fotos_cache) > 800:
                _fotos_cache.clear()
            _fotos_cache[_clave] = data
            return Response(content=data, media_type="image/jpeg",
                            headers={"Cache-Control": "public, max-age=86400"})
        except Exception as e:
            if "shoppingasia.com.py/storage" in fuente:
                _storage_caido["ts"] = _time.time()   # 5 min sin insistir
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
        wa = (f"https://wa.me/{WA_PEDIDOS}?text=" + _q(
            "¡Hola! Quiero hacer un pedido 🛒\n"
            f"Producto (SKU): {sku}\n"
            f"Artículo: {nombre} — {precio}"))
        _cls_fs = "fs multi" if n_fotos > 1 else "fs"
        _nav = ('<button class="nav prev" aria-label="anterior">&#8249;</button>'
                '<button class="nav next" aria-label="siguiente">&#8250;</button>'
                f'<span class="cnt">1/{min(n_fotos, 4)}</span>'
                if n_fotos > 1 else "")
        tarjetas.append(
            f'<div class="c"><div class="fw"><div class="{_cls_fs}">{fotos}'
            f'</div>{_nav}</div>{puntos}'
            f'<div class="tx"><div class="n">{_html.escape(nombre)}</div>'
            f'<div class="p">{precio}</div>'
            f'<div class="s">SKU {sku}</div></div>'
            f'<a class="btn" href="{wa}">🛒 Hacer pedido</a></div>')
    pagina = f"""<!doctype html><html lang='es'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Shopping Asia — {_html.escape(titulo)}</title><style>
:root{{color-scheme:light dark;--marca:#d81b60;--verde:#0a8f3c;--fondo:#f5f4f7;
--tarjeta:#fff;--texto:#1c1c1e;--suave:#8a8a90}}
@media(prefers-color-scheme:dark){{:root{{--fondo:#121214;--tarjeta:#1e1e22;
--texto:#f2f2f4;--suave:#9a9aa2}}}}
*{{box-sizing:border-box;margin:0}}
body{{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;background:var(--fondo);
color:var(--texto);padding-bottom:28px}}
header{{position:sticky;top:0;z-index:5;background:linear-gradient(120deg,#d81b60,#a4148f);
color:#fff;padding:13px 16px 11px;box-shadow:0 2px 10px rgba(0,0,0,.18)}}
header h1{{font-size:1.05rem;font-weight:800;letter-spacing:.3px}}
header .sub{{font-size:.8rem;opacity:.92;margin-top:2px}}
.bsc{{display:flex;gap:6px;margin-top:9px;flex-wrap:wrap}}
.bsc input{{flex:2 1 150px;min-width:0;padding:9px 12px;border:0;
border-radius:10px;font-size:.95rem;background:rgba(255,255,255,.95);color:#222}}
.bsc select{{flex:1 1 120px;min-width:0;padding:9px 8px;border:0;
border-radius:10px;font-size:.85rem;background:rgba(255,255,255,.88);color:#333}}
.bsc button{{padding:9px 16px;border:0;border-radius:10px;font-weight:700;
background:#fff;color:var(--marca);cursor:pointer;font-size:.9rem}}
.nota{{padding:12px 16px 4px;color:var(--suave);font-size:.85rem}}
.g{{display:grid;grid-template-columns:repeat(auto-fill,minmax(164px,1fr));
gap:12px;padding:12px}}
.c{{background:var(--tarjeta);border-radius:16px;overflow:hidden;display:flex;
flex-direction:column;box-shadow:0 1px 6px rgba(0,0,0,.09)}}
.fs{{display:flex;overflow-x:auto;scroll-snap-type:x mandatory;
scrollbar-width:none;background:linear-gradient(160deg,#faf7f9,#efe9f0);
aspect-ratio:1}}
.fs::-webkit-scrollbar{{display:none}}
.fs img{{flex:0 0 100%;width:100%;object-fit:contain;scroll-snap-align:center;
background:linear-gradient(160deg,#faf7f9,#f0edf2)}}
.dots{{display:flex;gap:5px;justify-content:center;padding:6px 0 0}}
.dots i{{width:7px;height:7px;border-radius:50%;background:var(--suave);
opacity:.45;cursor:pointer}}
.dots i.on{{opacity:1;background:var(--marca)}}
.fs.multi img{{cursor:pointer}}
.fw{{position:relative}}
.nav{{position:absolute;top:50%;transform:translateY(-50%);width:32px;
height:32px;border-radius:50%;border:0;background:rgba(255,255,255,.92);
color:#333;font-size:20px;line-height:1;display:flex;align-items:center;
justify-content:center;cursor:pointer;z-index:2;
box-shadow:0 1px 5px rgba(0,0,0,.25);opacity:0;transition:opacity .15s}}
.prev{{left:8px}}.next{{right:8px}}
.fw:hover .nav{{opacity:1}}
@media(pointer:coarse){{.nav{{opacity:.7;width:28px;height:28px}}}}
.cnt{{position:absolute;top:8px;right:8px;background:rgba(0,0,0,.45);
color:#fff;font-size:.68rem;font-weight:600;padding:2px 8px;
border-radius:10px;z-index:2}}
.tx{{padding:9px 12px 4px;flex:1}}
.n{{font-size:.84rem;line-height:1.25;font-weight:500;min-height:2.1em}}
.p{{font-size:1.02rem;font-weight:800;color:var(--verde);margin-top:4px}}
.s{{font-size:.68rem;color:var(--suave);margin-top:2px}}
.btn{{display:block;text-align:center;text-decoration:none;font-weight:700;
font-size:.9rem;color:#fff;background:var(--marca);margin:9px 12px 12px;
padding:10px 0;border-radius:12px}}
.btn:active{{transform:scale(.97)}}
</style></head><body>
<header><a href='/tienda' style='color:#fff;text-decoration:none'><h1>Shopping Asia 🛍️</h1></a><div class='sub'>{_html.escape(titulo)} · {len(items)} resultado{"s" if len(items) != 1 else ""}</div>
<form class='bsc' action='/buscar' method='get'>
<input name='q' type='search' placeholder='Buscá un producto...' value='{_html.escape(query)}'>
<select name='cat'><option value=''>Todas las categorías</option>{_opciones_cat(cat)}</select>
<button type='submit'>Buscar</button></form></header>
<div class='nota'>{_html.escape(nota)} Si un modelo tiene varias fotos, deslizá sobre la imagen.</div>
<div class='g'>{"".join(tarjetas)}</div>{extra_abajo}
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
    from . import catalogo_chico as _chi2
    _con_foto = [x for x in items
                 if x.get("imagenes") or _esp2.n_sync(x.get("sku"))
                 or _chi2.foto_sync(x.get("sku"))]
    if len(_con_foto) >= 2:
        items = _con_foto
    if not items:
        return HTMLResponse(
            "<h3>No encontramos resultados para esa búsqueda.</h3>",
            status_code=404)
    _tit = f"“{termino}”" + (f" en {cat}" if cat else "")
    return await _pagina_catalogo(
        items, _tit,
        "Tocá \"Hacer pedido\" en el que te guste y volvés al chat con "
        "todos los datos para concretar al toque.",
        query=termino, cat=cat)


# ── TIENDA PROVISORIA (31/08: la página oficial está caída; esta es la
# "página" que se pasa a los clientes: catálogo completo + categorías +
# buscador propio con filtro opcional) ──────────────────────────────────────
@app.get("/tienda")
async def tienda_portada():
    import html as _h

    from . import productos as _prod
    from . import tienda as _td
    idx = _prod.indice_actual()
    if not idx:
        return HTMLResponse("<h3>Catálogo cargando, probá en unos segundos."
                            "</h3>", status_code=503)
    cts = _td.conteos(idx)
    fichas = "".join(
        f'<a class="catf" href="/cat/{_h.escape(c)}"><b>{_h.escape(c)}</b>'
        f'<span>{n} productos</span></a>'
        for c, n in cts.items() if n)
    pagina = await _pagina_catalogo([], "", "")
    # portada: sin tarjetas; inyectamos las categorías en lugar de la grilla
    cuerpo = (f"<div class='nota'>Bienvenido/a a nuestra tienda 🛍️ Buscá "
              f"arriba lo que necesités (podés elegir una categoría para "
              f"afinar) o navegá por secciones:</div>"
              f"<div class='cats'>{fichas}</div>")
    h = pagina.body.decode("utf-8")
    import re as _re3
    h = _re3.sub(r"<div class='nota'>.*?</div>", "", h, count=1, flags=_re3.S)
    h = h.replace("<div class='g'></div>", cuerpo)
    h = h.replace(" ·\xa00 resultados", "").replace(" · 0 resultados", "")
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
        "Tocá \"Hacer pedido\" en el que te guste y volvés al chat con "
        "todos los datos.", cat=categoria, extra_abajo=nav)
    return r


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
