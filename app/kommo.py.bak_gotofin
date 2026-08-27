# -*- coding: utf-8 -*-
"""
Integración con Kommo (Salesbot / widget_request).

Flujo (según la doc de "private chatbot integration"):
1. Kommo hace POST a nuestro /webhook con { token(JWT), data:{message,...}, return_url }.
2. Debemos responder 200 en menos de 2 segundos (solo el ACK).
3. De forma asíncrona, hacemos POST al return_url con { data:{message}, execute_handlers:[...] }
   para que el bot le muestre el mensaje al cliente y continúe.

El JWT viene firmado con la CLAVE SECRETA de la integración (KOMMO_SECRET_KEY);
lo validamos para asegurarnos de que el pedido viene de Kommo y no de un tercero.
"""

import os
import httpx

try:
    import jwt  # PyJWT
except Exception:  # pragma: no cover
    jwt = None

from .config import cfg


def verificar_token(token: str):
    """Devuelve el payload si el JWT es válido, o None. Si no hay clave secreta
    configurada, no se valida (devuelve {} para no bloquear las pruebas)."""
    if not cfg.KOMMO_SECRET_KEY:
        return {}
    if not token or jwt is None:
        return None
    try:
        return jwt.decode(
            token,
            cfg.KOMMO_SECRET_KEY,
            algorithms=["HS256", "HS512"],
            options={"verify_aud": False, "verify_exp": False},
        )
    except Exception:
        return None



def _trocear(texto, limite=80, max_trozos=10):
    """Kommo limita cada handler 'show' a 80 caracteres. Partimos el texto en
    trozos de <= limite respetando palabras (y cortando duro palabras larguisimas)."""
    trozos, actual = [], ""
    for p in (texto or "").split():
        while len(p) > limite:
            if actual:
                trozos.append(actual); actual = ""
            trozos.append(p[:limite]); p = p[limite:]
        if len(actual) + (1 if actual else 0) + len(p) <= limite:
            actual = (actual + " " + p) if actual else p
        else:
            trozos.append(actual); actual = p
        if len(trozos) >= max_trozos:
            break
    if actual and len(trozos) < max_trozos:
        trozos.append(actual)
    return trozos[:max_trozos] or [(texto or "")[:limite]]

async def responder(return_url: str, mensaje: str):
    """Envía la respuesta del agente de vuelta a Kommo, que se la muestra al
    cliente. Se manda como un ÚNICO mensaje (un solo cobro de WhatsApp)."""
    if not return_url or not mensaje:
        return False

    # MODO de respuesta (se elige con la variable de entorno KOMMO_MODO):
    #   "externo" (por defecto) -> handler send_external_message: manda UN mensaje
    #                              real al cliente por su canal (WhatsApp). Sin limite
    #                              de largo y sin necesitar pasos extra en el bot.
    #   "data"    -> no manda handler; deja el texto en data.message para que un paso
    #                "Enviar mensaje" del bot lo envie con {{json.message}}.
    #   "show"    -> parte el texto en globitos de <=80c (handler show). Ultimo recurso.
    modo = (os.getenv("KOMMO_MODO", "show") or "show").strip().lower()

    if modo == "show":
        trozos = _trocear(mensaje, 80, 10)
        handlers = [{"handler": "show", "params": {"type": "text", "value": t}} for t in trozos]
    elif modo == "data":
        handlers = []  # el texto viaja solo en data.message; lo envia un paso del bot
    else:  # "externo": send_external_message (el correcto para mensajes reales)
        params = {
            "message": {"type": "external", "text": mensaje},
            "recipient": {"type": "main_contact", "way_of_communication": "over_all"},
        }
        canal = (os.getenv("KOMMO_CHANNEL_ID", "") or "").strip()
        if canal:
            try:
                params["channels"] = [{"id": int(canal)}]
            except Exception:
                params["channels"] = [{"id": canal}]
        handlers = [{"handler": "send_external_message", "params": params}]

    payload = {"data": {"message": mensaje}, "execute_handlers": handlers}
    print(f"[RESPONDER] modo={modo} | handlers={len(handlers)} | len_msg={len(mensaje)}", flush=True)
    headers = {"Accept": "application/json"}
    if cfg.KOMMO_TOKEN:
        headers["Authorization"] = f"Bearer {cfg.KOMMO_TOKEN}"
    try:
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.post(return_url, json=payload, headers=headers)
            print(f"[RESPONDER] POST return_url -> HTTP {r.status_code} | "
                  f"auth={'si' if cfg.KOMMO_TOKEN else 'NO'} | resp={r.text[:300]!r}", flush=True)
            return r.status_code < 400
    except Exception as e:
        print(f"[RESPONDER] ERROR al postear al return_url: {e}", flush=True)
        return False


def extraer_ad_id(data: dict) -> str:
    """Intenta sacar el identificador del anuncio de Meta que Kommo pasa en el
    payload. El nombre exacto del campo se define en el flujo del Salesbot
    (ej.: se manda como data.ad_id o data.source_id). Probamos varios.

    Para que esto funcione, en el Salesbot hay que incluir el campo del anuncio
    dentro del 'data' que se envía al webhook (paso de configuración en Kommo).
    """
    if not isinstance(data, dict):
        return ""
    for k in ("ad_id", "source_id", "referral", "ad", "campaign", "utm_content"):
        v = data.get(k)
        if v:
            return str(v)
    return ""
