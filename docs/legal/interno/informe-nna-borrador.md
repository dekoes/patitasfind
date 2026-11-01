# Informe de acciones implementadas: Decreto de entornos digitales seguros para niñas, niños y adolescentes

**BORRADOR INTERNO. No se entrega así.** Documento preparado con apoyo de IA a partir del código de GuauWoow al
17-10-2026; debe revisarlo un abogado antes de firmarse y entregarse. Los textos entre corchetes son datos que aporta
la persona dueña. La versión pública (sin datos internos de seguridad) va en `app/legal/plantillas/proteccion-nna.html`
§12 cuando se entregue.

- **Fundamento del informe:** Decreto de entornos digitales seguros para niñas, niños y adolescentes (DOF 14-10-2026,
  edición vespertina), transitorio Cuarto: «documentar e informar las acciones implementadas… dentro de un plazo
  máximo de treinta días naturales, contado a partir de su entrada en vigor».
- **Fecha límite interna:** jueves **12-11-2026** (el decreto no dice si el 14-10 cuenta como día 1; entregar antes
  del 12-11 evita la duda). Confirmar canal y formato con la ATDT a más tardar el **05-11-2026**.
- **Destinatario propuesto:** [AUTORIDAD RECEPTORA DEL INFORME NNA, p. ej. Agencia de Transformación Digital y
  Telecomunicaciones], con copia a la Consejería Jurídica del Ejecutivo Federal (Mesa de Trabajo del transitorio
  Tercero). Antes de enviar, revisar el DOF y gob.mx/atdt por si se publicó un formato o portal.
- **Fuente de los requisitos:** `docs/legal/secciones/gap-nna-decreto-entornos-digitales-2026.md` (sección 3.1, doce
  apartados) y `docs/legal/requisitos.json`.

---

## Encabezado (lo llena la persona dueña)

| Dato | Valor |
| --- | --- |
| Fecha del informe | [FECHA] |
| Razón social | [RAZÓN SOCIAL] |
| RFC | [RFC] |
| Domicilio | [DOMICILIO FISCAL] |
| Persona representante que firma | [NOMBRE Y CARGO] |
| Correo legal | [CORREO LEGAL, para avisos legales y requerimientos] |
| Contacto 24/7 para autoridades | [CONTACTO 24/7 PARA AUTORIDADES, teléfono y correo dedicados] (en el servidor: `AUTHORITY_CONTACT_EMAIL` y `AUTHORITY_CONTACT_PHONE`) |
| Sitio | https://[DOMINIO] |

---

## 1. Descripción del servicio

GuauWoow es una plataforma web (aplicación en `/app/` y bot de WhatsApp) para:

- adopción responsable de perros publicados por personas, Refugios y Casas de paso;
- reportes de perros perdidos y encontrados, con búsqueda por foto asistida por inteligencia artificial;
- chat de texto entre personas usuarias (sin imágenes; `backend/app/models.py`, clase `Message`: solo `content` de texto);
- alertas de perros perdidos cerca (apagadas por defecto);
- contenido importado de grupos públicos de Facebook [solo si se activa; estado: VERIFICAR_FUENTE_INDIRECTA];
- tienda solidaria de Refugios, donativos y directorio de Clínicas veterinarias con reseñas.

**Declaración:** el servicio está dirigido exclusivamente a personas mayores de 18 años (Términos; `proteccion-nna.html`
§1). No se aceptan cuentas de menores.

## 2. Matriz artículo por artículo

«Por diseño» = la obligación supone cuentas de menores y GuauWoow no las acepta (lectura sujeta a validación del
abogado: VERIFICAR_DECRETO_NNA).

| Disposición | Qué pide | Situación | Medida implementada | Evidencia (código y páginas) |
| --- | --- | --- | --- | --- |
| Art. 3 fr. I a VII | No exponer a menores a siete tipos de contenido | Aplica | Las siete categorías están prohibidas para todas las personas y son motivos de reporte propios, en la app y en el formulario público | `backend/app/services/legal_moderation.py` (`DECREE_REASONS`, `REASONS`); `app/index.html` (botón «Reportar»); `app/legal/js/reportes.js`; `comunidad.html`, `moderacion.html` §1 |
| Art. 4 fr. I | Verificar la edad sin limitarse a la autodeclaración | Aplica | Verificación por capas: fecha de nacimiento (rechazo de menores), casilla separada de 18+, código por SMS, señales de riesgo y verificación reforzada sin copias ni biometría | `backend/app/routers/auth.py` (`check_age_declaration`), `backend/app/services/age_check.py`, `backend/app/services/otp.py`, `backend/app/services/legal_acceptance.py` |
| Art. 4 fr. II | Publicar criterios para identificar y retirar contenido | Aplica | Lineamientos, moderación con plazos, escala de sanciones y apelación | `comunidad.html`, `moderacion.html`, `proteccion-nna.html` |
| Art. 4 fr. III | Clasificar el contenido para proteger a menores | Por diseño | Todo el servicio es para personas adultas | `proteccion-nna.html` §3 |
| Art. 4 fr. IV | Retirar de inmediato el contenido prohibido | Aplica | Lo que involucra a menores se oculta al recibir el reporte (sin esperar revisión); el resto de las siete categorías va a la cola urgente con plazo [PLAZO OBJETIVO DE REPORTES URGENTES] | `legal_moderation.intake`, `priority_for`, `due_for`; `GET /admin/cumplimiento/cola` |
| Art. 4 fr. V | Mecanismos de reporte visibles y siempre disponibles | Aplica | Botón «Reportar» en fichas, reportes, perfiles, Refugios, Clínicas, productos, reseñas y mensajes; formulario público sin cuenta con folio y consulta de estado | `POST /reports` (`backend/app/routers/reports.py`), `POST /cumplimiento/reportes-publicos` (`backend/app/routers/cumplimiento_reportes.py`) |
| Art. 4 fr. VI | Supervisión parental de cuentas de menores | Por diseño | Canal sin cuenta para madres, padres y tutores (formulario público con el motivo «Involucra a una niña, niño o adolescente») | `proteccion-nna.html` §8; `app/legal/js/reportes.js` |
| Art. 4 fr. VII | Seguridad desde el diseño | Aplica | Ver apartado 6 | — |
| Art. 4 fr. VIII | Configuración más estricta por defecto | Por diseño y aplica | Todas las cuentas nuevas empiezan con la configuración más protectora | apartado 6 |
| Art. 4 fr. IX | Evaluar riesgos y compartir reportes estadísticos | Aplica | Evaluación de riesgos (apartado 7) y estadísticas agregadas sin datos personales | `GET /cumplimiento/transparencia` (`backend/app/routers/cumplimiento_transparencia.py`); `informe-transparencia.html` |
| Art. 5 fr. I | Punto de contacto 24/7 con capacidad técnica inmediata | Aplica | Contacto publicado; registro de requerimientos en tres niveles; ocultar, suspender y preservar desde el panel en minutos | `GET /cumplimiento/autoridades/contacto`; `/admin/cumplimiento/autoridades` (apartado 8) |
| Art. 5 fr. II | Conservar la evidencia de lo retirado al menos 90 días hábiles | Aplica | Bóveda cifrada con hash encadenado; retención legal | `backend/app/services/evidence.py` (apartado 9) |
| Art. 5 fr. III | Alertar de inmediato a las autoridades sobre contenido contra menores | Aplica | Protocolo de menores en riesgo y denuncia ante el Ministerio Público el mismo día | `legal_moderation.quarantine` (apartado 10) |
| Transitorio Cuarto | Informar en 30 días naturales | Aplica | Este informe | — |

## 3. Verificación de edad por capas

| Capa | Qué se hace | Qué se guarda | Código |
| --- | --- | --- | --- |
| 1. Declaración y fecha | Registro con fecha de nacimiento (si indica menos de 18 años no se crea la cuenta) y casilla separada, desmarcada: «Declaro que tengo 18 años o más» | Declaración en la bitácora de aceptaciones de solo inserción (versión, fecha, IP, agente) | `routers/auth.py` (`check_age_declaration`), `services/age_check.check_birth_date`, `services/legal_acceptance.py` |
| 2. Teléfono | Código por SMS: una cuenta por teléfono real (no prueba la edad, y así se dice) | Hash del código; bitácora de envíos | `services/otp.py`, `models.PhoneVerificationLog` |
| 3. Señales de riesgo | Un reporte «Involucra a una niña, niño o adolescente» contra una cuenta, o la petición de un admin, la pasa a «verificación reforzada»: queda limitada (403 en acciones de escritura) | Constancia `AgeCheck` (fechas, método, resultado) | `services/age_check.py`, `dependencies.get_verified_user` |
| 4. Verificación reforzada | Confirmar la fecha de nacimiento, código NUEVO por SMS y declaración firmada; sin copia de identificaciones ni biometría | Solo la constancia | `services/age_check.py` |

**Métricas iniciales** (al [FECHA DE CORTE]): registros rechazados por edad: [N]; cuentas en verificación reforzada:
[N]; resultado: [N confirmadas / N cerradas]. [Consulta: tabla `age_checks` y bitácora de administración.]

**Lo que nunca se hace:** reconocimiento facial, comparación de selfies ni otro tratamiento biométrico.

## 4. Criterios publicados de identificación, retiro y moderación

- Lineamientos de la comunidad: https://[DOMINIO]/app/legal/comunidad.html
- Moderación, reportes, sanciones y apelaciones: https://[DOMINIO]/app/legal/moderacion.html
- Protección de niñas, niños y adolescentes: https://[DOMINIO]/app/legal/proteccion-nna.html
- Propiedad intelectual: https://[DOMINIO]/app/legal/derechos-de-autor.html
- Solicitudes de autoridades: https://[DOMINIO]/app/legal/autoridades.html

Cada medida que afecta a una persona queda registrada con la regla aplicada, el origen de la detección, la duración y
el plazo para apelar, y se le avisa (declaración de motivos), salvo que avisar ponga en riesgo una investigación
(`legal_moderation.record_action`, tabla `moderation_actions`). La apelación funciona aunque la cuenta esté
suspendida (folio + correo) y la resuelve una persona distinta de quien decidió (`POST /cumplimiento/apelaciones`;
`POST /admin/cumplimiento/apelaciones/{id}/resolver` rechaza a quien decidió la medida).

## 5. Mecanismo de reporte permanente

- **En la app:** botón «Reportar» con los motivos del catálogo; los de menores aparecen primero
  (`app/index.html`, `#flag-reasons`).
- **Sin cuenta:** formulario público en `moderacion.html` §1 y `proteccion-nna.html` §7, con folio, correo opcional y
  consulta del estado (`GET /cumplimiento/reportes-publicos/{folio}`); límite por IP y campo trampa contra robots.
- **Motivo prioritario «Involucra a una niña, niño o adolescente»:** el contenido se oculta al recibir el reporte,
  queda copia cifrada en la bóveda, se avisa a los administradores y el reporte encabeza la cola con plazo de respuesta
  [PLAZO DE RESPUESTA A REPORTES SOBRE MENORES, p. ej. 72 horas] (`MODERATION_MINOR_RESPONSE_HOURS`).
- **Capturas:** [ANEXAR capturas del botón «Reportar», del formulario público y del acuse con folio].

## 6. Configuración predeterminada y seguridad desde el diseño

Configuración de toda cuenta nueva (la más protectora):

| Medida | Dónde |
| --- | --- |
| Ubicación pública aproximada (~1 km) en perdidos y encontrados | `backend/app/services/geo.py` (`coarse`) |
| Teléfono nunca público; contacto solo al aprobarse una adopción | `backend/app/schemas.py` |
| Fotos sin metadatos EXIF (ubicación) | `backend/app/services/images.py` (`process_image_bytes`) |
| Alertas cercanas apagadas hasta que la persona las active | `models.User.notify_nearby` (por defecto `false`) |
| Correos promocionales apagados | `models.User.marketing_opt_in` (por defecto `false`) |
| Avisos por WhatsApp solo si se piden | `models.User.whatsapp_alerts` (por defecto `false`) |
| Cookies de analítica apagadas hasta aceptarlas | `app/legal/js/cookies.js` |
| Pantallas de la app no indexables | `app/index.html` (`<meta name="robots" content="noindex">`) |
| Chat solo de texto, privado; el equipo solo ve mensajes reportados por un participante | `moderacion.html` §3 |

Seguridad desde el diseño: verificación en dos pasos obligatoria para el personal administrador
(`backend/app/services/totp.py`), cifrado en reposo de documentos privados y de la bóveda
(`backend/app/services/crypto_storage.py`, AES-256-GCM), bitácora de administración (`admin_audit_logs`) y bloqueo
por hash de imágenes retiradas (`backend/app/services/staydown.py`).

## 7. Evaluación de riesgos y calendario de reportes estadísticos

[PENDIENTE — la persona dueña debe completar y anexar la primera evaluación antes del 12-11-2026.]

Plantilla propuesta (filas por funcionalidad, columnas por categoría del art. 3 fr. I a VII, con probabilidad,
impacto, mitigación vigente y responsable): registro, perfiles, fotos de perros, reportes de perdidos y encontrados,
búsqueda por foto con IA, chat de texto, alertas cercanas, bot de WhatsApp, botón de voluntarios, contenido importado,
tienda, donativos, clínicas y reseñas.

- **Periodicidad:** [PERIODICIDAD DE LA EVALUACIÓN DE RIESGOS, p. ej. cada seis meses] y ante cada funcionalidad nueva
  (en especial si el chat llega a admitir imágenes).
- **Reporte estadístico (sin datos personales):** reportes por categoría del art. 3, contenidos y cuentas retirados,
  cuentas suspendidas, registros rechazados o cerrados por edad, requerimientos de autoridad por nivel, alertas a
  autoridades y tiempos. Fuente: `GET /cumplimiento/transparencia` (tablas `content_reports`, `moderation_actions`,
  `authority_requests`, `age_checks`). Envío semestral a [AUTORIDAD] y publicación en `informe-transparencia.html`.

## 8. Punto de contacto 24/7 para autoridades

- **Canal:** [CONTACTO 24/7 PARA AUTORIDADES]; publicado en `autoridades.html` §1 y en
  `GET /cumplimiento/autoridades/contacto` (variables `AUTHORITY_CONTACT_EMAIL` y `AUTHORITY_CONTACT_PHONE`).
- **Titular y suplente:** [NOMBRE Y CARGO DEL TITULAR], [NOMBRE Y CARGO DEL SUPLENTE]; calendario de guardias:
  [CALENDARIO]. (No se publican los nombres.)
- **Primera respuesta:** [PLAZO DE PRIMERA RESPUESTA A AUTORIDADES]; el sistema calcula el objetivo al registrar el
  requerimiento: 60 minutos si hay menores o riesgo para la vida y 24 horas en los demás casos
  (`AUTHORITY_FIRST_RESPONSE_URGENT_MINUTES`, `AUTHORITY_FIRST_RESPONSE_HOURS`).
- **Capacidad técnica inmediata:** desde el panel (con verificación en dos pasos) se puede ocultar contenido, suspender
  cuentas, poner material en cuarentena y aplicar retención legal en minutos (`/admin/cumplimiento/...`).
- **Registro:** `authority_requests` guarda autoridad, tipo, expediente, fundamento, datos pedidos, nivel, plazos,
  verificación de autenticidad, revisión legal, decisión, respuesta y si se avisó a la persona; cada cambio queda en la
  bitácora de administración.
- **Tres niveles de entrega** (`autoridades.html` §3): el sistema impide marcar como entregado el nivel 2 (contenido de
  comunicaciones) sin autorización judicial o aportación de un participante, y el nivel 3 (ubicación) sin orden del
  Juez de control o el supuesto del CNPP art. 303 (`cumplimiento_reportes._check_delivery`).

## 9. Conservación de evidencia (al menos 90 días hábiles)

- **Qué entra:** cada ocultamiento preventivo, retiro de contenido, suspensión de cuenta, retiro por derechos de autor,
  cuarentena y orden de conservación: el contenido, sus datos asociados (autor, fechas, datos técnicos), el reporte y la
  decisión (`evidence.capture`).
- **Cómo:** paquete cifrado con AES-256-GCM en una carpeta privada que nunca se sirve
  (`EVIDENCE_DIR`, por defecto `uploads/private/evidencia`). [VERIFICAR: si se moverá a un bucket separado.]
- **Integridad:** SHA-256 de cada paquete e índice de solo inserción con hash encadenado
  (`evidence_records.prev_hash` / `row_hash`); verificación desde el panel
  (`GET /admin/cumplimiento/evidencia/verificar`); un trigger de PostgreSQL impide borrar filas o alterar sus hashes
  (`evidence.APPEND_ONLY_SQL`, migración 0004).
- **Plazo:** fin del día hábil 90 desde el retiro (`EVIDENCE_RETENTION_BUSINESS_DAYS`; calendario de días hábiles sin
  días de descanso obligatorio). [VERIFICAR con el abogado si se usa el calendario de la LFPA art. 28.] Se prorroga con
  retención legal (orden de autoridad, apelación pendiente o disputa de derechos de autor abierta).
- **Purga:** la tarea diaria de conservación borra solo el archivo de lo vencido sin retención; el índice se conserva
  (`services/retention.py`, fila R30 → `evidence.purge_expired`).
- **Acceso:** solo personal administrador con verificación en dos pasos; exportación para una autoridad solo por
  superadmin, con cadena de custodia y registro en la bitácora (`GET /admin/cumplimiento/evidencia/{id}/exportar`).
- **Eliminación de cuenta:** no borra la copia antes de que venza el plazo (LFPDPPP art. 25).

## 10. Protocolo de alerta inmediata ante contenido contra menores

1. **Detección:** reporte con motivo «Involucra a una niña, niño o adolescente» o «Material de abuso sexual infantil»
   (app o formulario público), revisión del equipo u orden de autoridad. [No hay todavía filtro automático de desnudos ni
   lista de hashes conocidos de terceros: VERIFICAR con la persona dueña si se contratará.]
2. **Contención en minutos:** el contenido se oculta al recibir el reporte. Si es material de abuso sexual infantil se
   pone en cuarentena (`legal_moderation.quarantine`): los archivos salen de la carpeta pública (incluida la
   miniatura), se guardan cifrados en la bóveda con retención legal, se bloquean por hash para impedir que se vuelvan
   a subir, la ficha queda oculta y sin fotos, y el panel muestra solo metadatos.
3. **Nunca a la IA:** las imágenes en cuarentena no se envían a sistemas de inteligencia artificial
   (`services/vision.py` consulta `staydown.is_quarantined_bytes` e `is_quarantined_url` antes de cualquier envío).
4. **Alerta el mismo día:** se crea automáticamente una denuncia pendiente ante el Ministerio Público
   (`authority_requests`, dirección «saliente», estado «pendiente_denuncia», plazo el mismo día) y se avisa por correo a
   los administradores; quien presenta la denuncia anota el folio. Orientación adicional en el 088 de la Guardia
   Nacional. [VERIFICAR_CSAM: postura penal escrita del abogado antes de operar este paso (CPF arts. 202 y 202 Bis).]
5. **Entrega:** la evidencia solo se exporta ligada a esa denuncia o requerimiento, por superadmin, como archivo; nunca
   se reproduce en el panel.
6. **Registro y métricas:** cuenta en el reporte estadístico (cuarentenas, alertas enviadas).

## 11. Canal para madres, padres y tutores

- Formulario público sin cuenta (`proteccion-nna.html` §7 y §8): motivo preseleccionado «Involucra a una niña, niño o
  adolescente»; ocultamiento inmediato; folio y correo para dar seguimiento.
- Respuesta en un máximo de [PLAZO DE RESPUESTA A REPORTES SOBRE MENORES, p. ej. 72 horas].
- Un reporte de menor contra una cuenta la pasa a verificación reforzada (`services/age_check.py`); si se confirma que
  es de una persona menor, se cierra y se eliminan sus datos salvo la evidencia (VERIFICAR_CUENTA_DE_MENOR).
- Eliminación de datos de la persona menor por Derechos ARCO (`derechos-arco.html`, `POST /cumplimiento/solicitudes`).

## 12. Anexos técnicos y páginas del centro legal

- **Anexo A.** Lista de páginas del centro legal con versión, fecha de vigencia y SHA-256: `app/legal/versiones.json`
  (se genera con `scripts/render-legal.py`). [ANEXAR la tabla al momento del envío.]
- **Anexo B.** Capturas del botón «Reportar», del formulario público, del acuse con folio y del aviso de una medida.
- **Anexo C.** Evaluación de riesgos (apartado 7).
- **Anexo D.** Extracto del registro de tablas: `content_reports` (prioridad, plazo, ocultamiento al recibir),
  `moderation_actions`, `moderation_appeals`, `evidence_records`, `blocked_image_hashes`, `authority_requests`,
  `copyright_notices`.
- **Anexo E.** Resultado de la verificación de la cadena de evidencia a la fecha del informe.

---

## Entrega y constancia (checklist interno)

- [ ] Confirmar canal y formato con la ATDT (antes del 05-11-2026) y con la CJEF.
- [ ] Completar los datos entre corchetes y la evaluación de riesgos (apartado 7).
- [ ] Revisión del abogado (puntos 1 a 9 de la sección 5 de `gap-nna-decreto-entornos-digitales-2026.md`).
- [ ] PDF firmado por la persona representante; SHA-256 del PDF.
- [ ] Envío por oficialía de partes o correo oficial; acuse con sello (o mensajería con constancia).
- [ ] Constancia NOM-151 si ya hay prestador.
- [ ] Publicar en `proteccion-nna.html` §12 la fecha, el folio o acuse y la versión pública (sustituir
      VERIFICAR_INFORME_NNA_ENVIADO y FECHA_Y_FOLIO_DEL_ENVIO_DEL_INFORME_NNA en `datos-legales.json`).
- [ ] Conservar el informe, el acuse y los anexos 10 años (propuesta).
