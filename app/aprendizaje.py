# -*- coding: utf-8 -*-
"""
Registro de aprendizaje del agente.

Cada intercambio (pregunta del cliente + respuesta del agente) queda registrado
con señales de calidad: ¿encontró productos?, ¿derivó?, ¿cayó en el fallback
"no te seguí"? Con eso:

- /aprendizaje muestra el resumen: totales, tasa de fallback/derivación y el
  TOP de consultas que quedaron SIN respuesta útil (la materia prima para
  crear reglas nuevas, sinónimos y entradas de la base de conocimiento).
- El archivo JSONL guarda el detalle para revisarlo periódicamente y convertir
  los hallazgos en mejoras (ese es el ciclo real de aprendizaje).

Nota Render: el disco es efímero (se borra en cada deploy). El registro en
memoria + descarga periódica por /aprendizaje alcanza para el ciclo de mejora;
si más adelante hace falta historial largo, se persiste afuera (repo/S3).
"""

import json
import os
import time
from collections import Counter, deque

RUTA = os.getenv("APRENDIZAJE_RUTA", "/tmp/aprendizaje.jsonl")

_recientes = deque(maxlen=300)
_stats = Counter()
_sin_candidatos = Counter()   # consultas de producto que no matchearon nada
_fallbacks = Counter()        # mensajes que terminaron en "no te seguí"


def registrar(lead_id, pregunta: str, respuesta: str, derivar: bool,
              candidatos) -> None:
    reg = {
        "ts": int(time.time()),
        "lead": str(lead_id or ""),
        "pregunta": (pregunta or "")[:400],
        "respuesta": (respuesta or "")[:400],
        "derivar": bool(derivar),
        "candidatos": candidatos if candidatos is not None else -1,
    }
    _stats["mensajes"] += 1
    if derivar:
        _stats["derivados"] += 1
    r = (respuesta or "").lower()
    if "no te segu" in r:  # el FALLBACK del agente
        _stats["fallbacks"] += 1
        reg["fallback"] = True
        _fallbacks[(pregunta or "").lower().strip()[:80]] += 1
    if candidatos == 0 and not derivar:
        _stats["sin_candidatos"] += 1
        _sin_candidatos[(pregunta or "").lower().strip()[:80]] += 1
    _recientes.append(reg)
    try:
        with open(RUTA, "a", encoding="utf-8") as f:
            f.write(json.dumps(reg, ensure_ascii=False) + "\n")
    except Exception:
        pass


def resumen(ultimos: int = 50) -> dict:
    total = _stats.get("mensajes", 0) or 1
    return {
        "stats": dict(_stats),
        "tasa_fallback": round(_stats.get("fallbacks", 0) / total, 3),
        "tasa_derivacion": round(_stats.get("derivados", 0) / total, 3),
        "consultas_sin_candidatos_top": _sin_candidatos.most_common(20),
        "fallbacks_top": _fallbacks.most_common(20),
        "ultimos": list(_recientes)[-ultimos:],
    }
