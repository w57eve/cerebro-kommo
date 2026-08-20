# -*- coding: utf-8 -*-
"""
Configuración del cerebro. TODO se lee de variables de entorno, así que en
Render se cargan como "Environment Variables" y nunca quedan en el código.

Ninguna clave va escrita acá. Las que son secretas (token de Kommo, API key de
Anthropic, clave secreta de la integración) SOLO se cargan en Render.
"""

import os


def _bool(v: str, defecto=False):
    if v is None:
        return defecto
    return str(v).strip().lower() in ("1", "true", "si", "sí", "yes", "on")


class Config:
    # --- Anthropic (la "nafta" del agente) ---
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    # Modelo barato por defecto (respuestas normales). Alias estable.
    ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5")
    # Modelo más capaz para casos difíciles (opcional; hoy no se usa salvo que
    # se active en el agente). Alias estable.
    ANTHROPIC_MODEL_COMPLEJO = os.getenv("ANTHROPIC_MODEL_COMPLEJO", "claude-sonnet-4-6")
    MAX_TOKENS = int(os.getenv("MAX_TOKENS", "450"))

    # --- Kommo ---
    # Subdominio de tu cuenta, ej: "shoppingasia.kommo.com"
    KOMMO_SUBDOMAIN = os.getenv("KOMMO_SUBDOMAIN", "")
    # Token de larga duración (para llamar a la API v4 de Kommo si hace falta).
    KOMMO_TOKEN = os.getenv("KOMMO_TOKEN", "")
    # Clave secreta de la integración privada: sirve para validar el JWT que
    # Kommo manda en cada webhook (widget_request). Si se deja vacía, no se
    # valida (útil para probar, NO recomendado en producción).
    KOMMO_SECRET_KEY = os.getenv("KOMMO_SECRET_KEY", "")

    # --- Datos públicos de Shopping Asia ---
    SITIO_WEB = os.getenv("SITIO_WEB", "https://www.shoppingasia.com.py")
    CATALOGO_URL = os.getenv("CATALOGO_URL", "https://catalogo.shoppingasia.com.py")
    GET_PRODUCTOS = os.getenv(
        "GET_PRODUCTOS", "https://www.shoppingasia.com.py/get-productos"
    )
    # Categorías a indexar del sitio (IDs separados por coma). 7 = calzados.
    # Se amplía agregando IDs: "7,3,10,..."
    CATEGORIAS = os.getenv("CATEGORIAS_INDEX", "7")
    # Cada cuántos minutos se refresca el índice de precios/productos en memoria.
    REFRESCO_MIN = int(os.getenv("REFRESCO_CATALOGO_MIN", "30"))

    # --- Vendedores (dato NO sensible; se puede sobrescribir por env) ---
    # Formato: "Nombre:numero,Nombre:numero" (número sin + ni espacios).
    VENDEDORES = os.getenv(
        "VENDEDORES",
        "Erika:595984356888,Analía:595976655588,Fabián:595976667222",
    )

    # Hora (0-23) hasta la que hay atención con asesor. Después de esta hora el
    # agente avisa que la atención humana es hasta las 19 y deja el botón igual.
    HORA_CIERRE_ONLINE = int(os.getenv("HORA_CIERRE_ONLINE", "19"))
    # Zona horaria de Paraguay (UTC-4 / UTC-3 según DST). Se usa solo para el
    # mensaje de "hasta las 19h"; no es crítico.
    TZ_OFFSET = int(os.getenv("TZ_OFFSET", "-4"))

    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


cfg = Config()
