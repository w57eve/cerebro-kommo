# -*- coding: utf-8 -*-
"""
Búsqueda de precio / nombre / foto de productos, usando SOLO datos públicos del
sitio (endpoint get-productos). Nunca usa el panel de PORTA ni credenciales.

Estrategia eficiente: baja los productos de las categorías configuradas una vez
y los mantiene en memoria, refrescando cada REFRESCO_MIN minutos. Después las
búsquedas por SKU o por nombre son instantáneas y no pegan al sitio en cada
mensaje.

NOTA para verificar en vivo: los nombres de campos del JSON (precio, nombre)
pueden variar. Acá se leen de forma defensiva probando varios nombres comunes.
Si algo no viene, se deja vacío y el agente deriva en vez de inventar.
"""

import asyncio
import re
import time

import httpx

from .config import cfg

_cache = {"ts": 0.0, "por_sku": {}, "items": []}
_lock = asyncio.Lock()


def _precio(p: dict):
    for k in ("precio", "precio_venta", "precio_final", "precio_oferta", "monto"):
        v = p.get(k)
        if v not in (None, "", 0, "0"):
            return v
    return None


def _nombre(p: dict) -> str:
    for k in ("nombre", "descripcion", "titulo", "articulo", "detalle"):
        v = p.get(k)
        if v:
            return str(v)
    return ""


def _imagenes(p: dict):
    imgs = []
    for i in (p.get("imagenes") or []):
        u = i.get("ubicacion") or i.get("url") or i.get("src") if isinstance(i, dict) else i
        if u:
            imgs.append(u)
    return imgs[:3]  # tope de 3 ángulos (igual criterio que el verificador)


async def _descargar():
    por_sku, items = {}, []
    cats = [c.strip() for c in cfg.CATEGORIAS.split(",") if c.strip()]
    async with httpx.AsyncClient(timeout=25, headers={"User-Agent": "cerebro-shoppingasia"}) as cli:
        for cat in cats:
            page = 1
            while page <= 200:
                url = (
                    f"{cfg.GET_PRODUCTOS}?page={page}&categoria={cat}"
                    "&precio=0&ordenar_por=2&marcas=&categorias="
                    "&categorias_top=&porcentajes=&atributos="
                )
                try:
                    r = await cli.get(url)
                    if r.status_code != 200:
                        break
                    data = r.json()
                except Exception:
                    break
                lote = ((data.get("paginacion") or {}).get("data")) or []
                if not lote:
                    break
                for p in lote:
                    sku = str(p.get("codigo_articulo") or p.get("sku") or "").strip()
                    if not sku:
                        continue
                    it = {
                        "sku": sku,
                        "nombre": _nombre(p),
                        "precio": _precio(p),
                        "imagenes": _imagenes(p),
                    }
                    por_sku[sku] = it
                    items.append(it)
                page += 1
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
            pass  # si falla la descarga, seguimos con lo que haya (o vacío)


def extraer_sku(texto: str):
    """SKU de Shopping Asia: EAN que empieza con 7457006 + 6 dígitos. Si no hay,
    intenta con cualquier número largo (8+ dígitos)."""
    m = re.search(r"7457006\d{6}", texto or "")
    if m:
        return m.group(0)
    m = re.search(r"\b\d{8,}\b", texto or "")
    return m.group(0) if m else None


async def por_sku(sku: str):
    await _asegurar()
    return _cache["por_sku"].get(str(sku).strip())


async def buscar(texto: str, limite: int = 3):
    """Búsqueda simple por coincidencia de palabras en el nombre. Devuelve hasta
    'limite' candidatos ordenados por cuántas palabras coinciden."""
    await _asegurar()
    toks = [w for w in re.findall(r"\w+", (texto or "").lower()) if len(w) > 2]
    if not toks:
        return []
    res = []
    for it in _cache["items"]:
        n = (it["nombre"] or "").lower()
        score = sum(1 for w in toks if w in n)
        if score:
            res.append((score, it))
    res.sort(key=lambda x: -x[0])
    return [it for _, it in res[:limite]]


def a_texto(it: dict) -> str:
    precio = f"{it['precio']}" if it.get("precio") not in (None, "") else "consultar"
    linea = f"- SKU {it['sku']}: {it['nombre'] or 'producto'} | precio: {precio}"
    if it.get("imagenes"):
        linea += f" | foto: {it['imagenes'][0]}"
    return linea
