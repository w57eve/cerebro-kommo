# -*- coding: utf-8 -*-
"""
Catálogo de productos del cerebro.

Fuente: el catálogo COMPLETO de Shopping Asia, que la app de precios ya publica
(nombre + precio + foto de cada producto, sincronizado desde PORTA y expuesto de
forma pública). Se lee de un único archivo consolidado:

    https://precios.shoppingasia.com.py/datos/_catalogo.json
    formato: { "SKU": ["NOMBRE", precio, "URL_FOTO"], ... }

Nunca usa el panel de PORTA ni credenciales: son datos ya públicos.

Estrategia: se baja el catálogo una vez y se mantiene en memoria, refrescando
cada REFRESCO_MIN minutos. Las búsquedas por SKU o por nombre son instantáneas.
"""

import asyncio
import re
import time

import httpx

from .config import cfg

_cache = {"ts": 0.0, "por_sku": {}, "items": []}
_lock = asyncio.Lock()


def _norm(t: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFD", t or "")
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return t.lower()


async def _descargar():
    """Baja el catálogo consolidado (o lo lee de un archivo local si la URL es
    una ruta). Devuelve (por_sku, items)."""
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
        nombre = v[0] or ""
        precio = v[1] if len(v) > 1 else None
        foto = v[2] if len(v) > 2 else ""
        it = {
            "sku": str(sku),
            "nombre": nombre,
            "precio": precio,
            "imagenes": [foto] if foto and "placeholder" not in str(foto) else [],
            "_n": _norm(nombre),
        }
        por_sku[str(sku)] = it
        items.append(it)
    return por_sku, items


async def _asegurar():
    vencido = (time.time() - _cache["ts"]) > cfg.REFRESCO_MIN * 60
    if _cache["por_sku"] and not vencido:
        return
    async with _lock:
        vencido = (time.time() - _cache["ts"]) > cfg.REFRESCO_MIN * 60
        if _cache["por_sku"] and not vencido:
            return
        try:
            por_sku, items = await _descargar()
            if por_sku:
                _cache.update(ts=time.time(), por_sku=por_sku, items=items)
        except Exception:
            pass  # si falla, seguimos con lo que haya (o vacío)


def extraer_sku(texto: str):
    """SKU de Shopping Asia: EAN que empieza con 7457006 + 6 dígitos. Si no hay,
    cualquier número largo (8+ dígitos)."""
    m = re.search(r"7457006\d{6}", texto or "")
    if m:
        return m.group(0)
    m = re.search(r"\b\d{8,}\b", texto or "")
    return m.group(0) if m else None


async def por_sku(sku: str):
    await _asegurar()
    return _cache["por_sku"].get(str(sku).strip())


# Palabras muy comunes que no ayudan a buscar (para no traer miles de resultados).
_STOP = {"para", "con", "los", "las", "una", "unos", "unas", "del", "por", "que",
         "tienen", "tenes", "tenés", "hay", "busco", "quiero", "necesito", "algun",
         "algún", "alguna", "producto", "productos", "precio", "cuanto", "cuánto",
         "sale", "vale", "este", "esta", "esa", "ese", "color", "talle", "tamaño"}


async def buscar(texto: str, limite: int = 4):
    """Búsqueda por nombre. Devuelve hasta 'limite' productos ordenados por
    cuántas palabras (útiles) del pedido aparecen en el nombre. Prefiere los que
    tienen foto."""
    await _asegurar()
    toks = [w for w in re.findall(r"\w+", _norm(texto)) if len(w) > 2 and w not in _STOP]
    if not toks:
        return []
    res = []
    for it in _cache["items"]:
        n = it["_n"]
        score = sum(1 for w in toks if w in n)
        if score:
            # bonus si tiene foto (mejor para mostrar)
            res.append((score, 1 if it["imagenes"] else 0, it))
    if not res:
        return []
    res.sort(key=lambda x: (-x[0], -x[1]))
    top = res[0][0]
    # Solo devolvemos los que igualan el mejor puntaje (los más relevantes).
    fuertes = [it for s, _, it in res if s == top]
    return fuertes[:limite]


def cantidad() -> int:
    return len(_cache["items"])


def a_texto(it: dict) -> str:
    precio = f"{it['precio']}" if it.get("precio") not in (None, "") else "consultar"
    linea = f"- SKU {it['sku']}: {it['nombre'] or 'producto'} | precio: {precio}"
    if it.get("imagenes"):
        linea += f" | foto: {it['imagenes'][0]}"
    return linea
