# Cerebro de ventas (agente Kommo) — estado y cómo seguir

_Copia local del estado del proyecto. Para retomar con cualquier modelo/sesión, pasale este archivo o pedile que lo lea._

## 0. RESUMEN — CAMBIO DE ARQUITECTURA (2026-08-27)
DECISIÓN: se abandona el canal widget_request/salesbot-show como vía de entrega.
Motivo: ese canal fue diseñado para guiones cortos de bot, no para conversar:
- handler "show" limita a 80 caracteres -> mensajes picados en globitos (feo).
- el Salesbot corre UNA vez por conversación -> no contesta mensajes siguientes.
Ambos problemas son de diseño de ese canal; forzarlo (bucle goto) resultó frágil
y en la última prueba dejó de responder del todo.

ARQUITECTURA v2 (la que usan las integraciones de IA serias en Kommo):
1. Webhook GENERAL de la cuenta, evento "Incoming message received":
   Kommo avisa a nuestro server por CADA mensaje entrante (todos, siempre).
   Endpoint: https://cerebro-kommo.onrender.com/webhook-mensajes
2. El cerebro agrupa mensajes seguidos (~6 s), piensa UNA respuesta (mismo
   agente de siempre: catálogo, fotos, reglas — nada de eso cambió).
3. Entrega: PATCH del lead -> campo "Respuesta bot" (se crea solo al arrancar
   el server) + POST /api/v4/bots/{id}/run -> un Salesbot MÍNIMO de 1 paso
   ("Enviar mensaje" = {{lead.Respuesta bot}}) manda el texto al cliente.
   -> UN solo mensaje, largo y natural, sin límite de 80, en TODOS los mensajes.
Código nuevo: app/kommo_api.py + endpoint /webhook-mensajes en app/main.py.
Diagnóstico: https://cerebro-kommo.onrender.com/diag-kommo
El endpoint viejo /webhook (widget) queda como respaldo pero ya no se usa.

## 0.1 PASOS EN EL PANEL DE KOMMO — EJECUTADOS el 2026-08-28 (via Claude+Chrome)
HECHO: bot "Enviar respuesta cerebro" creado, ID 110388 (un paso "Enviar
mensaje" = campo del lead [Respuesta bot], SIN disparador; el placeholder quedó
como chip reconocido). Webhook agregado: /webhook-mensajes con el evento
"Mensaje entrante recibido" (Kommo valida la URL con un GET; se agregó GET al
endpoint). Salesbot #4 (el del widget viejo, el de los mensajes entrecortados):
disparador ELIMINADO. El ID 110388 quedó como default en el código
(kommo_api.bot_id), así no hace falta tocar Render.
OJO: Salesbot #4 tenía ~48 sesiones activas colgadas en charlas viejas; en esos
leads el bots/run puede fallar hasta que expiren. Probar con charlas NUEVAS.

## 0.1b Detalle original de los pasos (referencia)
Con sesión de admin en Kommo:
1. TOKEN: Ajustes -> Integraciones -> nuestra integración privada -> token de
   larga duración. En Render: KOMMO_API_TOKEN (si ya es el mismo KOMMO_TOKEN,
   no hace falta duplicarlo; /diag-kommo dice si la cuenta responde 200).
2. DEPLOY primero (actualizar_github.bat) y abrir /diag-kommo: debe mostrar
   cuenta_http: 200 y campo_id (el server crea solo el campo "Respuesta bot").
3. BOT NUEVO: CRM -> Salesbot -> crear bot SIN disparador, con UN solo paso
   "Enviar mensaje" cuyo texto sea el campo del lead "Respuesta bot" (insertar
   placeholder de campo desde el editor). Guardar. El número del bot está en la
   URL del constructor -> en Render: KOMMO_BOT_ID.
4. WEBHOOK: Ajustes -> Integraciones -> botón "Web hooks" -> agregar URL
   https://cerebro-kommo.onrender.com/webhook-mensajes con el evento
   "Mensaje entrante recibido" (Incoming message received). Guardar.
   (Opcional: agregar ?clave=XXXX a la URL y poner WEBHOOK_CLAVE=XXXX en Render.)
5. APAGAR el bot viejo del widget (sacarle el disparador o desactivarlo) para
   que no choque con el nuevo ("no se puede continuar un bot si otro bot ya
   está corriendo en la misma entidad").
6. En Render: KOMMO_GOTO_FINISH=0 (el goto ya no se usa).
Prueba: charla nueva por WhatsApp, mandar 2-3 mensajes -> debe contestar a todos,
en un solo mensaje cada vez, completo (sin globitos de 80).

## 0.2 (HISTÓRICO) Bloqueo del canal viejo — ya no aplica, se deja de referencia

(Tema: que conteste TODOS los mensajes de una charla, por la vía vieja.)
Síntoma: responde a conversaciones NUEVAS (primer mensaje), pero en una charla que
ya venía mensajeando NO responde — ni aparece [WEBHOOK] en el log. Confirmado en vivo.
Causa: Kommo corre el Salesbot UNA sola vez por conversación; no lo vuelve a disparar
en mensajes siguientes, aunque el disparador sea "mensaje entrante desde cualquier
canal" (ese disparador está BIEN — no es el problema).

Dos caminos para cerrarlo:

A) Bucle por código (probar sin entrar a Kommo). Ya está en el código, detrás de
   variables en Render:
   - KOMMO_GOTO_FINISH = 1        (activa el goto)
   - KOMMO_GOTO_TIPO = question   (bucle: muestra la respuesta y ESPERA el próximo
     mensaje; cuando llega, vuelve al paso del widget y re-ejecuta). Default = question.
   - KOMMO_GOTO_STEP = 0          <- HALLAZGO (2026-08-27, doc oficial de Kommo):
     el 'step' del goto refiere a los pasos del FLUJO INTERNO DEL WIDGET (el JSON
     que devuelve onSalesbotDesignerSave en script.js), NO a los pasos del bot en
     el constructor de Kommo. Nuestro widget genera UN solo paso -> índice 0.
     Con step=1 apuntaba a un paso inexistente; por eso el bucle no andaba.
     El default en el código ya es 0; en Render poner 0 (o borrar la variable).
   Prueba: con una charla NUEVA (las viejas ya están "muertas"), mandar 2 mensajes
   seguidos; el 2º debe disparar un [WEBHOOK] nuevo y responder. "question" es seguro
   (no hace spam, sólo corre cuando el cliente escribe). Código: app/kommo.py, bloque
   'if modo == "show"' -> append goto.
   OJO al probar: si en el log aparecen [WEBHOOK] repetidos SIN que el cliente
   escriba (bucle inmediato con el mismo mensaje), apagar YA con KOMMO_GOTO_FINISH=0.
   Fuente: https://developers.kommo.com/docs/private-chatbot-integration
   ("goto" params type question|answer|finish + step; "go to step N of the widget bot").

C) Alternativa robusta documentada por Kommo (requiere token de la integración):
   webhook general de la cuenta en cada mensaje entrante + API "run a Salesbot"
   (POST /api/v4/salesbot/run) para relanzar el bot en ese lead en cada mensaje.
   No depende de bucles. Pendiente de acceso a Kommo para sacar el token.

B) Con acceso a Kommo (lo confiable). Entrar a Kommo (falta la contraseña del Gmail)
   y O configurar un bucle real en el CONSTRUCTOR del bot (respuesta -> paso "esperar
   mensaje del cliente" -> goto de vuelta), O preguntar a soporte de Kommo (plan
   Advanced) esta pregunta puntual:
   "¿Cómo hago que un Salesbot conteste TODOS los mensajes entrantes de una misma
   conversación, y no sólo el primero? El bot corre una vez por lead y no se vuelve a
   disparar en los mensajes siguientes."

Nota de diseño: un bot en bucle queda "activo". Cuando se quiera DERIVAR a un vendedor
habrá que cortar el bucle (mandar goto finish en vez de question cuando res["derivar"]
es True). Afinar eso una vez que el bucle ande.

## 0.3 RONDA 2026-08-28 (tarde) — afinado del agente + minado de chats
HECHO EN CÓDIGO (todo desplegado):
- MEMORIA de conversación: recuerda los últimos 8 intercambios por lead (antes
  procesaba cada mensaje suelto). No re-saluda, retoma el hilo.
- APRENDIZAJE: cada intercambio se registra con señales de calidad. Endpoint
  https://cerebro-kommo.onrender.com/aprendizaje -> tasas de fallback/derivación
  y TOP de consultas sin respuesta útil (materia prima para reglas nuevas).
- FILTRO DE LINKS: solo salen URLs legítimas (fotos storage/, /buscador,
  catalogo.shoppingasia.com.py, wa.me). Links inventados = línea borrada.
  También se borran meta-notas entre [corchetes].
- Ventas: 3-4 opciones por consulta; link "ver más" = /buscador?q=<término>
  con jerga mapeada (championes->calzado); derivación por IA con etiqueta
  [DERIVAR] (concretar compra, quejas, no puede resolver); quejas por regla
  directa; flujo calzados de pautas (horma chica + catálogo + botón "Hacer
  pedido" -> derivar) en base-conocimiento 5.1b.
- Reglas nuevas de los chats reales: "cómo comprar" (mini-guía), "por qué más
  caros", sinónimos pirex/pegatinas/turbante.

MINADO DE CHATS HISTÓRICOS (muestra de 40 leads, 20 con contenido):
- La API de Kommo NO expone el texto de mensajes viejos (solo IDs); el minado
  se hizo leyendo el panel con el navegador. El panel muestra ~10 mensajes por
  lead, así que las frecuencias son piso.
- Errores del bot viejo detectados: saludos repetidos (~6 leads), dobles
  respuestas (~5), mensajes con estado Error que nunca llegaron (~5), links de
  producto INVENTADOS/rotos, meta-notas filtradas al cliente, "¿te late?"
  (mexicanismo), negó su propio mensaje anterior, "no tenemos" seco sin
  alternativas, leads sin responder. -> TODOS con corrección aplicada (ver
  arriba); los de arquitectura (duplicados/Error) los resuelve la v2.
- Patrones de clientes: deixis con foto ("quiero ese" + imagen), mensaje
  truncado del click-to-chat ("Necesito más información sobre ..."), listas
  mayoristas con viñetas, "no me deja abrir el link" -> prefieren foto+precio
  en el chat, ubicación ("soy de Ciudad del Este"), catálogo Shein.
- PENDIENTES sacados del minado: repregunta única para mensaje truncado,
  respuesta ítem por ítem en listas mayoristas + derivar, filtro spam B2B,
  búsqueda por foto (hoy la imagen llega sin texto y el hilo muere).

REVISIÓN PERIÓDICA (para no perder el hilo):
- Tarea programada semanal en Cowork: leer este documento + /aprendizaje y
  proponer reglas nuevas con lo que falló en la semana. El ciclo de mejora es:
  registro -> detección -> regla nueva -> deploy.

FOTO REAL (pendiente en curso):
- Los bots de Kommo NO soportan imagen con URL dinámica (verificado en doc).
- Hoy la foto va como link pelado; falta probar si el mensaje del bot nuevo
  genera previsualización en WhatsApp.
- Si no previsualiza: la vía es la API de WhatsApp Cloud (Meta) directa para
  el mensaje de foto -> requiere acceso al Meta Business / developers de la
  cuenta que conectó WhatsApp Cloud API.

## 0.4 RONDA 2026-08-28 (noche) — el agente VE y usa las 3 bases
- VISIÓN (Claude): las fotos de clientes se descargan del link del webhook
  (amojo, sin auth) y la IA las describe -> búsqueda + memoria de la charla.
  Las capturas del catálogo se leen (nombre y precio incluidos).
- MATCH VISUAL (app/busqueda_imagen.py): reusa el índice de imágenes del
  verificador (CLIP ViT-B/16, 24.765 fotos, publicado en /indice/). El server
  baja el modelo ONNX cuantizado de HuggingFace y compara la foto del cliente
  contra TODO el catálogo. Umbrales calibrados: ALTA >=0.88, MEDIA >=0.80.
  Si algo falla, sigue solo con la descripción (tolerante). Para apagarlo:
  FOTO_MATCH=0 en Render (ej. si la RAM del starter no alcanza).
- CATÁLOGO RÁPIDO por SKU (app/catalogo_chico.py): lee catalogo.json publicado
  (hoy CALZADO IRUN + CROCS, 147 SKUs); cada candidato se marca "ESTÁ EN EL
  CATÁLOGO RÁPIDO (sección X)" solo si su SKU está. Escala solo al publicar
  rubros nuevos.
- Audio (v2): tipo voice/audio/ptt -> mensaje de cortesía + ofrece derivar
  ("derivame"/"pasame con" derivan por regla).
- Higiene: ** -> * (negrita WhatsApp), mexicanismos reemplazados por código
  (te late -> te parece, etc.), referencia a precio ("el de 116 mil") no se
  busca como producto, link de la web SIEMPRE al final en calzados.
- Derivación: "Tocá este enlace y te lleva al WhatsApp de {nombre}", rotación
  equitativa persistida en disco + pegajosa por cliente.
- Ofertas: "¿siguen las ofertas?" -> confirma y pregunta qué publicación vio
  (sin mandar catálogos a ciegas; catálogo chico solo si es calzado).
- Pautas: identificación exacta pendiente de que el usuario ponga el producto
  en el mensaje prellenado de cada anuncio de Meta (Kommo no pasa el ad id).

## 0.5 CIERRE 2026-08-28 noche — EN PRODUCCIÓN (deploy 317c40d, 18:53)
Todo el paquete del día quedó vivo. Claves de la última hora:
- Los deploys fallaban desde las 16:58: requirements con numpy/onnxruntime no
  compatibles con el Python default de Render. Solución: quedaron COMENTADOS en
  requirements.txt (el match visual por foto se apaga solo, sin romper nada) y
  .python-version=3.11.9 en el repo para cuando se reactiven.
- Otro bloqueo: .git/index.lock huérfano impedía que actualizar_github.bat
  commitee (fallaba en silencio). Si Render "no reacciona" tras el bat, revisar
  ese archivo y borrarlo.
- ELECCIÓN CONCRETADA es determinística: SKU de "Hacer pedido" o calce/talle
  con número => el server FUERZA la derivación (la IA solo redacta).
- VISIÓN funcionando en producción (describe fotos reales de clientes).
- PENDIENTE DECIDIDO PARA MÁS ADELANTE: migrar WhatsApp a API Cloud de Meta
  PROPIA (Meta Business + developers con el número, conectada a Kommo) para
  mandar FOTOS INCRUSTADAS de verdad. Hasta entonces, la foto viaja como link
  con miniatura instantánea (/foto/<sku>.jpg). También pendiente: reactivar el
  match visual (descomentar numpy/onnxruntime y verificar build).

## 0.6 ANÁLISIS EXPERTO 2026-08-29 — suite de regresión + verificación en vivo
- NUEVO: tests_regresion.py (35 tests) congela TODOS los incidentes resueltos
  (jerga, hilo, elección, precios, links, fotos, audio, derivación). Correr con
  `python3 tests_regresion.py` antes de cualquier deploy. El monitor de las
  9/13/17/21 la corre en cada ronda y revierte ajustes que la rompan.
- VERIFICADO EN VIVO (chat de Oscar, post-ajustes): el guard de relevancia evitó
  ofrecer monederos como botines; "Calse 41" confirmó y derivó con Erika +
  horario. El flujo elección->derivación FUNCIONA en producción.
- 3 pulidos salidos de ese chat: "quilombo/despelote" filtrados, "clase 41"
  reconocido como calce, y prohibido exponer lo interno ("veo que me pasaste
  monederos") o confirmar fallas propias ("el buscador está roto").
- Garantías duras vigentes (todas por código, no solo prompt): precios
  verificados contra catálogo ([PRECIO-FIX]), listas sin candidatos bloqueadas
  ([ANTI-INVENCION]), solo foto exacta autorizada, solo links verificados,
  léxico filtrado, derivación equitativa/pegajosa con horario.

## 1. Dónde está TODO
- Código del cerebro (GitHub): repo w57eve/cerebro-kommo. Copia local en
  C:\Users\Admin\Documents\aplicacion\automatizacion-kommo\cerebro-kommo
- Servicio en vivo (Render): https://cerebro-kommo.onrender.com
  (/ prueba, /health, /diag diagnóstico, /webhook). Plan starter.
  Panel Render: proyecto prj-da3n76710e5c738r2js0, servicio srv-da3n76bncjis73b4lk5g.
- App de precios (GitHub Pages): https://precios.shoppingasia.com.py/datos/_catalogo.json
  Se regenera/publica con publicar.bat de la app de precios (verificador-precios).
- Subir cambios del cerebro: actualizar_github.bat -> Render auto-deploy.

## 2. Cómo ENTREGA la respuesta (RESUELTO)
La respuesta al return_url sólo acepta ciertos handlers (probado en vivo):
- send_external_message -> 400 "Unsupported handler code".
- execute_handlers vacío (sólo data) -> 400 "TooFew" (exige >=1 handler).
- goto sin step -> 400 "FieldMissing: step".
- show con type:text, value <=80 caracteres -> 202 Accepted = ENTREGA OK. <- este anda.
- show limitado a 80 caract. por bloque -> el cerebro parte en trozos <=80 (_trocear).
- KOMMO_MODO en Render: show (el que anda, default), data (no se usa), externo (no soportado).

## 3. Autenticación al return_url (RESUELTO)
- POST al return_url necesita header Authorization: Bearer {KOMMO_TOKEN}. Sin él -> 401.
- JWT del webhook firmado HS512 (no HS256); verificar_token acepta ambos.
- TRAMPA que costó horas: variables en Render con el NOMBRE mal. Deben ser EXACTAS:
  ANTHROPIC_API_KEY, KOMMO_TOKEN, KOMMO_SECRET_KEY, KOMMO_SUBDOMAIN (mayúsculas,
  guion bajo, sin espacios). Nombre mal = se leen vacías (log: auth=NO).

## 4. Catálogo (RESUELTO — era el "no trae fotos")
- Fuente: _catalogo.json (la app de precios lo publica desde el panel PORTA).
- Formato REAL: 3 elementos [nombre, precio, foto] (foto al final, "" si no tiene).
  app/productos.py soporta 3 y 4 elementos.
- Causa del "no trae fotos": el _catalogo.json estaba VACÍO (bache de publicación) ->
  productos_cargados: 0 en /diag -> el agente no tenía qué mostrar y preguntaba.
  Se arregla corriendo publicar.bat de la app de precios. Tras republicar: 49.536, con fotos.
- Diagnóstico: https://cerebro-kommo.onrender.com/diag (productos_cargados, fetch_http).
- El cerebro usa el catálogo COMPLETO de precios... (todo el inventario), NO el de flyers
  (catalogo.shoppingasia.com.py, que es chico/curado).
- Fotos = link PELADO (https://...jpg), NUNCA markdown ![](url) (WhatsApp no lo renderiza).

## 5. Audios
- Llega sólo el ícono (no el archivo). reglas.es_audio() lo detecta y pide que lo
  escriban / deriva (AUDIO_MSG en app/agente.py). Transcripción real = proyecto aparte.

## 6. Derivación y pautas
- Al derivar manda el link de WhatsApp del vendedor de turno (wa.me). VENDEDORES (env)
  tiene 3 de ejemplo -> PENDIENTE los reales. Kommo pausa el bot cuando un vendedor escribe.
- Pautas (Facebook): el ID del anuncio NO le llega al webhook (sólo texto + nombre) -> el
  agente pregunta genérico. Para arreglar: pasar el ID del anuncio en el data del widget y
  mapear con datos/mapa-anuncios.md. Requiere editar el widget + el macro de Kommo. PENDIENTE.

## 7. Contrato Kommo (verificado)
- Webhook: {token(JWT), data:{message,from,nombre}, return_url} como x-www-form-urlencoded
  (NO JSON) -> llega como data[message]. main.py lo parsea.
- Respuesta al return_url: {data:{message}, execute_handlers:[{show <=80}...]} + Bearer.

## 8. Pendientes
1. EJECUTAR los pasos del panel de Kommo de la sección 0.1 (arquitectura v2).
2. Cargar los 4 vendedores reales (env VENDEDORES).
3. Pautas -> producto (ver 6).
4. "Parar al derivar" (cortar el bucle al derivar). Foto real (no link) = canal amojo.
5. Respaldo "búsqueda en la web en vivo" (get-productos) para productos nuevos.
6. Transcripción de audios (proyecto aparte).

## 9. Variables Render
ANTHROPIC_API_KEY, KOMMO_TOKEN (Bearer al return_url), KOMMO_SECRET_KEY (valida JWT;
vacío = no valida), KOMMO_SUBDOMAIN, KOMMO_MODO=show, CATALOGO_JSON_URL (default ok),
y para el bucle: KOMMO_GOTO_FINISH=1, KOMMO_GOTO_TIPO=question, KOMMO_GOTO_STEP=0.
Nombres EXACTOS o se leen vacías.

## Monitoreo 2026-08-29 (corrida automática)
- Suite de regresión: ✅ completa sin regresiones (todos los tests ok).
- No se pudo acceder a /aprendizaje ni /diag (fetch y navegador bloqueados en esta corrida) → sin revisión de intercambios reales ni estado del catálogo. Verificar manualmente https://cerebro-kommo.onrender.com/diag.
- Sin ajustes de código en esta corrida.

## Monitoreo 29/08/2026 (tarde)
- FIX regresión ofertas: pregunta GENERAL por ofertas ("tienen ofertas?", "que ofertas hay", "¿Pueden enviarme más información sobre la oferta?") ahora confirma y pregunta qué artículo vio, en vez de tirar el buscador. Con artículo nombrado ("ofertas de calzado") sigue al buscador. Regla nueva en reglas.py (_es_oferta_general) + 2 tests. Suite completa OK. Falta: actualizar_github.bat.
- Miniaturas de Meta: revisados 20 webhooks crudos en /ultimos-webhooks → Kommo NO reenvía el objeto "referral" de Meta (miniatura/headline/ad id) en el webhook de mensaje entrante; solo llega text + attachment cuando el CLIENTE manda foto. Por eso el bot no puede ver la miniatura. Pistas: probar campos del lead vía API (utm_content/anuncio) o personalizar el mensaje prellenado por pauta en Meta para que nombre el producto (engancha con mapa-anuncios.md).

## Investigación miniaturas Meta 29/08/2026 (con navegador, en Kommo)
- El anuncio (miniatura + texto + link fb.me) SÍ está pegado al mensaje entrante en el chat de Kommo (elemento feed-note__ads-post-preview, mismo message_id que el webhook), pero vive en amojo (backend de chats de Kommo).
- Verificado que NO llega por ningún camino accesible al servidor: webhook (raw sin referral), campos rastreados del lead (los 12 vacíos), /api/v4/leads/{id}/notes (0 notas), /api/v4/talks/{id} (sin dato de pauta). El endpoint interno amojo /v1/chats/{chat}/messages requiere sesión web de Kommo (CORS/auth interno) — no usable por integración.
- CONCLUSIÓN: no hay vía soportada. Solución recomendada: personalizar el mensaje prellenado de CADA pauta en Meta para que nombre el producto/rubro (ej: "Hola! Quiero info de los calzados en oferta"). Eso llega en el webhook como texto y el bot identifica solo.

## Mejora hilo-fotos 29/08/2026
- FIX: "Me pasan fotos de las opciones" (caso Stanley, lead 24740965) buscaba "fotos" como producto y ofrecía ÁLBUMES DE FOTOS. Ahora _pide_fotos en agente.py detecta el pedido, mantiene los productos del hilo y excluye "fotos" de la búsqueda. +4 tests. Suite completa OK. Falta: actualizar_github.bat.
- Verificado en producción: fix de ofertas ya desplegado y funcionando (2 leads lo recibieron bien). Catálogo OK: 49.536 productos, fetch 200.
- Detectado para futuro: catálogo con nombres genéricos repetidos ("ORGANIZADOR" x4, "ZAPATILLA", "CALZADOS") — el bot lista 4 veces el mismo nombre con precios distintos y el cliente no puede distinguir. Ver enriquecer nombres o instruir diferenciación por foto.

## Fix links web + sin-foto 29/08/2026
- BUG GRANDE RESUELTO: la web pasó a renderizar el buscador con JS → el HTML crudo ya no trae "/producto/" → _web_conteo daba siempre 0 → el bot NUNCA mandaba el "link ver más". Ahora usa la API JSON del propio front (/get-productos?query_string=... → paginacion.total), verificada sin cookies (200). Fallback al conteo viejo por si vuelven al HTML.
- Productos sin foto: a_texto marca "SIN FOTO en el sistema" + regla en el prompt: si piden foto de uno así, decir que la pasa el vendedor; nunca inventar link. +1 test.
- Suite completa OK. Falta: actualizar_github.bat (incluye también el fix pide-fotos).
- PENDIENTE (urgente, decidido con el dueño): aprendizaje persistente — el registro se borra en cada deploy de Render. Propuesta: token de GitHub en Render y aprendizaje.py sube JSONL diario al repo; el monitoreo lo analiza y convierte en sinónimos/reglas/conocimiento.

## Aprendizaje persistente en GitHub 29/08/2026
- aprendizaje.py ahora sube los intercambios en tandas (cada 10 mensajes o 10 min) a la rama "aprendizaje" del repo, archivo datos/aprendizaje/AAAA-MM-DD.jsonl. Rama separada: los push de código a main no chocan y Render no redespliega por datos. Tope 500 pendientes si GitHub falla; reintenta solo. /aprendizaje muestra bloque "github" (activo, pendientes, ultimo_envio, ultimo_error) para el monitoreo.
- FALTA DEL DUEÑO: 1) crear token fine-grained en GitHub (solo repo cerebro-kommo, permiso Contents: Read and write), 2) en Render → Environment agregar GITHUB_TOKEN=<token>, 3) doble clic actualizar_github.bat.
- Ciclo de aprendizaje: el monitoreo nocturno lee esos JSONL → consultas sin candidatos → sinónimos; fallbacks → reglas; respuestas del vendedor post-derivación → conocimiento. Cada mejora entra con test.

## Monitoreo 29/08/2026 17:15
- Suite 45/45 OK, sin regresiones. Aprendizaje→GitHub FUNCIONANDO: leí los 20 intercambios de hoy desde la rama "aprendizaje" (el token ya está activo en Render). /aprendizaje y /diag no accesibles desde el entorno de monitoreo (bloqueo de red del entorno, no implica caída del servicio).
- Detectado, propuesto sin implementar: (1) teléfono del cliente "0981496337" interpretado como SKU (lead 24744833) — detectar patrón 09xxxxxxxx; (2) bot siguió el juego del "te amo" de una clienta (lead 22541380) en vez de cortar cordial a la segunda; (3) listas de productos llegan con líneas vacías donde iban los ítems (caso "el grasep", lead 24745469: "¿cuál te gustó?" sin lista visible) — revisar hueco que deja PRECIO-FIX/fotos: colapsar también líneas de solo-espacios; (4) mismo lead dijo "116.mil" (precio del IRUN 36-41) y el bot contestó que los GRASEP van 320-380 mil — verificar de qué candidatos salieron esos precios.
- Sin ajustes de código esta corrida; ninguno de los 4 entra en los ajustes chicos permitidos.

## Fix precios inventados (caso David/grasep) 29/08/2026
- "116.mil" con punto no se reconocía como referencia a precio -> buscaba "116" (ofreció un altavoz). Regex de precio ahora tolera "116.mil"/"116,mil".
- La IA dijo "rondan entre 320.000 y 380.000 gs" (IRUN real: 80-193 mil). Nuevo _verificar_precios_texto: todo precio en TEXTO LIBRE que no salga de una fuente legítima (candidatos/contexto/prompt/mensaje/historial) se borra con su oración. Marca [PRECIO-TXT] en el log.
- Si el verificador borraba TODA la lista quedaba un hueco en blanco ("tengo varios modelos:" y nada). Ahora reconstruye la lista con los candidatos reales, sin repetidos.
- Orden: anti-invención corre ANTES del control de texto libre (si no, se tapaban la señal). Suite 49/49. Falta: actualizar_github.bat.

## Modelos duplicados + auditoría 29/08/2026 (tarde-noche)
- Modelos distintos con mismo nombre/precio: el contexto ya no repite renglones y la instrucción pide UNA mención + link "ver más" verificado (ahí el cliente ve cada modelo con su foto). Sin link: aclara que hay variantes. Test agregado. Suite 50/50.
- Auditoría por temor a acceso remoto: git log limpio (todos los commits de w57eve@gmail.com, ninguno ajeno). Los "misterios" tuvieron causa técnica encontrada: web pasó a JS (mató el conteo de links), plantillas de Meta en genérico tras migrar a WABA, y regex de "116.mil". Recomendado al dueño: 2FA en GitHub/Render/Kommo/Meta y revisar usuarios autorizados en cada uno.

## Fix "todo terreno" (caso Sonia) 29/08/2026 noche
- "Todo terreno para criatura" matcheó productos LITERALES del catálogo grande (zapatillas 444.000, un autito) y contaminó la regla de oro de calzados. Causa: la búsqueda de candidatos corre antes de la regla. Ahora la jerga de pauta ("todo terreno"/"todoterreno") saltea la búsqueda literal: va directo catálogo chico + link web calzado + aclaración "si era otro producto, decime cuál con claridad" (agregada a la regla de oro). Test con el caso de Sonia. Suite 51/51.
- Nota: el intercambio de Sonia se recuperó del JSONL de GitHub (el buffer en memoria se había reiniciado con el deploy) — la persistencia ya demostró su valor el primer día.
- Falta: actualizar_github.bat.

## Deploy sin amnesia 29/08/2026 noche
- Al arrancar, el servidor restaura la memoria de charlas (hasta 8 intercambios por lead, últimos 2 días) desde los JSONL de GitHub → un deploy ya no corta el hilo de conversaciones en curso. Al apagarse (deploy/reinicio), sube los registros pendientes antes de morir. Tests con GitHub simulado. Suite 53/53.
- Falta: actualizar_github.bat.

## Monitoreo 29/08/2026 (noche) — contexto ante frases genéricas
- Suite OK antes de tocar. Casos reales del JSONL/aprendizaje:
  1) "Este ceria" (typo de "sería") se buscó como producto → peines de CERDAS. Deixis ahora tolera seria/ceria/sera.
  2) "Pásame las opciones y precio" / "quiero más información" con charla previa → buscaba esas palabras (a Juve: "la búsqueda no da resultados"). Nuevo _pide_continuar: sigue el hilo, sin buscar el mensaje literal.
  3) "Que llegó recién" → matcheó LEGO. Nuevo _pide_novedades: no busca literal; ofrece lo nuevo del rubro hablado o deriva.
  4) "170000" pegado sin puntos ahora cuenta como referencia a precio.
- 7 tests nuevos con los casos reales. Suite 60/60. GitHub aprendizaje OK (56 regs, sin errores). Falta: actualizar_github.bat.

## Fix caso Brenda 29/08/2026 (noche)
- "Buenass! Qué tall? Disponen de maletas para viaje con ruedas 360?" → "tall" (typo de "qué tal") matcheaba productos TALLA (chanclas, cubre motos) y tapaba a la "Maleta Grande de Viaje con Ruedas 360°" que SÍ existe. Agregados a STOP de búsqueda: tall/quetal/buenass/disponen/etc. + sinónimos valija/equipaje → maleta. 2 tests. Suite 62/62.
- Falta: actualizar_github.bat (acumula también los fixes de contexto de la corrida anterior).

## Sonda web singular/plural 29/08/2026 (noche)
- Confirmado con la API de la web: el buscador de la página es LITERAL — "maleta" trae 16 maletas, "maletas" trae un candado y una balanza; "mochila" 34, "mochilas" 3 juguetes. Los nombres están cargados en singular.
- Nueva SONDA en agente.py: antes de armar el link "ver más", prueba las variantes (tal cual / singular / +s) contra /get-productos y elige la que CONTIENE el SKU del candidato que estamos recomendando (o la de más resultados). _web_resultados devuelve total+SKUs de la 1ra página, cacheado 6h. Marca [SONDA-WEB] en el log.
- Suite 63/63. Falta: actualizar_github.bat.

## Caso Gustavo + política de links 29/08/2026 (noche 2)
- Gustavo (24755852): "Podés pasar porfa / Foto" → buscó "podes" → PODS → ¡ofreció TIDE PODS y vapes con nicotina!; "Foto" solo → juegos de té, BBQ bucket, alambre. FIX: _pide_fotos ahora es por tokens (orden libre) y podes/pasar/foto/etc. entraron al STOP del buscador.
- Misael: "el todos terrenos" (plural) no matcheaba la jerga → ahora todos?/terrenos? con regex, mismo flujo calzados.
- POLÍTICA NUEVA (pedido del dueño): con VARIOS candidatos NO se pega la lista en texto — una línea con la familia + link "ver más" VERIFICADO (sonda) para que el cliente VEA con fotos. Solo sin link: 2-3 nombres máx. Prompt + contexto actualizados.
- Suite 67/67. Falta: actualizar_github.bat.

## Ubicación con Google Maps 29/08/2026
- Link del local verificado en vivo (abre "Shopping Asia", Av. Eusebio Ayala 1451): https://www.google.com/maps/place/Shopping+Asia/data=!4m2!3m1!1s0x0:0x8209184b8f599d4a
- Agregado a: regla 0-tokens de ubicación (con keywords nuevas: donde queda, como llegar, mapa...), links permitidos en _limpiar_salida, y base-conocimiento.md (copia del repo y la maestra). 5 tests. Suite 72/72.
- Falta: actualizar_github.bat.

## Monitoreo 30/08/2026 (corrida automática)
Suite 72/72 ok antes de tocar nada; catálogo 49.536 productos, fetch 200. 196 mensajes, 0% fallback, 9% derivación. Ajusté _CALZADO_TOKENS en app/agente.py: +"horma/orma" ("Orma grande" traía maletas y cubiteras) y +"correr/running" ("para correr en pistas" traía CORREAS); agregué sus 2 tests (suite ahora 74/74). Falta doble clic a actualizar_github.bat.
Pendientes detectados sin tocar: "taller 42" (typo de talle) respondió con llaves de tubo; texto unicode decorado (𝕔𝕒𝕝𝕫𝕒𝕕𝕠𝕤) no se normaliza (probar NFKD en _quita_tildes); saludo de pauta "más información" a veces busca "mas" y manda buscador?q=mas.

## Monitoreo 30/08/2026 13:10 (corrida automática)
Suite de regresión completa SIN regresiones (corrida local; avisos [CHICO] 403 son solo por falta de token en local, y los [PRECIO-FIX] del log son del propio test de listas inventadas).
NO pude leer /aprendizaje ni /diag: web_fetch bloqueado por procedencia y el navegador denegó la navegación (corrida sin usuario presente). Sin datos en vivo no toco código.
Siguen pendientes de la corrida anterior: "taller 42" (typo de talle), unicode decorado (probar NFKD en _quita_tildes), y buscador?q=mas del saludo de pauta. Falta doble clic a actualizar_github.bat de la corrida previa.

## Monitoreo 30/08/2026 ~08:30
Suite OK, catálogo OK (49.536 productos). 38 mensajes, fallback 0%, derivación 2,6%.
Ajusté: typos de "dirección" (DIRRCCION había caído al buscador → ofreció rótulas de auto) en reglas.py, y "terreno" al grupo botín en busqueda.py ("botines todo terreno" daba 0 candidatos). +4 tests en la suite.
Pendiente sin tocar: (a) "Tienen para mujer en 37" devolvió bicis/gargantillas (falta heredar rubro del hilo), (b) "Ropas kiero" prometió "opciones con fotos" pero el link se borró en la limpieza, (c) con clientes hablando de su salud el bot buscó productos ("sin dormir" → antifaz/bikinis). Falta doble clic a actualizar_github.bat.


## 0.7 — PENDIENTE DE DEPLOY (30/08 tarde): esperar que reviva el VPS

El dueño decidió NO desplegar hasta que vuelva la página (VPS DonWeb caído,
credenciales las maneja PORTA). Todo lo siguiente está TERMINADO Y TESTEADO
en el repo local (suite: 118 checks verdes) esperando `actualizar_github.bat`:

- Catálogo dinámico premium `/c/<término>` (todos los resultados, botón
  "Hacer pedido" wa.me/595976915333 igual al catálogo chico, fotos
  deslizables por SKU) + `/l/<skus>` con el mismo diseño.
- Buscador sobre el MAPA del catálogo: hiperónimos dirigidos
  (mascota⊃perro/gato sin cruzarlos, INF=infantil, dama=mujer...), familias
  PY (vincha=diadema, corpiño=sostén, juego=set=kit, ojota=chancla...),
  rescate del término más específico, listas cortas completadas,
  sinónimos camita/cama y frazada/acolchado.
- Fixes de chats: visión no dispara talle ni ensucia búsqueda (Yeni/Marta),
  "solo/xg" fuera de búsqueda, "Foto/Imágenes" siguen el hilo (Gustavo),
  typos shampiones/champiñones/champagne/grazep/knup, palabras META fuera
  del link del buscador, caché negativo de /foto.

FOTOS LOCALES (31/08): el dueño conectó D:/ECOMMERCE (~20.270 fotos,
LOTE/<sku>/<sku>.jpg + variantes "(2)") y "D:/Update 16 08 2026" (~4.199,
<sku>/<sku>,N.jpg multi-foto). generar_espejo.py v2 las junta con el
respaldo web y el depósito, VERIFICA (SKU en catálogo, imagen sana >=250px,
sin duplicados) y genera espejo MULTI-FOTO (hasta 4 por SKU + indice.json).
El cerebro ya lo consume (espejo_fotos.py, /foto?i=N, tarjetas deslizables).

ORDEN DE PUBLICACIÓN (sin esperar el VPS):
1. Doble clic `respaldo-fotos-github/verificar_fotos.bat` -> revisar informe
   (cuántas entran, cuáles quedan afuera y por qué).
2. Crear en github.com el repo `fotos` (Public).
3. Doble clic `respaldo-fotos-github/primera_publicacion.bat` (genera
   miniaturas ~20-40 min + push) y activar Pages (Settings -> Pages -> main).
4. Doble clic `actualizar_github.bat` (despliega cerebro con todo el lote).
5. Avisar a Claude: verifica /c y /foto en vivo + sondeo de chats.
6. (Cuando reviva el VPS) `python respaldar_fotos.py` en verificador-precios
   y doble clic `respaldo-fotos-github/publicar.bat` para sumar las que falten.

## 0.8 — IDENTIFICACIÓN DE PAUTAS POR UTM (31/08, listo en código)

Soporte Kommo confirmó: el "referral" de Meta NO se sincroniza nunca; el
camino oficial son UTMs en el link del anuncio (guía:
support.kommo.com/docs/es/haz-seguimiento-de-campaas-de-anuncios-en-whatsapp-con-utms).
El cerebro ya lee los UTM de la ficha del lead (kommo_api.utms_de_lead) y los
cruza con mapa-anuncios.md (conocimiento.ad_por_utm). Kommo ya está como
socio en la cuenta de WhatsApp de Meta (confirmado por el dueño 31/08).

La vinculación Kommo<->Meta YA está completa (los mensajes funcionan;
confirmado por el dueño 31/08). Falta solo:
1. En cada anuncio CTWA: link con ?utm_source=facebook&utm_medium=ctwa
   &utm_campaign=<producto> (grasep, crocs, ...).
2. Poner ese mismo valor como clave en datos/mapa-anuncios.md.
3. Verificación con el PRIMER lead que entre de una pauta con UTM: mirar
   su ficha -> Estadísticas -> Información rastreada; si los campos utm_*
   aparecen cargados, todo listo. Si quedaran vacíos, la guía menciona un
   permiso extra de "metadatos de anuncios" en WhatsApp Business -> Cuentas
   (banner), pero solo revisarlo en ese caso.

Herramienta nueva: `cerebro-kommo> python3 mapear_catalogo.py` (radiografía
del catálogo; correr tras cada sync grande; propone familias nuevas).

## Monitoreo 30/08/2026 (tarde)
- Suite 120/120 OK. Catálogo OK (49.536 productos, fetch 200). 173 mensajes, 6,9% derivación, 0 fallback.
- "todo terreno"/"grasep" daban 0 candidatos EN PRODUCCIÓN (sinónimos del 30/08 aún sin deploy) → falta doble clic a actualizar_github.bat (6 pendientes en cola).
- Ajusté busqueda.py: +"todoterreno/todoterrenos" (grupo botín) y +"grase" (grupo irun), con 2 tests nuevos en tests_regresion.py.

## Monitoreo 31/08/2026 10:23
- Suite 122/122 ok, catálogo 49.536 productos, GitHub activo. 372 mensajes, derivación 8,3%, fallback 0.
- Ajusté: "dnd" (abreviatura de dónde) en FAQ dirección de app/reglas.py + 2 tests — falta doble clic a actualizar_github.bat.
- Pendiente grande (no tocado): ante mensajes vagos ("más información", "foto y precio?") el buscador devuelve una lista genérica repetida (cepillos/shorts/relojes) y el bot la manda en vez de repreguntar; también hubo 1 pérdida de hilo (globos → estuches de celular, lead 24833664).

## Monitoreo 31/08/2026 (tarde, corrida programada)
- Suite 122/122 OK (sin regresiones). Sin cambios de código en esta corrida.
- No pude leer /aprendizaje ni /diag: el entorno de la corrida bloqueó tanto web_fetch (restricción de procedencia de URL) como el navegador (aprobación de sitio pendiente sin usuario presente). Sin datos de intercambios ni estado del catálogo esta vez.
- Pendientes de ayer siguen en pie: doble clic a actualizar_github.bat (dnd + sinónimos), y el problema de listas genéricas ante mensajes vagos.

## Monitoreo 31/08/2026 17:15 (corrida programada)
- Suite 123/123 OK. Catálogo OK (49.536 productos, fetch 200). 671 mensajes, derivación 9,2%, fallback 0, GitHub activo (8 pendientes en cola).
- Ajusté busqueda.py: +"camperita" en grupo campera ("Las camperitas si tienen en Xl" devolvía fajas, lead 24866578) + 1 test — falta doble clic a actualizar_github.bat.
- "todo terreno"/"grase" siguen apareciendo en sin_candidatos EN PRODUCCIÓN: los sinónimos del 30/08 aún no se deployaron (los 8 pendientes de GitHub incluyen esos fixes).
- Sigue vivo el problema de listas genéricas: ante "Buenas.." o "gracias" el bot manda la lista repetida cepillo/relojes o saluda de bienvenida en medio de la charla (leads 24870824, 24872746); y a "Quiro el catálogo" mostró fajas random. Propuesta: si el mensaje es saludo/agradecimiento sin pedido, responder corto sin lista.


## 0.9 — TIENDA PROVISORIA /tienda (31/08 noche)

Mientras la página oficial esté caída, la "página" para clientes es
https://cerebro-kommo.onrender.com/tienda — catálogo COMPLETO del cerebro:
portada con 14 categorías curadas (app/tienda.py), páginas de categoría
paginadas (/cat/<c>?p=N, 60 por página), buscador propio en TODAS las
páginas con filtro opcional de categoría (/buscar?q=&cat= -> /c/<q>?cat=),
tarjetas premium con carrusel (flechas + puntos + contador + clic +
arrastre, VERIFICADO con clics en navegador real). La base de conocimiento
(sección 5.0) le dice al bot que esa es la página que se comparte.
Cuando la web oficial reviva: avisar a Claude para decidir si la tienda
sigue (a los clientes les puede gustar más) o vuelve la oficial.
