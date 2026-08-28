# -*- coding: utf-8 -*-
"""
Catálogo de productos del cerebro.

Fuente: el catálogo COMPLETO de Shopping Asia que publica la app de precios
(nombre + precio + foto, sincronizado desde PORTA y expuesto de forma pública):

    https://precios.shoppingasia.com.py/datos/_catalogo.json
    formato: { "SKU": ["NOMBRE", precio, "URL_FOTO"], ... }

Nunca usa el panel de PORTA ni credenciales: son datos ya públicos.

La BÚSQUEDA la hace el motor de app/busqueda.py (BM25 + sinónimos + tipeo).
Acá se baja el catálogo, se mantiene en memoria y se arma el índice.
"""

import asyncio
import html
import re
import time

import httpx

from . import busqueda
from .config import cfg

_cache = {"ts": 0.0, "por_sku": {}, "items": [], "indice": None}
_lock = asyncio.Lock()


async def _descargar():
    url = cfg.CATALOGO_JSON_URL
    if url.startswith("http"):
        async with httpx.AsyncClient(
            timeout=60, headers={"User-Agent": "cerebro-shoppingasia"}
        ) as cli:
            r = await cli.get(url)
            r.raise_for_status()
            data = r.json()
    else:  # ruta local (para pruebas)
        import json
        from pathlib import Path
        data = json.loads(Path(url).read_text(encoding="utf-8"))

    por_sku, items = {}, []
    for sku, v in data.items():
        if not isinstance(v, list) or not v:
            continue
        nombre = html.unescape(v[0] or "").strip()   # &#039; -> ' , &quot; -> "
        # Formato del catalogo:
        #   NUEVO (4): [nombre, precio_retail, precio_oferta, foto]
        #   viejo (3): [nombre, precio, foto]
        if len(v) >= 4:
            retail, oferta, foto = v[1], v[2], v[3]
            precio = retail
            try:
                if oferta and 0 < float(oferta) < float(retail):
                    precio = oferta   # si hay oferta valida, se usa la oferta
            except Exception:
                pass
        else:
            precio = v[1] if len(v) > 1 else None
            foto = v[2] if len(v) > 2 else ""
        it = {
            "sku": str(sku),
            "nombre": nombre,
            "precio": precio,
            "imagenes": [foto] if foto and "placeholder" not in str(foto) else [],
        }
        por_sku[str(sku)] = it
        items.append(it)
    return por_sku, items


async def _asegurar():
    vencido = (time.time() - _cache["ts"]) > cfg.REFRESCO_MIN * 60
    if _cache["indice"] is not None and not vencido:
        return
    async with _lock:
        vencido = (time.time() - _cache["ts"]) > cfg.REFRESCO_MIN * 60
        if _cache["indice"] is not None and not vencido:
            return
        try:
            por_sku, items = await _descargar()
            if por_sku:
                indice = busqueda.Indice(items)   # arma el índice invertido/BM25
                _cache.update(ts=time.time(), por_sku=por_sku,
                              items=items, indice=indice)
        except Exception:
            pass  # si falla, seguimos con lo que haya (o vacío)


def extraer_sku(texto: str):
    """SKU de Shopping Asia: EAN 7457006 + 6 dígitos; si no, número largo (8+)."""
    m = re.search(r"7457006\d{6}", texto or "")
    if m:
        return m.group(0)
    m = re.search(r"\b\d{8,}\b", texto or "")
    return m.group(0) if m else None


async def por_sku(sku: str):
    await _asegurar()
    return _cache["por_sku"].get(str(sku).strip())


async def buscar(texto: str, limite: int = 4):
    await _asegurar()
    idx = _cache["indice"]
    return idx.buscar(texto, limite) if idx else []


def cantidad() -> int:
    return len(_cache["items"])


def indice_actual():
    """El índice de búsqueda vivo (o None si todavía no cargó el catálogo)."""
    return _cache["indice"]


import os as _os

# Base pública del cerebro: sirve las fotos OPTIMIZADAS (miniaturas rápidas)
# en /foto/<sku>.jpg — la preview de WhatsApp carga al instante.
FOTO_BASE = (_os.getenv("FOTO_BASE", "https://cerebro-kommo.onrender.com")
             or "").rstrip("/")


def foto_url(it: dict) -> str:
    """Link de foto que se le pasa al cliente: la miniatura rápida del cerebro."""
    if it.get("imagenes"):
        return f"{FOTO_BASE}/foto/{it['sku']}.jpg"
    return ""


def precio_texto(it: dict) -> str:
    """Precio YA formateado (ej. '240.000 gs') para que el LLM lo copie tal
    cual y no lo recalcule (recalculando mezclaba/erraba precios)."""
    p = it.get("precio")
    if p in (None, "", 0):
        return "consultar"
    try:
        return f"{int(float(p)):,} gs".replace(",", ".")
    except Exception:
        return f"{p} gs"


def a_texto(it: dict) -> str:
    precio = precio_texto(it)
    linea = f"- SKU {it['sku']}: {it['nombre'] or 'producto'} | precio: {precio}"
    f = foto_url(it)
    if f:
        linea += f" | foto: {f}"
    return linea
