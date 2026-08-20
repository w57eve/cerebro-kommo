# Base de conocimiento — Shopping Asia (para el bot de Kommo)

> Esta es la fuente con la que el bot responde. Lo que diga **`POR COMPLETAR`**
> lo llenás vos (yo no invento políticas). Todo lo demás ya viene cargado con
> datos públicos de la web.

---

## 1. La empresa
- **Nombre:** Shopping Asia
- **Rubro:** venta minorista y mayorista de productos variados (importados de Asia).
- **Dirección:** Av. Eusebio Ayala 1451 frente mismo a la comisaria septima, Asunción, Paraguay.
- **Sucursales:** no tenemos (¿hay más de una? direcciones).

## 2. Contacto y canales
- **Teléfono / Call Center:** +595 976 915333
- **WhatsApp:** +595 976 915333 (línea oficial en Kommo)
- **Email:** shoppingasiaweb@gmail.com
- **Web:** https://www.shoppingasia.com.py
- **Catálogo de flyers:** https://catalogo.shoppingasia.com.py
- **Verificador de precios:** https://precios.shoppingasia.com.py
- **Instagram:** @shopping_asia_py · **Facebook:** Shopping Asia · **TikTok:** shopping.asia.s.a
- **Kommo centraliza:** WhatsApp + mensajes directos + **comentarios de redes**
  (IG/FB/TikTok). El bot también atiende esos comentarios (ver §7).

## 3. Horarios
- **Local (atención general):** todos los días de **09:00 a 22:00 hs**, incluyendo
  **domingos y feriados**.
- **Atención online (personas/vendedores):** hasta las **19:00 hs**.
- **El bot:** responde **24/7** con info automática. Si el cliente necesita un
  vendedor:
  - **Antes de las 19:00** → ofrece el botón "Hablar con {vendedor}".
  - **Después de las 19:00** → avisa que la atención con asesor es hasta las 19 hs,
    igual deja el botón para que el cliente escriba y le respondan al reabrir, o
    resuelve lo que pueda de forma automática.

## 4. Cómo comprar / medios de pago / envíos
- **Cómo se compra:** puede comprar por la web, con tarjetas ceditos, débitos, transferencias, (¿se cierra por WhatsApp con un vendedor?, si se puede gestionar la compra con un asesor pagar por transferencias pasar la foto del comprobante o pagar por QR Y TAMBIEN PUEDE PAGAR EN EFECTIVO AL RECIBIR
  ¿retiro en local?,SI SE PUEDE PAGAR Y PASAR A RETIRAR ¿pago y envío?)el envió se hace apartir de una compra minima de 100.000 gs. hasta 15km es 20.000gs después sube 5.000gs. cada 5km es decir que desde 16km es 25.000gs hasta 20km y asi sucesivamente hasta los 30km, 150.000gs el envió es gratis hasta 15km, pueden pagar por transferencias,QR, se confirma el pago y se les envia, también pueden pagar en efectivo o tarjeta al recibir, solo en el caso de transferencias y qr se verifica antes de enviar es decir pagan de forma anticipada. en el caso de compras menores pueden solicitar bolt envios y le preparamos en ese caso pagan primero y se les prepara, hacemos envios a todo el país por medio de transportadora y para el envió se paga primero. 
- **Medios de pago:**  (efectivo, transferencia, tarjetas, QR,).
- **Envíos / delivery:**  (¿a todo el país?,el envió se hace apartir de una compra minima de 100.000 gs. hasta 15km es 20.000gs después sube 5.000gs. cada 5km es decir que desde 16km es 25.000gs hasta 20km y asi sucesivamente hasta los 30km, 150.000gs el envió es gratis hasta 15km, pueden pagar por transferencias,QR, se confirma el pago y se les envia, también pueden pagar en efectivo o tarjeta al recibir, solo en el caso de transferencias y qr se verifica antes de enviar es decir pagan de forma anticipada. en el caso de compras menores pueden solicitar bolt envios y le preparamos en ese caso pagan primero y se les prepara, hacemos envios a todo el país por medio de transportadora y para el envió se paga primero.).
- **Mayorista (escala de descuentos por monto de compra):** el descuento se aplica
  según el total de la compra. **Los huecos se rellenan con el porcentaje que
  antecede** (o sea: si el monto cae entre dos escalones, se aplica el % del escalón
  de abajo). Escala:
  - desde **1.500.000 gs** → **2%** (incluye todo hasta 3.999.999)
  - desde **4.000.000 gs** → **3%** (hasta 5.499.999)
  - desde **5.500.000 gs** → **4%** (hasta 5.999.999)
  - desde **6.000.000 gs** → **6%** (hasta 6.999.999)
  - desde **7.000.000 gs** → **7%** (hasta 7.999.999)
  - desde **8.000.000 gs** → **8%** (hasta 8.999.999)
  - desde **9.000.000 gs** → **9%** (hasta 9.999.999)
  - desde **10.000.000 gs** (hasta **15.000.000 gs**) → **10%**
- **Garantía / cambios / devoluciones:** POR COMPLETAR (48hs para cambios, tener el ticket y el articulo en caja y con sus etiquetas).

## 5. Precios y stock (cómo los sabe el bot)
- **Precio y nombre:** el bot los toma por sku y 
  **nombre** desde los datos ya publicados (sincronizados del panel de PORTA). Si hay
  oferta, la muestra.
- **Búsqueda por foto:** si el cliente manda una foto, el bot identifica el
  producto con el mismo motor del verificador.
- **Stock:**  (¿el bot debe informar stock? si debe informar, Hoy la web expone como agregar a carrito los que estan en stock y consultar disponibilidad, los productos que no se confirman existencias, se puede derivar.
  stock en vivo — si hace falta, se consulta PORTA en vivo y se deriva).

### 5.1 El catálogo NO es exhaustivo — orden de búsqueda (regla clave)
El catálogo de flyers **no tiene todos los productos**. El agente debe saberlo y
buscar en este orden, sin frustrar al cliente:

1. **Catálogo de flyers** (https://catalogo.shoppingasia.com.py) → lo primero, para
   lo que sí está armado con foto/flyer.
2. **Página web** (https://www.shoppingasia.com.py) → si el artículo **no está en el
   catálogo** (ej.: **prendas no están en el catálogo**), el agente lo busca en la web
   por nombre/SKU/foto y responde con precio + foto desde ahí.
3. **Derivar a un vendedor** → si **tampoco aparece en la web** (a veces son
   artículos **nuevos** que todavía no se cargaron), entonces el agente deriva a un
   vendedor con el botón "Hablar con {nombre}", pasando la consulta y lo que el
   cliente busca.

> Resumen para el agente: catálogo → web → vendedor. Nunca decir "no tenemos" sin
> antes pasar por la web; y si no está cargado en ningún lado, derivar (no inventar).

### 5.2 Búsqueda por foto = sugerencia, NO veredicto (regla de confianza)
El motor de búsqueda por imagen **no siempre acierta**: a veces los resultados no son
exactos. Por eso el agente **nunca canta un producto o precio solo porque la foto se
parece**. Orden de señales, de más exacta a menos: **SKU → nombre/texto → foto**. Si el
mensaje ya trae el SKU (los de la web normalmente sí), el agente usa el SKU y **no
depende de la imagen**. La foto es último recurso o herramienta para **confirmar**, no
para decidir. Lógica por nivel de confianza:

- **Confianza alta** (un solo candidato claro y muy parecido): el agente **propone
  confirmando**, no afirmando → *"¿Es este? [foto + nombre]"*. Recién con el "sí" da
  precio y avanza.
- **Confianza media / varios parecidos**: muestra **2–3 candidatos** (aprovecha los
  hasta 3 ángulos por SKU) y deja elegir → *"Encontré estos parecidos, ¿cuál es?"*.
- **Confianza baja**: no adivina. Pide el **SKU o el nombre**, o un detalle
  (color/talle/marca). Si aun así no aparece → **deriva a un vendedor**.

> En el peor caso el agente pregunta o deriva — **nunca manda un producto equivocado**.
> Esto se apoya en la regla dura: no prometer producto/precio que no esté confirmado.

## 6. Preguntas frecuentes (respuestas del bot)
> Formato: **P: necesito mas informacion** pregunta típica → **R:buenos días se ha comunicado con shopping Asia, en que le servimos** respuesta./siempre amable y cordial el tono.

- **P:** ¿Cuánto sale este producto? → **R:** el bot busca por SKU/nombre/foto y da
  precio + foto. (Automático.)
- **P:** ¿Tienen tal producto / color / talle? → **R:**  (informa
  disponibilidad y deriva a vendedor).
- **P:** ¿Hacen envíos? ¿Cuánto cuesta? → **R: si hacemos envios a todo el pais, a partir de una compra minima de 100.000gs e informar el precio,
- **P:** ¿Qué medios de pago aceptan? → **R: transferencias, QR, tarjetas y efectivo** .
- **P:** ¿Dónde están / puedo retirar? → **R:** Av. Eusebio Ayala 1451 frente mismo a la comisaria septima, Asunción;
  horario 9 a 22 todos los días. (Retiro: podes pagar y ya te preparamos, para pasar a retirar.)
- **P:** ¿Están abiertos hoy / feriados / domingos? → **R:** Sí, todos los días de
  9 a 22 hs.
- **P:** ¿Tienen precio mayorista? → **R:** Sí, hacemos descuentos por escala según
  el monto de la compra: desde 1.500.000 gs 2%, desde 4.000.000 gs 3%, desde
  5.500.000 gs 4%, desde 6.000.000 gs 6%, desde 7.000.000 gs 7%, desde 8.000.000 gs
  8%, desde 9.000.000 gs 9%, y desde 10.000.000 gs (hasta 15.000.000) 10%. (Los
  montos intermedios toman el % del escalón anterior.)
- **P:** ¿Puedo cambiar/devolver? → **R:** tenes 48hs para poder cambiar o devolver,trae tu ticket y el pructo con su caja y etiquetas intactas, si el cliente insiste entonces derivar, significa que tiene algun incveniente.
- **P:** Quiero hablar con una persona → **R:** botón "Hablar con {vendedor}"
  (rota entre los vendedores).
- **(sumar todas las que se te ocurran / las más repetidas del día a día)**

## 7. Comentarios de redes (IG/FB/TikTok)
- Entran a Kommo como conversaciones. Para comentarios **públicos**, la buena
  práctica es: responder amablemente y **llevar la charla al privado/WhatsApp**
  para dar precios y cerrar. POR COMPLETAR: ¿querés que el bot responda públicamente
  algo tipo "¡Hola! Te escribimos por privado 💬" y siga por DM? si

## 8. Tono y estilo del agente
- **Tratamiento: de "vos"** (voseo paraguayo, más cercano y de la jerga local).
  Tutear también está bien; es más cercano. El agente **se adapta al cliente**: si el
  cliente trata de "usted" o es más formal, acompaña ese registro; si es informal,
  responde relajado.
- Cercano y amable, cordial, atención de ventas real (no robótica). Emojis con
  moderación. Siempre ofrecer ayuda y proponer la opción más conveniente para el
  cliente.
- Reglas duras: no inventar precios ni políticas; **nunca prometer stock/precio que
  no esté confirmado**; si no está en esta base, derivar a un vendedor.

## 9. Reglas de derivación al vendedor (definido)
- **Vendedores reales (rotación fija, equitativa):**
  1. **Erika** → `wa.me/595984356888`
  2. **Analía** → `wa.me/595976655588`
  3. **Fabián** → `wa.me/595976667222`
- El agente muestra el botón **"💬 Hablar con {nombre}"** con el nombre del vendedor
  que toca según la rotación, y el link `wa.me/<número>` lleva un **mensaje
  pre-escrito** que incluye el producto/SKU (o la consulta sin resolver) y el nombre
  del vendedor.
- **Rotación equitativa** entre los tres (round-robin), en línea con la distribución
  de leads que ya hace Kommo.

---

### Estado (lo que ya quedó definido)
1. ✅ Medios de pago (efectivo, transferencia, tarjetas, QR).
2. ✅ Envíos/delivery (mínimo 100.000 gs; escala por km; gratis desde 150.000 gs
   hasta 15 km; transportadora a todo el país con pago anticipado).
3. ✅ Cómo se concreta la compra (web, WhatsApp con asesor, retiro en local).
4. ✅ Condiciones mayorista (escala de descuentos por monto — §4).
5. ✅ Garantía / cambios / devoluciones (48 hs, con ticket y producto en caja con
   etiquetas; si el cliente insiste, derivar).
6. ✅ Stock (informa lo que la web confirma; lo no confirmado se deriva / consulta
   PORTA en vivo).
7. ✅ Tono = **de "vos"** (voseo, cercano; se adapta al cliente) — §8.
8. ✅ Vendedores fijados (Erika, Analía, Fabián) con rotación equitativa — §9.
9. ✅ Regla catálogo→web→vendedor (§5.1): el catálogo no es exhaustivo.

**Queda pendiente de tu lado:** exportar los ~1.500 chats de Kommo (para la
destilación inicial) y pasar la API key de Kommo por un canal seguro.
