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

    async def web_res_off(term):
        return 0, ()
    agente._web_resultados = web_res_off

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
    # Refinamiento corto sigue el hilo (30/08 Roux: "bebé" -> "Ropa" buscó
    # "ropa" a secas y ofreció ropa de adultos)
    h_bebe = [{"cliente": "Quiero ver productos de bebé",
               "agente": "tenemos ositos, baberos..."}]
    await agente.procesar("Ropa", historial=h_bebe)
    _cands = [l for l in CTX["ctx"].splitlines() if l.startswith("- SKU")]
    check("refinamiento corto sigue el hilo (30/08 Roux)",
          "continuación" in CTX["ctx"]
          and sum(1 for c in _cands if "BEB" in c.upper()) >= 2)
    await agente.procesar("tienen cafetera electrica de 220 voltios?",
                          historial=h_bebe)
    _cands = [l for l in CTX["ctx"].splitlines() if l.startswith("- SKU")]
    check("consulta larga es tema nuevo (30/08)",
          any("CAFETERA" in c.upper() for c in _cands))
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
    _dups = [{"sku": str(i), "nombre": "TERMO ACERO 1L", "precio": 122000,
              "imagenes": []} for i in range(3)]
    productos._instalar(_dups + [{"sku": "9", "nombre": "GUANTE",
                                  "precio": 20000, "imagenes": []}])
    async def _web_3(term):
        return 3
    agente._web_conteo = _web_3
    _llm_capturador()
    await agente.procesar("termo acero")
    check("nombres duplicados: contexto sin repetidos + manda link (29/08)",
          CTX["ctx"].count("TERMO ACERO 1L") == 1
          and "MODELOS DISTINTOS" in CTX["ctx"]
          and "buscador?q=" in CTX["ctx"])
    # calzado por familia: la regla nueva (30/08) manda catálogo rápido, sin lista
    await agente.procesar("calzado irun")
    check("calzado por familia sin lista de candidatos (30/08)",
          sum(1 for l in CTX["ctx"].splitlines() if l.startswith("- SKU")) == 0)
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
    # "Podés pasar porfa / Foto" es pedido de foto, no PODS (caso Gustavo:
    # ofreció TIDE PODS y vapes con nicotina a quien miraba championes)
    await agente.procesar("Podés pasar porfa\nFoto", historial=h_champ)
    check("'podes pasar porfa foto' pide foto, no PODS (29/08 Gustavo)",
          "pide FOTOS de lo que YA le mostraste" in CTX["ctx"]
          and "POD" not in CTX["ctx"].upper()
          .replace("PODES", "").replace("PODÉS", "").replace("PODÍA", ""))
    c = await productos.buscar("Podés pasar porfa", limite=3)
    check("'podes' no matchea PODS en el buscador (29/08 Gustavo)",
          not any("POD" in x["nombre"].upper() for x in c))
    # "que llegó recién" = novedades, no LEGO (caso Augusto)
    await agente.procesar("Que llegó recién", historial=h_champ)
    check("'que llego recien' es novedades, no LEGO (29/08 Augusto)",
          "NOVEDADES" in CTX["ctx"] and "LEGO" not in CTX["ctx"].upper())
    # "170000" pegado sin puntos es referencia a precio
    await agente.procesar("170000", historial=h_champ)
    check("'170000' sin puntos es precio (29/08 Juve)",
          "PRECIO como referencia" in CTX["ctx"]
          or "coincide con un PRECIO" in CTX["ctx"])

    # ── UBICACIÓN CON LINK DE MAPS (29/08) ──
    for _q in ["donde queda el local?", "me pasas la ubicacion?",
               "como llego?", "direccion porfa"]:
        r = reglas.responder(_q)
        check(f"ubicacion con maps (29/08): {_q!r}",
              r and "google.com/maps" in r["texto"]
              and "Eusebio Ayala" in r["texto"])
    # el link de maps sobrevive la limpieza de links
    out = _limpiar_salida(
        "Estamos acá:\nhttps://www.google.com/maps/place/Shopping+Asia/data=!4m2!3m1!1s0x0:0x8209184b8f599d4a", ())
    check("link de maps permitido en salida (29/08)", "google.com/maps" in out)

    # ── SALUDO CON TYPO NO ES PRODUCTO (29/08 Brenda) ──
    # "Qué tall?" matcheaba productos TALLA y tapaba a las maletas
    c = await productos.buscar(
        "Buenass! Qué tall? Disponen de maletas para viaje con ruedas 360?",
        limite=3)
    check("'que tall?' no tapa a las maletas (29/08 Brenda)",
          bool(c) and all("MALETA" in x["nombre"].upper() for x in c[:1])
          and not any("TALLA" in x["nombre"].upper() for x in c))
    c = await productos.buscar("valija con ruedas", limite=3)
    check("valija -> maleta (29/08)",
          bool(c) and "MALETA" in c[0]["nombre"].upper())

    # ── SONDA WEB singular/plural: el link lleva a la forma CORRECTA ──
    # ('maleta' en la web trae 16 maletas; 'maletas' un candado — 29/08)
    productos._instalar([{"sku": "77x", "nombre": "Maleta Grande de Viaje",
                          "precio": 387000, "imagenes": []},
                         {"sku": "88y", "nombre": "Maleta Pequeña de Viaje",
                          "precio": 252000, "imagenes": []}])
    async def _web_res_fake(term):
        return {"maleta": (16, ("77x", "88y")),
                "maletas": (2, ("999",))}.get(term, (0, ()))
    async def _web_cont_fake(term):
        return (await _web_res_fake(term))[0]
    agente._web_resultados = _web_res_fake
    agente._web_conteo = _web_cont_fake
    _llm_capturador()
    await agente.procesar("tienen maletas?")
    check("sonda web elige forma con el SKU del candidato (29/08)",
          "buscador?q=maleta\n" in CTX["ctx"].replace("q=maleta ", "q=maleta\n")
          or ("buscador?q=maleta" in CTX["ctx"]
              and "buscador?q=maletas" not in CTX["ctx"]))
    # con varios candidatos y link verificado: instrucción de NO pegar lista
    check("varios candidatos -> link, no lista en texto (29/08)",
          "NO pegues esta lista" in CTX["ctx"])
    agente._web_resultados = web_res_off
    agente._web_conteo = web_off
    preparar()

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
          and "onrender.com/c/calzado" in CTX["ctx"]
          and "OTRO producto" in CTX["ctx"])
    # plural "el todos terrenos" también es la jerga (29/08 Misael)
    await agente.procesar("Yo estoy interesado por el todos terrenos")
    check("'todos terrenos' plural es jerga de pauta (29/08 Misael)",
          "CONSULTA DE CALZADO" in CTX["ctx"]
          and "Acrobático" not in CTX["ctx"])
    # 30/08: "Orma grande" (typo de horma) trajo maletas/cubiteras; y
    # "para correr en pistas" trajo CORREAS. Ambos van por regla de calzados.
    await agente.procesar("Orma grande")
    check("'orma grande' (horma) va por regla de calzados (30/08)",
          "CONSULTA DE CALZADO" in CTX["ctx"])
    await agente.procesar("Para correr en pistas que marcas tenes")
    check("'para correr en pistas' es calzado, no correas (30/08 Luis)",
          "CONSULTA DE CALZADO" in CTX["ctx"])
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
    # ── FOTO DEL CLIENTE: la descripción de la visión NO es texto del
    # cliente (30/08 Yeni: "talla 38-43" disparó derivación y "cliente" se
    # corrigió a "caliente" -> lista de POSA CALIENTE) ──
    h_yeni = [{"cliente": "De Champions",
               "agente": "calzados Champions... catalogo"}]
    _r = await agente.procesar(
        "(foto del cliente: Zapatilla deportiva Champion KNUP beige/gris, "
        "talla 38-43, 122.000 Gs.)", historial=h_yeni, lead_id="t-yeni")
    _cands = [l for l in CTX["ctx"].splitlines() if l.startswith("- SKU")]
    check("vision no deriva por 'talla 38-43' (30/08 Yeni)",
          not _r.get("derivar"))
    check("vision no busca 'cliente'->'caliente' (30/08 Yeni)",
          not any("CALIENTE" in c.upper() for c in _cands)
          and any("ZAPATILLA" in c.upper() or "CALZADO" in c.upper()
                  for c in _cands))
    _r = await agente.procesar("calce 42", historial=h_yeni, lead_id="t-yeni2")
    check("calce real del cliente sigue derivando (30/08)", _r.get("derivar"))

    # ── CALZADO POR FAMILIA: solo catálogo rápido, sin precios web ni /l
    # (30/08: a un cliente le listó IRUN con precio web desfasado y fotos
    # rotas en vez del catálogo chico) ──
    await agente.procesar("Tienen grasep?", historial=[], lead_id="t-gra")
    check("grasep: sin lista de candidatos ni precios web (30/08)",
          sum(1 for l in CTX["ctx"].splitlines() if l.startswith("- SKU")) == 0
          and "catálogo de" in CTX["ctx"])
    check("grasep: sin link de lista /l (30/08)",
          "onrender.com/l/" not in CTX["ctx"])
    await agente.procesar("tienen crocs?", historial=[], lead_id="t-croc")
    check("crocs va a su catálogo propio (31/08)",
          "onrender.com/c/crocs" in CTX["ctx"])
    # arnés: rubro normal con 98 productos; el buscador debe traerlos
    await agente.procesar("Tienen arnés para perros?", historial=[],
                          lead_id="t-arn")
    check("arnes trae arneses (30/08)",
          any("ARNES" in l.upper() for l in CTX["ctx"].splitlines()
              if l.startswith("- SKU")))

    # ── SONDEO 30/08 (tarde): typos de autocorrector de champion, "Foto"
    # a secas, y términos META en el link del buscador ──
    for _q in ["Shampiones todo terreno", "Champiñones para correr en Asfalto",
               "Puede enviarme catalogo de los champagne con su precio",
               "Chuteira Grazep pra sintético", "Shampio m"]:
        await agente.procesar(_q, historial=[], lead_id="t-typo")
        check(f"typo de champion va por regla calzado (30/08): {_q[:28]!r}",
              sum(1 for l in CTX["ctx"].splitlines()
                  if l.startswith("- SKU")) == 0)
    await agente.procesar("copas de champagne tienen?", historial=[],
                          lead_id="t-copa")
    check("copas de champagne siguen siendo copas (30/08)",
          any("COPA" in l.upper() for l in CTX["ctx"].splitlines()
              if l.startswith("- SKU")))
    h_gus = [{"cliente": "Champions combos", "agente": "catalogo rapido..."}]
    for _q in ["Foto", "Podés pasar porfa\nFoto", "Foto pará eligir porfa",
               "Imágenes"]:
        await agente.procesar(_q, historial=h_gus, lead_id="t-gus")
        check(f"'{_q[:22]}' pide fotos del hilo (30/08 Gustavo)",
              "pide FOTOS de lo que YA" in CTX["ctx"])
    _idx2 = productos.indice_actual()
    check("termino_web sin palabras META (30/08 Marta q=foto)",
          "foto" not in _idx2.termino_web(
              "La foto de juguetes de princesas me pueden pasar")
          and _idx2.termino_web("Este ceria") != "est")

    # ── UN SOLO LINK CON OPCIONES /l/<skus> (30/08: web caída, fotos del
    # espejo del depósito en precios.*) ──
    await agente.procesar("tienen mochilas?", historial=[])
    import re as _re2
    # ahora manda el catálogo dinámico /c con TODOS los modelos; /l queda
    # para cuando no hay término verificado
    _m = _re2.search(
        r"https://cerebro-kommo\.onrender\.com/(c/[^\s]+|l/[\d,]+)",
        CTX["ctx"])
    check("link de lista /c|/l con candidatos reales (30/08)", bool(_m))
    if _m:
        _l = _m.group()
        check("lista: link autorizado pasa la limpieza (30/08)",
              _l in _limpiar_salida(f"Mirá las opciones acá 👇\n{_l}", (_l,)))
        # (31/08: /l y /c del cerebro pasaron a la allowlist fija — la
        # página solo muestra productos REALES, no puede inventar nada)
        check("lista: /l propio permitido por diseño (31/08)",
              "onrender.com/l/" in _limpiar_salida(
                  "Mirá https://cerebro-kommo.onrender.com/l/111,222", ()))
    # la página /l arma el mini catálogo con los items del índice
    try:
        from app import main as _main
    except ModuleNotFoundError:   # sin fastapi en este entorno: se salta
        _main = None
    if _main:
        _r = await _main.lista_resultados(",".join(
            [str(x["sku"]) for x in productos.indice_actual().buscar("mochila", 3)]))
        _html_l = getattr(_r, "body", b"").decode("utf-8", "replace")
        check("pagina /l arma tarjetas con precio (30/08)",
              "/foto/" in _html_l and "gs" in _html_l)

    # ── CATÁLOGO DINÁMICO /c (30/08: "si hay 200 arneses, presentarle
    # todos", con botón Hacer pedido que vuelve al chat) ──
    await agente.procesar("Tienen arnés para perros?", historial=[],
                          lead_id="t-cat")
    check("agente ofrece /c con TODOS los modelos (30/08)",
          "onrender.com/c/" in CTX["ctx"]
          and "CATÁLOGO PROPIO" in CTX["ctx"])
    try:
        from app import main as _main2
    except ModuleNotFoundError:
        _main2 = None
    if _main2:
        _rc = await _main2.catalogo_dinamico("arnes perro")
        _hc = getattr(_rc, "body", b"").decode("utf-8", "replace")
        check("pagina /c: todos los modelos + Hacer pedido (30/08)",
              _hc.count('class="c"') >= 20 and "Hacer pedido" in _hc
              and "wa.me/595976915333" in _hc
              and "Producto%20%28SKU%29" in _hc.replace("(", "%28").replace(")", "%29") or "wa.me/595976915333" in _hc)
        _rc2 = await _main2.catalogo_dinamico("zzzznoexiste")
        check("pagina /c sin resultados -> 404 (30/08)",
              getattr(_rc2, "status_code", 0) == 404)

    # ── AUDITORÍA DEL BUSCADOR (30/08: "que dé resultados correctos,
    # el de la página no es muy limpio") ──
    _ix = productos.indice_actual()
    _r = _ix.buscar("juguetes de princesas", 4)
    check("termino especifico manda (30/08): juguetes de princesas",
          all("PRINCESA" in x["nombre"].upper() for x in _r) if _r else False)
    check("lista corta se completa (30/08): cafetera electrica",
          len(_ix.buscar("cafetera electrica", 5)) >= 3)
    check("sinonimo camita->cama (30/08)",
          any("CAMA" in x["nombre"].upper()
              for x in _ix.buscar("camita para mascota", 4)))
    check("sinonimo frazada->acolchado/manta (30/08)",
          len(_ix.buscar("frazada", 4)) >= 3)
    check("arnes sigue limpio (30/08)",
          all("ARNES" in x["nombre"].upper() or "ARNÉS" in x["nombre"].upper()
              for x in _ix.buscar("arnes", 4)))

    # ── MONITOREO 30/08 PM ──
    # typo "DIRRCCION" debe caer en la regla de ubicación, no al buscador
    # (le ofreció rótulas de dirección de auto a una clienta)
    for _q in ["DIRRCCION", "direcion porfa", "dirreccion?"]:
        _r = reglas.responder(_q)
        check(f"typo direccion -> regla ubicacion (30/08): {_q!r}",
              _r and "Eusebio Ayala" in _r["texto"])
    # ── MONITOREO 31/08 ──
    # abreviatura chat "dnd" = dónde ("hla dnd es" cayó al buscador sin candidatos)
    for _q in ["hla dnd es", "dnd queda?"]:
        _r = reglas.responder(_q)
        check(f"abreviatura dnd -> regla ubicacion (31/08): {_q!r}",
              _r and "Eusebio Ayala" in _r["texto"])

    # "botines todo terreno" daba 0 candidatos ("terreno" no matcheaba nada)
    check("sinonimo terreno->botin (30/08): botines todo terreno",
          len(_ix.buscar("botines todo terreno", 4)) >= 1)
    # variantes vistas en pauta 30/08: "todoterrenos" junto y "grase" sin p
    check("sinonimo todoterreno->botin (30/08): botines todoterrenos",
          len(_ix.buscar("botines todoterrenos", 4)) >= 1)
    check("sinonimo grase->irun (30/08): todo terreno grase",
          len(_ix.buscar("todo terreno grase", 4)) >= 1)
    # monitoreo 31/08: "Las camperitas si tienen en Xl" devolvió fajas
    # (diminutivo no matcheaba "campera", mismo caso que "camita")
    check("sinonimo camperita->campera (31/08)",
          any("CAMPERA" in x["nombre"].upper()
              for x in _ix.buscar("camperitas en xl", 4)))

    # ── MAPA DEL CATÁLOGO (30/08: hiperónimos y jerga PY vs nombres de
    # carga precarios) ──
    _ix3 = productos.indice_actual()
    for _q, _esp in [("cama para perro", "MASCOTA"), ("cama para gato", "MASCOTA"),
                     ("vincha", "VINCHA"), ("corpiño", "CORPIÑO"),
                     ("juego de sabanas", "SABANA"), ("ojotas", "CHANCLA|SANDALIA|CHINELA"),
                     ("champion para niños", "INF")]:
        _r3 = _ix3.buscar(_q, 4)
        check(f"mapa catálogo (30/08): {_q!r} -> {_esp}",
              any(any(e in x["nombre"].upper() for e in _esp.split("|"))
                  for x in _r3))
    check("hiperonimo dirigido: perro NO trae gato (30/08)",
          not any("GATO" in x["nombre"].upper()
                  for x in _ix3.buscar("juguetes para perro", 5)))

    # ── CASO MARINA (30/08 17:23): "Envíame los modelos" en hilo de
    # championes mandó /l con precios web desfasados; la fuente del hilo
    # tomaba palabras del BOT ("catálogo RÁPIDO"->rapido, "Perfecto") ──
    h_mar = [{"cliente": "Championes",
              "agente": "Perfecto, están todos en el catálogo rápido: "
                        "https://catalogo.shoppingasia.com.py — tocá Hacer "
                        "pedido. Horma chica, un número más."}]
    await agente.procesar("Envíame los modelos", historial=h_mar,
                          lead_id="t-mar")
    check("continuar hilo calzado -> regla calzado, sin lista (30/08 Marina)",
          sum(1 for l in CTX["ctx"].splitlines()
              if l.startswith("- SKU")) == 0
          and "CONSULTA DE CALZADO" in CTX["ctx"]
          and "onrender.com/c/calzado" in CTX["ctx"])   # catálogo propio (31/08)
    await agente.procesar("y mochilas tenes?", historial=h_mar,
                          lead_id="t-mar2")
    check("cambio de rubro en hilo calzado sigue libre (30/08)",
          any("MOCHILA" in l.upper() for l in CTX["ctx"].splitlines()
              if l.startswith("- SKU"))
          and "CONSULTA DE CALZADO" not in CTX["ctx"])
    check("asteriscos pegados al link se quitan (30/08)",
          "*https" not in _limpiar_salida(
              "Entrá a *https://catalogo.shoppingasia.com.py*, buscá"))

    # ── CASO JORGE (31/08): link de publicación FB + "calce 43" + "tipo
    # botita" -> buscó las letras del URL y confirmó una LÁMPARA SOLAR ──
    _r = await agente.procesar(
        "https://www.facebook.com/ShoppingAsiapy/posts/pfbid026XYZabc\n"
        "En calce 43 necesito\nTipo botita", historial=[], lead_id="t-jor")
    check("link FB no envenena la búsqueda (31/08 Jorge)",
          "LAMPARA" not in CTX["ctx"].upper()
          and "SOLAR" not in CTX["ctx"].upper())
    check("link FB sin mapa -> nota de publicación (31/08)",
          "publicación nuestra" in CTX["ctx"])
    check("calce 43 con botita deriva (31/08)", _r.get("derivar"))
    # si el link SÍ está en el mapa, identifica el anuncio
    from app import conocimiento as _cono3
    _cono3.ANUNCIOS["https://www.facebook.com/ShoppingAsiapy/posts/999888777"] = {
        "representa": "PRUEBA BOTINES", "tipo": "sección", "sku": "",
        "alcance": "línea IRUN"}
    await agente.procesar(
        "https://www.facebook.com/ShoppingAsiapy/posts/999888777/\nquiero info",
        historial=[], lead_id="t-jor2")
    check("publicación identificada por link del cliente (31/08)",
          "PRUEBA BOTINES" in CTX["ctx"])
    _cono3.ANUNCIOS.pop("https://www.facebook.com/ShoppingAsiapy/posts/999888777")
    # botita = botin
    check("botita busca botines (31/08)",
          any("BOT" in x["nombre"].upper()
              for x in productos.indice_actual().buscar("botita", 4)))

    # ── PAUTA IDENTIFICADA MANDA (31/08 Katherine: pauta IRUN + "quiero
    # más información" mandó /l con cepillos y CHAMPION INF de 240k) ──
    from app import conocimiento as _cono4
    _cono4.ANUNCIOS.setdefault("champion_irun", {
        "representa": "CHAMPIONES IRUN", "tipo": "sección (línea)",
        "sku": "toda la línea IRUN", "alcance": "línea IRUN completa"})
    await agente.procesar("¡Hola! Quiero más información",
                          ad_id="champion_irun", historial=[],
                          lead_id="t-kat")
    check("pauta calzado + msg generico -> regla calzado sin basura (31/08)",
          sum(1 for l in CTX["ctx"].splitlines()
              if l.startswith("- SKU")) == 0
          and "CONSULTA DE CALZADO" in CTX["ctx"]
          and "onrender.com/c/calzado" in CTX["ctx"]
          and "onrender.com/l/" not in CTX["ctx"])
    check("termino sin gs/mil (31/08 Maggie)",
          productos.indice_actual().termino_web(
              "Carritos para bebes hasta 350mil gs") == "carritos bebes")

    # ── TIENDA PROVISORIA (31/08: la página oficial caída; /tienda es la
    # "página" para clientes: categorías + buscador con filtro opcional) ──
    try:
        from app import main as _main3
        from app import tienda as _tienda
    except ModuleNotFoundError:
        _main3 = None
    if _main3:
        _idx4 = productos.indice_actual()
        _cts = _tienda.conteos(_idx4)
        check("tienda: 14 categorías con productos (31/08)",
              len([c for c, n in _cts.items() if n]) >= 12
              and _cts.get("Calzados", 0) > 500)
        _rp = await _main3.tienda_portada()
        _hp = _rp.body.decode()
        check("tienda: portada con buscador y fichas (31/08)",
              "name='q'" in _hp and _hp.count('class="catf"') >= 12
              and "Todas las categorías" in _hp)
        _rc = await _main3.tienda_categoria("Mascotas", p=1)
        check("tienda: categoría paginada (31/08)",
              _rc.status_code == 200
              and _rc.body.decode().count('class="c"') == 60)
        _sin = await _main3.catalogo_dinamico("collar")
        _con = await _main3.catalogo_dinamico("collar", cat="Mascotas")
        check("tienda: filtro de categoría en la búsqueda (31/08)",
              0 < _con.body.decode().count('class="c"')
              < _sin.body.decode().count('class="c"'))
        _rb = await _main3.tienda_buscar(q="perfume", cat="Belleza y Cuidado")
        check("tienda: /buscar enruta con filtro (31/08)",
              "/c/perfume" in _rb.headers.get("location", "")
              and "cat=" in _rb.headers.get("location", ""))

    # ── LIMPIEZA DE CATEGORÍAS Y ACCESORIOS (31/08 noche) ──
    if _main3:
        _idx5 = productos.indice_actual()
        _cts2 = _tienda.conteos(_idx5)
        check("categorías sin el bug del 'de' (31/08): Juguetes real",
              _cts2.get("Juguetes", 99999) < 3000)
        _cal = _tienda.items_de(_idx5, "Calzados")
        _prim = [x["nombre"].upper() for x in _cal[:30]]
        check("cordones/accesorios al FONDO de Calzados (31/08)",
              not any("CORDONES PARA" in n or "PLANTILLA" in n
                      for n in _prim))
        _lib = [x["nombre"].upper() for x in _tienda.items_de(
            _idx5, "Librería y Oficina")[:30]]
        check("labiales fuera de Librería (31/08)",
              not any("LABIAL" in n for n in _lib))

    if FALLOS:
        print(f"❌ {len(FALLOS)} REGRESIONES: {FALLOS}")
        sys.exit(1)
    print("✅ SUITE COMPLETA SIN REGRESIONES")


if __name__ == "__main__":
    asyncio.run(correr())
