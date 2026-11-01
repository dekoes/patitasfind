# Grupos públicos de Facebook y voluntarios

Guía para el equipo de GuauWoow: cómo funciona la lectura de grupos públicos de Facebook por estado,
cómo encontrar y cargar grupos, qué cuesta, cómo operarlo desde el panel y cómo ayudan los voluntarios.

> **Antes de activar grupos: revisión legal pendiente.** Leer grupos públicos con un proveedor externo
> (Apify) es una decisión del negocio que la investigación legal **no pudo validar** y marcó para el abogado
> (`docs/legal/secciones/contenido-plataforma.md` §3.10, `comunicaciones-cookies.md` v03 y P14,
> `buenas-practicas.md` 08 y 15). Puntos abiertos:
>
> - Los Términos de servicio de Meta (sección 3.2, numeral 3) y los *Automated Data Collection Terms*
>   prohíben recopilar datos con medios automatizados sin permiso por escrito. Que lo haga un tercero no
>   está analizado, y hay riesgo para la cuenta de Meta Business, la WhatsApp Cloud API y la Graph API.
> - LFPDPPP art. 17 (datos que no se obtienen del titular): se necesita aviso o medidas compensatorias.
>   Art. 26: hay que atender la oposición. La NMX 8.1 k) pide consentimiento para datos de redes sociales.
> - Derechos de autor de las fotos (LFDA 114 Octies): al importar, GuauWoow no tiene puerto seguro.
> - Contrato y DPA con Apify (encargado o fuente, país donde procesa, cuánto tiempo conserva los datos).
>
> Mientras no haya opinión del abogado, deja los grupos **pausados** o no configures `APIFY_TOKEN`. Así el
> catálogo se puede armar sin que se lea nada.

## 1. Cómo funciona

1. Alguien publica un reporte de perrito perdido o encontrado desde la app o el bot de WhatsApp. La app
   manda el **estado** (lo toma del geocodificador o del selector «Estado» del formulario). El bot lo deduce
   de la ciudad o de las coordenadas (`backend/app/data/estados_mx.py`: capitales y municipios grandes; en las
   zonas limítrofes, si dos estados quedan casi a la misma distancia, no adivina y no se leen grupos).
2. El backend encarga la tarea `fetch_zone(estado)`. La tarea toma los grupos **activos** de ese estado que
   no se han intentado leer en `FB_GROUPS_FETCH_INTERVAL_HOURS` (12 h por defecto; un intento con error
   también cuenta, para no reintentar en ráfaga).
3. Antes de cada corrida **aparta** su costo máximo del **presupuesto diario** (`FB_GROUPS_DAILY_BUDGET_USD`,
   en Redis, de forma atómica). Si no cabe, se detiene hasta el día siguiente (00:00 UTC) y lo anota una sola
   vez en los logs.
4. Apify (actor `apify/facebook-groups-scraper`) devuelve las publicaciones públicas del grupo desde
   la **última lectura correcta**, con tope de `FB_GROUPS_LOOKBACK_DAYS` (14 días). Si una lectura falla
   (saldo, tiempo, red), la siguiente vuelve a pedir desde la última correcta: no se pierden publicaciones.
   El máximo es `FB_GROUPS_MAX_POSTS_PER_RUN` (100) por grupo y corrida. Al terminar, GuauWoow **borra el
   dataset de la corrida en Apify** (no quedan copias de las publicaciones allá).
5. A cada publicación se le **quitan teléfonos, correos, @usuarios, enlaces (también sin `https://`, como
   `m.me/...` o `facebook.com/...`), tarjetas y CLABE, números de casa y nombres de contacto** («Contacto: …»,
   «pregunta por …»). Solo se importan las que parecen de perros perdidos o encontrados y cuya foto es de un
   perro (si la IA está configurada). Se guardan con fuente `facebook`, el estado y la ciudad del grupo, la fecha
   de la publicación y el enlace a la publicación original, y se deduplican por ese enlace (índice único: ni dos
   envíos simultáneos crean dos reportes).
6. Cada reporte nuevo pasa por el *matching* contra los reportes de la app.
7. Una tarea diaria marca como `expired` los reportes importados (y los envíos de voluntarios) cuya
   **publicación** tiene más de `FB_GROUPS_POST_TTL_DAYS` / `FB_VOLUNTEER_POST_TTL_DAYS` (30 días): dejan de ser
   públicos (ni el detalle ni las listas) y `FB_IMPORTED_PURGE_AFTER_DAYS` después (0 = el mismo día) se
   **borran su texto y sus fotos**. Se conserva el registro y el enlace, para no volver a importarlos.

Los teléfonos de las publicaciones importadas **nunca** se usan para escribir por WhatsApp ni SMS.

## 2. Configuración (servidor)

| Variable | Por defecto | Para qué sirve |
| --- | --- | --- |
| `APIFY_TOKEN` | vacío | Token de la API de Apify. Vacío = proveedor no configurado: las tareas avisan una vez y no hacen nada. |
| `APIFY_FB_GROUPS_ACTOR` | `apify/facebook-groups-scraper` | Actor de Apify que lee los grupos. |
| `FB_GROUPS_FETCH_INTERVAL_HOURS` | `12` | Un grupo no se vuelve a leer antes de este plazo. |
| `FB_GROUPS_LOOKBACK_DAYS` | `14` | En la primera lectura (o tras una pausa) se piden publicaciones de estos días. |
| `FB_GROUPS_MAX_POSTS_PER_RUN` | `100` | Tope de publicaciones por grupo y corrida. Controla el costo. |
| `FB_GROUPS_DAILY_BUDGET_USD` | `2.0` | Gasto máximo por día (UTC). Al pasarlo, se detiene. |
| `FB_GROUPS_COST_PER_1000_POSTS_USD` | `7.0` | Precio estimado del actor por cada 1,000 publicaciones: ~0.005 USD por publicación + 0.002 por el filtro de fecha, que siempre se usa (plan gratuito, oct. 2026; revísalo en la ficha del actor). |
| `FB_GROUPS_COST_PER_RUN_USD` | `0.005` | Cargo estimado por arranque de cada corrida. |
| `FB_GROUPS_POST_TTL_DAYS` | `30` | Los reportes importados de grupos caducan a estos días **de la publicación original**. |
| `FB_VOLUNTEER_POST_TTL_DAYS` | `30` | Lo mismo para los envíos de voluntarios. |
| `FB_IMPORTED_PURGE_AFTER_DAYS` | `0` | Días después de caducar en que se borran texto y fotos (0 = el mismo día; el aviso de contenido importado promete el borrado a los 30 días). |

El panel (**Admin → Facebook**) muestra si el proveedor está configurado. Sin token aparece el aviso
«Proveedor no configurado (APIFY_TOKEN)».

## 3. Cómo encontrar grupos públicos por estado

Hazlo a mano, con una cuenta personal y desde el navegador. GuauWoow no inicia sesión en Facebook.

1. En el buscador de Facebook escribe frases como las de la tabla de abajo y elige el filtro **Grupos**.
2. Abre cada resultado y revisa estos criterios:
   - **Público**: debajo del nombre dice «Grupo público». Los grupos privados no se pueden leer, no los cargues.
   - **Tema**: perros (o mascotas) perdidos y encontrados, rescate o adopción. **Descarta** los de compraventa
     de animales («vendo», «cachorros de raza», «criadero»): la venta de perros está prohibida en
     GuauWoow (ver `bienestar-animal.md`, hallazgo 04).
   - **Actividad**: varias publicaciones en la última semana.
   - **Zona**: que corresponda a un estado o a una ciudad concreta. Anota la ciudad si el grupo es local.
   - **Tamaño**: prefiere los grupos grandes (miles de miembros). Dos a cinco grupos buenos por estado
     rinden más que veinte pequeños, y cuestan menos.
3. Copia la URL del grupo en formato `https://www.facebook.com/groups/<alias o número>`, sin `?ref=...`
   ni `/posts/...`.
4. Cárgalos **pausados** al principio: con el CSV, los grupos nuevos quedan pausados salvo que la columna
   `active` diga `sí` (ver §4). Prueba uno con **Leer ahora** y revisa en el panel cuántos reportes creó y si
   hubo errores antes de activar el resto.

Frases de búsqueda sugeridas (cambia la ciudad por la capital o la zona metropolitana del estado):

| Para | Frases |
| --- | --- |
| Perdidos y encontrados | `perros perdidos <ciudad>`, `mascotas perdidas <ciudad>`, `perros extraviados <estado>`, `se busca perrito <ciudad>` |
| Rescate | `rescate animal <ciudad>`, `rescatistas <ciudad>`, `perritos en adopción <ciudad>` |
| Zonas metropolitanas | `mascotas perdidas zona metropolitana de <ciudad>`, `perros perdidos <municipio>` (p. ej. Zapopan, Ecatepec, San Nicolás) |

Este documento **no trae una lista de grupos reales**. Si alguien agrega nombres de grupos encontrados en
internet, deben llevar la nota **«verificar antes de activar»** hasta que una persona del equipo los revise
con los criterios de arriba.

## 4. Formato del CSV

Archivo de texto UTF-8 separado por comas, con este encabezado exacto en la primera línea:

```csv
name,state,city,group_url,active
"Perritos perdidos Zapopan (ejemplo, reemplázalo)",Jalisco,Zapopan,https://www.facebook.com/groups/ejemplo-zapopan,no
"Mascotas perdidas Monterrey (ejemplo, reemplázalo)",Nuevo León,Monterrey,https://www.facebook.com/groups/ejemplo-monterrey,no
```

El encabezado mínimo sigue siendo `name,state,city,group_url`; la columna `active` es opcional.

Las dos filas de arriba son **ejemplos inventados**. No las importes así.

| Columna | Obligatoria | Contenido |
| --- | --- | --- |
| `name` | sí | Nombre del grupo como aparece en Facebook. Si lleva comas, va entre comillas dobles. |
| `state` | sí | Nombre oficial corto del estado (lista abajo). |
| `city` | no | Ciudad o municipio si el grupo es local. Puede ir vacío: `Grupo,Jalisco,,https://...` |
| `group_url` | sí | `https://www.facebook.com/groups/<alias o número>` |
| `active` | no | `sí` / `1` / `true` = activo; `no` / `0` / vacío = **pausado**. Sin la columna, los grupos **nuevos** quedan pausados y los que ya existen conservan su situación. |

Estados válidos (los mismos de `backend/app/data/estados_mx.py`): Aguascalientes, Baja California,
Baja California Sur, Campeche, Chiapas, Chihuahua, Ciudad de México, Coahuila, Colima, Durango, Guanajuato,
Guerrero, Hidalgo, Jalisco, **México** (Estado de México), Michoacán, Morelos, Nayarit, Nuevo León, Oaxaca,
Puebla, Querétaro, Quintana Roo, San Luis Potosí, Sinaloa, Sonora, Tabasco, Tamaulipas, Tlaxcala, Veracruz,
Yucatán y Zacatecas.

Para importar, entra a **Admin → Facebook → Importar CSV**. También puedes bajar ahí la plantilla. El
resultado dice cuántos grupos se crearon (y cuántos quedaron pausados), cuántos se actualizaron o se omitieron
(misma URL) y qué filas tienen error, con su número de línea. El panel revisa el encabezado antes de enviar el
archivo. Los encabezados también se aceptan en español (`nombre,estado,ciudad,url,activo`).

## 5. Costos y presupuesto

- Costo estimado de una corrida = publicaciones × `FB_GROUPS_COST_PER_1000_POSTS_USD` / 1,000 +
  `FB_GROUPS_COST_PER_RUN_USD`. Con los valores por defecto, una corrida de un grupo cuesta como máximo
  100 × 7 / 1,000 + 0.005 = **0.705 USD**, y el presupuesto de 2 USD diarios alcanza para unas
  **280 publicaciones al día** (2 USD / 0.007, menos 0.005 USD por cada corrida).
- Antes de cada corrida se **aparta** su costo máximo (0.705 USD) de forma atómica en Redis; si no cabe, la
  corrida no se hace. Ese mismo monto es el tope de gasto que se le pasa a Apify (`maxTotalChargeUsd`), así que
  ninguna corrida puede cobrar más de lo apartado y varias tareas en paralelo nunca rebasan el presupuesto. Con
  2 USD caben dos corridas completas en curso a la vez.
- Al terminar se ajusta con el **costo real** que informa Apify para la corrida (`usageTotalUsd`) o, si no
  lo da, con la estimación por publicaciones devueltas. Si la corrida falla después de arrancar, se cuenta lo
  que Apify ya cobró (al menos el arranque).
- **Leer ahora** (manual) también cuenta para el presupuesto del día.
- El panel muestra el gasto de hoy contra el presupuesto (la barra se pone ámbar al 75 % y roja al 100 %),
  el costo acumulado por grupo y el historial de los últimos 7 días. Compáralos cada mes con la consola de
  Apify (*Billing*) y ajusta `FB_GROUPS_COST_PER_1000_POSTS_USD` y `FB_GROUPS_COST_PER_RUN_USD` a tu plan.

## 6. Operación desde el panel (Admin → Facebook)

- **Filtros**: por estado (incluido «Sin estado»), por situación (activos o pausados) y búsqueda por nombre,
  ciudad o URL.
- **Agregar / Editar**: nombre, URL del grupo, estado, ciudad y casilla «Activo».
- **Pausar / Activar**: un grupo pausado no se lee, pero sus reportes siguen visibles hasta que caducan.
- **Eliminar**: borra el grupo del catálogo. Los reportes que ya importó se conservan hasta que caducan.
- **Leer ahora**: encarga la lectura del grupo sin esperar el intervalo. Los resultados (publicaciones leídas,
  reportes creados, costo y último error) aparecen en la tabla unos minutos después; recarga la sección.
  Sin `APIFY_TOKEN` o con el presupuesto del día agotado, el panel muestra el motivo y no lee nada.
- **Estados sin grupos activos**: lista de estados sin cobertura, para saber dónde buscar más grupos.
- **Último error** (pasa el cursor para ver el texto completo):
  - «Apify rechazó el token»: revisa `APIFY_TOKEN` y los permisos del actor.
  - «Apify no tiene saldo»: recarga en Apify o espera al siguiente ciclo del plan.
  - «tardó demasiado» o «limitó las peticiones»: es temporal y se reintenta en la siguiente corrida, desde la
    última lectura correcta.
  - «Lectura incompleta»: Apify agotó el tiempo; se importó lo leído y la siguiente corrida pide de nuevo
    desde la última lectura correcta (los duplicados se descartan por enlace).
  - Si un grupo falla varias veces seguidas o lleva semanas sin crear reportes, **páusalo**. Puede que se
    haya vuelto privado o que ya no tenga actividad.

### Solicitudes de retiro

Cada reporte importado muestra la etiqueta «Importado de una publicación pública; su autor no es usuario de
GuauWoow», la fecha y el enlace a la publicación original, y el botón **«Soy el autor: retirar o
reclamar»**, que funciona **sin cuenta** (`POST /facebook/author-removal`, con límite por IP):

1. La persona deja su correo y su relación con la publicación. El reporte se **oculta de inmediato** y llega
   una solicitud con el motivo «Retiro pedido por el autor (sin cuenta)» a **Admin → Moderación** (también un
   aviso a los admins). La persona recibe un folio.
2. Si no descartas la solicitud, la tarea diaria **borra su texto y sus fotos a las 72 horas**. Si la
   solicitud no procede (abuso), descártala y vuelve a mostrar el reporte desde Moderación.
3. Responde a la persona en el correo que dejó. Si ejerce derechos ARCO, aplica los plazos del aviso de
   privacidad. Si lo pide para todo el grupo, pausa o elimina el grupo del catálogo.

El texto completo para el público está en la plantilla `app/legal/plantillas/contenido-importado.html`
(sección 8); hay que generarla y publicarla antes de configurar `APIFY_TOKEN`.

## 7. Voluntarios: enviar publicaciones a GuauWoow

Cualquier persona con sesión iniciada y teléfono verificado puede enviar una publicación que vio en Facebook.
Se convierte en un reporte con fuente `volunteer`, quien la envía queda como responsable y se busca
coincidencia con los reportes de la app.

- **Botón para voluntarios** (computadora): en la app, *Perfil → Ayuda → Botón para voluntarios*, se arrastra
  el botón «🐾 Enviar a GuauWoow» a la barra de marcadores. Funciona así:
  1. La persona abre una publicación o selecciona su texto en el muro del grupo y toca el marcador.
  2. Se abre `/app/?share=1&url=<publicación>&text=<texto>` en otra pestaña, con el formulario
     «Enviar publicación» ya lleno.
  3. Si seleccionó texto dentro de una publicación del muro, el botón toma el enlace de esa publicación y no
     el del grupo.
- **Android**: con GuauWoow instalada (menú del navegador → *Agregar a pantalla de inicio*), en Facebook se
  toca *Compartir → Más opciones → GuauWoow*. Para esto la app web declara un `share_target` (GET con
  `title`, `text` y `url`) en `manifest.webmanifest`.
- **iPhone**: Safari no permite recibir contenido compartido desde otras apps. La persona copia el enlace de
  la publicación y lo pega en *Ayuda → Enviar una publicación ahora*.
- El formulario pide el enlace de la publicación (no el del grupo ni el de un perfil: la app y el backend
  rechazan `/groups/<id>`, el inicio, `/marketplace` y `/<usuario>`), el texto, fotos opcionales (máximo 5),
  si el perrito se perdió o lo encontraron, la ciudad y el estado. La ciudad y el estado se llenan con la
  ubicación guardada de la persona. También pide marcar esta confirmación, que el backend exige y guarda con la
  fecha y la versión de los términos (`consent_at`, `consent_version`): *«Confirmo que la publicación es
  pública, que no incluyo datos de contacto de otras personas y que entiendo que GuauWoow puede retirarla a
  petición de su autor.»*
- Límites: **10 envíos al día** por persona. Una publicación ya enviada no se duplica (se compara el enlace).
  El texto pasa por el mismo filtro de datos personales que la lectura de grupos.
- Avisos: el envío no trae coordenadas, así que se avisa a los refugios y casas de paso de la ciudad (no a los
  vecinos por distancia) y se compara con los reportes de la app.
- En el detalle del reporte se muestra la etiqueta «vía voluntario», el aviso de contenido importado con el
  enlace al original y el botón de retiro. Caduca igual que lo importado de grupos (30 días) y no se renueva.
