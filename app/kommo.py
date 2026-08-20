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
            algorithms=["HS256"],
            options={"verify_aud": False, "verify_exp": False},
        )
    except Exception:
        return None


async def responder(return_url: str, mensaje: str):
    """Envía la respuesta del agente de vuelta a Kommo, que se la muestra al
    cliente. Se manda como un ÚNICO mensaje (un solo cobro de WhatsApp)."""
    if not return_url or not mensaje:
        return False
    payload = {
        "data": {"message": mensaje},
        "execute_handlers": [
            {
                "handler": "show",
                "params": {"type": "text", "value": mensaje},
            }
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=10) as cli:
            r = await cli.post(return_url, json=payload)
            return r.status_code < 400
    except Exception:
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
