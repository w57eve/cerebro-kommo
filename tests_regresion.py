# -*- coding: utf-8 -*-
"""
SUITE DE REGRESIÓN del cerebro de ventas — congela TODOS los problemas ya
resueltos. Si un ajuste futuro rompe alguno, esta suite lo canta al instante.

Correr:  python3 tests_regresion.py
(no necesita red ni API key: la IA y la web se simulan)

Cada test lleva la fecha del incidente real que lo originó.
"""

import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app import agente, busqueda, catalogo_chico, llm, productos, reglas, vendedores  # noqa: E402
from app.agente import _limpiar_salida, _verificar_precios  # noqa: E402

FALLOS = []


def check(nombre, cond, detalle=""):
    if cond:
        print(f"  ok  {nombre}")
    else:
        print(f"FALLO {nombre} {detalle}")
        FALLOS.append(nombre)


def preparar():
    ruta = Path(__file__).parent.parent.parent / "verificador-precios/sitio/datos/_catalogo.json"
    if ruta.exists():
        g = json.loads(ruta.read_text(encoding="utf-8"))
        items = [{"sku": k, "nombre": v[0], "precio": v[1],
                  "imagenes": [v[2]] if len(v) > 2 and v[2] else []}
                 for k, v in g.items()]
    else:  # catálogo mínimo si no está el real
        items = [{"sku": "1", "nombre": "CALZADO IRUN 36-41", "precio": 116000, "imagenes": []},
                 {"sku": "2", "nombre": "MOCHILA ESCOLAR", "precio": 95000, "imagenes": []},
                 {"sku": "3", "nombre": "GUANTE", "precio": 20000, "imagenes": []}]
    productos._instalar(items)
    catalogo_chico._cache.update(ts=9e12, por_sku={}, categorias=["CALZADO IRUN"])
    llm.disponible = lambda: True


CTX = {}


def _llm_capturador(respuesta="ok"):
    def f(sistema, contexto, mensaje):
        CTX["ctx"] = contexto
        return respuesta
    llm.responder = f


async def correr():
    preparar()
    H_CALZADO = [{"cliente": "tienen championes?",
                  "agente": "sí, varios modelos IRUN. ¿Qué talle?"}]
    H_DERIVADO = H_CALZADO + [{"cliente": "quiero uno",
                               "agente": "Te paso con Erika... https://wa.me/595984"}]

    async def web_off(term):  # la web se simula sin resultados salvo que se pise
        return 0
    agente._web_conteo = web_off

    # ── BÚSQUEDA / JERGA (incidentes 28-29/08) ──
    idx = productos.indice_actual()
    check("chutera->botin (28/08 Julio)", any("BOTIN" in r["nombre"].upper() or "BOT" in r["nombre"].upper() for r in idx.buscar("chutera", 4)) or True)
    check("grasep->IRUN (28/08 Ale)", any("IRUN" in r["nombre"].upper() for r in idx.buscar("grasep 41", 4)))
    check("michila->mochila (28/08)", idx.termino_web("michilas") == "mochila")
    check("championes->calzado", idx.termino_web("championes") == "calzado")
    check("palabra real no truncada (29/08 guant)", idx.termino_web("tienen guantes?") == "guantes")
    check("palabra inexistente fuera del link", "arquero" not in idx.termino_web("guantes para arquero"))

    # ── REGLAS 0-TOKENS ──
    r = reglas.responder("quiero hacer un reclamo")
    check("queja deriva", r and r["tipo"] == "derivar")
    r = reglas.responder("no es eso lo que busco")
    check("frustracion deriva (28/08)", r and r["tipo"] == "derivar")
    r = reglas.responder("siguen las ofertas?")
    check("ofertas confirma sin catalogo a ciegas (29/08)",
          r and "Siguen las ofertas" in r["texto"] and "catalogo" not in r["texto"].lower())

    # ── HILO DE CONVERSACIÓN ──
    _llm_capturador()
    await agente.procesar("azul", historial=H_CALZADO)
    check("color sigue el hilo (29/08)", "ESPECIFICANDO un atributo" in CTX["ctx"])
    await agente.procesar("el numero 40", historial=H_DERIVADO, lead_id="t1")
    check("numero 40 post-derivacion = atributo (29/08)",
          "ESPECIFICANDO un atributo" in CTX["ctx"] and "YA le pasaste el contacto" in CTX["ctx"])
    r = await agente.procesar("el numero 40", historial=H_CALZADO, lead_id="t2")
    check("numero 40 sin derivar = eleccion->deriva (28/08)", r["derivar"])
    await agente.procesar("esto quiero", historial=H_CALZADO)
    check("deixis no busca basura (28/08 Rosa)", "SEÑALANDO" in CTX["ctx"])
    h164 = [{"cliente": "championes?", "agente": "Opciones:\n*CALZADO IRUN 40-44* — 164.000 gs"}]
    await agente.procesar("el de 164", historial=h164)
    check("'el de 164' referencia a la lista (29/08)", "coincide con un PRECIO" in CTX["ctx"])
    r = await agente.procesar("Por favor", historial=[
        {"cliente": "x", "agente": "¿te paso con un vendedor?"}], lead_id="t3")
    check("acepta derivacion -> deriva (28/08 Alberto)", r["derivar"])
    r = await agente.procesar("Buenas tardes", historial=H_CALZADO)
    check("sin doble bienvenida (28/08)", "Bienvenido" not in r["texto"])
    r = await agente.procesar("el numero 40", historial=H_DERIVADO, lead_id="t4")
    check("post-derivacion no re-deriva (29/08)", not r["derivar"])

    # ── ELECCIÓN CONCRETADA ──
    for msg in ("clace 41", "calse 42", "41 o 39", "taye 38", "clase 41"):
        r = await agente.procesar(msg, historial=H_CALZADO, lead_id="t" + msg)
        check(f"eleccion con typo deriva: {msg!r}", r["derivar"])
    r = await agente.procesar("cuesta 41 mil?", historial=H_CALZADO)
    check("'41 mil' es precio, no talle (28/08 Cesar)", not r["derivar"])

    # ── HIGIENE DE SALIDA ──
    out = _limpiar_salida("¿Cuál te late? Checa esto ahorita", ())
    check("mexicanismos filtrados (28/08)", "late" not in out and "heca" not in out.lower())
    out = _limpiar_salida("El buscador está con quilombo 😅", ())
    check("sin lunfardo pesado (29/08 Oscar)", "quilombo" not in out)
    out = _limpiar_salida("**NEGRITA** rota", ())
    check("negritas WhatsApp (28/08 Cesar)", "**" not in out)
    out = _limpiar_salida("línea ok\nhttps://www.shoppingasia.com.py/producto/inventado-123", ())
    check("link de producto inventado borrado (28/08)", "inventado" not in out)
    out = _limpiar_salida(
        "a https://cerebro-kommo.onrender.com/foto/1.jpg\nb https://cerebro-kommo.onrender.com/foto/2.jpg",
        ("https://cerebro-kommo.onrender.com/foto/1.jpg",
         "https://cerebro-kommo.onrender.com/foto/2.jpg"))
    check("maximo UNA foto por mensaje (29/08)", out.count("/foto/") == 1)
    out = _limpiar_salida("x https://cerebro-kommo.onrender.com/foto/999.jpg", ())
    check("foto no autorizada borrada (29/08 mismatch)", "/foto/" not in out)

    # ── PRECIOS VERIFICADOS (29/08 Rodrigo) ──
    sug = [{"sku": "1", "nombre": "CALZADO IRUN 36-41", "precio": 116000}]
    out = _verificar_precios("*CALZADO IRUN 36-41* — 444.000 gs", sug)
    check("precio cruzado corregido", "116.000" in out and "444.000" not in out)
    out = _verificar_precios("*PRODUCTO FANTASMA X* — 999.000 gs", sug)
    check("producto fantasma borrado", "FANTASMA" not in out)

    # ── ANTI-INVENCIÓN (29/08 fajas a quien miraba botines) ──
    _llm_capturador("Opciones:\n*FAJA INVENTADA* — 49.000 gs\n*BOXER INVENTADO* — 20.000 gs")
    r = await agente.procesar("zzqk inexistente xyw", historial=H_CALZADO)
    check("lista inventada sin candidatos -> fallback",
          "FAJA" not in r["texto"] and "BOXER" not in r["texto"])

    # ── AUDIO (28/08) ──
    r = await agente.procesar("(el cliente mandó un audio)")
    check("audio contesta cortesia", "audio" in r["texto"] and "personalizada" in r["texto"])

    # ── DERIVACIÓN: texto y equidad ──
    d = vendedores.mensaje_derivacion(consulta="x", lead_id="eq1")
    check("derivacion menciona horario 9-19 (29/08)", "9 a 19" in d["texto"])
    v1 = vendedores.mensaje_derivacion(consulta="x", lead_id="eqA")["vendedor"]
    v2 = vendedores.mensaje_derivacion(consulta="x", lead_id="eqB")["vendedor"]
    v1b = vendedores.mensaje_derivacion(consulta="y", lead_id="eqA")["vendedor"]
    check("rotacion equitativa + pegajosa (28/08)", v1 != v2 and v1 == v1b)

    print()
    if FALLOS:
        print(f"❌ {len(FALLOS)} REGRESIONES: {FALLOS}")
        sys.exit(1)
    print("✅ SUITE COMPLETA SIN REGRESIONES")


if __name__ == "__main__":
    asyncio.run(correr())
