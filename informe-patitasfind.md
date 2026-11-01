# GuauWoow — Investigación y Propuesta de Plataforma de Adopción y Búsqueda de Perros en México

**Fecha:** 8 de septiembre de 2026
**Alcance:** Panorama de plataformas existentes en México y el mundo, propuesta de mejora con inteligencia artificial, WhatsApp y bots de redes sociales, y análisis de seguridad.
**Nota:** El directorio del proyecto GuauWoow está actualmente vacío; este documento sirve como documento fundacional del producto.

---

## 1. Resumen ejecutivo

- México es el país de América Latina con mayor abandono animal: **29.7 millones de perros y gatos en situación de calle** (Mars Petcare) y cerca de **500,000 animales abandonados al año**; ~**128,000 perros y gatos esperan en refugios**.
- Las plataformas mexicanas actuales (AdoptaMx, Adoptist, Ubicapet, Perromies by NUPEC, directorios de refugios) son esencialmente **catálogos estáticos + WhatsApp manual**: no hay matching inteligente, no hay búsqueda de mascotas perdidas y la verificación de adoptantes es débil.
- En el extranjero ya existe tecnología probada para lo que GuauWoow quiere hacer: **reconocimiento facial canino** (Finding Rover, ~98% de precisión, 15,000 reencuentros; Petco Love Lost en EE.UU.; Mascofinder en España que **rastrea Internet automáticamente** comparando fotos). Esto valida la viabilidad técnica y deja clara la oportunidad: **nadie lo ha hecho bien en México, con WhatsApp como canal principal**.
- La propuesta se organiza en **4 módulos**: (a) plataforma web/app de adopción, (b) bot de WhatsApp (reportes de perdidos/encontrados + gestión de adopciones), (c) motor de IA de reconocimiento de perros (fase gruesa → media → fina), y (d) bot de rastreo en redes sociales.
- Se identifican **8 vectores de abuso principales** (estafas de "adoptimo", suplantación, robo de perros usando la plataforma como catálogo, peleas de perros/carnada, contenido falso de rescates, doxing, bots de spam, venta encubierta). Para cada uno se define una contramedida.
- Se proponen **15 mejoras** sobre el estado del arte y **10 funciones** priorizadas por demanda de rescatistas y adoptantes.

---

## 2. Panorama del problema en México

Cifras clave que dimensionan el problema (fuente: Mars Petcare, INEGI, prensa especializada):

| Dato | Valor |
|---|---|
| Perros y gatos en situación de calle en México | 29.7 millones (1.º lugar en América Latina) |
| Animales abandonados por año | ~500,000 |
| Perros y gatos en refugios esperando adopción | ~128,000 (96 mil perros, 32 mil gatos) |
| Animales que mueren anualmente por maltrato (INEGI) | 60,000 |
| Perros con hogar esterilizados | Solo 55% |

Lectura estratégica: hay **más oferta (perros) que demanda (adoptantes)**, y la demanda se concentra en cachorros. La barrera real no es la falta de gente que quiere ayudar, sino la **fricción del proceso**: información dispersa en Facebook e Instagram, procesos opacos de cada refugio, sin estándares y sin herramientas de búsqueda para perros perdidos.

---

## 3. Qué existe hoy en México (estado del arte local)

| Plataforma / Organización | Qué hace | Debilidad (oportunidad para GuauWoow) |
|---|---|---|
| **AdoptaMx (@adopta.mx)** | Difusión de adopciones en redes y plataforma en línea | Difusión manual, sin matching, sin verificación de adoptantes |
| **Adoptist** (aliada de NUPEC, campaña Mextizos) | Plataforma de adopción con base de datos de refugios; NUPEC reporta 6,000+ adopciones promovidas | Centrada en catálogo; sin IA ni búsqueda de perdidos |
| **Perromies by NUPEC** | Adopciones digitales de 1,000+ perros | Limitada a la red de refugios aliados de la marca |
| **Ubicapet** | Directorio de grupos, asociaciones, veterinarias y servicios | Es un directorio estático; no gestiona procesos |
| **Adopta Un Amigo CDMX** | Difusión local en CDMX | Alcance limitado a una alcaldía/ciudad |
| **Refugios con WhatsApp manual** (Huellitas de Amor Tepic, Mundo Patitas, CIPAM, Fundación Haghenbeck, protectoras de Chapultepec, etc.) | Atienden adopciones por WhatsApp/Facebook de forma artesanal, caso por caso | Procesos lentos, dependen de voluntarios, no escalan; **aquí es donde WhatsApp es ya el canal de facto** |
| **Grupos de Facebook "Mascotas perdidas + colonia"** | Búsqueda de perdidos por publicaciones | La información se pierde en el feed en horas; sin búsqueda cruzada |

**Conclusión del estado local:** el ecosistema mexicano está fragmentado en difusión (redes), catálogos (plataformas) y procesos manuales (WhatsApp). No existe hoy una plataforma mexicana que una adopción + búsqueda de perdidos con IA + WhatsApp + rastreo en redes.

---

## 4. Qué se ha hecho en el mundo (lecciones transferibles)

### 4.1 Reconocimiento facial / matching por foto

- **Finding Rover (EE.UU.)** — pionero en reconocimiento facial canino: escanea ~130 puntos de referencia (distancia entre ojos, hocico, color y textura del pelaje). Reporta **98% de precisión** y **15,000 mascotas reencontradas**; asociado a 600 refugios. Solo opera en EE.UU.
- **Petco Love Lost (EE.UU.)** — base de datos nacional de perdidos/encontrados con reconocimiento facial; cualquiera sube una foto y cruza con animales reportados. Gratuito.
- **Mascofinder (España)** — el más cercano a la idea de GuauWoow: **rastrea Internet diariamente** (redes sociales y webs de protectoras) buscando imágenes que coincidan con mascotas perdidas, usando IA que analiza color de pelaje, manchas, forma de hocico, ojos, orejas y cola. Validación de usuarios previa, difusión por email geolocalizado y publicidad segmentada por zona. **Es la prueba de concepto directa del bot rastreador.**
- **Mr. Odis (Uruguay/Argentina)** — app latinoamericana que conecta fotos de perdidos con encontrados vía IA; incluye calendario de vacunas/desparasitación y directorio de servicios. Lección: la **descripción textual complementa a la foto** cuando la imagen es de mala calidad.
- **Estudio Saturdays.AI** — arquitectura de 3 fases validada con modelos abiertos: **fase gruesa** (clasificación de raza, Inception v3, ~83% accuracy), **fase media** (detección de rostro, YOLO v5, ~98.5% mAP), **fase fina** (identificación, Xception) + **decisión supervisada** con metadatos (edad, género). Usa datasets abiertos (Stanford Dogs, 120 razas). Es un blueprint técnico reproducible para GuauWoow.

### 4.2 Modelos de negocio / adopción

- **Petfinder (EE.UU.)** — 315,000 mascotas, 14,000 refugios; muestra que el modelo "red de refugios + catálogo nacional" escala si se da herramientas a los refugios.
- **Ooh! Cachorros (Colombia)** — publicación **100% gratuita para rescatistas independientes** y refugios pequeños, con plan institucional pagado. Lección de monetización sin cerrar el acceso a quien rescata.
- **Buscacucha / Guau (Argentina)** — formato "Tinder de adopción" con filtros por tamaño, edad, género y geolocalización; confirmaron que el filtro por edad es crítico y que la demanda se concentra en cachorros.
- **NexZoo (Colombia)** — lección clave: *"las apps con mejor diseño que nadie usa no salvan mascotas"*; la masa crítica de usuarios por ciudad importa más que las funciones. También valida que **los grupos de WhatsApp de barrio son hoy el canal más rápido**, y que las placas QR son un complemento útil.
- **Datos de comportamiento** — los gatos perdidos suelen quedarse en un radio de ~300 m; los perros recorren hasta ~3.5 km. Implica que la búsqueda debe ser **geolocalizada por radios**. Menos del 25% de perros perdidos y 5% de gatos regresan desde refugios en EE.UU. si no hay una herramienta de búsqueda.

### 4.3 El rol de WhatsApp en LatAm

En México y Latinoamérica, WhatsApp es el canal de facto de los rescatistas (la mayoría de los refugios mexicanos ya atienden adopciones por WhatsApp). Los grupos de barrio de "mascotas perdidas y encontradas" son el mecanismo más efectivo hoy, pero su falla es estructural: la información no se indexa ni se cruza. Esto es exactamente el hueco que GuauWoow puede ocupar: **mantener el canal que la gente ya usa, pero estructurar los datos detrás**.

---

## 5. Arquitectura propuesta de GuauWoow

```
┌─────────────────────────────────────────────────────────────┐
│                     USUARIOS Y CANALES                       │
│  App web/móvil   WhatsApp (bot)   Redes sociales (rastreo)  │
└──────────┬──────────────┬──────────────────┬────────────────┘
           │              │                  │
┌──────────▼──────────────▼──────────────────▼────────────────┐
│                    CAPA DE INGESTA                           │
│  Formularios     WhatsApp Cloud API      Bot rastreador      │
│  de adopción     (foto + ubicación)      (APIs/permisos)     │
└──────────┬──────────────────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────────────────┐
│              CAPA DE INTELIGENCIA ARTIFICIAL                 │
│  • Clasificación de raza (fase gruesa, Inception/ResNet)     │
│  • Detección de rostro (YOLO v8)                             │
│  • Embeddings de identidad (fase fina, Xception/Siamese)     │
│  • OCR/LLM para extraer datos de publicaciones rastreadas    │
│  • Geocercas y scores de cercanía                            │
└──────────┬──────────────────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────────────────┐
│              CAPA DE NÚCLEO DE NEGOCIO                       │
│  Base unificada Perros (perdidos / encontrados / adopción)   │
│  Matching engine  •  Motor de alertas  •  Verificación KYC   │
│  Anti-fraude  •  Mensajería orquestada  •  Reportes          │
└──────────┬──────────────────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────────────────┐
│                    CAPA DE SEGURIDAD                         │
│  Verificación de identidad  •  Moderación IA + humana        │
│  Cifrado  •  Auditoría  •  Bloqueo de patrones de fraude     │
└──────────────────────────────────────────────────────────────┘
```

### 5.1 Flujo 1 — "Perdí a mi perro" (el corazón emocional del producto)

1. El dueño sube una foto por **WhatsApp** (manda la foto al número de GuauWoow) o por la app.
2. El bot pide confirmar: colonia/CP, fecha, nombre, señas particulares.
3. La IA ejecuta fase gruesa → media → fina contra todos los perros **encontrados** reportados en un radio de 3.5 km (y contra lo que el bot rastreador haya capturado de redes).
4. Se generan N candidatos con % de similitud; el dueño confirma o descarta.
5. Al confirmar, GuauWoow conecta a ambas partes **dentro de la plataforma** (nunca expone teléfonos directamente) y sugiere punto de encuentro seguro.
6. Se dispara difusión automática: alerta WhatsApp a usuarios y refugios en la zona, imagen lista para compartir en redes, y publicidad geolocalizada opcional.

### 5.2 Flujo 2 — "Encontré / hay un perro en la calle"

1. Foto + ubicación (WhatsApp comparte ubicación en vivo o pin) al bot.
2. La IA clasifica y guarda en "encontrados" con geocerca; cruza automáticamente con reportes de perdidos cercanos.
3. Si hay match alto → notificación inmediata al dueño. Si no, queda publicado y se difunde en la zona.

### 5.3 Flujo 3 — Adopción responsable

1. Refugios/rescatistas registran perros (foto, edad, tamaño, temperamento, salud, esterilización).
2. Adoptantes crean perfil con **cuestionario responsable** (espacio, presupuesto, experiencia) — los refugios mexicanos ya exigen esto; GuauWoow lo estandariza.
3. Matching adoptante–perro por compatibilidad (estilo de vida, energía, convivencia con niños/otros animales).
4. Solicitud → entrevista → **cita presencial en refugio o punto seguro** → seguimiento post-adopción a 15/60/180 días.

### 5.4 Bot rastreador de redes sociales (el diferenciador)

- Mascofinder (España) ya demuestra que es viable: rastreo diario de imágenes publicadas en protectoras y redes, comparadas con la base de perdidos.
- Implementación responsable: priorizar **fuentes abiertas y cooperativas** (grupos públicos de Facebook, hashtags de Instagram/TikTok, feeds RSS de refugios) cumpliendo términos de servicio y la LFPDPPP mexicana; usar APIs oficiales donde existan (Meta Graph API para páginas y grupos con permisos).
- Pipeline: extracción → deduplicación (hash perceptual) → análisis IA (raza, color, señas) → extracción de texto del post con LLM (raza, zona, fecha, teléfono) → geocodificación → cruzado con la base de perdidos → alerta.
- Importante: el rastreador **alimenta la búsqueda de perdidos** (cruzar fotos encontradas en redes con perros reportados como perdidos en GuauWoow), no solo publica contenido.

---

## 6. Las 15 mejoras propuestas

Ordenadas por impacto × esfuerzo. Las primeras 5 son el mínimo viable diferenciador.

| # | Mejora | Problema que resuelve / referencia |
|---|---|---|
| 1 | **Bot de WhatsApp para reportar perdidos/encontrados (foto + ubicación en un mensaje)** | Elimina la fricción de apps que nadie descarga; WhatsApp ya es el canal de facto de rescatistas mexicanos (NexZoo lo confirma) |
| 2 | **Matching por foto con IA (fase gruesa–media–fina) + decisión supervisada** | Reproduce la arquitectura validada por Saturdays.AI (Inception v3 + YOLO + Xception) y Finding Rover (~98% precisión) con modelos abiertos |
| 3 | **Bot rastreador de redes sociales que cruza fotos de perros encontrados con reportes de perdidos** | Prueba de concepto directa: Mascofinder (España). En México nadie lo hace; las publicaciones de Facebook se pierden en horas |
| 4 | **Geocercas inteligentes por radio de desplazamiento real** (300 m gatos / 3.5 km perros) | Evita alertar a gente inútilmente lejos; datos de comportamiento animal documentados |
| 5 | **Verificación de identidad de adoptantes (KYC ligero: CURP/INE opcional + teléfono validado + historial)** | El fraude "adoptimo" es la estafa de mascotas de mayor crecimiento en México; Mascofinder solo permite alertas a usuarios validados tras una semana |
| 6 | **Chat blindado dentro de la plataforma** (los teléfonos se revelan solo tras verificación mutua y en puntos de encuentro seguros) | Previene doxing, extorsión y robo (ver vector de abuso 3) |
| 7 | **Ficha única de perro con código QR / placa** que cualquiera escanea para avisar al dueño sin app | Complemento probado por NexZoo; funciona sin batería ni internet en la placa |
| 8 | **Matching adoptante–perro por compatibilidad de estilo de vida** (no solo filtros) | Las apps tipo Buscacucha usan solo filtros; un cuestionario de compatibilidad reduce devoluciones |
| 9 | **Seguimiento post-adopción estructurado** (15/60/180 días con recordatorios por WhatsApp) | Las devoluciones saturan refugios; el seguimiento es el dolor #1 que reportan los rescatistas |
| 10 | **Alertas de difusión automática en la zona** (imagen lista para compartir + mensaje WhatsApp a usuarios y refugios cercanos) | Mascofinder lo hace con email geolocalizado; en México WhatsApp es el equivalente natural |
| 11 | **Registro sanitario digital del perro** (vacunas, desparasitación, esterilización, recordatorios) | Mr. Odis ya lo hace; centraliza algo que hoy vive en cartillas de papel falsificables (riesgo documentado en el Congreso CDMX) |
| 12 | **Panel para refugios/rescatistas** con gestión de casos, tránsito temporal y carga masiva | El modelo de Ooh! Cachorros (gratuito para rescatistas, plan institucional pagado) asegura adopción por la oferta |
| 13 | **Detección IA de contenido duplicado / fotos robadas** (hash perceptual + búsqueda inversa) | Contra estafas que reusan fotos de cachorros ajenos (modalidad documentada por Guardia Civil España) |
| 14 | **Reputación y credenciales verificadas de refugios** (sellos de verificación, reseñas de adoptantes, convenios) | El Congreso CDMX documenta "rescates falsos" que monetizan la empatía; la reputación verificable los ahoga |
| 15 | **Modo comunidad: red de hogares de tránsito y voluntarios georreferenciada** | Los rescatistas pierden perros por falta de tránsito temporal; una red visible por zona reduce abandono de casos |

---

## 7. Las 10 funciones más demandadas

Cinco demandadas por **rescatistas y refugios** (quienes hacen la labor diaria) y cinco por **personas que cuidan y buscan perritos** (demanda).

### Por rescatistas / refugios

| # | Función | Por qué la piden |
|---|---|---|
| R1 | **Carga y gestión de casos centralizada** (estado del perro: rescatado → en tránsito → en adopción → adoptado) | Hoy lo manejan en cuadernos y chats sueltos; pierden seguimiento |
| R2 | **Pre-filtro automático de adoptantes** con cuestionario responsable estandarizado | Les ahorra horas de entrevistas con gente no apta; los refugios mexicanos ya lo hacen manual |
| R3 | **Seguimiento post-adopción automatizado** con alertas de devolución | El dolor #1: perros devueltos meses después, sin registro |
| R4 | **Red de hogares de tránsito y voluntarios** por zona, con disponibilidad | El cuello de botella físico de todo rescate |
| R5 | **Difusión multi-red automática** (un solo registro → publicado en la plataforma, WhatsApp y redes con la imagen optimizada) | Hoy republican a mano en 5 grupos de Facebook; el feed los entierra en horas |

### Por cuidadores / adoptantes / dueños

| # | Función | Por qué la piden |
|---|---|---|
| C1 | **Reportar perro perdido/encontrado desde WhatsApp con foto y ubicación** | Menor fricción posible; no requiere descargar nada |
| C2 | **Búsqueda por foto con IA** ("mi perro se parece a estos reportados cerca") | Es la función emocional estrella (Finding Rover, Petco Love Lost) |
| C3 | **Mapa en vivo de perdidos/encontrados en mi colonia** con alertas de cercanía | La gente quiere ayudar, pero solo si es cerca de su casa |
| C4 | **Adopción con trámite transparente y estado visible** (solicitud → entrevista → cita, todo rastreable) | Hoy el proceso es una caja negra por WhatsApp |
| C5 | **Cartilla sanitaria digital con recordatorios** (vacunas, desparasitación, esterilización) y QR del perro | Unifica lo que hoy está en papel y se pierde; además desincentiva venta ilegal |

---

## 8. Seguridad: cómo podrían usar mal la plataforma y cómo defenderla

### 8.1 Vectores de abuso identificados (con evidencia documentada)

| # | Ataque | Descripción real documentada | Contramedida en GuauWoow |
|---|---|---|---|
| 1 | **Estafa "adoptimo" / pagos por adelantado** | Estafa de mayor crecimiento en México (jul-2026): el "vendedor" dice que el perro está en otra ciudad y cobra "envío, vacunas, jaula"; modalidad idéntica documentada en España (Guardia Civil) y EE.UU. (IC3/FBI) | Adopciones **siempre gratuitas y en persona**; bloqueo de mensajes que contienen solicitudes de pago (detección de palabras + contexto con LLM); banner permanente "GuauWoow jamás cobra por adopción" |
| 2 | **Suplantación / perfiles falsos de refugio** | Alerta oficial CERT-MX sobre perfiles falsos que piden dinero o datos; reporte "Spot the Scam" sobre rescates falsos que monetizan la empatía | Verificación KYC de refugios (documento + domicilio + video de instalaciones); sello visible; reporte comunitario con revisión en <24 h |
| 3 | **Robo de perros usando la plataforma como catálogo** | Publicar "perdido" para obtener la ubicación de un perro valioso; o contactar "encontrados" para quedárselos | Nunca revelar ubicación exacta en público (solo geocerca aproximada); contacto solo vía chat interno; **prueba de tenencia** (fotos del perro en casa, datos del microchip/placa) exigida antes de entregar un encontrado; código de entrega con verificación |
| 4 | **Carnada para peleas de perros** | Personas que adoptan perros medianos/grandes como carnada para entrenamiento de peleas; preocupación constante de rescatistas mexicanos | Cuestionario con señales de riesgo; entrevista obligatoria; negación de adopción de perros grandes a perfiles nuevos sin historial verificado; seguimiento post-adopción con fotos verificables |
| 5 | **Venta encubierta (mascotas de raza)** | Criaderos ilegales usando la plataforma como vitrina; venta con cartillas veterinarias falsas (caso 2026 documentado en el Congreso CDMX) | Fotos con marcas de agua y detección de reutilización (hash perceptual); análisis de precios/solicitudes de dinero; reporte a autoridades sanitarias; prohibición de transacciones en la plataforma |
| 6 | **Doxing y acoso** | Publicar datos de una persona bajo pretexto de "perro perdido" o exponer al dueño en el chat | Datos de contacto nunca públicos; pseudónimos hasta la entrega; moderación de descripciones con datos personales (teléfonos, direcciones) |
| 7 | **Contenido falso y spam / bots** | Inundación de reportes falsos para sabotear o estafar; contenido de "rescates" fabricados para donaciones | Rate limiting por número de teléfono; score de reputación; validación cruzada (la foto corresponde a un perro real: detección NSFW/duplicados); revisión humana en cadena para cuentas nuevas |
| 8 | **Riesgos legales del rastreador** (para la plataforma misma) | Incumplir términos de servicio de redes sociales o la LFPDPPP al capturar fotos de personas | Solo fuentes públicas vía APIs oficiales/permisos; respetar robots.txt y ToS; anonimizar/no almacenar datos personales de terceros; proceso de takedown en 48 h; asesoría legal en la fase 2 |

### 8.2 Principios de seguridad transversales

1. **Privacidad por defecto:** ubicaciones aproximadas en público; exactas solo tras validación.
2. **Verificación progresiva:** teléfono → identidad → entrevista → historial. Cada capacidad sensible se desbloquea con más verificación (patrón Mascofinder).
3. **Encuentros seguros:** recomendación de puntos públicos (refugios, veterinarias aliadas) para entregas; código de confirmación de entrega.
4. **Cadena de custodia del perro:** cada cambio de estado queda registrado (quién entregó, quién recibió, cuándo, dónde).
5. **Moderación mixta IA + humana:** la IA filtra (duplicados, solicitudes de dinero, datos personales); humanos resuelven los casos ambiguos.
6. **Transparencia antifraude:** todo usuario ve el estado de verificación de su contraparte (sello, antigüedad, reseñas).

---

## 9. Marco legal y ético en México (resumen, no es asesoría legal)

- **LFPDPPP:** consentimiento informado para datos personales; aviso de privacidad; derechos ARCO; minimización (no guardar más datos de los necesarios). Aplica a fotos, ubicaciones y teléfonos.
- **Ley de Protección de Animales de la CDMX / normativa estatal:** sanciona maltrato y abandono; la plataforma puede integrar un canal de denuncia a autoridades (diferenciador social).
- **Ley General de Salud (aviso A-002, comercio de mascotas):** comercialización de perros requiere aviso sanitario; por eso GuauWoow debe **prohibir explícitamente la venta** y detectarla.
- **Términos de servicio de Meta/TikTok:** el rastreador debe operar con APIs oficiales o acuerdos; el scraping agresivo puede acarrear bloqueos y responsabilidad. Plan B: alianzas con grupos/rescatistas que voluntariamente conecten sus grupos a GuauWoow (ingesta cooperativa).
- **Datos biométricos:** el reconocimiento facial de perros no es dato biométrico humano, pero las fotos pueden contener personas; se deben anonimizar.

---

## 10. Roadmap sugerido

| Fase | Duración | Entregables |
|---|---|---|
| **0 — Fundaciones** | Semanas 1–4 | Este documento, definición de marca, diseño de flujos WhatsApp, piloto con 3–5 refugios aliados de una alcaldía |
| **1 — MVP WhatsApp + plataforma básica** | Meses 2–4 | Bot de WhatsApp (reportar perdido/encontrado con foto+ubicación), catálogo de adopción con fichas, mapa básico, verificación de teléfono. Piloto en una zona de CDMX o ciudad mediana |
| **2 — Motor de IA** | Meses 4–7 | Clasificación de raza + detección de rostro + embeddings; matching perdidos↔encontrados en geocercas; alertas automáticas. Entrenamiento con dataset propio del piloto |
| **3 — Rastreador de redes + refuerzos** | Meses 7–10 | Ingesta cooperativa de grupos aliados (APIs oficiales), KYC de adoptantes, chat blindado, reputación de refugios, anti-fraude v1 |
| **4 — Escala** | Meses 10–18 | Otras ciudades, panel de refugios completo, red de tránsito, cartilla sanitaria, plan institucional (modelo Ooh! Cachorros: gratis para rescatistas, pago para marcas/instituciones) |

**Indicadores de éxito:** tiempo mediano de reencuentro perdido–encontrado; % de reportes con match candidato; tasa de devolución post-adopción; número de reportes vía WhatsApp por semana; % de perros adoptados vs. ingresados por refugio aliado.

---

## 11. Fuentes principales

- Abandono animal en México (29.7 M, cifras de refugios): CRM Noticias — https://www.crmnoticias.com.mx/mexico-lidera-la-problematica-del-abandono-animal-en-america-latina-mas-de-29-millones-de-perros-y-gatos-en-situacion-de-calle/ ; Edomex al Día (Mars/Calm, 128,000 en refugios) — https://edomexaldia.com/la-adopcion-no-cambia-una-vida-cambia-dos/
- Plataformas y programas en México: NUPEC Perromies/Mextizos — https://nupec.com/blog-nupec/conoce-mas-sobre-el-programa-de-apoyo-a-refugios-de-nupec/ ; Ubicapet — https://ubicapet.com.mx/centro-de-ayuda/directorios/grupos-y-asociaciones-animalistas ; AdoptaMx/Adoptist — mencionadas en CRM Noticias; refugios por estado — https://wamiz.es/gato/consejos/165262/
- Finding Rover (reconocimiento facial, 98%, 15,000 reencuentros): https://www.animalshealth.es/animaladas/una-app-usa-el-reconocimiento-facial-para-encontrar-mascotas-perdidas
- Mascofinder (rastreo web con IA): https://www.doogweb.es/2019/11/22/mascofinder-reconocimiento-facial-perros-perdidos/
- Arquitectura técnica IA (Saturdays.AI, Inception/YOLO/Xception): https://saturdays.ai/2021/11/21/identificacion-mascotas-inteligencia-artificial/
- Mr. Odis (LatAm, IA + servicios): https://www.elobservador.com.uy/nota/uruguayo-desarrollo-una-tecnologia-de-inteligencia-artificial-que-ayuda-a-encontrar-mascotas-perdidas-2023125191635
- Petco Love Lost: https://es.elpasoanimalservices.org/lost-and-found/lost-pet-resources
- NexZoo (lecciones de apps en Colombia, WhatsApp como canal real): https://nexzoo.org/apps-mascotas-perdidas-colombia-2026/
- Ooh! Cachorros (modelo gratuito para rescatistas): https://oohcachorros.com/
- Buscacucha/Guau (apps estilo Tinder, Argentina): https://www.lanacion.com.ar/sociedad/mascotas-diez-apps-y-sitios-para-adoptar-entrenar-y-cuidar-a-perros-y-gatos-nid1765801/
- Fraude y seguridad: Congreso CDMX (venta ilegal, cartillas falsas, rescates falsos): https://www.congresocdmx.gob.mx/archivo-cf8fca75046872491ffaace77935c1762356538a.pdf ; estafas de adopción online (alerta 2026): https://www.ccpc.ie/data/docs/default-source/manage-your-money/scams-real-cases-real-consequences.pdf ; CERT-MX alerta TikTok (citada en el documento del Congreso CDMX)

---

*Documento preparado como base de diseño del producto GuauWoow. No constituye asesoría legal; validar el plan de cumplimiento con un abogado antes de lanzar el rastreador y el tratamiento de datos.*
