# -*- coding: utf-8 -*-
"""
Índice del ESPEJO DE FOTOS en GitHub Pages (repo "fotos").

El espejo publica hasta 4 fotos por SKU (<sku>.jpg, <sku>_2.jpg ...) y un
indice.json {sku: cantidad}. Con esto el catálogo dinámico sabe cuántas
fotos deslizables mostrar por producto, y /foto sabe si existe la i-ésima.
"""

import os
import time

import httpx

URL_BASE = os.getenv("ESPEJO_FOTOS_URL", "https://w57eve.github.io/fotos")

_cache = {"ts": 0.0, "n": {}}


async def _asegurar():
    # con índice: refresco cada 1 h; sin índice (falló): reintento a los
    # 10 min — NUNCA en cada llamada (martillaba a GitHub por cada foto)
    _espera = 3600 if _cache["n"] else 600
    if _cache["ts"] and time.time() - _cache["ts"] < _espera:
        return
    try:
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get(f"{URL_BASE}/indice.json",
                              headers={"User-Agent": "cerebro"})
            r.raise_for_status()
            j = r.json()
        if isinstance(j, dict) and j:
            _cache.update(ts=time.time(), n={str(k): int(v)
                                             for k, v in j.items()})
            print(f"[ESPEJO] índice de fotos: {len(j)} SKUs", flush=True)
    except Exception as e:
        print(f"[ESPEJO] índice no disponible: {e}", flush=True)
        _cache["ts"] = time.time()   # reintenta en ~10 min


async def cantidad(sku) -> int:
    """Cuántas fotos tiene el SKU en el espejo (0 si no está)."""
    await _asegurar()
    return _cache["n"].get(str(sku or "").strip(), 0)


def n_sync(sku) -> int:
    """Cantidad en el espejo SIN red (usa el cache ya cargado; 0 si vacío)."""
    return _cache["n"].get(str(sku or "").strip(), 0)


def url_foto(sku, i: int = 0) -> str:
    """URL de la i-ésima foto del espejo (i=0 es la principal)."""
    sku = str(sku or "").strip()
    return (f"{URL_BASE}/{sku}.jpg" if i == 0
            else f"{URL_BASE}/{sku}_{i + 1}.jpg")
