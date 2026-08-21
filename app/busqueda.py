# -*- coding: utf-8 -*-
"""
Motor de búsqueda del cerebro — construido a medida para el catálogo de
Shopping Asia (mejor que el buscador básico de la web).

Qué hace, en capas:
1. Normaliza: baja tildes, arregla HTML/encoding (&quot;, Â), separa letra/número.
2. Singular/plural: 'mochilas' == 'mochila'.
3. Sinónimos y jerga paraguaya: 'championes'→zapatilla, 'audífonos'→auricular,
   'anteojos'→lente, 'remera'↔camiseta, y abreviaturas (mujer↔fem, hombre↔masc,
   niño↔inf, etc.).
4. Ranking BM25 (relevancia real, pondera palabras raras/específicas) + refuerzos:
   - cobertura: prioriza productos que tienen TODAS las palabras del pedido.
   - posición: la palabra buscada vale más si aparece temprano en el nombre.
   - adyacencia: bonus si las palabras salen juntas ('mochila escolar').
   - accesorios: baja 'funda/estuche/porta/… para X' cuando se busca X.
5. Tolerancia a errores de tipeo: si una palabra no existe, busca la más parecida
   (distancia de edición) en el vocabulario real del catálogo.

Todo en Python puro (sin dependencias pesadas): corre liviano en Render.
"""

import html
import math
import re
import unicodedata
from collections import defaultdict

# ── Palabras función (ruido). No hace falta sacar palabras de producto: BM25 ya
#    le baja el peso a las muy comunes. 'oc' es un código interno del catálogo. ──
STOP = {
    "de", "para", "con", "y", "el", "la", "los", "las", "un", "una", "unos",
    "unas", "en", "por", "al", "del", "o", "su", "sus", "que", "es", "mi",
    "oc", "tipo", "estilo", "modelo",
    # saludos / relleno / verbos de consulta (para que no sean el "sustantivo")
    "hola", "buenas", "buenos", "buen", "dia", "dias", "tarde", "tardes",
    "noche", "noches", "gracias", "favor", "porfa", "porfavor", "che",
    "tienen", "tenes", "tienes", "hay", "quiero", "busco", "buscando",
    "necesito", "queria", "querria", "me", "gustaria", "tenian", "vende",
    "venden", "consulta", "consultar", "precio", "cuanto", "sale", "vale",
    "como", "estan", "tal", "ver", "algun", "alguna",
}

# ── Nombres que indican ACCESORIO (no el producto en sí). Si el nombre empieza
#    con esto y el cliente no lo pidió, se baja el puntaje. ──
ACCESORIO = {
    "funda", "estuche", "forro", "protector", "soporte", "porta", "cable",
    "adaptador", "repuesto", "film", "mica", "sticker", "calcomania", "cobertor",
}

# ── Grupos de sinónimos / jerga PY. Se guardan en singular (se singulariza al
#    construir). Cualquier palabra del grupo trae a las demás en la búsqueda. ──
_GRUPOS = [
    ["champion", "championes", "zapatilla", "tenis", "calzado", "champione"],
    ["remera", "camiseta", "playera", "polera"],
    ["auricular", "audifono", "audífono", "handsfree"],
    ["lente", "anteojo", "gafa", "antiparra"],
    ["cartera", "bolso", "bolsa", "morral"],
    ["campera", "chaqueta", "casaca", "abrigo", "chamarra"],
    ["celular", "telefono", "teléfono", "movil", "móvil", "smartphone"],
    ["pantalon", "pantalón", "jean", "jeans", "vaquero"],
    ["short", "bermuda", "calza"],
    ["sandalia", "ojota", "chinela", "chancla", "chancleta"],
    ["gorra", "gorro", "jockey"],
    ["reloj", "reloj"],
    ["perfume", "fragancia", "colonia", "eau"],
    ["parlante", "altavoz", "speaker", "bocina"],
    ["licuadora", "batidora"],
    ["olla", "cacerola", "cacerol"],
    ["sabana", "sábana"],
    ["toalla", "toallon", "toallón"],
    ["collar", "gargantilla"],
    ["pulsera", "brazalete", "esclava"],
    ["aro", "arete", "zarcillo", "caravana", "pendiente"],
    ["anillo", "sortija"],
    ["billetera", "monedero", "portamoneda"],
    ["media", "calcetin", "calcetín", "soquete"],
    ["maquillaje", "cosmetico", "cosmético", "makeup"],
    ["labial", "lapiz labial", "lipstick"],
    ["cargador", "cargadores"],
    ["mochila", "mochilas"],
    ["peluche", "muñeco de peluche"],
    ["juguete", "jugueteria"],
    ["mujer", "dama", "femenino", "femenina", "fem", "señora", "chica"],
    ["hombre", "varon", "varón", "masculino", "masculina", "masc", "caballero"],
    ["niño", "nino", "nena", "nene", "infantil", "inf", "chico", "kids"],
    ["bebe", "bebé", "beba"],
    ["grande", "gr", "xl", "grand"],
    ["mediano", "md", "medium"],
]


def _quita_tildes(t: str) -> str:
    t = unicodedata.normalize("NFD", t or "")
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def normalizar(t: str) -> str:
    t = html.unescape(t or "")           # &quot; -> "
    t = _quita_tildes(t)                 # tildes/ñ -> n
    t = t.lower()
    t = t.replace("&quot;", " ").replace('"', " ")
    return t


def singular(w: str) -> str:
    if len(w) > 4 and w.endswith("es"):
        return w[:-2]
    if len(w) > 3 and w.endswith("s"):
        return w[:-1]
    return w


def tokenizar(t: str):
    t = normalizar(t)
    t = re.sub(r"([a-z])(\d)", r"\1 \2", t)   # h123 -> h 123
    t = re.sub(r"(\d)([a-z])", r"\1 \2", t)
    toks = re.findall(r"[a-z0-9]+", t)
    return [singular(w) for w in toks if len(w) >= 2]


# Como los tokens se comparan en singular, agregamos las formas singulares de las
# stopwords (ej. 'buenas'->'buena', 'dias'->'dia') para que no se cuelen.
STOP = STOP | {singular(w) for w in STOP}


def _construir_exp():
    exp = {}
    for grupo in _GRUPOS:
        formas = set()
        for w in grupo:
            for pw in tokenizar(w):     # tokeniza+singulariza cada forma
                formas.add(pw)
        for w in formas:
            exp.setdefault(w, set()).update(formas)
    return exp


EXP = _construir_exp()


def _lev1(a: str, b: str) -> bool:
    """True si la distancia de edición entre a y b es <= 1 (rápido)."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:                       # una sustitución
        return sum(1 for x, y in zip(a, b) if x != y) == 1
    if la > lb:                        # una borrada
        a, b = b, a
        la, lb = lb, la
    i = j = 0
    dif = 0
    while i < la and j < lb:
        if a[i] == b[j]:
            i += 1
            j += 1
        else:
            dif += 1
            j += 1
            if dif > 1:
                return False
    return True


class Indice:
    """Índice invertido + BM25 sobre los nombres de producto."""

    K1 = 1.5
    B = 0.6

    def __init__(self, items):
        self.items = items                       # lista de dicts con 'nombre'
        self.docs = []                           # tokens por producto (singular)
        self.inv = defaultdict(list)             # palabra -> [(doc_id, freq)]
        self.df = defaultdict(int)               # palabra -> nº de productos
        self.vocab_por_inicial = defaultdict(list)
        self.N = 0
        self.avgdl = 1.0
        self._construir()

    def _construir(self):
        total_len = 0
        for i, it in enumerate(self.items):
            toks = tokenizar(it.get("nombre", ""))
            self.docs.append(toks)
            total_len += len(toks)
            freqs = defaultdict(int)
            for w in toks:
                freqs[w] += 1
            for w, f in freqs.items():
                self.inv[w].append((i, f))
                self.df[w] += 1
        self.N = max(1, len(self.items))
        self.avgdl = (total_len / self.N) or 1.0
        for w in self.df:
            self.vocab_por_inicial[w[:1]].append(w)

    def _idf(self, df):
        return math.log(1 + (self.N - df + 0.5) / (df + 0.5))

    def _expandir(self, token):
        """token -> conjunto de palabras a buscar (sinónimos; si no hay match,
        corrección de tipeo por vocabulario)."""
        formas = set(EXP.get(token, {token}))
        # ¿alguna forma existe en el catálogo?
        if any(f in self.df for f in formas):
            return formas
        # tolerancia a tipeo: buscar palabra parecida (misma inicial, len±1)
        if len(token) >= 4:
            cerca = [w for w in self.vocab_por_inicial.get(token[:1], [])
                     if abs(len(w) - len(token)) <= 1 and _lev1(token, w)]
            if cerca:
                cerca.sort(key=lambda w: -self.df[w])   # el más común primero
                return {cerca[0]}
        return formas

    def buscar(self, consulta, limite=4):
        q = [w for w in tokenizar(consulta) if w not in STOP]
        if not q:
            return []
        n_q = len(q)

        # Info por término del pedido: formas (sinónimos), docs con match EXACTO,
        # postings (unión de sinónimos) e idf.
        info = []
        for token in q:
            formas = self._expandir(token)
            exact_docs = {d for d, _ in self.inv.get(token, ())}
            postings = {}
            for f in formas:
                for doc, fr in self.inv.get(f, ()):
                    postings[doc] = postings.get(doc, 0) + fr
            idf = self._idf(max(1, len(postings)))
            info.append({"tok": token, "formas": formas, "exact": exact_docs,
                         "post": postings, "idf": idf})

        puntajes = defaultdict(float)
        cobertura = defaultdict(int)
        for d_info in info:
            idf = d_info["idf"]
            for doc, fr in d_info["post"].items():
                dl = len(self.docs[doc]) or 1
                tf = (fr * (self.K1 + 1)) / (fr + self.K1 * (1 - self.B + self.B * dl / self.avgdl))
                puntajes[doc] += idf * tf
                cobertura[doc] += 1
        if not puntajes:
            return []

        # El PRIMER término del pedido suele ser el producto en sí (el sustantivo).
        # Un producto que ni siquiera lo tiene (ni por sinónimo) se baja fuerte.
        head = info[0]
        head_docs = set(head["post"].keys())

        finales = []
        for doc, base in puntajes.items():
            toks = self.docs[doc]
            score = base

            # Premio por match EXACTO (no solo sinónimo): "cartera" gana a "bolsa".
            for d_info in info:
                if doc in d_info["exact"]:
                    score += d_info["idf"] * 1.2
            # Premio si el sustantivo principal aparece EXACTO.
            if doc in head["exact"]:
                score += 3.0

            # Posición: vale más si el término sale temprano en el nombre.
            pos_bonus = 0.0
            for d_info in info:
                formas = d_info["formas"]
                for idx, w in enumerate(toks[:6]):
                    if w in formas:
                        pos_bonus += max(0.0, 3.0 - idx) * 0.6
                        break

            # Adyacencia: las palabras del pedido aparecen juntas.
            adj = 4.0 if (n_q >= 2 and " ".join(q) in " ".join(toks)) else 0.0

            total = score + pos_bonus + adj

            # Penalización: nombre de ACCESORIO (funda/porta/estuche/cable…) al
            # principio y el cliente no pidió un accesorio.
            if any(t in ACCESORIO for t in toks[:2]) and not any(t in ACCESORIO for t in q):
                total *= 0.4
            # Penalización fuerte: no tiene el sustantivo principal del pedido.
            if doc not in head_docs:
                total *= 0.2

            cubre_todo = 1 if cobertura[doc] >= n_q else 0
            tiene_foto = 1 if it_foto(self.items[doc]) else 0
            finales.append((cubre_todo, total, tiene_foto, doc))

        # Si hay productos que cubren TODO el pedido Y tienen el sustantivo
        # principal, nos quedamos con esos.
        con_head = [f for f in finales if f[3] in head_docs]
        base_lista = con_head if con_head else finales
        completos = [f for f in base_lista if f[0]]
        elegidos = completos if completos else base_lista
        elegidos.sort(key=lambda x: (-x[1], -x[2]))
        return [self.items[d] for _, _, _, d in elegidos[:limite]]


def it_foto(it) -> bool:
    return bool(it.get("imagenes"))
