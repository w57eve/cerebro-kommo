# Cerebro de ventas (agente Kommo) — estado y cómo seguir

_Copia local del estado del proyecto. Para retomar con cualquier modelo/sesión, pasale este archivo o pedile que lo lea._

## 0. RESUMEN
El agente FUNCIONA en lo esencial: responde dentro de Kommo con IA, entrega el
mensaje al cliente, usa el catálogo completo (49.536 productos) y manda fotos.
Queda UN bloqueo (ver 0.1): sólo contesta el PRIMER mensaje de cada conversación.
Todo lo demás (entrega, auth, catálogo, fotos, audios) ya está resuelto.

## 0.1 BLOQUEO ACTUAL — que conteste TODOS los mensajes de una charla
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
1. BLOQUEO: que conteste TODOS los mensajes de una charla (ver 0.1). Es lo único que falta.
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
