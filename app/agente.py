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

from . import busqueda, conocimiento, kommo, llm, productos, reglas, vendedores

# ── Higiene de salida ──────────────────────────────────────────────────────
_URL_RE = _re.compile(r"https?://[^\s)\]]+")

# Prefijos de links LEGÍTIMOS (todo lo demás se considera inventado y se borra)
# OJO: /buscador NO está acá a propósito: solo se permite el link de búsqueda
# EXACTO que calcula el servidor (va como 'permitidos_extra'), porque la IA
# tendía a armar buscadores con la frase entera del cliente.
_LINKS_BASE = (
    "https://www.shoppingasia.com.py/storage/",   # fotos originales del catálogo
    "https://cerebro-kommo.onrender.com/foto/",   # fotos optimizadas (miniatura)
    "https://catalogo.shoppingasia.com.py",       # catálogo de pautas
    "https://wa.me/",                             # derivación a vendedor
)


def _limpiar_salida(texto: str, permitidos_extra=()) -> str:
    """Borra meta-notas entre corchetes y CUALQUIER link que no sea legítimo
    (el bot viejo inventaba URLs de producto rotos: eso no puede volver a salir)."""
    # 1) meta-notas: [cualquier cosa] (la etiqueta [DERIVAR] ya fue procesada)
    texto = _re.sub(r"\[[^\]\n]*\]", "", texto)
    # 2) links: solo los permitidos; la línea con un link inventado se borra entera
    permitidos = _LINKS_BASE + tuple(permitidos_extra)

    def _ok(u: str) -> bool:
        u = u.rstrip(".,;:!?")
        if u.rstrip("/") == "https://www.shoppingasia.com.py":
            return True   # la portada sí existe
        return any(u.startswith(p) for p in permitidos)

    lineas = []
    for ln in texto.splitlines():
        urls = _URL_RE.findall(ln)
        if urls and not all(_ok(u) for u in urls):
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
    "¡Hola! 🎧 Me llegó tu audio, pero por acá todavía no puedo "
    "escucharlos. ¿Me lo escribís en un mensajito así te ayudo enseguida? "
    "Si preferís, te paso con un asesor 🙌"
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
- Cuando tengas el producto (o candidatos), mostralo con su **precio** y pasá el
  **link de la foto** que te doy en el contexto. Mostrar la foto adentro del chat
  es lo más práctico; la mayoría de los clientes no quieren salir a la web.
- Si hay un solo candidato claro: presentalo confirmando ("¿es este? [foto]").
  Si hay varios: mostrá 3–4 opciones con foto y que elija. La búsqueda no es
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
- **FOTOS: mandá SIEMPRE el link PELADO** (ej. https://www.shoppingasia.com.py/...jpg),
  tal cual, en su propia línea. NUNCA uses markdown ni corchetes: nada de
  ![texto](url) ni [texto](url). WhatsApp NO renderiza markdown (se ve roto); en
  cambio, un link pelado lo previsualiza solo. Un link por línea.

Reglas duras (no las rompas nunca):
- No inventás precios, stock ni políticas. Si no está en el catálogo ni en los
  datos que te paso, NO lo afirmes.
- **PRECIOS: copialos TAL CUAL** vienen en el contexto (ya están formateados,
  ej. "240.000 gs"). No los recalcules, no los redondees, y JAMÁS le pongas a
  un producto el precio de otro: cada precio va pegado a SU producto de la
  lista del contexto. Si dudás, no des el precio y ofrecé confirmarlo.
- **FRUSTRACIÓN = DERIVAR, nunca discutir.** Si el cliente muestra molestia
  ("no es eso", "no me entendés", "ya te dije", repite lo mismo) o después de
  DOS intentos seguís sin acertar el producto, no sigas insistiendo: disculpa
  breve y [DERIVAR]. Un cliente peleando con un bot es una venta perdida.
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
                   historial=None, lead_id: str = "", origen: str = "") -> dict:
    """Decide la respuesta. Devuelve {"texto", "derivar", "candidatos"}.

    historial: lista de intercambios previos de ESTA charla, cada uno
    {"cliente": ..., "agente": ...}. Le da memoria a la conversación.

    Clave para no parecer un bot: si el cliente saluda Y pregunta algo en el
    mismo mensaje, saludamos (por su nombre si lo tenemos) y en el MISMO mensaje
    contestamos/mostramos los productos. No devolvemos solo un saludo.
    """
    # Nota de voz: no podemos escucharla todavia -> pedimos texto / derivamos.
    if reglas.es_audio(mensaje):
        return {"texto": AUDIO_MSG, "derivar": False, "candidatos": None}

    saludo = reglas.es_saludo(mensaje)

    # Solo un saludo (sin pedido) -> bienvenida y a esperar el pedido.
    # PERO si viene de una PAUTA, no: ahí el agente abre directo con el
    # producto/sección del anuncio (sigue al LLM con ese contexto).
    if reglas.solo_saludo(mensaje) and not ad_id:
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
    elif (origen or "").lower() in ("facebook", "instagram", "instagram_business"):
        contexto += (
            f"El chat entró por {origen} (desde una publicación/pauta de redes, "
            "no sabemos cuál exactamente). Si el cliente pide 'más información', "
            "'la oferta' o 'lo del anuncio', se refiere a LO QUE VIO en esa "
            "publicación: casi siempre son los productos del CATÁLOGO CHICO "
            "pautado. Respondé así: preguntá cuál producto vio (o pedile que "
            "mande la foto/captura) Y en el MISMO mensaje pasale "
            "https://catalogo.shoppingasia.com.py explicando que ahí están las "
            "ofertas publicadas (botón 'Hacer pedido' lo trae de vuelta acá). "
            "NO mandes ofertas genéricas de la página web.\n")

    sugeridos = []
    sku = productos.extraer_sku(mensaje)
    if sku:
        it = await productos.por_sku(sku)
        if it:
            sugeridos = [it]
            contexto += "Producto confirmado (podés dar precio/foto):\n" + productos.a_texto(it) + "\n"
        else:
            contexto += (f"El SKU {sku} no está en el catálogo. No afirmes que "
                         "existe; ofrecé buscarlo o derivar.\n")
    else:
        cand = await productos.buscar(mensaje, limite=5)
        sugeridos = cand
        if len(cand) == 1:
            contexto += "Posible producto (confirmá con el cliente):\n" + productos.a_texto(cand[0]) + "\n"
        elif len(cand) > 1:
            contexto += ("Varios candidatos (mostrá 3–4 con su foto y pedí que "
                         "elija, no adivines):\n")
            contexto += "\n".join(productos.a_texto(c) for c in cand) + "\n"

    # VOCABULARIO DE PAUTAS: términos que la gente trae de la publicidad y que
    # NO existen en el catálogo grande ni en el buscador de la web — esos
    # productos viven en el CATÁLOGO CHICO pautado. Valor = término para el
    # link opcional del buscador de la web. (Se amplía con cada pauta nueva.)
    _PAUTA_TERMINOS = {
        "todo terreno": "calzado",
        "todoterreno": "calzado",
        "irun": "calzado",
        "i run": "calzado",
    }
    _msg_n = busqueda.normalizar(mensaje)
    pauta_term = next((t for t in _PAUTA_TERMINOS if t in _msg_n), "")
    if pauta_term:
        contexto += (
            f"OJO: el cliente menciona '{pauta_term}', que es de las PAUTAS y "
            "NO está en el catálogo grande ni en la web con ese nombre: esos "
            "modelos están en el CATÁLOGO CHICO. Respondé así: 1) decile que "
            "esos modelos están en nuestro catálogo rápido y pasale el link "
            "https://catalogo.shoppingasia.com.py explicando en simple que "
            "ahí ve modelos y talles y que al tocar 'Hacer pedido' vuelve acá "
            "con el calzado elegido; 2) si es calzado, recordá la horma chica "
            "(conviene un número más); 3) OPCIONAL al final: el link 'ver más' "
            "de la web por si quiere ver más calzados. NO digas 'no tenemos'.\n")

    # Link "ver más": resultados de ESTA búsqueda en la web (jerga ya mapeada,
    # ej. championes -> calzado). VERIFICADO contra el catálogo: corrige tipeos
    # (michila -> mochila) y descarta palabras que no existen en ningún producto.
    _idx = productos.indice_actual()
    if pauta_term:
        term_web = _PAUTA_TERMINOS[pauta_term]
    else:
        term_web = _idx.termino_web(mensaje) if _idx else busqueda.termino_web(mensaje)
    link_web = ""
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
            # Links legítimos de ESTA respuesta: fotos de los candidatos y el
            # link de búsqueda EXACTO calculado por el servidor (ningún otro).
            permitidos = tuple(productos.foto_url(it) for it in sugeridos
                               if it.get("imagenes"))
            if link_web:
                permitidos += (link_web,)
            derivar = "[DERIVAR]" in texto
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
