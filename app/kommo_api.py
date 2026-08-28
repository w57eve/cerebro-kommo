# -*- coding: utf-8 -*-
"""
Capa de entrega v2 — API oficial de Kommo (sin widget_request).

Cómo entrega la respuesta (mensaje ÚNICO, largo y natural, sin límite de 80):
1. Escribe el texto en un campo del lead ("Respuesta bot", se crea solo).
2. Lanza por API un Salesbot mínimo de 1 paso que envía {{lead.Respuesta bot}}.

Requiere en Render:
- KOMMO_SUBDOMAIN  (ej. "shoppingasia" o "shoppingasia.kommo.com")
- KOMMO_API_TOKEN  (token de larga duración; si falta usa KOMMO_TOKEN)
- KOMMO_BOT_ID     (id del bot de 1 paso; está en la URL del constructor)
"""

import os
import time

import httpx

from .config import cfg

NOMBRE_CAMPO = os.getenv("KOMMO_FIELD_NOMBRE", "Respuesta bot")

_cache = {"campo_id": 0, "nombres": {}}  # nombres: contact_id -> nombre


def _token() -> str:
    return (os.getenv("KOMMO_API_TOKEN", "") or cfg.KOMMO_TOKEN or "").strip()


def _base() -> str:
    sub = (cfg.KOMMO_SUBDOMAIN or "").strip().rstrip("/")
    if not sub:
        return ""
    if "." not in sub:
        sub += ".kommo.com"
    if not sub.startswith("http"):
        sub = "https://" + sub
    return sub


def _headers() -> dict:
    return {"Authorization": f"Bearer {_token()}",
            "Content-Type": "application/json"}


def listo() -> bool:
    return bool(_base() and _token())


def bot_id() -> int:
    try:
        return int((os.getenv("KOMMO_BOT_ID", "") or "0").strip())
    except Exception:
        return 0


async def _campo_id(cli: httpx.AsyncClient) -> int:
    """ID del campo de texto del lead donde va la respuesta. Orden:
    env KOMMO_FIELD_ID -> buscarlo por nombre -> crearlo (tipo textarea)."""
    fijo = (os.getenv("KOMMO_FIELD_ID", "") or "").strip()
    if fijo:
        try:
            return int(fijo)
        except Exception:
            pass
    if _cache["campo_id"]:
        return _cache["campo_id"]

    url = f"{_base()}/api/v4/leads/custom_fields"
    pagina = url + "?limit=250"
    objetivo = NOMBRE_CAMPO.strip().lower()
    while pagina:
        r = await cli.get(pagina, headers=_headers())
        if r.status_code != 200:
            print(f"[API] listar campos -> HTTP {r.status_code} {r.text[:200]!r}", flush=True)
            break
        j = r.json()
        for f in (j.get("_embedded", {}).get("custom_fields") or []):
            if (f.get("name") or "").strip().lower() == objetivo:
                _cache["campo_id"] = int(f["id"])
                print(f"[API] campo '{NOMBRE_CAMPO}' encontrado id={_cache['campo_id']}", flush=True)
                return _cache["campo_id"]
        pagina = (j.get("_links", {}).get("next", {}) or {}).get("href")

    # No existe -> lo creamos (textarea = texto largo, no 255c)
    r = await cli.post(url, headers=_headers(),
                       json=[{"name": NOMBRE_CAMPO, "type": "textarea"}])
    if r.status_code in (200, 201):
        j = r.json()
        campos = j.get("_embedded", {}).get("custom_fields") or []
        if campos:
            _cache["campo_id"] = int(campos[0]["id"])
            print(f"[API] campo '{NOMBRE_CAMPO}' CREADO id={_cache['campo_id']}", flush=True)
            return _cache["campo_id"]
    print(f"[API] crear campo -> HTTP {r.status_code} {r.text[:200]!r}", flush=True)
    return 0


async def asegurar_campo() -> int:
    """Se llama al arrancar el server: garantiza que el campo exista para que
    se pueda elegir en el constructor del bot."""
    if not listo():
        return 0
    try:
        async with httpx.AsyncClient(timeout=20) as cli:
            return await _campo_id(cli)
    except Exception as e:
        print(f"[API] asegurar_campo ERROR: {e}", flush=True)
        return 0


async def nombre_contacto(contact_id) -> str:
    """Nombre del contacto (para saludar por nombre). Best-effort, con caché."""
    if not (contact_id and listo()):
        return ""
    cid = str(contact_id)
    if cid in _cache["nombres"]:
        return _cache["nombres"][cid]
    try:
        async with httpx.AsyncClient(timeout=10) as cli:
            r = await cli.get(f"{_base()}/api/v4/contacts/{cid}", headers=_headers())
            nombre = (r.json().get("name") or "") if r.status_code == 200 else ""
    except Exception:
        nombre = ""
    _cache["nombres"][cid] = nombre
    if len(_cache["nombres"]) > 2000:
        _cache["nombres"].clear()
    return nombre


async def entregar(lead_id, texto: str) -> bool:
    """Escribe la respuesta en el campo del lead y lanza el bot que la envía."""
    if not (lead_id and texto):
        return False
    if not listo():
        print("[API] falta KOMMO_SUBDOMAIN o el token; no puedo entregar.", flush=True)
        return False
    bid = bot_id()
    if not bid:
        print("[API] falta KOMMO_BOT_ID; no puedo lanzar el bot.", flush=True)
        return False
    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=20) as cli:
            campo = await _campo_id(cli)
            if not campo:
                return False
            r1 = await cli.patch(
                f"{_base()}/api/v4/leads/{lead_id}", headers=_headers(),
                json={"custom_fields_values": [
                    {"field_id": campo, "values": [{"value": texto}]}]})
            r2 = await cli.post(
                f"{_base()}/api/v4/bots/{bid}/run", headers=_headers(),
                json={"entity_id": int(lead_id), "entity_type": "leads"})
        ok = r1.status_code < 400 and r2.status_code < 400
        print(f"[API] entregar lead={lead_id} campo->HTTP {r1.status_code} "
              f"bot->HTTP {r2.status_code} ({time.time()-t0:.1f}s) "
              f"{'OK' if ok else 'FALLO ' + r1.text[:150] + ' | ' + r2.text[:150]}",
              flush=True)
        return ok
    except Exception as e:
        print(f"[API] entregar ERROR: {e}", flush=True)
        return False


async def diagnostico() -> dict:
    """Para /diag-kommo: estado de token, cuenta, campo y bot."""
    info = {"base": _base(), "token": "si" if _token() else "NO",
            "bot_id": bot_id() or "NO configurado",
            "campo_nombre": NOMBRE_CAMPO}
    if not listo():
        info["error"] = "falta KOMMO_SUBDOMAIN o el token"
        return info
    try:
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(f"{_base()}/api/v4/account", headers=_headers())
            info["cuenta_http"] = r.status_code
            if r.status_code == 200:
                info["cuenta"] = r.json().get("name")
            else:
                info["cuenta_error"] = r.text[:200]
            info["campo_id"] = await _campo_id(cli)
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {e}"
    return info
