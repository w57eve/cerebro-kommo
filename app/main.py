# -*- coding: utf-8 -*-
"""
Servidor del cerebro (FastAPI).

Endpoints:
- GET  /            -> estado simple
- GET  /health      -> healthcheck para Render
- POST /webhook     -> lo llama Kommo (Salesbot widget_request)
- POST /probar      -> para pruebas manuales sin Kommo (mandás {"mensaje": "..."})

Clave del webhook: contestamos 200 en menos de 2 segundos (solo el ACK) y el
trabajo real (pensar la respuesta + contestarle a Kommo) se hace en segundo plano.
"""

from fastapi import BackgroundTasks, FastAPI, Request

from . import agente, kommo
from .config import cfg

app = FastAPI(title="Cerebro de ventas — Shopping Asia")


@app.get("/")
async def raiz():
    return {"ok": True, "servicio": "cerebro-shoppingasia"}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "ia": "on" if cfg.ANTHROPIC_API_KEY else "off (falta ANTHROPIC_API_KEY)",
        "kommo_validacion": "on" if cfg.KOMMO_SECRET_KEY else "off",
    }


@app.post("/webhook")
async def webhook(request: Request, bg: BackgroundTasks):
    """Lo llama Kommo. Respondemos 200 ya mismo y procesamos en segundo plano."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    token = body.get("token", "")
    data = body.get("data") or {}
    return_url = body.get("return_url", "")

    # Validación del origen (JWT firmado con la clave secreta de la integración).
    if kommo.verificar_token(token) is None:
        # Firma inválida: no procesamos, pero devolvemos 200 para no reintentar.
        return {"status": "ignored", "reason": "token invalido"}

    mensaje = ""
    if isinstance(data, dict):
        mensaje = data.get("message") or data.get("text") or ""

    if return_url and mensaje:
        bg.add_task(agente.procesar_y_responder, mensaje, return_url, data)

    return {"status": "ok"}


@app.post("/probar")
async def probar(request: Request):
    """Prueba manual del cerebro sin Kommo:
        curl -X POST .../probar -H 'Content-Type: application/json' \
             -d '{"mensaje":"hacen envios?","ad_id":""}'
    """
    body = await request.json()
    mensaje = body.get("mensaje", "")
    ad_id = body.get("ad_id", "")
    res = await agente.procesar(mensaje, ad_id=ad_id)
    return res
