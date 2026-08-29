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

import base64
import json
import os
import threading
import time
from collections import Counter, deque

RUTA = os.getenv("APRENDIZAJE_RUTA", "/tmp/aprendizaje.jsonl")

_recientes = deque(maxlen=300)
_stats = Counter()
_sin_candidatos = Counter()   # consultas de producto que no matchearon nada
_fallbacks = Counter()        # mensajes que terminaron en "no te seguí"

# ── Persistencia en GitHub (el disco de Render se borra en cada deploy) ──
# Los intercambios se suben en tandas a la rama RAMA del repo (rama separada:
# los push de código del dueño van a main y nunca chocan; Render tampoco
# redespliega por estos commits). Archivo: datos/aprendizaje/AAAA-MM-DD.jsonl.
# Necesita GITHUB_TOKEN en Render (fine-grained, permiso Contents write).
GH_REPO = os.getenv("GITHUB_REPO", "w57eve/cerebro-kommo")
GH_RAMA = os.getenv("GITHUB_RAMA_APRENDIZAJE", "aprendizaje")
_FLUSH_CADA = 10          # subir cada N intercambios...
_FLUSH_SEGUNDOS = 600     # ...o si pasaron 10 min desde la última subida
_pendientes = []          # regs aún no subidos (se reintentan solos)
_lock = threading.Lock()
_gh_estado = {"ultimo_envio": 0, "ultimo_error": "", "subidos": 0}
_ultimo_flush = time.time()


def _gh_headers(token):
    return {"Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "cerebro-kommo"}


def _asegurar_rama(cli, token):
    """Crea la rama de datos si no existe (apuntando a main)."""
    base = f"https://api.github.com/repos/{GH_REPO}"
    r = cli.get(f"{base}/git/ref/heads/{GH_RAMA}", headers=_gh_headers(token))
    if r.status_code == 200:
        return True
    r = cli.get(f"{base}/git/ref/heads/main", headers=_gh_headers(token))
    if r.status_code != 200:
        return False
    sha = r.json()["object"]["sha"]
    r = cli.post(f"{base}/git/refs", headers=_gh_headers(token),
                 json={"ref": f"refs/heads/{GH_RAMA}", "sha": sha})
    return r.status_code in (200, 201, 422)  # 422: la creó otro proceso


def subir_ahora(cli=None) -> str:
    """Sube los pendientes al repo. Devuelve '' si ok o el motivo si no.
    `cli` inyectable para tests (objeto con .get/.put/.post estilo httpx)."""
    token = (os.getenv("GITHUB_TOKEN", "") or "").strip()
    if not token:
        return "sin GITHUB_TOKEN"
    with _lock:
        tanda = list(_pendientes)
    if not tanda:
        return ""
    propio = cli is None
    if propio:
        import httpx
        cli = httpx.Client(timeout=15)
    try:
        if not _asegurar_rama(cli, token):
            _gh_estado["ultimo_error"] = "no pude asegurar la rama"
            return "rama"
        dia = time.strftime("%Y-%m-%d", time.gmtime())
        path = f"datos/aprendizaje/{dia}.jsonl"
        url = f"https://api.github.com/repos/{GH_REPO}/contents/{path}"
        nuevas = "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in tanda)
        for _intento in (1, 2):   # reintento simple si hay conflicto de sha
            r = cli.get(url + f"?ref={GH_RAMA}", headers=_gh_headers(token))
            sha, previo = None, ""
            if r.status_code == 200:
                j = r.json()
                sha = j.get("sha")
                previo = base64.b64decode(j.get("content", "") or "").decode(
                    "utf-8", "replace")
            cuerpo = {
                "message": f"aprendizaje {dia}: +{len(tanda)} intercambios",
                "branch": GH_RAMA,
                "content": base64.b64encode(
                    (previo + nuevas).encode("utf-8")).decode(),
            }
            if sha:
                cuerpo["sha"] = sha
            r = cli.put(url, headers=_gh_headers(token), json=cuerpo)
            if r.status_code in (200, 201):
                with _lock:
                    del _pendientes[:len(tanda)]
                _gh_estado.update(ultimo_envio=int(time.time()),
                                  ultimo_error="")
                _gh_estado["subidos"] += len(tanda)
                return ""
            if r.status_code != 409:   # 409: otro proceso tocó el archivo
                break
        _gh_estado["ultimo_error"] = f"HTTP {r.status_code}"
        return f"HTTP {r.status_code}"
    except Exception as e:
        _gh_estado["ultimo_error"] = str(e)[:120]
        return str(e)[:120]
    finally:
        if propio:
            cli.close()


def _flush_si_toca():
    global _ultimo_flush
    ahora = time.time()
    if len(_pendientes) >= _FLUSH_CADA or (
            _pendientes and ahora - _ultimo_flush > _FLUSH_SEGUNDOS):
        _ultimo_flush = ahora
        threading.Thread(target=subir_ahora, daemon=True).start()


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
    with _lock:
        _pendientes.append(reg)
        del _pendientes[:-500]   # tope de seguridad si GitHub falla mucho
    _flush_si_toca()
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
        "github": {**_gh_estado, "pendientes": len(_pendientes),
                   "activo": bool(os.getenv("GITHUB_TOKEN", "").strip())},
        "ultimos": list(_recientes)[-ultimos:],
    }
