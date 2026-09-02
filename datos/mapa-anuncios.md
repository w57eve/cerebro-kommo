# Mapa de anuncios de Meta → producto / sección

Cada fila conecta un **anuncio de Meta** con lo que representa, para que el agente
sepa de qué habla la conversación que entra desde ese anuncio y responda preciso.
Se agregó **Tipo** (puntual / sección / genérico / web) y **Alcance-apertura**
(cómo arranca el agente), porque muchas pautas son genéricas (videos de una
sección) y no traen un SKU.

| ID anuncio (Meta) | Representa | Tipo | SKU(s) | Alcance / apertura del agente | Notas |
|---|---|---|---|---|---|
| 120248620117310576 | OFERTAS DE PRENDAS | genérico | — | Sección **Prendas** (ofertas). Ofrece catálogo de prendas, pregunta qué busca. | chat en redes y WhatsApp |
| 120248330444190576 | CHAMPIONS IRUN | sección (línea) | toda la línea IRUN | Categoría **IRUN** completa. Ofrece catálogo IRUN, acota por talle/color. | chat en redes y WhatsApp |
| 120246977609390576 | Maquillaje | web | — | Destino **página web**. Suele llegar ya mirando la web; ayuda con dudas/precios y deriva si hace falta. | destino página web |
| 120248642144860576 | CALZADOS (video general) | genérico | — | Sección **Calzados**. Ofrece catálogo de calzados, pregunta qué busca. | video general de la sección · chat redes y WhatsApp |
| champion_irun | CHAMPIONES IRUN (campaña "champion irun") | sección (línea) | toda la línea IRUN | Categoría **IRUN** completa: regla fija de calzados (catálogo chico primero, horma chica). | clave UTM: utm_campaign=champion_irun en los anuncios "championes de calidad" (31/08) |
| calzados_irun_nuevo | CALZADOS IRUN (video, campaña "CALZADOS IRUN NUEVO") | sección (línea) | toda la línea IRUN | Categoría **IRUN** completa: regla fija de calzados (catálogo chico primero, horma chica). | clave UTM: utm_campaign=calzados_irun_nuevo · video · saludo del anuncio ya pasa el catálogo (31/08) |
| prendas_invierno | OFERTA DE PRENDAS — ropa de invierno | sección | — | Sección **Prendas de invierno** (camperas, buzos, abrigos, frazadas). NO está en el catálogo chico: preguntar qué busca (tipo de prenda, talle) y ofrecer opciones del catálogo grande. | clave UTM: utm_campaign=prendas_invierno (31/08) |
| https://www.facebook.com/ShoppingAsiapy/posts/122115226179299504 | BOTINES GRASEP (publicación FB) | sección (línea) | toda la línea IRUN | Botines GRASEP / línea **IRUN**: regla fija de calzados. | identificada por el chat de Jorge 31/08; el cliente pega este link |

## OFERTA FLASH — una publicación por artículo (01/09)
NO hace falta una fila por publicación. Regla automática del cerebro:
si el link del anuncio lleva `utm_content=flash_<SKU>` (también vale
`sku_<SKU>` o el SKU pelado), el bot identifica el artículo EXACTO del
catálogo: saluda nombrándolo, da el precio y cierra — sin listas ni búsqueda.
- Link tipo para cada pauta flash:
  `https://wa.me/<numero>?utm_source=fb&utm_medium=paid&utm_campaign=oferta_flash&utm_content=flash_<SKU>`
  (en el Administrador de anuncios: parámetros de URL, campo key/value).
- Para PUBLICACIONES ORGÁNICAS (sin utm): poner en el texto/botón un link
  de WhatsApp con mensaje precargado que incluya el SKU, p. ej.
  `https://wa.me/<numero>?text=Hola!%20Quiero%20la%20OFERTA%20FLASH%20SKU%20<SKU>`
  — el bot ya extrae el SKU del mensaje y confirma el producto exacto.

## Cómo se completa a futuro
- **ID anuncio:** el de Meta Ads (lo captura Kommo cuando el chat entra desde un
  anuncio click-to-WhatsApp).
- **Tipo:** `puntual` (un producto/SKU), `sección` (una categoría/línea),
  `genérico` (video de sección, consultas variadas), `web` (manda a la página).
- **SKU(s):** solo si es puntual (máxima exactitud).
- **Alcance / apertura:** para genéricos, la sección + cómo arranca el agente.

> Cada anuncio nuevo = una fila nueva. Los genéricos no necesitan SKU: el agente
> usa la sección como marco y acota con el catálogo + búsqueda por foto/nombre.
