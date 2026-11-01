# Documento de seguridad (SGSDP) de GuauWoow

> **Uso interno y confidencial.** No se publica. Versión 2026-10-17. Documento base preparado con apoyo de IA a partir de `docs/legal/requisitos.json` y `docs/legal/secciones/seguridad-incidentes.md`; debe revisarlo el abogado de datos personales antes de darlo por aprobado. Los datos entre corchetes (`[ASÍ]`) los llena el dueño.

| Campo | Valor |
|---|---|
| Responsable del tratamiento | [RAZÓN SOCIAL] · RFC [RFC] · [DOMICILIO FISCAL] |
| Departamento de datos personales (LFPDPPP art. 29) | [DEPARTAMENTO DE DATOS PERSONALES] · [CORREO DE PRIVACIDAD] |
| Responsable de seguridad | [RESPONSABLE DE SEGURIDAD] · [CORREO DE SEGURIDAD] |
| Fecha de aprobación | [FECHA DE APROBACIÓN] |
| Próxima revisión | 12 meses después de la aprobación, o antes si ocurre un cambio sustancial o un incidente (sección 8) |

## 1. Objeto, alcance y fundamento

Este documento describe el sistema de gestión de seguridad de los datos personales (SGSDP) de GuauWoow: qué datos tratamos, dónde están, quién responde de ellos, qué riesgos tienen, qué medidas los protegen, qué falta y cómo se revisa.

- **Alcance:** la app web `/app/`, la landing, el panel de administración, la API, la base de datos, los archivos (públicos y privados), los respaldos, el bot de WhatsApp, la tienda, los donativos, el directorio de clínicas y la importación de grupos públicos de Facebook (apagada en producción hasta los dictámenes).
- **Fundamento:** LFPDPPP 2025, arts. 13 (responsabilidad), 18 (medidas de seguridad), 19 (vulneraciones) y 20 (confidencialidad). El Reglamento de 2011 (arts. 60 a 62) se usa solo como referencia «en lo que no se oponga a la LFPDPPP vigente» (conflicto resuelto 1 de `requisitos.json`). Ninguna obligación de este documento se funda solo en el Reglamento.
- **Regla de veracidad:** la sección 5 lista solo medidas comprometidas para el lanzamiento (contratos del flujo de código, octubre de 2026). Todo lo demás está en el análisis de brecha (sección 6) y no debe afirmarse en páginas públicas hasta que exista.

## 2. Funciones y obligaciones por rol

| Rol | Persona y suplente | Funciones | Obligaciones |
|---|---|---|---|
| Responsable (operador) | [REPRESENTANTE LEGAL] | Aprueba este documento, el presupuesto de seguridad y las decisiones de riesgo | Garantizar que existan las medidas; responder ante la SABG y los titulares |
| Departamento de datos personales | [DEPARTAMENTO DE DATOS PERSONALES] / [SUPLENTE] | Atiende solicitudes ARCO, revocaciones, limitación y quejas; mantiene el aviso de privacidad | Responder en 20 días hábiles y hacer efectiva la respuesta en 15 (art. 31); llevar los expedientes ARCO 5 años |
| Responsable de seguridad | [RESPONSABLE DE SEGURIDAD] / [SUPLENTE] | Lidera incidentes, revisa accesos, coordina respaldos, vulnerabilidades y esta revisión anual | Mantener la bitácora de vulneraciones; activar el runbook (`runbook-incidentes.md`) |
| Superadmin | [NOMBRES] | Configuración, roles, acceso a documentos privados y bóveda de evidencia | MFA obligatoria; acceso solo con necesidad; todo acceso queda en la bitácora de administración |
| Admin de moderación | [NOMBRES] | Reportes, retiros, apelaciones, solicitudes de autoridad | MFA; no copiar ni capturar contenido; seguir `politicas-internas.md` |
| Verificación de Refugios y Clínicas | [NOMBRES] | Revisa documentos de identidad y de verificación | MFA; no descargar a equipos personales; respetar el borrado a 30 días |
| Finanzas y facturación | [NOMBRES] | Conciliación con Mercado Pago, CFDI de comisión, estados de cuenta | MFA; no guardar datos de tarjeta; cuidar los datos fiscales |
| Desarrollo e infraestructura | [NOMBRES] | Código, servidores, secretos, respaldos | No usar datos reales en desarrollo; rotar secretos tras incidentes |
| Punto de contacto 24/7 para autoridades | [CONTACTO 24/7] / [SUPLENTE] | Recibe requerimientos y alertas | Primera respuesta conforme a `politicas-internas.md` sección 2 |
| Abogado externo | [ABOGADO] | Dictámenes, notificaciones, denuncias, SABG | Confidencialidad profesional |
| Contador | [CONTADOR] | Obligaciones fiscales, CFDI, conservación fiscal | Confidencialidad |
| Encargados (proveedores) | Ver sección 3.2 | Tratan datos por cuenta de GuauWoow | Contrato o términos que obliguen a confidencialidad y seguridad (LFPDPPP art. 20) |

Toda persona con acceso a datos firma un acuerdo de confidencialidad antes de recibir acceso (pendiente: ver brecha B-11) y recibe la capacitación de la sección 7.

## 3. Inventario de datos y sistemas

### 3.1 Datos por categoría

Los plazos remiten al calendario de conservación de `requisitos.json` (`retention`, R01 a R48). La tabla viva y autorizada es la que genera el backend en `/cumplimiento/conservacion` (página pública `conservacion.html`).

| Categoría | Datos | Dónde | Encargado y país | Plazo |
|---|---|---|---|---|
| Cuenta y perfil | Nombre, correo, teléfono, foto, rol, preferencias | Tabla `users` | Hosting [PROVEEDOR DE HOSTING], [PAÍS O REGIÓN DEL HOSTING] | R01, R02 |
| Edad y aceptaciones | Fecha de nacimiento, declaración 18+, versión y hash del documento aceptado, fecha, IP, agente de usuario | Bitácora de aceptaciones de solo inserción (nueva, contrato L-legal) | Hosting | R03, R04 |
| Teléfono verificado | Número, códigos OTP, IP | `phone_verification_logs` | Hosting; proveedor SMS [PROVEEDOR SMS] ([PAÍS DEL PROVEEDOR SMS]) | R37 |
| Ubicación | Zona redondeada, coordenadas aproximadas públicas | `users`, `lost_reports`, `dogs` | Hosting; teselas y geocodificación de OpenStreetMap (fuera de México) | R22, R23 |
| Fotos de perros | Imágenes sin metadatos EXIF | `uploads/` públicos | Hosting; Cloudflare (CDN); proveedor de IA (solo fotos de perros y texto, sin identificadores) | Vida del contenido; R29 para la caché de IA |
| Chats | Mensajes entre personas usuarias | `conversations`, `messages` | Hosting | R21 |
| Adopciones | Cuestionarios, postulaciones, puntaje | `adoption_applications`, `matches` | Hosting | R19, R20 |
| Perdidos y encontrados | Reportes, fotos, zona, contacto | `lost_reports` | Hosting | R23, R24 |
| Bot de WhatsApp | Número (hash donde aplique), mensajes, fotos enviadas | `bot_interactions` | Meta (WhatsApp Cloud API), Estados Unidos | R27, R28 |
| Contenido importado (apagado) | Foto y texto depurado, zona, enlace | `lost_reports` de origen Facebook; `facebook_groups` | Apify (por confirmar país) | R25, R26 |
| Pedidos | Folio, montos, ID de Mercado Pago, nombre, domicilio y teléfono de entrega | `orders`, `order_items`, `payment_events` | Hosting; Mercado Pago (México); paquetería | R05, R06, R14 |
| Donativos | Folio, ID de pago, monto, Refugio, comisiones, nombre si se compartió | `donations`, `payment_events` | Hosting; Mercado Pago | R11, R12 |
| Datos fiscales | RFC, régimen, CP, uso de CFDI del comprador; perfil fiscal del Refugio; CFDI | `order_invoices`, `refuge_fiscal_profiles`, `cfdis` | Hosting; PAC [PAC DE CFDI] (México) | R07, R08, R09 |
| Cuentas de Mercado Pago de Refugios | Identificador de la cuenta y tokens OAuth cifrados | `refuge_payment_accounts` | Hosting; Mercado Pago | R13 |
| Documentos privados | INE, actas, cédulas, constancias de situación fiscal | `uploads/private/` (cifrados en reposo) | Hosting | R15, R16, R17 |
| Clínicas y reseñas | Cédula del responsable, constancia del Registro Nacional de Profesionistas, reseñas internas | `veterinaries`, `veterinary_reviews` | Hosting; Google Places (solo `place_id`; nada se almacena) | R16, R43, R44 |
| Moderación y evidencia | Reportes, decisiones, apelaciones; copia cifrada de lo retirado | `content_reports`; bóveda de evidencia cifrada (nueva, contrato L-reportes) | Hosting; Cloudflare R2 (región por definir) | R30, R31, R32, R33 |
| Solicitudes | ARCO, revocación, limitación, quejas, retiro de importados, con folio | Centro de solicitudes (nuevo, contrato L-solicitudes) | Hosting | R35 |
| Autoridades | Requerimientos, respuestas, alertas y denuncias | Registro de solicitudes de autoridad (nuevo, contrato L-reportes) | Hosting | R34 |
| Bitácora de administración | Acción, persona, fecha, objeto | `admin_audit_logs` | Hosting | R36 |
| Incidentes | Registro de incidentes y avisos enviados | Registro de incidentes (nuevo, contrato L-seguridad) | Hosting | R35 |
| Registros técnicos | IP, agente, ruta, código | Nginx y aplicación | Hosting; Sentry (errores, datos personales filtrados) | R37, R39 |
| Analítica | Identificador seudónimo y eventos, solo con consentimiento | PostHog | PostHog (región por confirmar) | R39, R40 |
| Respaldos | Copia cifrada de la base de datos y archivos | Servidor y copia externa | [PROVEEDOR DE RESPALDOS EXTERNOS] | R38 |

### 3.2 Registro de medios de almacenamiento y encargados

| Medio o encargado | Qué guarda | País o región | Contrato o términos | Revisado |
|---|---|---|---|---|
| Servidor (VPS) [PROVEEDOR DE HOSTING] | Base de datos, archivos, registros | [PAÍS O REGIÓN DEL HOSTING] | [CONTRATO O DPA] | [FECHA] |
| Cloudflare (CDN, TLS, R2) | Tráfico en tránsito; respaldos y bóveda cifrados | Estados Unidos y red global; región de R2 [REGIÓN DE RESPALDOS] | [TÉRMINOS ACEPTADOS] | [FECHA] |
| Sentry | Errores técnicos sin datos personales | [REGIÓN SENTRY] | [TÉRMINOS] | [FECHA] |
| PostHog | Analítica con consentimiento | [REGIÓN POSTHOG] | [TÉRMINOS] | [FECHA] |
| Mercado Pago (MP Agregador) | Pagos, reembolsos, cuentas de Refugios | México | Términos Standard y para Desarrolladores | [FECHA] |
| Meta (WhatsApp Cloud API) | Mensajes del bot (hasta 30 días en Meta) | Estados Unidos | Platform Terms y WhatsApp Business | [FECHA] |
| Proveedor de IA (Alibaba Cloud DashScope) | Fotos de perros y texto, sin identificadores | Singapur | [TÉRMINOS; sin entrenamiento] | [FECHA] |
| Proveedor SMS [PROVEEDOR SMS] | Número y código | [PAÍS DEL PROVEEDOR SMS] | [DPA] | [FECHA] |
| Proveedor de correo [PROVEEDOR DE CORREO] | Correo, nombre, mensajes | [PAÍS DEL PROVEEDOR DE CORREO] | [DPA] | [FECHA] |
| PAC [PAC DE CFDI] | Datos fiscales | México | [CONTRATO] | [FECHA] |
| Apify (solo si se activa la importación) | Publicaciones públicas | Por confirmar | [CONTRATO] | [FECHA] |
| Equipos de administradores | Ningún dato descargado (regla) | México | Acuerdo de confidencialidad | [FECHA] |

Regla fija: documentos de identidad, actas, chats y datos de contacto nunca se envían a proveedores de IA.

## 4. Análisis de riesgos

Escala: probabilidad (B baja, M media, A alta) e impacto para la persona titular (B, M, A). Riesgo inherente = sin medidas; residual = con las medidas de la sección 5.

| # | Riesgo | Datos afectados | Prob. | Impacto | Inherente | Medidas (sección 5) | Residual | Brecha (sección 6) |
|---|---|---|---|---|---|---|---|---|
| R-1 | Fuga de documentos de identidad de Refugios o Clínicas | INE, actas, cédulas, CSF | M | A | Alto | M-3, M-4, M-2, M-8 | Medio | B-1, B-6 |
| R-2 | Toma de cuenta de administrador (phishing, contraseña filtrada) | Todos | M | A | Alto | M-2, M-8 | Medio | B-2, B-3 |
| R-3 | Exposición de chats o de la ubicación de personas | Chats, zona | M | A | Alto | M-1, M-8, M-11 | Medio | B-1, B-4 |
| R-4 | Extorsión a dueños de perros perdidos con datos de contacto | Teléfono, zona | A | M | Alto | M-12, M-11 | Medio | B-15 |
| R-5 | Refugios o vendedores usan datos de adoptantes o compradores para otros fines | Contacto, domicilio | M | M | Medio | M-13 | Medio | B-11 |
| R-6 | Compromiso de tokens de Mercado Pago, Meta, SMS o correo | Pagos, mensajes | B | A | Medio | M-1, M-9 | Bajo-medio | B-5 |
| R-7 | Envío de datos personales a un proveedor de IA | Fotos con personas, texto | M | M | Medio | Regla fija (3.2); M-11 | Bajo | B-12 |
| R-8 | Conservar datos más tiempo del necesario | Todos | A | M | Alto | M-5, M-6 | Bajo | B-7 |
| R-9 | Contenido de abuso sexual infantil o que involucra a menores | Imágenes, cuentas | B | A | Alto | M-12, M-14 | Medio | B-14 |
| R-10 | Pérdida de datos por ransomware o falla del servidor | Todos | M | A | Alto | M-7 | Medio | B-6 |
| R-11 | Datos de terceros importados de Facebook | Fotos, texto | M (si se activa) | M | Medio | M-16 (función apagada) | Bajo | B-13 |
| R-12 | Analítica sin consentimiento | Navegación | M | B | Bajo | M-10 | Bajo | B-9 |
| R-13 | Vulnerabilidad en dependencias o en el código (IDOR, subida de archivos) | Todos | M | A | Alto | M-9 | Medio | B-3 |
| R-14 | Suplantación de GuauWoow por correo o WhatsApp | Credenciales, pagos | M | M | Medio | M-9 (canal de reporte) | Medio | B-10 |
| R-15 | Menores registrados pese al requisito de 18 años | Cuenta, chats | M | A | Alto | M-15 | Medio | B-14 |

## 5. Medidas de seguridad vigentes al lanzamiento

Solo se listan medidas comprometidas en los contratos del flujo de código (octubre de 2026). Antes de aprobar este documento, el responsable de seguridad confirma en producción cada una y anota la evidencia.

| # | Medida | Tipo | Riesgos | Evidencia |
|---|---|---|---|---|
| M-1 | Cifrado en tránsito (TLS) en todo el sitio, la app y la API | Técnica | R-3, R-6 | [CAPTURA O PRUEBA] |
| M-2 | Autenticación de dos factores (TOTP) obligatoria para cuentas de administración | Técnica | R-1, R-2 | [LISTA DE ADMINS CON MFA] |
| M-3 | Cifrado en reposo de documentos privados (INE, actas, cédulas, constancias de situación fiscal) | Técnica | R-1 | [PRUEBA] |
| M-4 | Borrado de documentos de identidad y de verificación 30 días después de la decisión; se conserva solo la constancia de verificación | Técnica y administrativa | R-1, R-8 | [CORRIDA DE PURGA] |
| M-5 | Purgas automáticas de conservación conforme a la tabla publicada (`/cumplimiento/conservacion`) | Técnica | R-8 | [REGISTRO DE CORRIDAS] |
| M-6 | Bloqueo y retención legal: la evidencia de retiros se conserva al menos 90 días hábiles y puede retenerse más por orden o apelación | Administrativa y técnica | R-8, R-9 | [PRUEBA] |
| M-7 | Respaldos cifrados | Técnica | R-10 | [PRUEBA DE RESTAURACIÓN] |
| M-8 | Bitácora de administración de todas las acciones de administradores | Técnica | R-1, R-2, R-3 | [EXPORTACIÓN] |
| M-9 | Registro de incidentes, aviso de vulneraciones a las personas afectadas, `security.txt` y política de divulgación responsable | Administrativa y técnica | R-6, R-13, R-14 | [REGISTRO] |
| M-10 | Banner de cookies con «Necesarias» y «Analítica» (PostHog apagado hasta aceptar) y enlace «Preferencias de cookies» en cada pie de página | Técnica | R-12 | [CAPTURA] |
| M-11 | Centro de preferencias: alertas cercanas y correo promocional apagados por defecto, alertas por WhatsApp con opt-in, comandos BAJA, ALTA, ELIMINAR y PERSONA en el bot | Técnica | R-3, R-4, R-7 | [CAPTURA] |
| M-12 | Reportes públicos sin cuenta; lo que involucra a menores se oculta de inmediato y se revisa con prioridad; el material de abuso sexual infantil se pone en cuarentena, nunca se muestra ni se envía a IA y se denuncia al Ministerio Público | Administrativa y técnica | R-4, R-9 | [PRUEBA] |
| M-13 | Registro de documentos legales con versión y SHA-256, aceptación por casillas separadas y bitácora de aceptaciones de solo inserción; aviso de cambios con 30 días | Administrativa | R-5 | [REGISTRO] |
| M-14 | Solicitudes de autoridad en tres niveles con contacto 24/7 (`politicas-internas.md` sección 2) | Administrativa | R-9 | [REGISTRO] |
| M-15 | Verificación de edad por capas: fecha de nacimiento, casilla 18+ separada, OTP por SMS, señales de riesgo y verificación reforzada sin copias de identificación ni biometría | Técnica y administrativa | R-15 | [PRUEBA] |
| M-16 | Importación de Facebook apagada en producción; cuando se active: minimización, etiqueta, borrado real a 30 días y retiro a petición del autor en menos de 72 horas | Administrativa y técnica | R-11 | [CONFIGURACIÓN] |
| M-17 | Centro de solicitudes con folio y plazos; verificación de identidad sin guardar copias más de lo necesario | Administrativa | Todos | [COLA DE SOLICITUDES] |
| M-18 | Pagos en Mercado Pago: la Plataforma no recibe ni guarda datos de tarjeta | Técnica | R-6 | [CONFIGURACIÓN] |

## 6. Análisis de brecha y plan de trabajo

Medidas recomendadas por la investigación que **no** están comprometidas para el lanzamiento. No deben afirmarse en páginas públicas hasta que existan. Algunas ya se observaron en el código el 17-10-2026 (marcadas «observada»): hay que reconfirmarlas y, si se mantienen, pasarlas a la sección 5.

| # | Brecha | Fuente | Prioridad | Responsable | Fecha objetivo |
|---|---|---|---|---|---|
| B-1 | Reautenticación para ver documentos, coordenadas exactas o exportar; sesiones de administración cortas; lista blanca de IP opcional para `/admin` | seguridad-incidentes-22 | Alta | [RESPONSABLE] | [FECHA] |
| B-2 | Revisión trimestral de accesos firmada; altas y bajas de acceso el mismo día con constancia | seguridad-incidentes-22 | Alta | [RESPONSABLE] | [FECHA] |
| B-3 | Prueba de penetración externa antes del lanzamiento y anual (OWASP Top 10, ASVS nivel 2); escaneo de dependencias en CI (pip-audit, npm audit, Trivy); parches críticos en 7 días; imágenes fijadas por versión | seguridad-incidentes-28 | Alta | [RESPONSABLE] | [FECHA] |
| B-4 | Registros técnicos: rotación por tiempo (90 días) y truncado o seudonimización de IP a los 30 días; alertas de picos de fallos de acceso | seguridad-incidentes-20 | Media | [RESPONSABLE] | [FECHA] |
| B-5 | Inventario de secretos, rotación anual y tras incidentes; llave de respaldos fuera del servidor | seguridad-incidentes-02, -19, -23 | Alta | [RESPONSABLE] | [FECHA] |
| B-6 | Respaldos: prueba de restauración mensual registrada (RPO 24 h, RTO [RTO OBJETIVO]); credenciales de la copia externa de solo escritura; cifrar las instantáneas locales de archivos privados; reaplicar supresiones tras restaurar | seguridad-incidentes-19 | Alta | [RESPONSABLE] | [FECHA] |
| B-7 | Registro de corridas de purga con alerta si fallan; filtro global de registros bloqueados | seguridad-incidentes-18, -v03 | Alta | [RESPONSABLE] | [FECHA] |
| B-8 | «Modo incidente» que congele purgas con un interruptor (hoy: pausa manual de tareas, ver runbook) | seguridad-incidentes-06 | Media | [RESPONSABLE] | [FECHA] |
| B-9 | Confirmar región de Sentry y PostHog; descartar IP en PostHog; sin Session Replay | comunicaciones-cookies; datos-personales | Media | [RESPONSABLE] | [FECHA] |
| B-10 | SPF, DKIM y DMARC; avisos de inicio de sesión desde dispositivo nuevo | seguridad-incidentes-27 | Media | [RESPONSABLE] | [FECHA] |
| B-11 | Acuerdos de confidencialidad firmados por admins, moderadores y voluntarios; convenio de datos con Refugios, Casas de paso y vendedores | seguridad-incidentes-08 | Alta | [RESPONSABLE] | [FECHA] |
| B-12 | Registro de encargados con DPA o términos aceptados, revisión anual; contratar IA sin entrenamiento con fotos | seguridad-incidentes-09 | Alta | [RESPONSABLE] | [FECHA] |
| B-13 | Dictamen jurídico antes de activar la importación de Facebook; evaluación de impacto | requisitos K; conflicto 9 | Bloqueante para activar | [ABOGADO] | [FECHA] |
| B-14 | Evaluación de riesgos del Decreto NNA cada 6 meses; postura penal escrita sobre la conservación de material de abuso | gap-nna-06, -10 | Alta | [ABOGADO] | 12-11-2026 y cada 6 meses |
| B-15 | Textos «Cómo protegerte» y avisos contra extorsión en la app | seguridad-incidentes-27 | Media | [RESPONSABLE] | [FECHA] |
| B-16 | SAQ A de PCI DSS anual archivado | seguridad-incidentes-14 | Media | [RESPONSABLE] | [FECHA] |
| B-17 | Constancias NOM-151 de aceptaciones y versiones (opcional) | contenido-plataforma | Baja | [RESPONSABLE] | [FECHA] |
| B-18 | Seguro de ciberriesgos y responsabilidad civil (opcional) | seguridad-incidentes-26 | Baja | [REPRESENTANTE LEGAL] | [FECHA] |
| B-19 | Medidas observadas en el código (reconfirmar): contraseñas con bcrypt, CSP estricta, firma HMAC de webhooks de Mercado Pago, eliminación de EXIF, coordenadas públicas aproximadas, filtrado de datos personales en Sentry, «Cerrar sesión en todos los dispositivos», archivos privados fuera del acceso público | seguridad-incidentes (estado del código) | Alta | [RESPONSABLE] | Antes del lanzamiento |
| B-20 | Orientación psicológica para el equipo de moderación después de revisar contenido sensible (por ejemplo, canalización a la Línea de la Vida, art. 6 del Decreto NNA, como recurso de orientación) | gap-nna (plan de atención, «Personas») | Media | [RESPONSABLE] | [FECHA] |

## 7. Capacitación

- **Al ingresar** y **cada año**: principios de la LFPDPPP, este documento, el runbook de incidentes, las políticas internas, phishing, manejo de documentos de identidad, protocolo de niñas, niños y adolescentes, y qué no se dice ni se entrega por teléfono o redes.
- **Quién:** toda persona con acceso a datos (administradores, moderadores, verificación, finanzas, desarrollo, voluntarios con acceso).
- **Constancia:** nombre, fecha, temas, duración y firma; se guarda en la carpeta de evidencias (`politicas-internas.md` sección 10).
- **Apoyo:** orientación psicológica para el equipo de moderación después de revisar contenido sensible. Es un compromiso pendiente (brecha B-20); mientras no exista, no se afirma en páginas públicas.

## 8. Revisión y mejora

- Revisión **anual** de todo el documento, firmada por el responsable de seguridad y el representante legal.
- Revisión **extraordinaria** tras: un incidente (cierre del runbook), una función nueva (tienda, alertas, clínicas, importación de Facebook, cambio de proveedor de IA), un proveedor nuevo o un cambio de ley.
- Cada revisión actualiza el inventario (3), la matriz de riesgos (4), las medidas (5) y la brecha (6), y queda en la tabla de control.

| Versión | Fecha | Cambios | Aprobó |
|---|---|---|---|
| 2026-10-17 | 17-10-2026 | Primera versión base (pendiente de aprobación) | [PENDIENTE] |
