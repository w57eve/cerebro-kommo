# -*- coding: utf-8 -*-
"""
MAPA DEL CATÁLOGO — radiografía completa de cómo está cargado el stock.

Filosofía (del dueño, 30/08/2026): "los pasos correctos para hacer un buscador
es ese: saber todo lo que hay y con qué nombres fueron cargados, y a partir de
ahí ya es fácil hacer un súper buscador profesional y exacto".

Genera datos/mapa-catalogo.json con:
- vocabulario completo con frecuencias (las 8.800+ palabras tal cual se usan)
- sustantivos cabeza (primera palabra de cada nombre) con conteos
- abreviaturas de carga detectadas (P/, C/, VDE...)
- palabras de UNA sola aparición (typos de carga probables) con su corrección
  más cercana en el propio vocabulario
- familias detectadas (palabras que conviven para el mismo concepto)

Correr después de cada sincronización grande:  python3 mapear_catalogo.py
El resumen en pantalla dice qué agregarle a la capa de sinónimos/hiperónimos
de app/busqueda.py (_GRUPOS y _HIPER) — ahí vive la precisión del buscador.
"""

import collections
import json
import re
import sys
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).parent
CATALOGO = RAIZ.parent.parent / "verificador-precios/sitio/datos/_catalogo.json"
SALIDA = RAIZ / "datos/mapa-catalogo.json"

sys.path.insert(0, str(RAIZ))
from app import busqueda  # noqa: E402


def norm(s):
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def main():
    g = json.loads(CATALOGO.read_text(encoding="utf-8"))
    nombres = [v[0] for v in g.values()]

    voc = collections.Counter()
    heads = collections.Counter()
    ab = collections.Counter()
    for n in nombres:
        nn = norm(n)
        toks = re.findall(r"[a-záéíóúñü]{2,}", nn)
        for t in toks:
            voc[t] += 1
        if toks:
            heads[toks[0]] += 1
        for m in re.findall(r"\b([a-zA-Z]{1,4})/(?=\s|\w)", n):
            ab[m.upper()] += 1

    # typos de carga probables: palabras únicas con vecina frecuente a 1 letra
    unicas = [w for w, c in voc.items() if c == 1 and len(w) >= 5]
    frecuentes = {w for w, c in voc.items() if c >= 10}
    typos = {}
    por_inicial = collections.defaultdict(list)
    for w in frecuentes:
        por_inicial[w[0]].append(w)
    for w in unicas:
        cerca = [f for f in por_inicial.get(w[0], [])
                 if abs(len(f) - len(w)) <= 1 and busqueda._lev1(w, f)]
        if cerca:
            typos[w] = max(cerca, key=lambda f: voc[f])

    # cobertura de la capa de sinónimos/hiperónimos actual
    cubiertas = set()
    for gr in busqueda._GRUPOS:
        cubiertas |= {norm(x) for x in gr}
    cubiertas |= set(busqueda._HIPER)

    mapa = {
        "productos": len(nombres),
        "palabras_distintas": len(voc),
        "vocabulario": dict(voc.most_common()),
        "cabezas": dict(heads.most_common(300)),
        "abreviaturas": dict(ab.most_common(20)),
        "typos_probables": typos,
        "sinonimos_cubiertos": sorted(cubiertas),
    }
    SALIDA.parent.mkdir(exist_ok=True)
    SALIDA.write_text(json.dumps(mapa, ensure_ascii=False, indent=1),
                      encoding="utf-8")

    print(f"MAPA: {len(nombres)} productos, {len(voc)} palabras distintas")
    print(f"Guardado en {SALIDA}")
    print(f"\nTypos de carga probables detectados: {len(typos)} (muestra):")
    for w, f in list(typos.items())[:12]:
        print(f"  {w!r} -> ¿{f!r}? ({voc[f]} usos)")
    print("\nCabezas top-30 SIN sinónimos/hiperónimos todavía:")
    sin_cubrir = [(w, c) for w, c in heads.most_common(60)
                  if busqueda.singular(w) not in cubiertas][:30]
    print("  " + ", ".join(f"{w}({c})" for w, c in sin_cubrir))
    print("\n(Estas son las candidatas a nuevas familias en _GRUPOS/_HIPER "
          "de app/busqueda.py)")


if __name__ == "__main__":
    main()
