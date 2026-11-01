# Políticas internas y procedimientos de GuauWoow

> **Uso interno y confidencial.** Versión 2026-10-17. Documento base preparado con apoyo de IA a partir de `docs/legal/requisitos.json` (`takedown_procedure`, `retention`, `hard_deadlines`, `pending_watch`, `compliance_matrix`) y de las secciones de `docs/legal/secciones/`; debe revisarlo el abogado. Los datos entre corchetes (`[ASÍ]`) los llena el dueño. Los plazos marcados **«propuesta»** salen de la investigación y el dueño debe confirmar que el equipo puede cumplirlos (`owner_data_needed` O46) antes de publicarlos.

Documentos relacionados: `documento-de-seguridad.md` (inventario, riesgos y medidas) y `runbook-incidentes.md` (vulneraciones).

## Índice

1. Moderación de contenido y apelaciones
2. Solicitudes de autoridades
3. Derechos ARCO y otras solicitudes de personas usuarias
4. Protocolo de niñas, niños y adolescentes (incluye material de abuso sexual infantil)
5. Conservación, bloqueo y borrado
6. Accesos, secretos, respaldos, registros y vulnerabilidades
7. Verificación de Refugios y Clínicas con mínimos datos
8. Evaluación interna de riesgos de lavado de dinero
9. Vigilancia normativa y calendario de fechas duras
10. Carpeta de evidencias
11. Evaluación de riesgos antes de funciones nuevas
12. Control de versiones

---

## 1. Moderación de contenido y apelaciones

**Fundamento:** Decreto de entornos digitales seguros para NNA (DOF 14-10-2026) arts. 3, 4 y 5; LFDA art. 114 Octies; LFPC arts. 10 y 90; LGAMVLV arts. 20 Quáter a 20 Sexies; leyes estatales de bienestar animal.

### 1.1 Entrada de reportes

- Botón «Reportar» en todo contenido, perfil, producto, reseña y mensaje de la app.
- Formulario público sin cuenta (páginas `moderacion.html` y `proteccion-nna.html`).
- Motivos: las siete categorías del art. 3 del Decreto NNA (acoso y ciberacoso; abuso, explotación o violencia sexual; odio, extremismo violento o violencia masiva; intercambio que incite al odio o la violencia; conductas ilícitas o apología del delito; pornografía y material sexual explícito; suicidio, autolesiones y trastornos alimenticios), «involucra a una niña, niño o adolescente», venta o cobro por animales, maltrato, contenido íntimo, difamación, mi imagen o mis datos, derechos de autor o marca, estafa, suplantación, reseña falsa, facturas, rifa o sorteo.
- Cada reporte queda con motivo, origen (persona usuaria, persona sin cuenta, filtro automático, revisión propia, autoridad) y fecha.

### 1.2 Triage y plazos

| Tipo | Acción inmediata | Plazo objetivo |
|---|---|---|
| Involucra a menores (art. 3 del Decreto o motivo «involucra a una niña, niño o adolescente») | Se oculta de inmediato y se revisa con prioridad; ver sección 4 | Revisión en menos de 24 h (propuesta) |
| Contenido íntimo sin consentimiento | Ocultar con reporte creíble, bloquear por hash, resguardar cifrado, avisar con la leyenda legal | Menos de 24 h (propuesta) |
| Venta o cobro por animales | Retención para revisión humana | Revisión en 24 h o menos (propuesta) |
| Riesgo inminente para personas o animales | Retiro preventivo de lo manifiestamente ilícito | Inmediato |
| Derechos de autor | Ver 1.5 | Retiro en menos de 24 h hábiles (propuesta) |
| Contenido importado de Facebook (solo si está activo) | Retiro a petición del autor | Menos de 72 h (contrato L-fb) |
| Reseñas de Clínicas | Filtro previo; revisión humana de lo retenido | 24 h hábiles (propuesta) |
| Resto de reportes | Revisión humana | 72 h hábiles (propuesta) |

### 1.3 Decisión y aviso

1. Aplicar la regla publicada (Términos, Normas de la comunidad, Productos prohibidos).
2. Registrar en la bitácora de administración: regla, decisión, persona que decidió y si hubo detección automática.
3. Enviar al autor la declaración de motivos (regla incumplida, cómo se detectó, cómo apelar), salvo riesgo inminente, orden de autoridad o investigación en curso.
4. Avisar el resultado a quien reportó.
5. Mover una copia del contenido retirado y sus metadatos a la **bóveda de evidencia cifrada** durante al menos **90 días hábiles** (Decreto NNA art. 5 fr. II), con retención legal si hay apelación, orden de conservación o caso con menores.

### 1.4 Escala para venta o cobro por animales (propuesta de la investigación)

1. Primer caso: retiro y aviso.
2. Segundo caso: suspensión de publicaciones por 30 días.
3. Tercer caso o cobro confirmado: retiro de la verificación del Refugio y de los donativos.

Toda sanción queda en la bitácora.

### 1.5 Derechos de autor (contrato L-autor)

1. Aviso por el formulario público (sin cuenta y sin exigir certificados); acuse con folio. Si faltan requisitos, se pide completarlos sin retirar.
2. Retiro o inhabilitación expedita y aviso a quien subió el contenido, con copia del aviso y enlace al contra-aviso.
3. Contra-aviso por el formulario público; copia inmediata a quien avisó; restauración entre el día hábil 10 y el 15 salvo prueba de que inició un procedimiento.
4. Bloqueo de imágenes idénticas (staydown) y política de reincidentes publicada en `derechos-de-autor.html` (propuesta de la investigación: 2 avisos procedentes en 12 meses, suspensión de 30 días; 3, cancelación).
5. Desde alrededor del 03-02-2027 aplica el formulario del capítulo V del Reglamento de la LFDA (arts. 37 Bis a 37 Nonies); revisar que el formulario lo cumpla.

### 1.6 Apelaciones (contrato L-reportes)

- La persona sancionada puede apelar aunque su cuenta esté suspendida.
- Resuelve un administrador **distinto** de quien decidió, con respuesta razonada.
- Plazos (propuesta): 15 días para apelar; respuesta en 10 días hábiles.
- Durante la suspensión la persona conserva sus derechos ARCO.

## 2. Solicitudes de autoridades

**Fundamento:** CPEUM art. 16; CNPP arts. 222, 291 y 303; LFPDPPP arts. 9 fr. V y VII y 36; LMTR art. 182; LSNIIMSP art. 26; Decreto NNA art. 5; LFPC art. 13 (PROFECO).

### 2.1 Canal y guardia

- Contacto 24/7 para autoridades: [CONTACTO 24/7] (correo y teléfono dedicados; titular [TITULAR 24/7] y suplente [SUPLENTE 24/7]; calendario de guardias en [UBICACIÓN DEL CALENDARIO]).
- Primera respuesta (propuesta): **1 hora** en casos con menores o riesgo para la vida; **24 horas** en los demás.
- Solo se atienden requerimientos **por escrito** (oficio, correo institucional o notificación formal). Las solicitudes verbales o por redes se redirigen al canal escrito.

### 2.2 Verificación

1. Autenticidad: dominio del remitente, número de oficio, sello y firma; llamada de vuelta al número oficial de la autoridad.
2. Competencia de la autoridad y fundamentación y motivación del acto.
3. Revisión del abogado antes de entregar, salvo emergencia con riesgo para la vida o la seguridad de una persona (LFPDPPP art. 9 fr. V), que atiende la guardia con registro y revisión posterior.

### 2.3 Tres niveles de entrega

| Nivel | Qué datos | Qué se requiere |
|---|---|---|
| 1. Datos de cuenta | Nombre, correo, teléfono verificado, IP de alta, fechas | Oficio fundado y motivado de autoridad competente (LFPDPPP arts. 9 fr. VII y 36) |
| 2. Contenido | Chats, archivos y mensajes almacenados | Autorización judicial (CPEUM art. 16; CNPP art. 291) o aportación voluntaria de una persona participante |
| 3. Ubicación | Ubicación en tiempo real o historial | Orden del juez de control, o requerimiento directo del fiscal en los casos excepcionales del CNPP art. 303, con registro y seguimiento de la ratificación judicial |

- **Órdenes de conservación** (CNPP art. 303): retención legal inmediata en la bóveda de evidencia.
- **Respuesta estándar** si una autoridad invoca el Decreto NNA para pedir chats sin orden judicial: «El Decreto de entornos digitales seguros para niñas, niños y adolescentes (DOF 14-10-2026) obliga a GuauWoow a atender requerimientos de información y a preservar evidencia, pero no modifica el artículo 16 constitucional ni el artículo 291 del Código Nacional de Procedimientos Penales, que exigen autorización judicial para entregar el contenido de comunicaciones privadas. Hemos preservado la evidencia relacionada con [identificación] y la entregaremos de inmediato al recibir la autorización judicial correspondiente. Los datos de registro de la cuenta se entregan con el presente oficio.»

### 2.4 Entrega y registro

1. Extraer solo lo mínimo solicitado; entregar por canal seguro y con acuse.
2. Registrar en el registro de solicitudes de autoridad: autoridad, tipo (judicial, ministerial, administrativa, fiscal), fundamento, datos pedidos y entregados, fechas de recepción y respuesta, decisión (total, parcial, rechazada) y motivo, si fue emergencia, y si se avisó a la persona.
3. Avisar a la persona afectada, salvo prohibición legal o riesgo para una investigación; documentar la razón de no avisar.
4. Anotar el acceso en la bitácora de administración y contar el caso para el informe de transparencia.
5. **PROFECO:** registrar el requerimiento con fecha límite de 15 días, pedir prórroga una sola vez si hace falta y poder exportar el expediente de un pedido en horas (comprobante, aceptación con versión y hash, mensajes, pagos, reembolsos, rastreo).
6. **IMPI y otras autoridades de propiedad intelectual:** mismo procedimiento; retiro del producto o contenido si la orden lo pide.

## 3. Derechos ARCO y otras solicitudes de personas usuarias

**Fundamento:** LFPDPPP 2025 arts. 21 a 31 (ARCO), 25 (negativa de cancelación), 26 (oposición), 17 (datos obtenidos de forma indirecta); LFPC art. 16.

### 3.1 Tipos (centro de solicitudes, contrato L-solicitudes)

Acceso, rectificación, cancelación, oposición; revocación del consentimiento; limitación del uso o divulgación; quejas y aclaraciones; retiro de una publicación importada por su autor. Cada solicitud recibe un **folio** y se sigue en la cola de administración con sus plazos.

### 3.2 Plazos

| Paso | Plazo |
|---|---|
| Acuse con folio | Inmediato |
| Respuesta | 20 días hábiles desde la recepción (LFPDPPP art. 31) |
| Hacer efectiva la respuesta procedente | 15 días hábiles desde la respuesta |
| Ampliación | Una sola vez, cuando las circunstancias lo justifiquen, avisando a la persona dentro del primer plazo (LFPDPPP art. 31; confirmar el texto exacto con el abogado) |
| Retiro de publicación importada | Menos de 72 horas (contrato L-fb) |
| Quejas y aclaraciones | Los plazos publicados en `atencion-y-quejas.html` |

### 3.3 Identidad

- Verificar la identidad de quien solicita (o de su representante) por el medio menos invasivo: sesión iniciada con teléfono verificado, o confirmación por el correo o teléfono registrados.
- Si hace falta ver una identificación, revisarla sin conservar copia más tiempo del necesario para resolver; anotar solo «identidad verificada: método, fecha, persona».

### 3.4 Resolución

1. Revisar la solicitud y los datos involucrados en todas las tablas y proveedores (sección 3.1 del documento de seguridad).
2. Decidir; si se niega total o parcialmente, fundar la causa legal (por ejemplo, en la cancelación, art. 25: datos necesarios para cumplir un contrato o una obligación legal, o evidencia que debe conservarse).
3. Recordar: la eliminación de la cuenta no vacía la bóveda de evidencia ni los registros fiscales mientras corra su plazo; esos datos quedan **bloqueados**, sin uso operativo.
4. Propagar rectificaciones y cancelaciones a los Refugios que recibieron datos de la persona, cuando aplique.
5. Responder por el mismo medio, con fundamento y, en su caso, con los datos.
6. Guardar el expediente 5 años (R35).

### 3.5 Otras solicitudes

- **Bot de WhatsApp:** los comandos BAJA, ALTA, ELIMINAR y PERSONA se atienden automáticamente; ELIMINAR genera una solicitud con folio.
- **Solicitud de la LFPC art. 16** (qué datos usamos con fines mercadotécnicos y con quién se compartieron): tratar en la misma cola. [Confirmar plazo con el abogado].
- **Eliminación de datos de la plataforma de Meta:** se atiende y se registra para el informe de transparencia.

## 4. Protocolo de niñas, niños y adolescentes

**Fundamento:** Decreto NNA (DOF 14-10-2026) arts. 3, 4 y 5 y transitorio Cuarto; CNPP art. 222; CPF arts. 202 y 202 Bis; LGDNNA art. 5. GuauWoow es solo para mayores de 18 años, pero el decreto aplica igual (conflicto resuelto 8).

### 4.1 Prevención: verificación de edad por capas (contrato L-edad)

1. Registro: fecha de nacimiento, casilla «Tengo 18 años o más» separada y OTP por SMS.
2. Señales de riesgo (reportes «involucra a un menor», menciones de edad o escuela, edad incoherente): la cuenta pasa a verificación reforzada.
3. Verificación reforzada **sin copias de identificaciones y sin biometría**. Se guarda solo la constancia: fecha, método, persona que verificó y resultado.
4. Si se confirma minoría de edad: cierre de la cuenta, reembolso de compras en curso, borrado de datos salvo la evidencia obligatoria, y aviso a madre, padre o tutor si se conoce.

### 4.2 Contenido que involucra a menores

1. **Detección:** reporte, filtro o revisión propia.
2. **Contención en minutos:** ocultar de inmediato; suspender la cuenta si hay indicios de delito; bloquear por hash para impedir resubidas; copia a la bóveda con acceso bloqueado.
3. **Revisión con prioridad** por moderación (sección 1.2).
4. **Alerta el mismo día** si hay indicios de delito: denuncia ante el Ministerio Público (FGR o fiscalía estatal) y orientación en el 088 de la Guardia Nacional; registrar folio, fecha, hora y persona que denunció en el registro de solicitudes de autoridad.
5. **Personas:** aviso a quien reportó, sin detalles; orientación psicológica para el equipo (Línea de la Vida como recurso).

### 4.3 Material de abuso sexual infantil

- **Nunca** se reproduce, se descarga a equipos personales, se reenvía ni se envía a proveedores de IA.
- Se pone en **cuarentena**: solo el original, con hash, en la bóveda, con acceso bloqueado; solo el contacto 24/7 y superadmin con MFA, y cada acceso queda en la bitácora.
- Se denuncia al Ministerio Público y se piden instrucciones de entrega y destrucción.
- Se deja constancia de que la conservación es exclusivamente para la entrega del art. 5 fr. II del decreto y del CNPP art. 222.
- **Pendiente bloqueante:** postura penal escrita del abogado (CPF arts. 202 y 202 Bis) antes de operar este paso.

### 4.4 Madres, padres y tutores

Reporte sin cuenta en `proteccion-nna.html`. Se suspende el contenido o la cuenta mientras se verifica. Respuesta en 72 horas (propuesta).

### 4.5 Evaluación y reportes

- Evaluación de riesgos por funcionalidad y por categoría del art. 3: antes del **12-11-2026** y cada 6 meses o ante funciones nuevas.
- Reporte estadístico semestral sin datos personales, enviado a la ATDT con constancia y publicado en el informe de transparencia (propuesta; el decreto no fija periodicidad ni autoridad; confirmar canal con la ATDT y la CJEF).
- Informe de implementación del transitorio Cuarto: confirmar el canal con la ATDT y la CJEF antes del **05-11-2026**; entregar a más tardar el **12-11-2026**; conservar acuse 10 años (R46).

## 5. Conservación, bloqueo y borrado

**Fundamento:** LFPDPPP arts. 10, 12, 24 y 25; CCom arts. 38 y 49; CFF art. 30; LFPIORPI art. 18; Decreto NNA art. 5 fr. II. Calendario único: conflicto resuelto 4 y `retention` (R01 a R48).

1. **Fuente única:** la tabla de conservación configurada en el backend y publicada en `/cumplimiento/conservacion` (`conservacion.html`). Cualquier cambio de plazo se hace ahí y se refleja en el aviso de privacidad.
2. **Purgas automáticas** (contrato L-seguridad): se ejecutan según esa tabla. El responsable de seguridad revisa cada mes que hayan corrido y que no haya errores.
3. **Documentos de identidad y de verificación:** se borran 30 días después de la decisión; queda solo la constancia de verificación.
4. **Bloqueo:** al eliminar una cuenta, lo que la ley obliga a conservar (pedidos, donativos, aceptaciones, evidencia) queda bloqueado, sin uso operativo, hasta que vence su plazo; luego se suprime.
5. **Retención legal:** la evidencia de retiros se conserva al menos 90 días hábiles y más si hay apelación, orden de conservación o caso con menores. Una retención legal se registra con motivo, fecha y quién la ordenó, y se levanta por escrito.
6. **Incidentes y verificaciones de la SABG:** congelar las purgas mientras duren (runbook, paso 2, y 11.1).
7. **Respaldos:** se cifran; al restaurar uno, se reaplican las supresiones y bloqueos posteriores a la fecha del respaldo.
8. **Borrado seguro:** usar métodos que impidan recuperar la información (la Guía de Borrado Seguro del INAI de 2016 sirve de referencia técnica histórica; la autoridad vigente es la SABG).

## 6. Accesos, secretos, respaldos, registros y vulnerabilidades

| Tema | Regla vigente (contrato) | Pendiente (ver brecha del documento de seguridad) |
|---|---|---|
| Cuentas de administración | MFA (TOTP) obligatoria; bitácora de administración de todas las acciones | Permisos separados (moderación, verificación, finanzas, configuración); altas y bajas el mismo día; revisión trimestral firmada |
| Secretos y llaves | Rotar tras cualquier incidente (runbook, paso 4) | Inventario; rotación anual; llave de respaldos fuera del servidor |
| Respaldos | Cifrados | Objetivos RPO 24 h y RTO [RTO OBJETIVO]; prueba de restauración mensual registrada; credenciales de la copia externa de solo escritura; reaplicar supresiones al restaurar (sección 5.7) |
| Registros técnicos | Sin contraseñas, OTP, tokens ni contenido de chats en los registros | Rotación por tiempo; IP truncada a los 30 días |
| Vulnerabilidades | `security.txt` y política de divulgación responsable; acuse de los reportes | Escaneo en CI; pentest; parches críticos en 7 días |
| Cuentas de cobro de los Refugios | Cada Refugio cobra con su propia cuenta de Mercado Pago vinculada por OAuth | Tratar la desvinculación y la nueva vinculación de una cuenta como cambio sensible: confirmar con el contacto verificado del Refugio y registrar en la bitácora |
| Encargados | Regla fija: ningún documento de identidad, acta, chat ni dato de contacto va a proveedores de IA | Registro con DPA o términos; revisión anual |
| Confidencialidad | Acceso solo con necesidad | Acuerdo de confidencialidad firmado antes del acceso; capacitación anual |

## 7. Verificación de Refugios y Clínicas con mínimos datos

1. Pedir solo lo necesario para verificar (identidad del responsable, personalidad jurídica, datos fiscales si va a vender, cédula del veterinario responsable en el caso de Clínicas).
2. Identificaciones aceptadas: INE, CURP biométrica (física o digital) o pasaporte; de las actas, solo las páginas esenciales.
3. Los documentos se guardan cifrados en reposo y se borran 30 días después de la decisión (aprobación o rechazo); se conserva la constancia (quién, cuándo, método, resultado, vigencia).
4. Clínicas: cotejo de la cédula en el Registro Nacional de Profesionistas y reverificación anual (contrato L-vet).
5. Cada vista de un documento queda en la bitácora de administración.

## 8. Evaluación interna de riesgos de lavado de dinero

**Fundamento:** LFPIORPI arts. 17 fr. I, II c), XI y XIII, y 18; Acuerdo 115/2026 (RCG, en vigor 30-11-2026); conflicto resuelto 12. Confianza baja sobre la fr. XI: requiere opinión escrita de abogado especialista (`lawyer_points`).

| Riesgo | Situación de GuauWoow | Control | Pendiente |
|---|---|---|---|
| Recibir donativos como asociación (fr. XIII) | No aplica si el operador es sociedad mercantil; aplica a los Refugios A.C. | Información a Refugios en `prevencion-lavado.html` | Confirmar forma jurídica del operador |
| Administrar recursos de terceros (fr. XI) | Con Split 1:1, cada Refugio cobra con su cuenta; GuauWoow no custodia | La cuenta de la plataforma **no** debe cobrar donativos en producción (opción de respaldo desactivada) | Opinión escrita del abogado de PLD |
| Vales, tarjetas de regalo o saldos (fr. II c) | No existen | Regla de producto: nunca crearlos | — |
| Sorteos (fr. I) | Prohibidos en la Plataforma | Moderación y productos prohibidos | — |
| Montos altos | Tope por donativo [TOPE POR DONATIVO] y tope diario [TOPE DIARIO DE DONATIVOS] | Topes en el sistema | Monitoreo de acumulados a 6 meses por donante y Refugio (por confirmar si existe) |
| Autodonaciones | Bloqueadas | El sistema rechaza donar al propio Refugio | Revisar donativos desde IP o dispositivos del Refugio |
| Refugios fachada o en el listado 69-B | Verificación de Refugios; Mercado Pago verifica cada cuenta | Revisión al alta | Consulta trimestral del listado 69-B |

Revisar esta evaluación: al entrar en vigor el Acuerdo 115/2026 (30-11-2026), cuando la UIF publique sus medidas para asociaciones sin fines de lucro, al cambiar la UMA (febrero de 2027) y ante cualquier cambio del modelo de cobro.

## 9. Vigilancia normativa y calendario

**Responsable:** [RESPONSABLE DE VIGILANCIA NORMATIVA]. Cada revisión se anota en la bitácora de vigilancia ([UBICACIÓN DE LA BITÁCORA]) con fecha, fuentes, hallazgos y acciones. Los cambios que afecten páginas públicas se reflejan en 30 días o menos, con el aviso previo de 30 días cuando el cambio es importante.

### 9.1 Fechas duras (de `hard_deadlines`)

| Fecha | Qué | Quién |
|---|---|---|
| Antes del lanzamiento | Completar `datos-legales.json`, páginas bloqueantes y checklist de cobros; sin marcadores vacíos | Dueño y abogado |
| 31-10-2026 | El Senado debe resolver la LISR y la LIF 2027; vence la regla 10ª Bis de Redes de Medios de Disposición | Contador; vigilancia |
| 05-11-2026 | Confirmar con la ATDT y la CJEF el canal del informe NNA | Dueño y abogado |
| 12-11-2026 | Entregar el informe de implementación del Decreto NNA (cómputo alternativo: 13-11-2026) | Representante legal |
| 30-11-2026 | Entran en vigor las RCG de la LFPIORPI modificadas (Acuerdo 115/2026) | Refugios A.C.; abogado de PLD |
| Noviembre y diciembre de 2026 | Publicación de la LISR y la LIF 2027; actualizar tasas de retención para el 01-01-2027 | Contador |
| 31-12-2026 | Entra en vigor la Tercera modificación a la RMF 2026 (Anexo 7) | Contador |
| 31-01-2027 | Termina la UMA 2026 ($117.31); recalcular umbrales y multas | Contador |
| Alrededor del 03-02-2027 | Entra en vigor el capítulo V del Reglamento de la LFDA (formulario obligatorio de aviso y contra-aviso) | Producto y abogado |
| 01-03-2027 | Exigibles la evaluación de riesgo y el manual de políticas PLD de sujetos obligados | Refugios A.C. |
| 01-04-2027 | Aplicación del Código Nacional de Procedimientos Civiles y Familiares como supletorio (LFPDPPP art. 4) | Abogado |
| Cada 180 días por Refugio | Renovar el token OAuth de Mercado Pago de cada Refugio vinculado | Sistema |
| Rodante | Evidencia de cada retiro: al menos 90 días hábiles | Moderación |

### 9.2 Revisiones periódicas

| Frecuencia | Qué revisar |
|---|---|
| Semanal | DOF y Gaceta de Diputados por la Ley General de bienestar animal |
| Mensual | DOF; gob.mx/atdt y gob.mx/cjef (Mesa de Trabajo del Decreto NNA); gob.mx/buengobierno (SABG); Términos de Mercado Pago (los cambios entran en vigor a los 10 días; el rechazo es en 5); políticas de Meta y Google; PCI SSC; `Expires` de `security.txt`; corridas de purga |
| Trimestral | Actualización de la LFPDPPP y reglamento nuevo; listado 69-B para Refugios; revisión de accesos de administración (cuando exista) |
| Semestral | Evaluación de riesgos del Decreto NNA; reporte estadístico e informe de transparencia; políticas de Meta y Google |
| Anual | Este documento, el documento de seguridad y el runbook; capacitación; simulacro; tasas fiscales y UMA; SAQ A |
| Al publicarse | Nuevas Disposiciones de Redes de Medios de Disposición (repetir el análisis de receptor de pagos); minuta de reforma a los arts. 18 Bis y 127 de la LFPC; reformas de Veracruz y Baja California (cotejo con abogado local); cualquier ley de ciberseguridad |

## 10. Carpeta de evidencias

Carpeta privada y versionada en [UBICACIÓN DE LA CARPETA]:

- versiones publicadas de los documentos legales con su SHA-256 y la bitácora de aceptaciones;
- expedientes ARCO y de otras solicitudes;
- documento de seguridad, inventario y matriz de riesgos;
- constancias de capacitación y acuerdos de confidencialidad;
- contratos, DPA y términos aceptados de encargados, y copias fechadas de los términos de Mercado Pago, Meta, Google y Apify, con la excepción escrita de Mercado Pago para donativos (R47);
- registro de incidentes y avisos enviados;
- corridas de purga;
- informes de pruebas de seguridad y escaneos (cuando existan);
- revisiones de accesos;
- SAQ A (cuando exista);
- evaluaciones de riesgos de funciones nuevas y del Decreto NNA, informe NNA y acuses;
- registro de solicitudes de autoridad y de verificaciones de la SABG;
- registros de eliminación de datos de la plataforma de Meta;
- dictámenes de abogado y contador (custodia de fondos, PLD, importación de Facebook, postura penal sobre material de abuso);
- opcional: constancias NOM-151.

## 11. Evaluación de riesgos antes de funciones nuevas

Antes de activar o cambiar una función que trate datos (tienda, alertas cercanas, puntaje de compatibilidad, importación de Facebook, IA o proveedor de IA nuevo, Clínicas, proveedores nuevos):

1. Describir finalidad, datos, personas afectadas y proveedores.
2. Revisar la base legal y si cambia el aviso de privacidad.
3. Evaluar riesgos con la escala del documento de seguridad y por categoría del art. 3 del Decreto NNA.
4. Definir medidas y responsables.
5. Obtener el visto bueno del abogado cuando haya dictamen pendiente. **La importación de grupos de Facebook no se activa sin los dictámenes jurídicos** (conflicto resuelto 9).
6. Guardar la evaluación en la carpeta de evidencias.

## 12. Control de versiones

| Versión | Fecha | Cambios | Aprobó |
|---|---|---|---|
| 2026-10-17 | 17-10-2026 | Primera versión base (pendiente de aprobación) | [PENDIENTE] |
