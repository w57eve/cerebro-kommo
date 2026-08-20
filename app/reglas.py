# -*- coding: utf-8 -*-
"""
Motor de reglas de 0 tokens.

Antes de gastar un solo token de IA, intentamos responder con reglas: saludos,
horarios, ubicación, medios de pago, envíos, mayorista, cambios, y el pedido de
"hablar con una persona". Si una regla matchea, se responde directo (gratis).

IMPORTANTE (costo WhatsApp): cada mensaje que sale de la línea oficial se cobra.
Por eso las respuestas de reglas son de UN solo mensaje, completas y cortas.

Cómo crece: se agregan entradas a REGLAS con las consultas más repetidas del día
a día (y las que salgan de los 1.500 chats viejos). Cada regla nueva = más
respuestas a 0 tokens = menos costo de IA.
"""

import re
import unicodedata


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFD", t or "")
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")  # saca tildes
    return t.lower().strip()


# Cada regla: (lista de patrones/keywords, respuesta). Si CUALQUIER patrón
# aparece en el mensaje normalizado, matchea.
REGLAS = [
    (
        ["hola", "buenas", "buen dia", "buenos dias", "buenas tardes",
         "buenas noches", "que tal"],
        "¡Hola! Bienvenido/a a Shopping Asia 🙌 ¿En qué te puedo ayudar? "
        "Contame qué producto estás buscando y te paso precio y foto.",
    ),
    (
        ["horario", "abierto", "abren", "cierran", "atienden", "hasta que hora",
         "feriado", "domingo", "que hora abren"],
        "Estamos abiertos todos los días de 9 a 22 hs, incluyendo domingos y "
        "feriados. La atención con un asesor es hasta las 19 hs; fuera de ese "
        "horario te puedo ayudar igual por acá.",
    ),
    (
        ["donde estan", "direccion", "ubicacion", "ubicados", "como llego",
         "retiro", "retirar", "sucursal", "local"],
        "Estamos en Av. Eusebio Ayala 1451, frente a la comisaría séptima, "
        "Asunción. Podés pagar y pasar a retirar, o te lo enviamos. ¿Querés "
        "que te ayude con algún producto?",
    ),
    (
        ["medios de pago", "como pago", "formas de pago", "pagar", "tarjeta",
         "transferencia", "efectivo", "que aceptan"],
        "Aceptamos efectivo, transferencia, QR y tarjetas. En transferencia y "
        "QR se confirma el pago antes de enviar; también podés pagar en "
        "efectivo o tarjeta al recibir. ¿Te ayudo con tu pedido?",
    ),
    (
        ["envio", "envios", "delivery", "mandan", "hacen envio", "cuanto sale el envio",
         "envian", "a todo el pais"],
        "Sí, hacemos envíos. Desde una compra mínima de 100.000 gs: hasta 15 km "
        "cuesta 20.000 gs y sube 5.000 gs cada 5 km más. Desde 150.000 gs el "
        "envío es gratis hasta 15 km. También enviamos a todo el país por "
        "transportadora (se abona el envío por adelantado). ¿Qué estás buscando?",
    ),
    (
        ["mayorista", "por mayor", "descuento por cantidad", "precio mayorista",
         "al por mayor"],
        "Sí, tenemos descuentos por escala según el monto: desde 1.500.000 gs "
        "2%, 4.000.000 gs 3%, 5.500.000 gs 4%, 6.000.000 gs 6%, 7.000.000 gs "
        "7%, 8.000.000 gs 8%, 9.000.000 gs 9% y desde 10.000.000 gs 10%. "
        "¿Querés que te arme un presupuesto?",
    ),
    (
        ["cambio", "cambiar", "devolucion", "devolver", "garantia"],
        "Tenés 48 hs para cambios o devoluciones, presentando el ticket y el "
        "producto en su caja y con las etiquetas intactas. Si tenés algún "
        "inconveniente puntual, te derivo con un asesor.",
    ),
]

# Pedido explícito de hablar con una persona -> se maneja como derivación.
DERIVAR = ["hablar con", "un vendedor", "una persona", "un asesor", "asesor",
           "atencion humana", "hablar con alguien", "vendedor", "vendedora"]


def responder(mensaje: str):
    """Devuelve un dict con la respuesta si alguna regla matchea, o None.

    - {"tipo": "texto", "texto": ...}   respuesta directa (0 tokens)
    - {"tipo": "derivar", "texto": ...} el cliente pidió hablar con una persona
    """
    m = _norm(mensaje)
    if not m:
        return None

    for claves in [DERIVAR]:
        if any(k in m for k in claves):
            return {"tipo": "derivar", "texto": ""}

    for claves, resp in REGLAS:
        if any(k in m for k in claves):
            return {"tipo": "texto", "texto": resp}

    return None
