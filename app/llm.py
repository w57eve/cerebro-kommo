# -*- coding: utf-8 -*-
"""
Capa de IA (Anthropic). Se usa SOLO cuando las reglas no alcanzan.

Ahorro de tokens:
- El bloque de sistema (base de conocimiento + instrucciones) va marcado con
  prompt caching (cache_control). Así, en llamadas repetidas, ese bloque grande
  se cobra a precio de "cache read" (mucho más barato) en vez de recobrarlo entero.
- Se usa el modelo barato (Haiku) por defecto.
- max_tokens acotado: respuestas cortas = menos costo y menos mensajes.
"""

try:
    from anthropic import Anthropic
except Exception:  # el paquete se instala en Render; localmente puede faltar
    Anthropic = None

from .config import cfg

_cliente = (
    Anthropic(api_key=cfg.ANTHROPIC_API_KEY)
    if (Anthropic is not None and cfg.ANTHROPIC_API_KEY)
    else None
)


def disponible() -> bool:
    return _cliente is not None


def responder(sistema: str, contexto: str, mensaje: str, modelo: str = None) -> str:
    """Llamada síncrona a Anthropic. Desde el código async se invoca con
    asyncio.to_thread(...) para no bloquear el event loop."""
    if _cliente is None:
        return ""
    sys_blocks = [
        {
            "type": "text",
            "text": sistema,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    contenido = ""
    if contexto:
        contenido += f"[Contexto interno, no lo repitas literal]\n{contexto}\n\n"
    contenido += f"Mensaje del cliente:\n{mensaje}"
    try:
        r = _cliente.messages.create(
            model=modelo or cfg.ANTHROPIC_MODEL,
            max_tokens=cfg.MAX_TOKENS,
            system=sys_blocks,
            messages=[{"role": "user", "content": contenido}],
        )
        return "".join(
            b.text for b in r.content if getattr(b, "type", None) == "text"
        ).strip()
    except Exception:
        return ""
