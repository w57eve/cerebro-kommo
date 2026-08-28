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


# ── Saludos ──
SALUDOS = ["hola", "holis", "buenas", "buen dia", "buenos dias", "buenas tardes",
           "buenas noches", "que tal", "buenass", "hello", "ola"]

# Palabras que NO cuentan como "consulta" (saludo + cortesía + charla) para
# decidir si el mensaje es SOLO un saludo o si además trae un pedido real.
_IGNORAR = {
    "hola", "holis", "buenas", "buenos", "buen", "dia", "dias", "tarde",
    "tardes", "noche", "noches", "que", "tal", "como", "estan", "estas",
    "esta", "va", "todo", "bien", "gracias", "por", "favor", "porfa",
    "porfavor", "che", "ok", "saludos", "disculpe", "disculpa", "perdon",
    "amigo", "amiga", "senor", "senora", "seno", "estimado", "estimada",
    "hello", "hi", "ola", "y", "el", "la", "me", "puedo", "podria",
}


def es_saludo(mensaje: str) -> bool:
    n = _norm(mensaje)
    return any(s in n for s in SALUDOS)


def solo_saludo(mensaje: str) -> bool:
    """True si el mensaje es SOLO un saludo/cortesía (sin pedido concreto)."""
    n = _norm(mensaje)
    n = re.sub(r"[^\w\s]", " ", n)
    palabras = [w for w in n.split() if len(w) > 1 and w not in _IGNORAR]
    return len(palabras) == 0


# Cada regla: (lista de patrones/keywords, respuesta). Si CUALQUIER patrón
# aparece en el mensaje normalizado, matchea.
REGLAS = [
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
        ["siguen las ofertas", "sigue la oferta", "siguen la oferta",
         "sigue esa oferta", "aun tienen la oferta", "todavia tienen la oferta",
         "todavia esta la oferta", "sigue vigente", "esta vigente la oferta",
         "siguen las promos", "sigue la promo", "siguen los precios"],
        "¡Sí, así es! Siguen las ofertas 🙌 ¿Qué publicación viste? Decime el "
        "producto o mandame una captura y te paso precio y disponibilidad al "
        "toque.",
    ),
    (
        ["como comprar", "como compro", "como hago el pedido", "como puedo comprar",
         "como podemos comprar", "como hago para comprar", "como pedir"],
        "¡Es fácil! 1) Elegí el producto (decime el nombre, mandame una foto o "
        "el SKU y te paso precio y stock). 2) Confirmamos disponibilidad. "
        "3) Elegís retiro en el local (Av. Eusebio Ayala 1451, Asunción) o envío "
        "a todo el país (compra mínima 100.000 gs). 4) Pagás por transferencia, "
        "QR, tarjeta o efectivo. ¿Qué producto te interesa?",
    ),
    (
        ["por que mas caro", "porque mas caro", "por que algunos son mas caros",
         "diferencia de precio", "por que la diferencia"],
        "¡Buena pregunta! Las diferencias de precio se dan por la marca, el "
        "material, el origen o el modelo, aunque parezcan similares. Decime "
        "cuáles estás comparando y te explico la diferencia puntual.",
    ),
    (
        ["cambio", "cambiar", "devolucion", "devolver", "garantia"],
        "Tenés 48 hs para cambios o devoluciones, presentando el ticket y el "
        "producto en su caja y con las etiquetas intactas. Si tenés algún "
        "inconveniente puntual, te derivo con un asesor.",
    ),
]

# Pedido explícito de hablar con una persona -> se maneja como derivación.
# También QUEJAS/RECLAMOS: eso siempre lo atiende una persona, nunca el bot.
DERIVAR = ["hablar con", "un vendedor", "una persona", "un asesor", "asesor",
           "atencion humana", "hablar con alguien", "vendedor", "vendedora",
           "derivame", "derivar", "pasame con", "que me atienda", "personalizada",
           "queja", "reclamo", "reclamar", "estafa", "no llego", "no me llego",
           "nunca llego", "defectuoso", "fallado", "mal estado", "vino roto",
           "llego roto", "denuncia", "denunciar", "me cobraron",
           # frustración con el bot -> a una persona, sin discutir
           "no me sirve", "no es eso", "no me entendes", "no me estas entendiendo",
           "no entendes nada", "no es lo que busco", "no era eso", "ya te dije",
           "desastre", "inutil", "pesimo", "que malo", "no sirve", "no sirven"]


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


# ── Notas de voz / audio ──
# WhatsApp+Kommo nos mandan solo un indicador (ej. 🔊) cuando llega una nota de
# voz; no recibimos el archivo, asi que todavia no podemos "escucharlas".
_AUDIO_MARCAS = ("\U0001F50A", "\U0001F3A4", "\U0001F399", "\U0001F3A7", "\U0001F3B5", "\U0001F3B6")


def es_audio(mensaje: str) -> bool:
    """True si el mensaje es SOLO un indicador de nota de voz (sin texto real)."""
    s = (mensaje or "").strip()
    if not s:
        return False
    solo = "".join(ch for ch in s if ch.isalnum())
    return (not solo) and any(m in s for m in _AUDIO_MARCAS)
