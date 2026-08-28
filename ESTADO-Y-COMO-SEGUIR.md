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
