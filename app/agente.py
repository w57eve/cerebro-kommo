# -*- coding: utf-8 -*-
"""
Orquestador del agente. Este es el "cerebro" que decide cómo responder.

Orden (de más barato a más caro):
1. REGLAS (0 tokens): saludos, horarios, envíos, pagos, mayorista, cambios,
   y pedido de hablar con una persona -> deriva a vendedor.
2. Datos de producto (0 tokens de IA): si hay SKU o el texto parece un producto,
   busca precio/foto en el índice del sitio.
3. IA (Haiku, con caché): solo para lo abierto/ambiguo, usando la base de
   conocimiento como sistema.

Reglas duras metidas en el system prompt: tono de "vos", NO inventar precios,
catálogo -> web -> vendedor, la foto es sugerencia (se confirma), y responder en
UN solo mensaje (cada mensaje de la línea oficial se cobra).
"""

import asyncio
import re as _re

from . import (busqueda, catalogo_chico, conocimiento, kommo, llm,
               productos, reglas, vendedores)

# ── Higiene de salida ──────────────────────────────────────────────────────
_URL_RE = _re.compile(r"https?://[^\s)\]]+")

# Prefijos de links LEGÍTIMOS (todo lo demás se considera inventado y se borra)
# OJO: /buscador NO está acá a propósito: solo se permite el link de búsqueda
# EXACTO que calcula el servidor (va como 'permitidos_extra'), porque la IA
# tendía a armar buscadores con la frase entera del cliente.
# OJO: las fotos NO están acá: solo se permite la foto EXACTA del candidato
# que el server autoriza en cada respuesta (permitidos_extra). Sin esto, la IA
# pegaba fotos de un producto junto al nombre de otro, o fotos inventadas.
_LINKS_BASE = (
    "https://catalogo.shoppingasia.com.py",       # catálogo de pautas
    "https://wa.me/",                             # derivación a vendedor
)


def _limpiar_salida(texto: str, permitidos_extra=()) -> str:
    """Borra meta-notas entre corchetes y CUALQUIER link que no sea legítimo
    (el bot viejo inventaba URLs de producto rotos: eso no puede volver a salir)."""
    # 1) meta-notas: [cualquier cosa] (la etiqueta [DERIVAR] ya fue procesada)
    texto = _re.sub(r"\[[^\]\n]*\]", "", texto)
    # WhatsApp usa *negrita* con UNA estrella; el ** de markdown se ve roto.
    texto = texto.replace("**", "*")
    # Mexicanismos -> paraguayo (la IA a veces se le escapa aunque el prompt
    # lo prohíba; acá se corrige SIEMPRE antes de enviar).
    for _mx, _py in (("te late", "te parece"), ("¿qué onda", "¿qué tal"),
                     ("que onda", "que tal"), ("ahorita", "ahora"),
                     ("platicar", "charlar"), ("platicamos", "charlamos"),
                     ("padrísimo", "buenísimo"), ("padrisimo", "buenisimo"),
                     ("chido", "bueno"), ("órale", "dale"), ("orale", "dale"),
                     ("güey", ""), ("checa", "mirá"), ("checar", "mirar")):
        texto = _re.sub(_re.escape(_mx), _py, texto, flags=_re.IGNORECASE)
    # 2) links: solo los permitidos; la línea con un link inventado se borra entera
    permitidos = _LINKS_BASE + tuple(permitidos_extra)

    def _ok(u: str) -> bool:
        u = u.rstrip(".,;:!?")
        if u.rstrip("/") == "https://www.shoppingasia.com.py":
            return True   # la portada sí existe
        return any(u.startswith(p) for p in permitidos)

    lineas, fotos_vistas = [], 0
    for ln in texto.splitlines():
        urls = _URL_RE.findall(ln)
        if urls and not all(_ok(u) for u in urls):
            continue
        # tope: UNA sola linea con link de foto (la gente no toca los links;
        # los candidatos van como texto y las fotos solo al confirmar)
        if any("/foto/" in u or "/storage/" in u for u in urls):
            fotos_vistas += 1
            if fotos_vistas > 1:
                continue
        lineas.append(ln)
    limpio = "\n".join(lineas)
    limpio = _re.sub(r"\n{3,}", "\n\n", limpio).strip()
    return limpio

# ── Verificación del buscador de la web ────────────────────────────────────
# Antes de ofrecer el link /buscador?q=..., comprobamos que la web tenga
# resultados DE VERDAD (una página vacía no contiene links /producto/).
_web_cache = {}   # termino -> (ts, tiene_resultados)


async def _web_tiene_resultados(term: str) -> bool:
    import time as _t

    import httpx as _httpx
    from urllib.parse import quote as _q
    v = _web_cache.get(term)
    if v and _t.time() - v[0] < 6 * 3600:
        return v[1]
    ok = False
    try:
        async with _httpx.AsyncClient(timeout=7) as cli:
            r = await cli.get(
                f"https://www.shoppingasia.com.py/buscador?q={_q(term)}",
                headers={"User-Agent": "cerebro"})
        ok = r.status_code == 200 and ("/producto/" in r.text
                                       or "storage/sku" in r.text)
    except Exception:
        ok = False   # ante la duda, mejor sin link que con un link vacío
    if len(_web_cache) > 500:
        _web_cache.clear()
    _web_cache[term] = (_t.time(), ok)
    return ok


AUDIO_MSG = (
    "¡Hola! 🎧 Me llegó tu audio, pero por acá no puedo escucharlos. "
    "¿Me lo escribís en un mensajito, por favor? Así te atiendo mejor. "
    "O si preferís, te derivo con un vendedor para una atención más "
    "personalizada 🙌"
)

FALLBACK = (
    "Perdón, no te seguí bien 🙏 ¿Me decís qué producto buscás (nombre o SKU)? "
    "Si preferís, te paso con un asesor."
)

_INSTRUCCIONES = """
Sos un agente de ventas de Shopping Asia (Paraguay). No sos un bot cualquiera:
atendés como un vendedor experimentado, humano, cordial y resolutivo. Tu objetivo
es ayudar al cliente a encontrar lo que busca y avanzar la venta.

Tono: hablás de "vos" (voseo paraguayo, cercano). Te adaptás al cliente: si es
formal, acompañás; si es relajado, relajado. Emojis con moderación.

Saludos (importante para no parecer un bot): si te paso el nombre del cliente,
saludalo por su nombre UNA sola vez. Y si el cliente saluda Y encima pregunta algo
("buenas, tienen cafetera?"), NO respondas solo el saludo: saludá y en el MISMO
mensaje contestá o mostrale los productos. Nunca devuelvas "¿en qué le servimos?"
como única respuesta cuando ya te preguntaron algo concreto.

Cómo trabajás (MUY IMPORTANTE):
- Tenés acceso al CATÁLOGO COMPLETO (nombre, precio y foto de casi todos los
  productos). Cuando el cliente pregunta por algo, tu primer reflejo es BUSCAR y
  OFRECER, no interrogar. En el contexto te paso lo que encontré.
- **Preguntá lo MÍNIMO.** A lo sumo UNA cosa (ej. talle o color) y solo si de
  verdad hace falta para avanzar. Nada de tandas de preguntas.
- Cuando tengas el producto (o candidatos), mostralo con su **precio** en
  texto claro. Nada de listas de links.
- Si hay un solo candidato claro: presentalo confirmando ("¿es este? *nombre*
  — precio") y ahí sí podés sumar SU foto (una sola). Si hay varios: mostrá
  3–4 opciones como TEXTO (*nombre* — precio) y que elija. La búsqueda no es
  perfecta: si no estás seguro, ofrecé opciones o pedí el SKU, nunca inventes.
- **El enlace a la web es la excepción**, no la regla: usalo solo si el cliente
  ya vio tus opciones y quiere VER MÁS variedad, o está solo curioseando. En ese
  caso mandá el "link ver más" que te paso en el contexto (lleva directo a los
  resultados de SU búsqueda en la web, no a la portada).
- Si el cliente quiere CONCRETAR (pagar, reservar, comprar ya), tiene una QUEJA
  o reclamo, o no podés resolver con los datos que tenés: escribí tu respuesta
  breve y terminá el mensaje con la etiqueta [DERIVAR] en una línea aparte. El
  sistema la reemplaza por el contacto del vendedor de turno. No inventes vos
  números ni nombres de vendedores.
- **POCOS LINKS (los clientes casi no los tocan).** Presentá los candidatos
  como TEXTO: *nombre* — precio, sin link de foto por cada uno. Links
  permitidos por mensaje: el catálogo rápido (si aplica) y el "ver más"
  verificado del contexto — nada más. UNA foto como máximo, y solo cuando
  estés confirmando UN producto puntual ("¿es este?") o el cliente pida ver
  foto: en ese caso el link de foto va pelado en su propia línea (nunca
  markdown ![](url); WhatsApp lo muestra roto).
- **TYPOS DE CELULAR:** la gente escribe desde el teléfono y le pifia a las
  letras vecinas ("michila" = mochila, "cinto" puede ser "cinta", c por s,
  m por n). Interpretá la intención sin corregirlos en voz alta ni burlarte;
  los candidatos del contexto ya vienen de la búsqueda con typos corregidos.

Reglas duras (no las rompas nunca):
- No inventás precios, stock ni políticas. Si no está en el catálogo ni en los
  datos que te paso, NO lo afirmes.
- **PRECIOS: copialos TAL CUAL** vienen en el contexto (ya están formateados,
  ej. "240.000 gs"). No los recalcules, no los redondees, y JAMÁS le pongas a
  un producto el precio de otro: cada precio va pegado a SU producto de la
  lista del contexto. Si dudás, no des el precio y ofrecé confirmarlo.
- **ELECCIÓN HECHA = DERIVAR YA.** Cuando el cliente ya ELIGIÓ (dijo qué
  producto quiere y su talle/color, eligió del catálogo, o dice "quiero ese",
  "el 38", "ese quiero"): NO preguntes si quiere que lo derives ni le ofrezcas
  más opciones. Confirmá su elección en UNA línea y derivá con [DERIVAR] en el
  mismo mensaje (el sistema pone el enlace del vendedor especializado).
- **FRUSTRACIÓN = DERIVAR, nunca discutir.** Si el cliente muestra molestia
  ("no es eso", "no me entendés", "ya te dije", repite lo mismo) o después de
  DOS intentos seguís sin acertar el producto, no sigas insistiendo: disculpa
  breve y [DERIVAR]. Un cliente peleando con un bot es una venta perdida.
- **CATÁLOGO RÁPIDO por SKU (dato exacto, no adivines):** si un candidato del
  contexto dice "ESTÁ EN EL CATÁLOGO RÁPIDO", ese producto está publicado en
  https://catalogo.shoppingasia.com.py con fotos y talles: ofrecé ese link
  (botón 'Hacer pedido' lo trae de vuelta acá). Si NO lo dice, ese producto NO
  está en el catálogo rápido: no lo prometas ahí.
- **DERIVACIÓN: una sola vez por charla.** Si en la conversación previa ya
  derivaste (aparece un link wa.me), NO uses [DERIVAR] de nuevo: recordale que
  ese mismo vendedor lo va a atender y repetile el mismo link si hace falta.
- **LINKS: SOLO los que te paso en el contexto** (fotos del catálogo, link "ver
  más", catálogo de pautas). NUNCA armes ni inventes URLs de producto: el
  sistema borra cualquier link que no venga del contexto y tu mensaje queda
  incompleto. Si no tenés link real, mandá nombre + precio + SKU y listo.
- Nada de meta-notas ni texto entre corchetes en la respuesta (el cliente lo ve
  tal cual). La única etiqueta permitida es [DERIVAR] al final.
- Léxico paraguayo: nada de mexicanismos tipo "¿te late?"; usá "¿te gustó?",
  "¿cuál te interesa?", "al toque", voseo siempre.
- Si el producto pedido NO está: nunca cierres con "no tenemos" seco; ofrecé
  2-3 alternativas del mismo rubro de los candidatos del contexto, o derivá.
- Nunca niegues lo que vos mismo dijiste antes (tenés la conversación previa
  en el contexto: usala).
- Si el cliente dice que un link no le abre: no insistas con el link; mandale
  nombre + precio + foto (link de foto del contexto) directo en el chat.
- Orden para encontrar un artículo: catálogo/base completa → si no aparece,
  DERIVÁS a un vendedor (a veces son artículos nuevos todavía no cargados).
- Respondé en UN solo mensaje, completo y no muy largo. Nada de varios mensajes
  seguidos.
- Si el cliente quiere cerrar la compra o hablar con una persona, derivá al
  vendedor (el sistema te lo indica con un botón aparte).

Cómo vende un VENDEDOR EXPERIMENTADO (tu estándar):
- RELEVANCIA ante todo: si los candidatos del contexto NO se parecen a lo que
  el cliente pidió (pidió zapatillas y hay cestos), NO los muestres — decí que
  lo confirmás con el equipo y derivá. Mostrar cualquier cosa mata la venta.
- STOCK: nunca digas "está disponible" ni "no hay stock" — vos no ves el stock.
  Decí "lo tenemos en catálogo" y que el vendedor confirma disponibilidad.
- COHERENCIA: no te contradigas entre mensajes ni cambies un precio ya dado.
  Lo que dijiste antes (está en la conversación previa) sigue valiendo.
- ANUNCIO MANDA: si la foto del cliente es un anuncio/captura con producto y
  precio visibles, ESE es el tema y ESE es el precio — no ofrezcas otra cosa
  más cara ni vuelvas a preguntar qué busca.
- CIERRE: cada mensaje termina moviendo la venta UN paso (una pregunta
  concreta, una confirmación o la derivación). Nunca cierres con tarea para el
  cliente si podés resolverla vos.
- Si ofreciste pasar con un vendedor y el cliente acepta ("sí", "dale", "por
  favor"), NO vuelvas a preguntar: derivá en ese mismo mensaje.

Datos de la empresa (horarios, pagos, envíos, etc.) están en la base de abajo.
"""


def _sistema() -> str:
    return _INSTRUCCIONES + "\n\n===== BASE DE CONOCIMIENTO =====\n" + conocimiento.BASE


SISTEMA = _sistema()


def _nombre_corto(nombre: str) -> str:
    nombre = (nombre or "").strip()
    if not nombre or nombre.lower() in ("none", "null", "{{contact.name}}"):
        return ""
    return nombre.split()[0].capitalize()   # solo el primer nombre


def _bienvenida(nombre: str = "") -> str:
    n = _nombre_corto(nombre)
    hola = f"¡Hola {n}! " if n else "¡Hola! "
    return (hola + "Bienvenido/a a Shopping Asia 🙌 ¿Qué estás buscando? "
            "Decime el producto y te paso precio y foto.")


def _prefijo_saludo(saludo: bool, nombre: str = "") -> str:
    if not saludo:
        return ""
    n = _nombre_corto(nombre)
    return f"¡Hola {n}! " if n else "¡Hola! "


async def procesar(mensaje: str, ad_id: str = "", nombre: str = "",
                   historial=None, lead_id: str = "", origen: str = "",
                   foto_matches=None) -> dict:
    """Decide la respuesta. Devuelve {"texto", "derivar", "candidatos"}.

    historial: lista de intercambios previos de ESTA charla, cada uno
    {"cliente": ..., "agente": ...}. Le da memoria a la conversación.

    Clave para no parecer un bot: si el cliente saluda Y pregunta algo en el
    mismo mensaje, saludamos (por su nombre si lo tenemos) y en el MISMO mensaje
    contestamos/mostramos los productos. No devolvemos solo un saludo.
    """
    # Nota de voz: no podemos escucharla todavia -> pedimos texto / derivamos.
    # (v2: llega como "(el cliente mandó un audio)"; legado: ícono 🔊 en texto)
    if "(el cliente mandó un audio)" in mensaje or reglas.es_audio(mensaje):
        return {"texto": AUDIO_MSG, "derivar": False, "candidatos": None}

    saludo = reglas.es_saludo(mensaje)

    # ACEPTÓ la derivación ofrecida ("¿te paso con un vendedor?" -> "sí/dale/
    # por favor"): derivar YA, directo y sin IA. Va ANTES que todo porque
    # "por favor" caía en el filtro de saludos y repreguntaba.
    _m0 = busqueda.normalizar(mensaje)
    if (historial and _re.fullmatch(
            r"\s*(si+|s[ií]\s*dale|dale|ok+a?|bueno|por\s*favor|porfa|claro"
            r"|obvio|de una|hacele|hace(lo)?)[.!\s]*", _m0)
            and any(w in (historial[-1].get("agente") or "").lower()
                    for w in ("vendedor", "asesor", "te paso con", "te derivo"))):
        d = vendedores.mensaje_derivacion(consulta="acepta derivación",
                                          lead_id=lead_id)
        return {"texto": "¡De una! " + d["texto"], "derivar": True,
                "candidatos": None}

    # Solo un saludo (sin pedido) -> bienvenida y a esperar el pedido.
    # PERO si viene de una PAUTA o la charla YA VENÍA, no: nada de volver a
    # dar la bienvenida a mitad de conversación.
    if reglas.solo_saludo(mensaje) and not ad_id and not historial:
        return {"texto": _bienvenida(nombre), "derivar": False, "candidatos": None}

    pref = _prefijo_saludo(saludo, nombre)

    # 1) Reglas de 0 tokens (FAQ / derivar). Nota: el saludo ya NO corta acá.
    r = reglas.responder(mensaje)
    if r and r["tipo"] == "texto":
        return {"texto": pref + r["texto"], "derivar": False, "candidatos": None}
    if r and r["tipo"] == "derivar":
        sku = productos.extraer_sku(mensaje) or ""
        d = vendedores.mensaje_derivacion(sku=sku, consulta=mensaje[:180], lead_id=lead_id)
        return {"texto": pref + d["texto"], "derivar": True, "candidatos": None}

    # 2) Datos de producto (contexto para el LLM y para la respuesta templada)
    contexto = ""
    if historial:
        contexto += ("Conversación previa de esta charla (lo más reciente al "
                     "final; NO vuelvas a saludar, continuá con naturalidad):\n")
        for h in list(historial)[-6:]:
            contexto += f"Cliente: {h.get('cliente','')}\n"
            contexto += f"Vos: {h.get('agente','')}\n"
        contexto += "---\n"
    n_corto = _nombre_corto(nombre)
    if n_corto:
        contexto += (f"El cliente se llama {n_corto}. Si saludó, devolvé el "
                     "saludo por su nombre UNA vez.\n")
    ctx_ad = conocimiento.contexto_anuncio(ad_id)
    if ctx_ad:
        contexto += ctx_ad + "\n"
    elif (origen or "").lower() in ("facebook", "instagram",
                                    "instagram_business", "pauta"):
        contexto += (
            f"El chat entró por {origen} (desde una publicación/pauta de redes, "
            "no sabemos cuál exactamente). Si el cliente pide 'más información', "
            "'la oferta' o 'lo del anuncio', se refiere a LO QUE VIO en esa "
            "publicación. NO adivines cuál es: preguntá qué producto vio o "
            "pedile que mande una captura de la publicación (la captura la "
            "podés ver). NO mandes ofertas genéricas de la página web, y solo "
            "mencioná el catálogo rápido (catalogo.shoppingasia.com.py) si lo "
            "que busca es CALZADO — ropa, maquillaje y otros rubros NO están "
            "ahí.\n")

    # "Esto", "este", "es esta", "ese quiero": el cliente SEÑALA algo (la foto
    # o lo anterior), no nombra un producto. Buscar ese texto trae basura
    # (le llegó a ofrecer cestos y perfumes a quien mandó una zapatilla).
    _deixis = bool(_re.fullmatch(
        r"\s*(es\s+)?(esto|este|esta|ese|esa|eso)( de ah[ií])?( quiero| busco"
        r"| me interesa)?[.!\s]*", busqueda.normalizar(mensaje)))
    if _deixis and (historial or "(foto del cliente:" in mensaje):
        contexto += (
            "OJO: el cliente está SEÑALANDO ('esto/ese') la foto que mandó o "
            "lo último que se habló: NO es un producto para buscar. Respondé "
            "sobre ESO (mirá la foto descripta y la conversación previa). Si "
            "no queda claro a qué se refiere, UNA repregunta o derivá. "
            "PROHIBIDO ofrecer productos sueltos del catálogo acá.\n")

    # "El de 116 mil", "el de 45.000 gs": es una REFERENCIA A PRECIO de algo
    # que ya vio (en la charla, en el catálogo chico o en una foto), NO un
    # producto para buscar. Sin esto, "116" matcheaba cualquier cosa (llegó a
    # ofrecer estuches de celular a alguien que miraba botines).
    if _re.search(r"\b\d{2,3}(?:[.,]\d{3})?\s*(?:mil|gs|guaranies|guaraníes)\b",
                  mensaje.lower()):
        contexto += (
            "OJO: el cliente menciona un PRECIO como referencia ('el de X "
            "mil'). NO es un producto para buscar: se refiere a algo que ya "
            "vio (en esta charla, en el catálogo rápido o en una foto). Mirá "
            "la conversación previa; si ahí está el producto de ese precio, "
            "seguí con ese. Si no sabés cuál es, pedile el nombre o que toque "
            "'Hacer pedido' en el catálogo para traer los datos. PROHIBIDO "
            "ofrecer productos no relacionados solo porque coincida un "
            "número.\n")

    if "(foto del cliente:" in mensaje:
        contexto += (
            "El sistema de VISIÓN ya miró la foto del cliente: su descripción "
            "va en el mensaje entre paréntesis. Usála como si VOS hubieras "
            "visto la foto (viste la foto, a través del sistema): identificá "
            "el producto con los candidatos del contexto, que salen de esa "
            "descripción. Si es una captura del catálogo con nombre/precio "
            "visibles, usá ESOS datos directamente. Si el cliente después "
            "dice 'esa marca' o 'ese', se refiere a LO DE LA FOTO. Nunca "
            "digas que no podés ver imágenes.\n")

    if "(el cliente mandó una foto)" in mensaje:
        contexto += ("El cliente mandó una FOTO que no podés ver. No adivines "
                     "qué es: pedile con buena onda el nombre del producto o "
                     "el SKU (o que lo escriba), y ofrecé el asesor si prefiere. "
                     "Si en la conversación previa ya pasó esto, derivá con "
                     "[DERIVAR].\n")

    async def _linea(it):
        # marca por SKU si el producto está publicado en el CATÁLOGO RÁPIDO
        _cat = await catalogo_chico.categoria_de(it.get("sku"))
        _extra = (f" | ESTÁ EN EL CATÁLOGO RÁPIDO (sección {_cat})"
                  if _cat else "")
        return productos.a_texto(it) + _extra

    sugeridos = []
    sku = productos.extraer_sku(mensaje)
    if sku:
        it = await productos.por_sku(sku)
        if it:
            sugeridos = [it]
            contexto += "Producto confirmado (podés dar precio/foto):\n" + await _linea(it) + "\n"
        else:
            contexto += (f"El SKU {sku} no está en el catálogo. No afirmes que "
                         "existe; ofrecé buscarlo o derivar.\n")
    elif _deixis:
        pass   # señala la foto/lo anterior: la búsqueda de texto solo mete ruido
    else:
        cand = await productos.buscar(mensaje, limite=5)
        sugeridos = cand
        if len(cand) == 1:
            contexto += "Posible producto (confirmá con el cliente):\n" + await _linea(cand[0]) + "\n"
        elif len(cand) > 1:
            contexto += ("Varios candidatos (mostrá 3–4 con su foto y pedí que "
                         "elija, no adivines):\n")
            for _c in cand:
                contexto += await _linea(_c) + "\n"

    # COINCIDENCIA VISUAL: la foto del cliente ya fue comparada contra las
    # fotos de todo el catálogo (mismo motor del verificador de precios).
    if foto_matches:
        _visuales = []
        for _sku, _score in foto_matches:
            _it = await productos.por_sku(_sku)
            if not _it or _score < 0.80:
                continue
            _conf = "ALTA" if _score >= 0.88 else "MEDIA"
            _visuales.append((_conf, _score, _it))
        if _visuales:
            contexto += ("COINCIDENCIA VISUAL: la foto del cliente se comparó "
                         "contra las fotos de TODO el catálogo. Resultados:\n")
            for _conf, _score, _it in _visuales:
                contexto += (f"- confianza {_conf} ({_score:.0%}): "
                             + await _linea(_it) + "\n")
            contexto += ("Con confianza ALTA presentá ese producto CONFIRMANDO "
                         "('¿es este? [nombre, precio, foto]'). Con MEDIA "
                         "mostrá las opciones y que elija. La foto es "
                         "sugerencia, no veredicto: nunca afirmes sin "
                         "confirmar.\n")
            _ya = {x[2]["sku"] for x in _visuales}
            sugeridos = [x[2] for x in _visuales] + [
                s for s in sugeridos if s.get("sku") not in _ya]

    # REGLA DE ORO DE CALZADOS: toda consulta de la familia calzado (champion,
    # botines, chutera, futsal, todo terreno, IRUN...) — venga de pauta, de la
    # página o directa — se responde con el CATÁLOGO CHICO primero y el link
    # de la web con "más opciones" después. Los modelos pautados viven en el
    # catálogo chico (en el grande/web muchos ni aparecen con ese nombre).
    _CALZADO_TOKENS = {"champion", "champione", "zapatilla", "teni", "calzado",
                       "botin", "chutera", "taquilla", "futsal", "futbol",
                       "deportivo", "irun",
                       # typos frecuentes de celular (letras vecinas / s-c-z)
                       "fitsal", "futzal", "fusal", "chanpion", "champio",
                       "sapatilla", "zapato", "sapato", "calsado", "calzada",
                       "grasep", "graseep", "grassep", "gracep"}
    _msg_n = busqueda.normalizar(mensaje)
    _toks = set(busqueda.tokenizar(mensaje))
    pauta_term = ("calzado" if (_toks & _CALZADO_TOKENS
                                or "todo terreno" in _msg_n
                                or "todoterreno" in _msg_n) else "")

    # ── ELECCIÓN CONCRETADA (detección DETERMINÍSTICA en el servidor) ──
    # El cliente ya eligió si: mandó un SKU (venía del botón "Hacer pedido" o
    # del catálogo chico), o dio su calce/talle con número, o respondió con el
    # número solo ("42") cuando la charla ya venía. En ese caso se DERIVA SÍ O
    # SÍ (la IA solo redacta la confirmación; la derivación la fuerza el server).
    # Aceptó la derivación ofrecida ("¿te paso con un vendedor?" -> "sí/dale/
    # por favor"): derivar YA, sin volver a preguntar (pasaba que repreguntaba).
    _afirma = bool(_re.fullmatch(
        r"\s*(si+|s[ií]\s*dale|dale|ok+a?|bueno|por\s*favor|porfa|claro"
        r"|obvio|de una|hacele|hace(lo)?)[.!\s]*", _msg_n))
    _ofrecio_vendedor = bool(historial) and any(
        w in (historial[-1].get("agente") or "").lower()
        for w in ("vendedor", "asesor", "te paso con", "te derivo"))
    eligio = False
    if _afirma and _ofrecio_vendedor:
        eligio = True
    elif sku and ("hacer un pedido" in _msg_n
                or await catalogo_chico.categoria_de(sku)):
        eligio = True
    elif (_re.search(r"\b(calce|calse|clace|calze|kalce|talle|talla|taye"
                     r"|numero|nro|n)\s*:?\s*\d{2}\b", _msg_n)
          and (historial or sugeridos or pauta_term)):
        eligio = True
    elif (_re.fullmatch(r"\s*(?:el\s+)?\d{2}(?:\s*(?:o|y|,|/)\s*\d{2})*\s*",
                        _msg_n) and historial):
        eligio = True   # "42", "el 40", "41 o 39" respondiendo al talle
    if eligio:
        contexto += (
            "ELECCIÓN CONCRETADA: el cliente YA eligió (producto y/o calce). "
            "PROHIBIDO ofrecer el catálogo, más opciones o links: confirmá su "
            "elección en UNA o DOS líneas (producto y precio si los tenés, y "
            "el calce que dijo) y nada más. El sistema agrega el contacto del "
            "vendedor automáticamente al final de tu mensaje.\n")

    if pauta_term and not eligio:
        contexto += (
            "CONSULTA DE CALZADO (regla fija, en este ORDEN): "
            "1) PRIMERO el catálogo rápido: pasá "
            "https://catalogo.shoppingasia.com.py explicando en simple que ahí "
            "están los modelos con talles y que al tocar 'Hacer pedido' vuelve "
            "acá con el calzado elegido; si preguntó por talle/calce, recordá "
            "la horma chica (conviene un número más). "
            "2) el link de la web va SIEMPRE AL FINAL, como ÚLTIMO renglón del "
            "mensaje: 'en la página tenés más opciones, deslizá hacia abajo "
            "para verlas 👉' + el link 'ver más' que te doy abajo. Nada va "
            "después de ese link. "
            "Si además encontré candidatos que coincidan con lo pedido, podés "
            "mostrar 2-3 con foto y precio antes del paso 1. NUNCA digas 'no "
            "tenemos' en calzados: lo pautado está en el catálogo chico.\n")

    # Link "ver más": resultados de ESTA búsqueda en la web (jerga ya mapeada,
    # ej. championes -> calzado). VERIFICADO contra el catálogo: corrige tipeos
    # (michila -> mochila) y descarta palabras que no existen en ningún producto.
    _idx = productos.indice_actual()
    if pauta_term:
        term_web = pauta_term   # "calzado": familia de la consulta
    else:
        term_web = _idx.termino_web(mensaje) if _idx else busqueda.termino_web(mensaje)
    link_web = ""
    if eligio:
        term_web = ""   # ya eligió: nada de links de "ver más"
    if term_web and not sku and await _web_tiene_resultados(term_web):
        from urllib.parse import quote as _q
        link_web = f"https://www.shoppingasia.com.py/buscador?q={_q(term_web)}"
        contexto += ("Link 'ver más' (VERIFICADO: la web tiene resultados; va "
                     f"TAL CUAL, no lo modifiques ni armes otro): {link_web}\n")
    elif term_web and not sku:
        contexto += ("OJO: la web NO tiene resultados para esta búsqueda. NO "
                     "mandes ningún link de buscador; resolvé con los "
                     "candidatos del catálogo o derivá.\n")

    # Sin resultados en el catálogo -> no pelear con el cliente: aclarar UNA
    # vez como máximo, y si la charla ya venía sin acertar, derivar directo.
    if not sugeridos and not sku and not pauta_term:
        if historial:
            contexto += (
                "NO encontré nada en el catálogo para este pedido y la charla "
                "ya venía: no insistas ni repreguntes de nuevo; pedí una "
                "disculpa breve y derivá con [DERIVAR].\n")
        else:
            contexto += (
                "NO encontré nada en el catálogo para este pedido: no "
                "inventes. Hacé UNA sola repregunta (nombre exacto, foto o "
                "SKU) y ofrecé pasar con un asesor; si insiste sin aclarar, "
                "derivá con [DERIVAR].\n")

    # 3) IA para redactar (tono humano). Si no hay IA o falla, respuesta templada.
    if llm.disponible():
        texto = await asyncio.to_thread(llm.responder, SISTEMA, contexto, mensaje)
        if texto:
            # Links legítimos de ESTA respuesta: la foto EXACTA del candidato
            # (solo si hay UNO claro: con varios no se puede garantizar que la
            # foto corresponda al nombre) y el link de búsqueda del servidor.
            permitidos = ()
            if len(sugeridos) == 1 and sugeridos[0].get("imagenes"):
                permitidos = (productos.foto_url(sugeridos[0]),)
            if link_web:
                permitidos += (link_web,)
            derivar = "[DERIVAR]" in texto or eligio
            texto = _limpiar_salida(texto.replace("[DERIVAR]", ""), permitidos)
            if derivar:
                d = vendedores.mensaje_derivacion(
                    sku=(sku or ""), consulta=mensaje[:180], lead_id=lead_id)
                texto = (texto + "\n\n" + d["texto"]).strip()
                return {"texto": texto, "derivar": True, "candidatos": len(sugeridos)}
            if texto:
                return {"texto": texto, "derivar": False, "candidatos": len(sugeridos)}

    # Sin IA: si hay productos, los ofrecemos (0 tokens), con saludo si aplica.
    if sugeridos:
        return {"texto": pref + _respuesta_productos(sugeridos), "derivar": False, "candidatos": len(sugeridos)}
    if saludo:
        return {"texto": _bienvenida(nombre), "derivar": False, "candidatos": None}
    return {"texto": FALLBACK, "derivar": False, "candidatos": 0}


def _precio_txt(it: dict) -> str:
    p = it.get("precio")
    if p in (None, "", 0):
        return "consultá el precio"
    try:
        return f"{int(p):,} gs".replace(",", ".")
    except Exception:
        return f"{p} gs"


def _respuesta_productos(items: list) -> str:
    """Respuesta armada (sin IA) para ofrecer productos con foto y precio."""
    if len(items) == 1:
        it = items[0]
        t = f"Creo que buscás esto: *{it['nombre']}* — {_precio_txt(it)}."
        if productos.foto_url(it):
            t += f"\n📷 {productos.foto_url(it)}"
        t += "\n¿Es este? Si querés te doy más datos o te paso con un vendedor 🙂"
        return t
    t = "Encontré estas opciones 👇\n"
    for it in items[:4]:
        t += f"\n• *{it['nombre']}* — {_precio_txt(it)}"
        if productos.foto_url(it):
            t += f"\n  📷 {productos.foto_url(it)}"
    t += "\n\n¿Cuál te interesa?"
    return t


async def procesar_y_responder(mensaje: str, return_url: str, data: dict):
    """Tarea de fondo: decide y contesta a Kommo. Si corresponde derivar, manda
    también (en el mismo mensaje) el enlace al vendedor de turno."""
    ad_id = kommo.extraer_ad_id(data)
    nombre = ""
    if isinstance(data, dict):
        nombre = data.get("nombre") or data.get("name") or ""
    res = await procesar(mensaje, ad_id=ad_id, nombre=nombre)
    await kommo.responder(return_url, res["texto"])
