# -*- coding: utf-8 -*-
"""
Índice del CATÁLOGO RÁPIDO (catalogo.shoppingasia.com.py) por SKU.

Fuente: https://catalogo.shoppingasia.com.py/datos/catalogo.json
(categorías -> items -> sku). Con esto el agente sabe con EXACTITUD qué
productos están publicados en el catálogo chico — hoy calzados, y cuando se
publiquen más rubros (ropa, maquillaje...) los reconoce solo, sin tocar código.
"""

import os
import time

import httpx

URL = os.getenv("CATALOGO_CHICO_URL",
                "https://catalogo.shoppingasia.com.py/datos/catalogo.json")

_cache = {"ts": 0.0, "por_sku": {}, "categorias": []}


async def _asegurar():
    if _cache["por_sku"] and time.time() - _cache["ts"] < 3600:
        return
    try:
        async with httpx.AsyncClient(timeout=20) as cli:
            r = await cli.get(URL, headers={"User-Agent": "cerebro"})
            r.raise_for_status()
            j = r.json()
        por_sku, cats = {}, []
        for cat in j.get("categorias", []):
            nombre = (cat.get("nombre") or "").strip()
            if nombre:
                cats.append(nombre)
            for it in cat.get("items", []):
                sku = str(it.get("sku") or "").strip()
                if sku:
                    por_sku.setdefault(sku, nombre)
        if por_sku:
            _cache.update(ts=time.time(), por_sku=por_sku, categorias=cats)
            print(f"[CHICO] catálogo rápido: {len(por_sku)} SKUs en "
                  f"{len(cats)} categorías: {', '.join(cats)}", flush=True)
    except Exception as e:
        print(f"[CHICO] no se pudo cargar: {e}", flush=True)
        _cache["ts"] = time.time() - 3000   # reintenta en ~10 min


async def categoria_de(sku) -> str:
    """Nombre de la sección del catálogo rápido donde está el SKU, o ""."""
    await _asegurar()
    return _cache["por_sku"].get(str(sku or "").strip(), "")


async def categorias() -> list:
    await _asegurar()
    return list(_cache["categorias"])


def cantidad() -> int:
    return len(_cache["por_sku"])
