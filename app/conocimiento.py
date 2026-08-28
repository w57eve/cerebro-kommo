# -*- coding: utf-8 -*-
"""
Carga la base de conocimiento (base-conocimiento.md) y el mapa de anuncios de
Meta (mapa-anuncios.md). Con eso se arma el "system prompt" del agente y se sabe
de qué habla una conversación que entró desde una publicidad.
"""

from pathlib import Path

DATOS = Path(__file__).resolve().parent.parent / "datos"


def cargar_base() -> str:
    p = DATOS / "base-conocimiento.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def cargar_anuncios() -> dict:
    """Devuelve {id_anuncio: {representa, tipo, sku, alcance}} leyendo la tabla
    markdown. Es tolerante al formato (viejo de 4 columnas o nuevo de 6)."""
    p = DATOS / "mapa-anuncios.md"
    mapa = {}
    if not p.exists():
        return mapa
    for linea in p.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea.startswith("|"):
            continue
        cols = [c.strip() for c in linea.strip("|").split("|")]
        if not cols:
            continue
        clave = cols[0].strip().rstrip("/")
        # clave valida: ID numerico de Meta O la URL de la publicacion
        es_url = ("instagram.com/" in clave or "facebook.com/" in clave
                  or "fb.com/" in clave or clave.startswith("http"))
        if not (clave.isdigit() or es_url):
            continue  # saltea encabezado y separadores
        cols[0] = clave
        # Formato nuevo (6 col): ID | Representa | Tipo | SKU | Alcance | Notas
        # Formato viejo (4 col): ID | Producto | SKU | Notas
        if len(cols) >= 5:
            mapa[cols[0]] = {
                "representa": cols[1],
                "tipo": cols[2],
                "sku": cols[3],
                "alcance": cols[4],
            }
        else:
            mapa[cols[0]] = {
                "representa": cols[1] if len(cols) > 1 else "",
                "tipo": "",
                "sku": cols[2] if len(cols) > 2 else "",
                "alcance": cols[3] if len(cols) > 3 else "",
            }
    return mapa


# Se cargan una vez al iniciar el proceso.
BASE = cargar_base()
ANUNCIOS = cargar_anuncios()


def contexto_anuncio(ad_id: str) -> str:
    """Texto corto para inyectar al LLM según de qué anuncio vino el chat."""
    if not ad_id:
        return ""
    a = ANUNCIOS.get(str(ad_id).strip())
    if not a:
        return ""
    partes = [f"La conversación entró desde la publicidad '{a['representa']}'"]
    if a.get("tipo"):
        partes.append(f"(tipo: {a['tipo']})")
    if a.get("sku") and a["sku"] not in ("", "—", "-"):
        partes.append(f". SKU(s) del anuncio: {a['sku']}")
    if a.get("alcance"):
        partes.append(f". Enfoque: {a['alcance']}")
    partes.append(
        ". IMPORTANTE: el cliente YA vio ese anuncio; NO preguntes en genérico "
        "'¿qué estás buscando?'. Saludá y arrancá DIRECTO con ese producto/"
        "sección (precio, opciones, talle/color si aplica; si es calzado de "
        "pauta, aplicá el flujo de horma chica + catálogo)."
    )
    return " ".join(partes)
