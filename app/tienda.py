# -*- coding: utf-8 -*-
"""
TIENDA PROVISORIA — categorías del catálogo completo (31/08/2026).

Mientras la página oficial esté caída, la "página" que se pasa a los clientes
es la tienda del cerebro (/tienda): todo el catálogo, con NUESTRO buscador,
navegable por categorías y con filtro opcional de categoría al buscar.

Las categorías son CURADAS (palabras como las dice el cliente); un producto
pertenece a una categoría si su nombre matchea alguna palabra (con los mismos
sinónimos e hiperónimos del buscador). Un producto puede estar en más de una.
"""

from . import busqueda

# Cada categoría: palabras clave (en lenguaje de cliente; el buscador les
# aplica sinónimos/hiperónimos, así "champion" también trae zapatillas).
CATEGORIAS = {
    "Calzados": ["calzado", "zapatilla", "champion", "botin", "chutera",
                 "sandalia", "chancla", "crocs", "zapato", "bota", "irun",
                 "mocasin", "alpargata", "pantufla"],
    "Ropa y Moda": ["remera", "camiseta", "vestido", "pantalon", "short",
                    "pollera", "campera", "buzo", "blusa", "camisa", "prenda",
                    "corpiño", "boxer", "media", "lenceria", "pijama",
                    "malla", "bikini", "jean", "blazer", "chaleco", "sueter",
                    "gorra", "bufanda", "cinturon", "poncho", "kimono",
                    "ropa"],
    "Carteras y Bolsos": ["cartera", "bolso", "mochila", "billetera",
                          "maleta", "morral", "riñonera", "neceser",
                          "portafolio", "valija"],
    "Mascotas": ["mascota", "perro", "gato", "arnes", "jaula", "gatera",
                 "rascador", "bebedero", "comedero", "pecera"],
    "Juguetes": ["juguete", "muñeca", "lego", "peluche", "princesa",
                 "rompecabezas", "bloques", "pistola de juguete", "carroza",
                 "dinosaurio", "sorpresita"],
    "Hogar y Cocina": ["olla", "sarten", "cafetera", "termo", "vaso", "plato",
                       "cuchillo", "taza", "jarra", "bandeja", "organizador",
                       "cortina", "sabana", "acolchado", "manta", "almohada",
                       "toalla", "espejo", "florero", "lampara", "velador",
                       "perchero", "canasto", "escoba", "balde", "colador",
                       "frasco", "mate", "bombilla", "yerbera", "guampa",
                       "molde", "cesto", "hielera", "cubiertos", "fuente"],
    "Electrónica": ["auricular", "parlante", "cargador", "cable", "camara",
                    "linterna", "ventilador", "secador", "plancha",
                    "licuadora", "batidora", "freidora", "aspiradora",
                    "pila", "usb", "bluetooth", "proyector", "microfono",
                    "teclado", "mouse", "smartwatch", "reloj", "foco",
                    "extractor", "calculadora"],
    "Belleza y Cuidado": ["perfume", "maquillaje", "labial", "rimel",
                          "sombra de ojos", "crema", "shampoo", "jabon",
                          "peine", "vincha", "esmalte", "pestaña",
                          "mascarilla", "serum", "desodorante", "brocha",
                          "cosmetiquera", "quitaesmalte", "acondicionador"],
    "Bebés y Niños": ["bebe", "pañal", "carrito de bebe", "cuna", "mamadera",
                      "chupete", "babero", "andador", "infantil"],
    "Deportes": ["pesa", "mancuerna", "soga", "bicicleta", "pelota",
                 "futbol", "colchoneta", "tobillera", "rodillera",
                 "patineta", "patin", "guante de arquero", "silbato"],
    "Fiesta y Cotillón": ["globo", "disfraz", "cotillon", "vela de cumpleaños",
                          "guirnalda", "confeti", "antifaz", "piñata",
                          "cumpleaños", "sorpresita", "decoracion"],
    "Navidad": ["navidad", "navideño", "arbolito de navidad", "papa noel",
                "reno", "pesebre"],
    "Librería y Oficina": ["cuaderno", "lapiz", "boligrafo", "marcador",
                           "resaltador", "carpeta", "regla", "tijera",
                           "cartulina", "pegamento", "plastilina", "pincel",
                           "acuarela", "agenda", "sticker", "pizarra"],
    "Herramientas y Auto": ["taladro", "destornillador", "martillo",
                            "alicate", "tornillo", "auto", "neumatico",
                            "candado", "sierra", "pintura", "brocha de pintar",
                            "cinta metrica", "soldador", "manguera"],
}

# Palabras que EXPULSAN a un producto de una categoría (limpieza 31/08):
# p. ej. "LÁPIZ labial" caía en Librería y los pañales "SIN PERFUME" en Belleza
EXCLUIR = {
    "Calzados": ["adorno", "navideño", "almohadilla", "desodorante",
                 "secador de calzado", "acrobatico", "ambientador"],
    "Librería y Oficina": ["labial", "adhesivo para coche"],
    "Belleza y Cuidado": ["always", "pañal", "pampers", "diario"],
    "Juguetes": ["mascota", "perro", "gato"],
    "Ropa y Moda": ["arnes", "mascota", "almohadilla"],
}

_cache = {"idx_id": None, "skus": {}}


def _clasificar(idx):
    """{categoria: set(doc_ids)} usando la MISMA expansión del buscador."""
    if _cache["idx_id"] == id(idx) and _cache["skus"]:
        return _cache["skus"]
    por_cat = {}
    for cat, palabras in CATEGORIAS.items():
        docs = set()
        for palabra in palabras:
            for tok in busqueda.tokenizar(palabra):
                if tok in busqueda.STOP:
                    continue
                for forma in idx._expandir(tok):
                    for d, _ in idx.inv.get(forma, ()):
                        docs.add(d)
        # exclusiones: si el nombre trae una palabra vetada, afuera
        _vetos = set()
        for palabra in EXCLUIR.get(cat, []):
            _vetos |= {tok for tok in busqueda.tokenizar(palabra)
                       if tok not in busqueda.STOP}
        if _vetos:
            docs = {d for d in docs
                    if not (_vetos & set(idx.docs[d]))}
        por_cat[cat] = docs
    _cache.update(idx_id=id(idx), skus=por_cat)
    return por_cat


def conteos(idx) -> dict:
    """{categoria: cantidad de productos}"""
    return {c: len(d) for c, d in _clasificar(idx).items()}


def items_de(idx, categoria: str, con_foto_primero=True) -> list:
    """Todos los items de una categoría (dicts del catálogo)."""
    docs = _clasificar(idx).get(categoria, set())
    items = [idx.items[d] for d in docs]

    def _es_accesorio(it):
        toks = busqueda.tokenizar(it.get("nombre") or "")[:2]
        return any(tk in busqueda.ACCESORIO for tk in toks)

    # orden: primero el producto en sí con foto; los ACCESORIOS (cordones,
    # plantillas, fundas...) al final — el que entra a Calzados quiere ver
    # calzados (31/08)
    items.sort(key=lambda it: (_es_accesorio(it),
                               not busqueda.it_foto(it),
                               it.get("nombre") or ""))
    # regla del dueño (31/08): mostrar SOLO los que tienen foto SERVIBLE
    # AHORA — con la web caída, la foto del storage no cuenta (mostraba
    # tarjetas vacías arriba); espejo y catálogo chico siempre sirven.
    con_foto = [it for it in items if busqueda.it_foto(it)]
    if len(con_foto) >= 12:
        return con_foto
    return items


def filtrar(idx, items: list, categoria: str) -> list:
    """Filtra una lista de resultados a una categoría (para el buscador)."""
    if not categoria or categoria not in CATEGORIAS:
        return items
    docs = _clasificar(idx).get(categoria, set())
    skus_cat = {str(idx.items[d].get("sku")) for d in docs}
    return [it for it in items if str(it.get("sku")) in skus_cat]
