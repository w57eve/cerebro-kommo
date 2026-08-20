# Cerebro de ventas — Shopping Asia (agente para Kommo)

Agente de ventas para responder en Kommo (WhatsApp + redes) usando la
infraestructura de Shopping Asia: base de conocimiento, precios/SKU del sitio,
catálogo, web y derivación a vendedores. Diseñado para **gastar poco**: primero
resuelve con reglas (0 tokens), y solo usa IA (Haiku, con caché) para lo abierto.

## Qué hace
- Recibe los mensajes desde Kommo (Salesbot `widget_request`).
- Responde en **un solo mensaje** (cada mensaje de la línea oficial se cobra).
- Usa reglas para lo repetido (horarios, envíos, pagos, mayorista, cambios…).
- Busca precio/foto por **SKU o nombre** en el sitio (datos públicos).
- La búsqueda por foto/nombre es **sugerencia**: si no es clara, ofrece opciones
  o pide el SKU; nunca inventa.
- Deriva al **WhatsApp personal** del vendedor de turno (wa.me) — esa parte no
  se cobra.

## Estructura
```
app/            código del agente
  main.py       servidor FastAPI (webhook)
  agente.py     orquestador (reglas -> producto -> IA)
  reglas.py     respuestas de 0 tokens (se amplía con el tiempo)
  productos.py  índice de precios/SKU/fotos del sitio
  vendedores.py rotación + botón "Hablar con {vendedor}"
  kommo.py      valida el webhook y contesta a Kommo
  llm.py        llamada a Anthropic (con prompt caching)
  conocimiento.py  carga base-conocimiento.md y el mapa de anuncios
datos/          base-conocimiento.md + mapa-anuncios.md
render.yaml     configuración para Render
```

## Desplegar en Render (paso a paso)
1. En Render: **New → Web Service** y conectá este repo de GitHub.
2. Build Command: `pip install -r requirements.txt`
   Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   (Si usás "Blueprint", Render lee `render.yaml` y lo hace solo.)
3. Plan: **Starter** (no se duerme).
4. En **Environment** cargá estas variables (los valores NO van en el repo):

   | Variable | Qué es | ¿Obligatoria? |
   |---|---|---|
   | `ANTHROPIC_API_KEY` | tu API key de Anthropic | Sí |
   | `KOMMO_SUBDOMAIN` | `tucuenta.kommo.com` | Sí |
   | `KOMMO_TOKEN` | token de larga duración de Kommo | Sí |
   | `KOMMO_SECRET_KEY` | clave secreta de la integración (valida el webhook) | Recomendada |
   | `CATEGORIAS_INDEX` | categorías del sitio a indexar (ej. `7`) | No (default 7) |
   | `VENDEDORES` | `Nombre:numero,...` | No (ya trae los 3) |

5. Deploy. Cuando termine, Render te da una URL tipo
   `https://cerebro-shoppingasia.onrender.com`.
6. Probá que vive: abrí `.../health` en el navegador.
7. En Kommo, en el Salesbot, poné esa URL + `/webhook` como destino del
   `widget_request`. (Y sumá el campo del anuncio de Meta al `data` si querés
   que detecte la campaña.)

## Probar sin Kommo
```
curl -X POST https://TU-URL/probar -H "Content-Type: application/json" \
  -d '{"mensaje":"hacen envios?","ad_id":""}'
```

## Notas para afinar en vivo
- Los nombres de campos del JSON del sitio (precio, nombre) se leen de forma
  defensiva; si algún precio no aparece, conviene confirmar el nombre exacto del
  campo en `get-productos` y ajustarlo en `app/productos.py`.
- El campo del anuncio de Meta que Kommo pasa al `data` se define en el flujo del
  Salesbot; `app/kommo.py:extraer_ad_id` prueba varios nombres.
- Cada consulta repetida que veas conviene sumarla como regla en `app/reglas.py`:
  eso la vuelve gratis (0 tokens).
