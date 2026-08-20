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

from . import conocimiento, kommo, llm, productos, reglas, vendedores

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

Reglas duras (no las rompas nunca):
- No inventás precios, stock ni políticas. Si no está en la base ni en los datos
  que te paso, NO lo afirmes: ofrecé buscarlo o derivá.
- Precio/producto SOLO si te lo paso confirmado en el contexto. Si la búsqueda por
  foto o nombre no es clara, NO cantes un producto: mostrá 2–3 opciones y pedí que
  el cliente confirme, o pedí el SKU. La foto es una sugerencia, no un veredicto.
- Orden para encontrar un artículo: primero el catálogo, si no está lo buscás en la
  web, y si tampoco aparece (a veces son artículos nuevos) DERIVÁS a un vendedor.
  El catálogo NO tiene todo (ej.: las prendas no están en el catálogo).
- Respondé en UN solo mensaje, completo y no muy largo. Nada de mandar varios
  mensajes seguidos.
- Si el cliente quiere cerrar la compra o hablar con una persona, derivá al
  vendedor (te lo indica el sistema con un botón aparte).

Datos de la empresa (horarios, pagos, envíos, etc.) están en la base de abajo.
"""


def _sistema() -> str:
    return _INSTRUCCIONES + "\n\n===== BASE DE CONOCIMIENTO =====\n" + conocimiento.BASE


SISTEMA = _sistema()


async def procesar(mensaje: str, ad_id: str = "") -> dict:
    """Decide la respuesta. Devuelve:
       {"texto": str, "derivar": bool}
    """
    # 1) Reglas de 0 tokens
    r = reglas.responder(mensaje)
    if r and r["tipo"] == "texto":
        return {"texto": r["texto"], "derivar": False}
    if r and r["tipo"] == "derivar":
        sku = productos.extraer_sku(mensaje) or ""
        d = vendedores.mensaje_derivacion(sku=sku, consulta=mensaje[:180])
        return {"texto": d["texto"], "derivar": True}

    # 2) Datos de producto (para dárselos al LLM como contexto confirmado)
    contexto = ""
    ctx_ad = conocimiento.contexto_anuncio(ad_id)
    if ctx_ad:
        contexto += ctx_ad + "\n"

    sku = productos.extraer_sku(mensaje)
    if sku:
        it = await productos.por_sku(sku)
        if it:
            contexto += "Producto confirmado (podés dar precio/foto):\n" + productos.a_texto(it) + "\n"
        else:
            contexto += (f"El SKU {sku} no está en el índice del sitio. No "
                         "afirmes que existe; ofrecé buscarlo o derivar.\n")
    else:
        cand = await productos.buscar(mensaje, limite=3)
        if len(cand) == 1:
            contexto += "Posible producto (confirmá con el cliente):\n" + productos.a_texto(cand[0]) + "\n"
        elif len(cand) > 1:
            contexto += ("Varios candidatos parecidos (mostralos y pedí que "
                         "elija, no adivines):\n")
            contexto += "\n".join(productos.a_texto(c) for c in cand) + "\n"

    # 3) IA (solo si hay API key; si no, respuesta segura)
    if not llm.disponible():
        return {"texto": FALLBACK, "derivar": False}
    texto = await asyncio.to_thread(llm.responder, SISTEMA, contexto, mensaje)
    if not texto:
        return {"texto": FALLBACK, "derivar": False}
    return {"texto": texto, "derivar": False}


async def procesar_y_responder(mensaje: str, return_url: str, data: dict):
    """Tarea de fondo: decide y contesta a Kommo. Si corresponde derivar, manda
    también (en el mismo mensaje) el enlace al vendedor de turno."""
    ad_id = kommo.extraer_ad_id(data)
    res = await procesar(mensaje, ad_id=ad_id)
    await kommo.responder(return_url, res["texto"])
