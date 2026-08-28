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

from . import busqueda, conocimiento, kommo, llm, productos, reglas, vendedores

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


async def procesar(mensaje: str, ad_id: str = "", nombre: str = "") -> dict:
    """Decide la respuesta. Devuelve {"texto": str, "derivar": bool}.

    Clave para no parecer un bot: si el cliente saluda Y pregunta algo en el
    mismo mensaje, saludamos (por su nombre si lo tenemos) y en el MISMO mensaje
    contestamos/mostramos los productos. No devolvemos solo un saludo.
    """
    # Nota de voz: no podemos escucharla todavia -> pedimos texto / derivamos.
    if reglas.es_audio(mensaje):
        return {"texto": AUDIO_MSG, "derivar": False}

    saludo = reglas.es_saludo(mensaje)

    # Solo un saludo (sin pedido) -> bienvenida y a esperar el pedido.
    if reglas.solo_saludo(mensaje):
        return {"texto": _bienvenida(nombre), "derivar": False}

    pref = _prefijo_saludo(saludo, nombre)

    # 1) Reglas de 0 tokens (FAQ / derivar). Nota: el saludo ya NO corta acá.
    r = reglas.responder(mensaje)
    if r and r["tipo"] == "texto":
        return {"texto": pref + r["texto"], "derivar": False}
    if r and r["tipo"] == "derivar":
        sku = productos.extraer_sku(mensaje) or ""
        d = vendedores.mensaje_derivacion(sku=sku, consulta=mensaje[:180])
        return {"texto": pref + d["texto"], "derivar": True}

    # 2) Datos de producto (contexto para el LLM y para la respuesta templada)
    contexto = ""
    n_corto = _nombre_corto(nombre)
    if n_corto:
        contexto += (f"El cliente se llama {n_corto}. Si saludó, devolvé el "
                     "saludo por su nombre UNA vez.\n")
    ctx_ad = conocimiento.contexto_anuncio(ad_id)
    if ctx_ad:
        contexto += ctx_ad + "\n"

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

    # Link "ver más": resultados de ESTA búsqueda en la web (jerga ya mapeada,
    # ej. championes -> calzado). Solo para cuando el cliente quiere más variedad.
    term_web = busqueda.termino_web(mensaje)
    if term_web and not sku:
        from urllib.parse import quote as _q
        contexto += ("Link 'ver más' (resultados de esta búsqueda en la web): "
                     f"https://www.shoppingasia.com.py/buscador?q={_q(term_web)}\n")

    # 3) IA para redactar (tono humano). Si no hay IA o falla, respuesta templada.
    if llm.disponible():
        texto = await asyncio.to_thread(llm.responder, SISTEMA, contexto, mensaje)
        if texto:
            # El LLM pide derivar con la etiqueta [DERIVAR] al final.
            if "[DERIVAR]" in texto:
                texto = texto.replace("[DERIVAR]", "").strip()
                d = vendedores.mensaje_derivacion(
                    sku=(sku or ""), consulta=mensaje[:180])
                texto = (texto + "\n\n" + d["texto"]).strip()
                return {"texto": texto, "derivar": True}
            return {"texto": texto, "derivar": False}

    # Sin IA: si hay productos, los ofrecemos (0 tokens), con saludo si aplica.
    if sugeridos:
        return {"texto": pref + _respuesta_productos(sugeridos), "derivar": False}
    if saludo:
        return {"texto": _bienvenida(nombre), "derivar": False}
    return {"texto": FALLBACK, "derivar": False}


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
        if it.get("imagenes"):
            t += f"\n📷 {it['imagenes'][0]}"
        t += "\n¿Es este? Si querés te doy más datos o te paso con un vendedor 🙂"
        return t
    t = "Encontré estas opciones 👇\n"
    for it in items[:4]:
        t += f"\n• *{it['nombre']}* — {_precio_txt(it)}"
        if it.get("imagenes"):
            t += f"\n  📷 {it['imagenes'][0]}"
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
