# Plan de respuesta a incidentes (runbook) de GuauWoow

> **Uso interno y confidencial.** Versión 2026-10-17. Documento base preparado con apoyo de IA a partir de `breach_procedure` de `docs/legal/requisitos.json` y de `docs/legal/secciones/seguridad-incidentes.md` (P7 a P11); debe revisarlo el abogado. Los datos entre corchetes (`[ASÍ]`) los llena el dueño. Complementa el `documento-de-seguridad.md`.

**Fundamento:** LFPDPPP 2025, arts. 18 (medidas de seguridad), 19 (aviso de vulneraciones a titulares), 54 y 55 (verificación), 58 fr. XIV, 62 a 64 (delitos); Reglamento de 2011, arts. 63 a 66, solo como referencia; Meta Platform Terms 6.b y 7; Términos para Desarrolladores de Mercado Pago cl. 1.6, 6.6 y sección 10; Código Penal Federal, arts. 211 bis 1 a 211 bis 7. No existe ley federal de ciberseguridad vigente al 17-10-2026 (sección 11).

## 1. Cuándo se usa

Ante cualquier sospecha de: pérdida o destrucción no autorizada de datos; robo, extravío o copia no autorizada; uso, acceso o tratamiento no autorizado; daño, alteración o modificación no autorizada (clasificación del Reglamento de 2011, art. 63, como referencia). También ante caídas graves del servicio, compromiso de credenciales o tokens, y avisos de proveedores o autoridades.

Ante contenido que involucre a niñas, niños o adolescentes, usar además el protocolo de `politicas-internas.md` sección 4.

## 2. Roles y suplentes

| Rol | Titular | Suplente | Qué hace |
|---|---|---|---|
| Líder del incidente | [RESPONSABLE DE SEGURIDAD] | [SUPLENTE] | Decide, coordina y abre y cierra el incidente |
| Técnico | [TÉCNICO] | [SUPLENTE] | Contención, análisis forense, recuperación |
| Legal | [ABOGADO] | [SUPLENTE] | Evalúa la afectación significativa, avisos, denuncia, SABG |
| Comunicación | [COMUNICACIÓN] | [SUPLENTE] | Avisos a titulares, a plataformas y al público |
| Registro | [REGISTRO] | [SUPLENTE] | Lleva la bitácora y la cadena de custodia |

Si una persona tiene dos roles, el registro no lo lleva quien hace la contención.

## 3. Detección

Fuentes: alertas de Sentry y del monitoreo; reportes a [CORREO DE SEGURIDAD] y por la política de divulgación responsable (`security.txt`); avisos de proveedores (Mercado Pago, Meta, Cloudflare, hosting, proveedor de IA, SMS, correo, PAC); revisión de la bitácora de administración; reportes de personas usuarias; comunicados de la SABG; alertas de filtraciones del dominio.

Quien detecta algo avisa de inmediato al líder del incidente por [CANAL DE GUARDIA] y no borra nada.

## 4. Severidad

| Nivel | Cuándo | Ejemplos |
|---|---|---|
| S1 | Datos de identificación oficial, credenciales o hashes, CLABE o datos fiscales, chats, cuestionarios de adopción, ubicación exacta o domicilio, toma de cuentas; o compromiso de tokens de Mercado Pago, Meta, SMS o correo; o cualquier fuga con riesgo de fraude o extorsión | Acceso indebido a `uploads/private/`; toma de una cuenta de superadmin |
| S2 | Datos de contacto (nombre con teléfono o correo) sin los anteriores; indisponibilidad prolongada | Exportación indebida de una lista de correos |
| S3 | Sin datos personales | Alteración de la landing |

S1 y S2 obligan a evaluar si hay **afectación significativa** de derechos patrimoniales o morales (LFPDPPP art. 19), que es lo que activa el aviso a titulares.

## 5. Fases y plazos

| Paso | Fase | Plazo | Qué se hace |
|---|---|---|---|
| 1 | Detección | Continuo | Fuentes de la sección 3 |
| 2 | Apertura y preservación | Hora 0 | Abrir el incidente en el registro de incidentes; congelar las purgas automáticas (pausar las tareas programadas de conservación mientras dure la investigación); instantánea del servidor; copia de registros con hash SHA-256 y cadena de custodia (quién, cuándo, dónde, qué) |
| 3 | Clasificación | Primeras horas | Tipo (sección 1), severidad (sección 4), sistemas, categorías de datos y número estimado de titulares |
| 4 | Contención | Primeras 4 horas | Revocar sesiones; rotar secretos y tokens (Mercado Pago, firma de webhooks, Meta, SMS, correo, OAuth de Refugios, claves de la aplicación); bloquear IP o cuentas; aislar el servicio afectado |
| 5 | Avisos contractuales | Hasta 24 horas | Mercado Pago si toca pagos, webhooks, token o secreto de firma (formulario de la sección 10 de sus Términos para Desarrolladores) y privacidad@mercadolibre.com si afecta datos de compradores o donantes (cl. 6.6); Meta «tan pronto como sea posible» si hay datos de WhatsApp Cloud API o de la API de Páginas (Platform Terms 6.b.i) y mantenerla informada (6.b.ii); otros proveedores según su contrato |
| 6 | Aviso a titulares | De inmediato al confirmar la afectación significativa; meta interna 72 horas o menos, antes si hay riesgo de fraude | Correo y notificación en la app con las plantillas de la sección 7, enviados con el aviso a personas afectadas del panel de administración (contrato L-seguridad); aviso público si es amplio; registro de cada envío por persona (usuario, canal, fecha y versión del aviso) |
| 7 | Autoridades | Según dictamen | El abogado decide el aviso voluntario a la SABG (la LFPDPPP no lo exige a particulares) y la denuncia ante la FGR o la fiscalía estatal; si hay menores involucrados, protocolo de `politicas-internas.md` sección 4 |
| 8 | Recuperación | Tras contener | Corregir la causa; restaurar desde respaldo si hace falta y **reaplicar las supresiones y bloqueos** posteriores a la fecha del respaldo; verificar |
| 9 | Cierre | Al terminar | Análisis de causa raíz (sección 9); acciones correctivas; actualizar el documento de seguridad; cerrar en el registro; reanudar purgas sin borrar evidencia que siga siendo necesaria |
| 10 | Simulacro | Anual | Ejercicio sobre un escenario (fuga de `uploads/private/` o toma de cuenta de superadmin), con registro |

### Evidencia y cadena de custodia

- Nunca trabajar sobre el original: copiar, calcular SHA-256 y trabajar sobre la copia.
- Anotar cada acceso a la evidencia (persona, fecha, motivo).
- El acceso ilícito a sistemas es delito federal cuando están protegidos por un mecanismo de seguridad (CPF art. 211 bis 1): documentar los mecanismos que había (MFA, cifrado, permisos) para la denuncia.
- Si quien provocó la vulneración era personal autorizado y actuó con ánimo de lucro, puede ser delito (LFPDPPP art. 62; el doble con datos sensibles, art. 64): avisar al abogado.

## 6. Evaluación de la afectación significativa

Preguntas para el abogado y el líder:

1. ¿Qué datos exactos salieron o se alteraron y de cuántas personas?
2. ¿Permiten fraude, extorsión, suplantación, localización física o daño a la reputación?
3. ¿Estaban cifrados y la llave sigue segura?
4. ¿Hay evidencia de uso indebido?

Si la respuesta a 2 es sí o no se puede descartar, se avisa. La decisión y su razón quedan en el registro, también cuando se decide no avisar.

## 7. Plantillas de aviso a titulares

Contienen siempre cinco elementos: qué pasó, qué datos, qué hicimos, qué recomendamos y dónde informarse.

### 7.1 Correo

**Asunto:** Aviso de seguridad de GuauWoow: [RESUMEN]

> Hola, [NOMBRE]:
>
> Te escribimos porque detectamos un incidente de seguridad que puede afectarte y queremos que lo sepas de inmediato.
>
> 1. **Qué pasó.** El [FECHA] [descripción breve: por ejemplo, una persona no autorizada accedió a una parte de nuestros sistemas].
> 2. **Qué datos se vieron afectados.** [Lista exacta: por ejemplo, tu nombre, correo y teléfono]. No se vieron afectados: [por ejemplo, tus contraseñas, que guardamos cifradas; los datos de tu tarjeta, que nunca recibimos].
> 3. **Qué hicimos.** [Acciones: cerramos el acceso, cambiamos las credenciales, cerramos todas las sesiones, ...].
> 4. **Qué te recomendamos.** [Por ejemplo: cambia tu contraseña; desconfía de mensajes o llamadas que mencionen a tu perro o te pidan códigos o pagos; GuauWoow nunca te pedirá tu código de verificación].
> 5. **Dónde obtener más información.** Escríbenos a [CORREO DE PRIVACIDAD] o consulta https://[DOMINIO]/app/legal/seguridad.html. Puedes ejercer tus derechos de acceso, rectificación, cancelación y oposición conforme a nuestro Aviso de Privacidad.
>
> Lamentamos lo ocurrido.
> Equipo de GuauWoow

### 7.2 Notificación en la app

> **Aviso de seguridad.** El [FECHA] detectamos [resumen]. Pudo afectar [datos]. Ya [acciones]. Te recomendamos [recomendación]. Más información: [enlace al aviso completo].

### 7.3 Aviso público (si el incidente es amplio)

Fecha; resumen; datos afectados; acciones; recomendaciones; estado (en investigación o resuelto); contacto. Se publica en la página de Seguridad y se enlaza desde el informe de transparencia.

### 7.4 Aviso a Mercado Pago (formulario o correo)

> Asunto: Incidente de seguridad, cuenta [ID DE CUENTA O APLICACIÓN]. Fecha y hora de detección: [ ]. Qué componentes se vieron afectados (pagos, webhooks, token, secreto de firma, datos de compradores o donantes): [ ]. Acciones: [rotación de credenciales, bloqueo, ...]. Contacto técnico: [ ].

### 7.5 Aviso a Meta (formulario de incidentes)

> App ID [ ]; cuenta de WhatsApp Business [ ]. Fecha de detección [ ]. Datos de la plataforma involucrados [ ]. Acciones [ ]. Mantendremos informada a Meta hasta el cierre.

## 8. Directorio de contactos

| Contacto | Para qué | Dato |
|---|---|---|
| Mercado Pago, formulario de incidentes (sección 10 de los Términos para Desarrolladores) | Pagos, webhooks, tokens | [ENLACE O CANAL] |
| Mercado Pago, privacidad | Datos de compradores o donantes | privacidad@mercadolibre.com |
| Meta, formulario de incidentes | WhatsApp Cloud API, API de Páginas | [ENLACE]; App ID [ ] |
| Cloudflare | CDN, R2 | [CONTACTO] |
| Hosting [PROVEEDOR DE HOSTING] | Servidor | [CONTACTO] |
| Proveedor de IA | Fotos | [CONTACTO] |
| Sentry / PostHog | Monitoreo y analítica | [CONTACTO] |
| Proveedor SMS / correo | OTP y correos | [CONTACTO] |
| PAC [PAC DE CFDI] | CFDI | [CONTACTO] |
| Apify (si está activo) | Importación | [CONTACTO] |
| Google | OAuth y Places | [CONTACTO] |
| Abogado | Dictámenes y denuncias | [ABOGADO] |
| Contador | Efectos fiscales | [CONTADOR] |
| Aseguradora (si existe) | Póliza de ciberriesgos | [ASEGURADORA] |
| FGR o fiscalía estatal (policía cibernética) | Denuncia | [CONFIRMAR CANAL VIGENTE] |
| Ministerio Público y 088 de la Guardia Nacional | Casos con menores | Ver `politicas-internas.md` sección 4 |

Los canales del CERT-MX no se pudieron confirmar en la investigación: verificarlos al momento.

## 9. Cierre y análisis posterior (post-mortem)

Plantilla:

1. Resumen y línea de tiempo (detección, contención, avisos, cierre).
2. Causa raíz y factores que contribuyeron.
3. Datos y personas afectadas; si se avisó y por qué.
4. Qué funcionó y qué no.
5. Acciones correctivas, preventivas y de mejora, con responsable y fecha.
6. Cambios al documento de seguridad y a este runbook.
7. Lecciones para la capacitación.

## 10. Registro de incidentes (bitácora de vulneraciones)

Campos mínimos: identificador; fechas de detección, confirmación y cierre; fuente de detección; tipo (sección 1); sistemas afectados; categorías de datos; número de titulares; severidad; afectación significativa (sí o no y por qué); fecha, canal y número de avisos a titulares; avisos contractuales (Meta, Mercado Pago, otros) con fecha; denuncia (autoridad, fecha, folio); aviso voluntario a la SABG (sí o no); causa raíz; acciones inmediatas y definitivas; responsable; enlace a la evidencia preservada. Incluye los incidentes no notificados. Se conserva al menos **5 años** (R35). Cada registro dispara la revisión del documento de seguridad.

## 11. Procedimientos especiales

### 11.1 Verificación de la SABG

1. Quien reciba la notificación o la visita avisa de inmediato al departamento de datos personales y al representante legal; se pide y conserva copia de la orden (LFPDPPP art. 55).
2. Se llama al abogado para acompañar la diligencia.
3. Se congelan las purgas: queda prohibido alterar o eliminar información desde la notificación.
4. Se entrega solo lo requerido, con inventario y acuse; nunca se obstruye (art. 58 fr. XIV).
5. Se registra: fecha, personal actuante, documentos entregados y plazos; el abogado da seguimiento a los plazos de la LFPA.
6. La carpeta de evidencias (`politicas-internas.md` sección 10) acredita la diligencia (art. 60).

### 11.2 Auditorías de Meta y datos recibidos por error

- Meta puede auditar una vez por año natural con 10 días hábiles de aviso y pedir certificaciones (Platform Terms 7.a a 7.d): designar responsable, reunir evidencia y responder en plazo.
- Si recibimos datos de la plataforma de Meta por error: avisar a Meta, eliminarlos y guardar prueba de la eliminación (3.d.iii).

### 11.3 Si se publica una ley de ciberseguridad

Hoy no hay obligación legal de avisar incidentes a una autoridad de ciberseguridad. La vigilancia normativa mensual (`politicas-internas.md` sección 9) revisa el DOF; si se publica una ley con plazos de aviso, se agrega aquí un paso entre el 5 y el 6 con la autoridad, el plazo y el formato.

## 12. Control de versiones

| Versión | Fecha | Cambios | Aprobó |
|---|---|---|---|
| 2026-10-17 | 17-10-2026 | Primera versión base (pendiente de aprobación) | [PENDIENTE] |
