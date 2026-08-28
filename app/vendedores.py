# -*- coding: utf-8 -*-
"""
Rotación de vendedores y armado del botón / enlace "Hablar con {vendedor}".

La derivación va al WhatsApp PERSONAL del vendedor (wa.me), que es WhatsApp
normal y NO se cobra por la API. El agente resuelve o deriva rápido para que la
menor cantidad de mensajes salga de la línea oficial (esa sí se cobra).
"""

from urllib.parse import quote

from .config import cfg

_lista = []
for par in cfg.VENDEDORES.split(","):
    par = par.strip()
    if ":" in par:
        nombre, numero = par.split(":", 1)
        nombre, numero = nombre.strip(), numero.strip()
        if nombre and numero:
            _lista.append((nombre, numero))

# Round-robin en memoria. Con varios workers no es perfectamente parejo, pero
# la distribución "oficial" y pareja de leads ya la hace Kommo (Round Robin);
# esto es solo para elegir a quién mostrar en el botón.
# Rotación EQUITATIVA: el contador se guarda en disco para que un reinicio o
# deploy no vuelva a arrancar siempre por el primer vendedor de la lista.
_RUTA_RR = "/tmp/vendedor_rr.txt"


def _cargar_i() -> int:
    try:
        return int(open(_RUTA_RR).read().strip())
    except Exception:
        import random
        return random.randrange(len(_lista)) if _lista else 0


def _guardar_i(i: int):
    try:
        with open(_RUTA_RR, "w") as f:
            f.write(str(i))
    except Exception:
        pass


_estado = {"i": _cargar_i()}
_asignados = {}   # lead_id -> (nombre, numero): un cliente = UN solo vendedor


def siguiente(lead_id: str = ""):
    """Vendedor para este cliente. PEGAJOSO por lead: si a este cliente ya se
    le asignó un vendedor en esta charla, se repite el MISMO (nunca dos
    vendedores distintos para la misma persona)."""
    if not _lista:
        return None
    lead_id = str(lead_id or "")
    if lead_id and lead_id in _asignados:
        return _asignados[lead_id]
    nombre, numero = _lista[_estado["i"] % len(_lista)]
    _estado["i"] += 1
    _guardar_i(_estado["i"])
    if lead_id:
        if len(_asignados) > 5000:
            _asignados.clear()
        _asignados[lead_id] = (nombre, numero)
    return nombre, numero


def enlace(numero: str, texto: str) -> str:
    return f"https://wa.me/{numero}?text={quote(texto)}"


def mensaje_derivacion(sku: str = "", consulta: str = "", lead_id: str = "") -> dict:
    """Arma el texto para el cliente + el enlace al vendedor de turno.

    Devuelve {"texto": <lo que ve el cliente, con el link>, "vendedor": nombre}.
    """
    sig = siguiente(lead_id)
    if not sig:
        return {
            "texto": "En un momento te contacta un asesor. ¿Me dejás tu "
                     "consulta así te responden más rápido?",
            "vendedor": None,
        }
    nombre, numero = sig
    # Mensaje pre-escrito que el cliente le manda al vendedor (incluye SKU/consulta).
    partes = [f"Hola {nombre}, vengo de Shopping Asia."]
    if sku:
        partes.append(f"Me interesa el SKU {sku}.")
    if consulta:
        partes.append(f"Consulta: {consulta}")
    pre = " ".join(partes)
    link = enlace(numero, pre)
    texto = (
        f"Te paso con {nombre}, de nuestro equipo, que te va a atender 💬\n"
        f"Tocá este enlace y te lleva directo al WhatsApp de {nombre} 👇\n"
        f"{link}"
    )
    return {"texto": texto, "vendedor": nombre}
