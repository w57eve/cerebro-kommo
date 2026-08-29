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
    # Pregunta GENERAL por ofertas (viene de una publicación): confirmar y
    # preguntar qué artículo vio, NUNCA tirar resultados del buscador.
    ok_gen = all(
        (x := reglas.responder(q)) and "oferta" in x["texto"].lower()
        and "interesa" in x["texto"].lower()
        for q in ["hola tienen ofertas?", "que ofertas tienen", "ofertas",
                  "hay ofertas?", "tienen alguna oferta?",
                  "¿Pueden enviarme más información sobre la oferta?"])
    check("oferta general confirma y pregunta articulo (29/08)", ok_gen)
    # Con artículo nombrado NO matchea la regla: sigue al buscador normal.
    check("oferta con articulo va al buscador (29/08)",
          reglas.responder("ofertas de calzado") is None
          and reglas.responder("tienen ofertas en notebooks?") is None)

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
    # "Me pasan fotos de las opciones": pide fotos de lo YA mostrado; no
    # buscar "fotos" como producto (le ofreció álbumes de fotos a Stanley).
    h_org = [{"cliente": "Organizador para perfumes tienen?",
              "agente": "Sí, tenemos:\n*ORGANIZADOR* — 38.000 gs\n*ORGANIZADOR* — 50.000 gs"}]
    for _q in ["Me pasan fotos de las opciones", "mandame fotos",
               "tenes fotos?", "quiero ver las fotos"]:
        await agente.procesar(_q, historial=h_org)
        check(f"pide fotos sigue el hilo (29/08 Stanley): {_q!r}",
              "pide FOTOS de lo que YA le mostraste" in CTX["ctx"]
              and "ALBUM" not in CTX["ctx"].upper())
    # Producto sin foto queda marcado para que la IA no invente una (29/08)
    check("producto sin foto marcado (29/08)",
          "SIN FOTO en el sistema" in productos.a_texto(
              {"sku": "1", "nombre": "CHAMPION INF", "precio": 240000,
               "imagenes": []})
          and "SIN FOTO" not in productos.a_texto(
              {"sku": "2", "nombre": "X", "precio": 1000,
               "imagenes": ["https://www.shoppingasia.com.py/storage/sku/x.jpg"]}))
    h164 = [{"cliente": "championes?", "agente": "Opciones:\n*CALZADO IRUN 40-44* — 164.000 gs"}]
    await agente.procesar("el de 164", historial=h164)
    check("'el de 164' referencia a la lista (29/08)", "coincide con un PRECIO" in CTX["ctx"])
    # "116.mil" CON PUNTO: es referencia a precio, no búsqueda (29/08 David:
    # buscó "116" y terminó ofreciendo un altavoz y precios inventados)
    h116 = [{"cliente": "el grasep", "agente": "Tenemos:\n*CALZADO IRUN 36-41* — 116.000 gs"}]
    await agente.procesar("116.mil", historial=h116)
    check("'116.mil' con punto es precio, no busqueda (29/08 David)",
          "coincide con un PRECIO" in CTX["ctx"] or "PRECIO como referencia" in CTX["ctx"])
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
    # Si borra TODA la lista, reconstruye con los candidatos reales y no
    # deja el hueco en blanco (29/08 David: "tengo varios modelos:" y nada)
    out = _verificar_precios(
        "Encontré varios modelos:\n*GRASEP CLASICO* — 350.000 gs\n"
        "*GRASEP PREMIUM* — 380.000 gs\n¿Cuál te gustó?",
        [{"sku": "1", "nombre": "CALZADO IRUN 36-41", "precio": 116000},
         {"sku": "2", "nombre": "CALZADO IRUN 36-41", "precio": 116000},
         {"sku": "3", "nombre": "CALZADO IRUN 38-43", "precio": 122000}])
    check("lista borrada se reconstruye con candidatos reales (29/08 David)",
          "116.000" in out and "122.000" in out and "GRASEP" not in out
          and out.count("116.000") == 1 and "\n\n\n" not in out)
    # Precio INVENTADO en texto libre (no en lista) se borra (29/08 David:
    # "rondan entre 320.000 y 380.000 gs" para un calzado de 116.000)
    from app.agente import _verificar_precios_texto
    fuentes = ["catalogo: *CALZADO IRUN 36-41* — 116.000 gs", "116.mil"]
    out = _verificar_precios_texto(
        "Los GRASEP rondan entre *320.000 y 380.000 gs* según modelo. "
        "¿Te referís al de 116 mil? Ese está disponible.", fuentes)
    check("precio inventado en texto libre borrado (29/08 David)",
          "320.000" not in out and "380.000" not in out
          and "116 mil" in out and "disponible" in out)
    out = _verificar_precios_texto("Sale *116.000 gs* y hay stock.", fuentes)
    check("precio legitimo en texto libre se conserva (29/08)",
          "116.000" in out)

    # ── MODELOS DISTINTOS MISMO NOMBRE: una mención + link, sin repetir ──
    _dups = [{"sku": str(i), "nombre": "CALZADO IRUN 38-43", "precio": 122000,
              "imagenes": []} for i in range(3)]
    productos._instalar(_dups + [{"sku": "9", "nombre": "GUANTE",
                                  "precio": 20000, "imagenes": []}])
    async def _web_3(term):
        return 3
    agente._web_conteo = _web_3
    _llm_capturador()
    await agente.procesar("calzado irun")
    check("nombres duplicados: contexto sin repetidos + manda link (29/08)",
          CTX["ctx"].count("CALZADO IRUN 38-43") == 1
          and "MODELOS DISTINTOS" in CTX["ctx"]
          and "buscador?q=" in CTX["ctx"])
    agente._web_conteo = web_off
    preparar()   # restaurar catálogo real para lo que siga

    # ── CONTEXTO ANTE FRASES GENÉRICAS (29/08 noche) ──
    h_champ = [{"cliente": "Champion", "agente": "Tengo estos:\n*CHAMPION INF* — 240.000 gs"}]
    # typo de "sería" es deixis, no producto ("Este ceria" -> peines de CERDAS)
    await agente.procesar("Este ceria", historial=h_champ)
    check("'este ceria' (typo de seria) es deixis (29/08)", "SEÑALANDO" in CTX["ctx"])
    # pedir opciones/info/precios continúa el hilo (caso Juve)
    for _q in ["Pásame las opciones y precio", "quiero mas informacion",
               "dame mas detalles", "precios?"]:
        await agente.procesar(_q, historial=h_champ)
        check(f"continuar el hilo (29/08 Juve): {_q!r}",
              "LO YA HABLADO" in CTX["ctx"])
    # "que llegó recién" = novedades, no LEGO (caso Augusto)
    await agente.procesar("Que llegó recién", historial=h_champ)
    check("'que llego recien' es novedades, no LEGO (29/08 Augusto)",
          "NOVEDADES" in CTX["ctx"] and "LEGO" not in CTX["ctx"].upper())
    # "170000" pegado sin puntos es referencia a precio
    await agente.procesar("170000", historial=h_champ)
    check("'170000' sin puntos es precio (29/08 Juve)",
          "PRECIO como referencia" in CTX["ctx"]
          or "coincide con un PRECIO" in CTX["ctx"])

    # ── "TODO TERRENO" = jerga del anuncio IRUN, no búsqueda literal ──
    # (29/08 Sonia: le listó zapatillas de otra familia y un AUTITO)
    productos._instalar([
        {"sku": "1", "nombre": "Zapatillas Deportivas Todo Terreno para Hombre",
         "precio": 444000, "imagenes": []},
        {"sku": "2", "nombre": "Auto Acrobático con Ruedas Todo Terreno",
         "precio": 22000, "imagenes": []},
        {"sku": "3", "nombre": "CALZADO IRUN 36-41", "precio": 116000,
         "imagenes": []}])
    _llm_capturador()
    r = await agente.procesar("Todo terreno para criatura")
    check("'todo terreno' va por regla de calzados, sin literales (29/08 Sonia)",
          "CONSULTA DE CALZADO" in CTX["ctx"]
          and "Acrobático" not in CTX["ctx"]
          and "Senderismo" not in CTX["ctx"]
          and "catalogo.shoppingasia.com.py" in CTX["ctx"]
          and "OTRO producto" in CTX["ctx"])
    preparar()

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
    check("derivacion NO promete que la vendedora escribe sola (29/08)",
          "escribiendo" not in d["texto"] and "va a escribir" not in d["texto"]
          and "Tocá este enlace" in d["texto"])
    v1 = vendedores.mensaje_derivacion(consulta="x", lead_id="eqA")["vendedor"]
    v2 = vendedores.mensaje_derivacion(consulta="x", lead_id="eqB")["vendedor"]
    v1b = vendedores.mensaje_derivacion(consulta="y", lead_id="eqA")["vendedor"]
    check("rotacion equitativa + pegajosa (28/08)", v1 != v2 and v1 == v1b)

    # ── APRENDIZAJE PERSISTENTE EN GITHUB (29/08) ──
    import base64 as _b64
    import os as _os

    from app import aprendizaje as _ap

    class _Resp:
        def __init__(self, st, js=None):
            self.status_code, self._js = st, js or {}
        def json(self):
            return self._js

    class _GHFake:   # simula la API de GitHub: rama existe, archivo con 1 línea
        def __init__(self):
            self.subido = None
        def get(self, url, **kw):
            if "/git/ref/" in url:
                return _Resp(200, {"object": {"sha": "abc"}})
            previo = _b64.b64encode("{\"viejo\": 1}\n".encode()).decode()
            return _Resp(200, {"sha": "f1", "content": previo})
        def put(self, url, **kw):
            self.subido = _b64.b64decode(kw["json"]["content"]).decode()
            return _Resp(200)
        def post(self, url, **kw):
            return _Resp(201)

    _os.environ.pop("GITHUB_TOKEN", None)
    _ap.registrar("L1", "hola", "buenas", False, 3)
    check("aprendizaje sin token no explota y encola (29/08)",
          _ap.subir_ahora() == "sin GITHUB_TOKEN" and len(_ap._pendientes) >= 1)
    _os.environ["GITHUB_TOKEN"] = "tok-test"
    fake = _GHFake()
    err = _ap.subir_ahora(cli=fake)
    check("aprendizaje sube a github preservando lo previo (29/08)",
          err == "" and fake.subido and fake.subido.startswith("{\"viejo\": 1}")
          and '"hola"' in fake.subido and len(_ap._pendientes) == 0)
    # Restauración de memoria post-deploy desde los JSONL (29/08)
    class _GHMem:
        def get(self, url, **kw):
            r = _Resp(200)
            r.text = ('{"ts": 2, "lead": "77", "pregunta": "azul?", "respuesta": "sí"}\n'
                      '{"ts": 1, "lead": "77", "pregunta": "championes", "respuesta": "IRUN"}\n'
                      '{"ts": 3, "lead": "", "pregunta": "x", "respuesta": "y"}\n')
            return r
    mem = _ap.cargar_memoria(max_dias=1, cli=_GHMem())
    check("memoria post-deploy restaurada y ordenada (29/08)",
          list(mem.keys()) == ["77"] and len(mem["77"]) == 2
          and mem["77"][0]["cliente"] == "championes"
          and mem["77"][1]["agente"] == "sí")
    _os.environ.pop("GITHUB_TOKEN", None)
    check("memoria sin token devuelve vacío (29/08)",
          _ap.cargar_memoria() == {})

    print()
    if FALLOS:
        print(f"❌ {len(FALLOS)} REGRESIONES: {FALLOS}")
        sys.exit(1)
    print("✅ SUITE COMPLETA SIN REGRESIONES")


if __name__ == "__main__":
    asyncio.run(correr())
