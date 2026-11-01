# Cómo llenar los datos legales de GuauWoow

El centro legal (Términos, Aviso de Privacidad, políticas, guías y formularios de `/app/legal/`) son **55 páginas
que se generan** desde plantillas. Tú no editas las páginas: llenas **un solo archivo**,
`app/legal/datos-legales.json`, y el script `scripts/render-legal.py` pone cada dato en todas las páginas donde
aparece. Lo que no llenes se queda **resaltado** en la página (borde punteado), nunca en blanco, y el despliegue a
producción se niega a salir mientras quede algo pendiente.

Ten a la mano antes de empezar:

- La constancia de situación fiscal del SAT y el acta constitutiva (razón social, RFC, régimen, domicilio).
- Los buzones de correo que vas a usar (contacto, privacidad, facturación, seguridad, legal, accesibilidad).
- Los contratos o paneles de tus proveedores (hosting, correo, SMS, respaldos, Sentry, PostHog, PAC).
- El archivo `.env` del servidor: varios datos deben coincidir con él y `--check` los compara.
- Una cita con tu abogado y otra con tu contador para las notas `VERIFICAR` (al final de esta guía).

## Paso a paso

1. **Crea o completa el archivo de datos** (conserva lo que ya hayas escrito):

   ```bash
   python3 scripts/render-legal.py --init
   ```

2. **Abre `app/legal/datos-legales.json` y llena los valores**, grupo por grupo, en el orden de esta guía. Reglas:
   - Cada valor va entre comillas: `"RFC": "PFM2601011A2"`. No borres claves ni cambies sus nombres.
   - Escribe el dato tal como debe leerse en la página (con mayúsculas, acentos y puntuación). Los ejemplos de la
     lista de abajo muestran el tono.
   - `FECHA_DE_ENTRADA_EN_VIGOR` va en formato `AAAA-MM-DD` (por ejemplo `2026-11-20`).
   - Las claves `VERIFICAR_*` llevan `true` (sin comillas) o un texto: ver [Notas VERIFICAR](#notas-verificar).
   - Un valor vacío (`""`) deja el marcador resaltado. Así puedes avanzar por partes.
   - `python3 scripts/render-legal.py --list` muestra todas las claves con su descripción en la terminal.

3. **Genera las páginas**:

   ```bash
   python3 scripts/render-legal.py
   ```

   Escribe las 55 páginas de `app/legal/`, `app/legal/aviso-simplificado.txt`, `app/.well-known/security.txt`,
   el registro de versiones `app/legal/versiones.json` (y su copia `backend/app/data/versiones-legales.json`), las
   páginas legales de `app/sitemap.xml`, el aviso del formulario de registro en `app/index.html` y la lista de
   claves de esta guía.

4. **Revisa qué falta**:

   ```bash
   python3 scripts/render-legal.py --check
   ```

   Termina con `Textos legales completos y al día.` cuando ya no falta nada. Mientras tanto lista los datos vacíos,
   las notas `VERIFICAR` pendientes y cualquier error (ver [Qué revisa `--check`](#qué-revisa---check)).

5. **Mira el resultado** en tu computadora:

   ```bash
   cd app && python3 server.py      # y abre http://localhost:8082/app/legal/
   ```

6. **Guarda y despliega**. El archivo de datos se sube al repositorio (todo es información pública de las páginas):

   ```bash
   git add app/legal app/index.html app/sitemap.xml app/.well-known backend/app/data/versiones-legales.json \
           docs/legal/LLENAR-DATOS.md
   git commit -m "Datos legales"
   ```

   `backend/scripts/deploy.sh` vuelve a correr `--check` en el servidor (con su `.env`) y se niega a desplegar a
   producción si falla.

## Qué juntar para cada grupo

La lista completa, con la descripción, un ejemplo y las páginas donde aparece cada clave, está al final
([Lista de claves](#lista-de-claves)). En resumen:

- **Identidad y empresa.** Todo sale de la constancia de situación fiscal y del acta constitutiva. La razón social
  lleva el tipo societario (S.A.S., S.A. de C.V.) y se escribe igual en todas partes. `DOMICILIO_FISCAL` es el
  domicilio físico donde realmente recibes documentos (PROFECO, autoridades, solicitudes de datos); si el del SAT es
  otro, va en `DOMICILIO_ANTE_EL_SAT_SI_ES_DISTINTO`. `DOMINIO` debe ser igual a `DOMAIN` del `.env`.
- **Contacto y canales.** Crea los buzones antes de publicarlos. `CORREO_DE_CONTACTO` conviene que sea igual a
  `SUPPORT_EMAIL` del `.env`. `CONTACTO_24_7_PARA_AUTORIDADES` debe contestarse de verdad las 24 horas.
- **Proveedores y países.** Copia el nombre legal de cada proveedor y el país o región de sus servidores tal como
  aparece en tu contrato o en su panel (Sentry y PostHog muestran la región en la configuración de la organización).
- **Plazos y políticas.** Son compromisos públicos: elige plazos que tu equipo pueda cumplir. Cuatro deben ser
  iguales a la configuración del servidor, y `--check` los compara:

  | Clave | Variable del servidor | Valor por defecto |
  |-------|-----------------------|-------------------|
  | `PLAZO_DE_RESGUARDO_DE_PERROS_ENCONTRADOS` | `FOUND_DOG_HOLD_DAYS` | 30 días |
  | `PLAZO_LOCAL_DE_RESPALDOS` | `BACKUP_RETENTION_DAYS` | 14 días |
  | `PLAZO_DE_CONSERVACION_DE_RESPALDOS_EXTERNOS` | `BACKUP_OFFSITE_RETENTION_DAYS` | 30 días |

- **Tienda y donativos.** Las comisiones y los topes también se comparan con el servidor:

  | Clave | Variable del servidor |
  |-------|-----------------------|
  | `COMISION_TIENDA` | `MERCADOPAGO_MARKETPLACE_FEE_PERCENT` |
  | `COMISION_DONATIVOS` | `MERCADOPAGO_DONATION_FEE_PERCENT` |
  | `TOPE_POR_DONATIVO` | `DONATION_MAX_MXN` |
  | `TOPE_DIARIO_DE_DONATIVOS` | `DONATION_DAILY_MAX_MXN` |

  Mientras tu contador no confirme `VERIFICAR_REGIMEN_PLATAFORMAS`, ambas comisiones deben ser **0** en el `.env`
  y en las páginas (`--check` falla si hay una comisión mayor que 0). No actives los donativos sin la autorización
  escrita de Mercado Pago (`AUTORIZACION_DE_MERCADO_PAGO_PARA_DONATIVOS`).
- **Decisiones de negocio.** Fechas y estados que cambian con el tiempo (revisión legal, informe del Decreto NNA,
  dictamen NMX, auditorías). Cuando algo todavía no existe, escribe la frase honesta que lo diga (los ejemplos lo
  muestran: «no contamos con dictamen todavía», «Por ahora nadie lo ha solicitado»).

## Notas VERIFICAR

Las claves `VERIFICAR_*` son notas que aparecen dentro del texto, resaltadas, donde hace falta que alguien
confirme algo antes de publicar: tu abogado, tu contador, el equipo técnico (que la app haga lo que dice la página)
o tú como dueño. La lista de abajo dice, para cada una, **qué confirmar** y **el valor sugerido**.

- `true` (sin comillas) = se confirmó la cláusula tal como está: la nota desaparece y, si estaba sola en un
  párrafo o viñeta, también el párrafo.
- Un texto = reemplaza la nota en la página. Úsalo cuando tu asesor pida otra redacción o cuando la nota
  dice «escribe aquí: «…»» (algunas notas publican una frase solo cuando la práctica ya existe; mientras no exista,
  su valor es `true` y no se publica nada en su lugar).
- Varias notas aparecen en más de una página: un texto las reemplaza en todas a la vez. Si la frase no encaja en
  todas, pide el ajuste en la plantilla y usa `true`.
- Si una nota dice «si no, quita este párrafo» y la práctica no existe, no pongas `true`: pide que se cambie la
  plantilla (`app/legal/plantillas/<página>.html`) o que se implemente lo que describe.
- Para la cita con tu abogado o contador, imprime la sección de su grupo de la lista de abajo.

## Versiones y fecha de entrada en vigor

- Cada plantilla imprime su versión (`Versión: 2026-10-17`) y `FECHA_DE_ENTRADA_EN_VIGOR` llena «Vigente desde» en
  todas. La versión de `terminos` y `privacidad` debe ser igual a `legal_terms_version` / `legal_privacy_version`
  de `backend/app/config.py` (deja vacías `LEGAL_TERMS_VERSION` y `LEGAL_PRIVACY_VERSION` en el `.env`).
- `app/legal/versiones.json` es el registro público: por cada página, su versión, fecha de entrada en vigor,
  huella SHA-256 del archivo publicado, si pide aceptarla otra vez (Términos, Aviso de Privacidad, Condiciones de
  compra y los anexos de Refugios, vendedores, Clínicas y Casas de paso) y un resumen de cambios. El backend lo
  copia a su registro al arrancar (y con `python -m app.cli sync-legal-docs`); `historial.html` lo muestra.
- **Para publicar una versión nueva** de una página: cambia la fecha de «Versión» en su plantilla (en todos los
  lugares donde aparece), describe los cambios en el párrafo «Cambios principales…» de su sección Versiones, cambia
  `config.py` si es `terminos` o `privacidad`, pon la nueva `FECHA_DE_ENTRADA_EN_VIGOR` (al menos 30 días después
  del aviso si cambia derechos u obligaciones) y genera. La versión anterior queda publicada para siempre en
  `/app/legal/<página>-<versión>.html` con su misma huella.
- Cuando llega la fecha de entrada en vigor, esa versión queda **fija**: si después cambia su texto (o un dato que
  aparece en ella) sin cambiar la versión, `render-legal.py` se niega a generar los documentos que se aceptan y
  avisa en los demás. La salida es publicar una versión nueva.
- `app/legal/plantillas/security.txt` tiene la fecha `Expires`: renuévala antes de que venza (máximo un año
  adelante). `--check` falla 30 días antes.

## Qué revisa `--check`

| Revisión | `--check` (desplegar) | `--check-generated` (CI) |
|----------|:---------------------:|:------------------------:|
| Datos vacíos y notas `VERIFICAR` pendientes | falla | no |
| Archivos generados al día con plantillas y datos | falla | falla |
| Toda clave usada está documentada en `datos-legales.example.json` (y ninguna sobra) | falla | falla |
| Páginas bien formadas, enlaces y anclas que existen, sin notas `PLANTILLA`, scripts `js/*.js` presentes | falla | falla |
| Versiones: cada plantilla con su `Versión:`, sin fechas contradictorias, `config.py` igual a terminos/privacidad | falla | falla |
| Versiones anteriores archivadas con su misma huella; texto de una versión vigente sin cambios | falla | falla |
| `security.txt` vencido (o a menos de 30 días) | falla | solo si ya venció |
| Comisiones, topes, plazos y dominio iguales al `.env` del servidor | falla | no |

En CI, el trabajo «Textos legales completos» corre `--check` sin bloquear en las ramas y **bloquea en las
etiquetas de versión** (`v*`): no etiquetes una versión para producción con datos pendientes.

## Lista de claves

<!-- claves:inicio -->
_Generado por `python3 scripts/render-legal.py` desde `app/legal/datos-legales.example.json`: 286 claves. No edites esta lista a mano._

### Identidad y empresa

- **`RAZON_SOCIAL`** — Denominación o razón social exacta del operador de GuauWoow, con su tipo societario (o nombre completo de la persona física con actividad empresarial), tal como aparece en la constancia de situación fiscal del SAT. Escríbela igual en todas partes. Ejemplo: `GuauWoow México, S.A.S.`. _En: 56 páginas._
- **`FORMA_JURIDICA`** — Tipo de persona y forma jurídica del operador. Ejemplo: `persona moral, Sociedad por Acciones Simplificada (S.A.S.)`. _En: quienes-somos._
- **`RFC`** — Registro Federal de Contribuyentes del operador (12 caracteres persona moral, 13 persona física). Ejemplo: `PFM2601011A2`. _En: 55 páginas._
- **`REGIMEN_FISCAL`** — Régimen fiscal del operador como aparece en su constancia de situación fiscal. Ejemplo: `Régimen General de Ley Personas Morales`. _En: quienes-somos._
- **`FOLIO_MERCANTIL_ELECTRONICO`** — Folio mercantil electrónico del Registro Público de Comercio; si no aplica, escribe «No aplica». Ejemplo: `N-2026012345`. _En: quienes-somos._
- **`REPRESENTANTE_LEGAL`** — Nombre completo de la persona representante legal del operador. Ejemplo: `María Pérez López`. _En: quienes-somos._
- **`DOMICILIO_FISCAL`** — Domicilio físico en México donde se reciben reclamaciones, notificaciones de PROFECO, oficios de autoridades y solicitudes ARCO (no un apartado postal ni una oficina virtual sin confirmar): calle, número, colonia, alcaldía o municipio, código postal y entidad. Ejemplo: `Av. Insurgentes Sur 1234, piso 5, Col. Del Valle, Benito Juárez, 03100, Ciudad de México`. _En: 56 páginas._
- **`DOMICILIO_ANTE_EL_SAT_SI_ES_DISTINTO`** — Domicilio fiscal registrado ante el SAT, solo si es distinto de DOMICILIO_FISCAL; si es el mismo, escribe «Es el mismo». Ejemplo: `Es el mismo`. _En: quienes-somos._
- **`DEPARTAMENTO_DE_DATOS_PERSONALES`** — Persona o área designada para atender solicitudes de datos personales (LFPDPPP). Ejemplo: `Departamento de Datos Personales, a cargo de María Pérez López`. _En: acuerdo-datos-refugios, centro-legal, derechos-arco, privacidad, privacidad-refugios, quienes-somos, seguridad._
- **`REGISTRO_DE_MARCA`** — Estado de la marca GuauWoow ante el IMPI: solicitud en trámite con número de expediente o registro otorgado con su número. Mientras no esté registrada, las páginas no usan ® ni «M.R.». Ejemplo: `solicitud en trámite, expediente 3123456`. _En: creditos, derechos-de-autor, quienes-somos, terminos, terminos-tienda._
- **`DOMINIO`** — Dominio público del sitio, sin https:// ni / final. Debe coincidir con DOMAIN del .env (--check lo compara). También sustituye %%SITE_URL%% (https://DOMINIO) en las páginas legales. Ejemplo: `guauwoow.com`. _En: 57 páginas._
- **`OTROS_DOMINIOS_OFICIALES`** — Otros dominios del operador (redirecciones, .com.mx, etc.) o «Ninguno». Ejemplo: `patitasfind.com.mx (redirige a guauwoow.com)`. _En: canales-oficiales, quienes-somos._

### Contacto y canales

- **`CORREO_DE_CONTACTO`** — Correo de atención a clientes, aclaraciones, quejas, revocación de compras y reportes (LFPC, art. 76 Bis). Conviene que sea el mismo que SUPPORT_EMAIL del .env (--check avisa si no). Ejemplo: `hola@guauwoow.com`. _En: 55 páginas._
- **`CORREO_DE_PRIVACIDAD`** — Correo del Departamento de Datos Personales para solicitudes ARCO, revocación del consentimiento y el listado de exclusión. Ejemplo: `privacidad@guauwoow.com`. _En: 20 páginas._
- **`CORREO_DE_FACTURACION`** — Correo donde se piden facturas (CFDI) de las comisiones de GuauWoow y dudas de facturación. Puede ser el mismo de contacto. Ejemplo: `facturacion@guauwoow.com`. _En: canales-oficiales, facturacion, quienes-somos, terminos, terminos-refugios, terminos-tienda, terminos-vendedores._
- **`CORREO_DE_SEGURIDAD`** — Buzón para reportar vulnerabilidades e incidentes de seguridad; también va en «Contact» de /.well-known/security.txt. Ejemplo: `seguridad@guauwoow.com`. _En: canales-oficiales, estado-del-servicio, quienes-somos, security.txt, seguridad._
- **`CORREO_LEGAL`** — Correo para avisos legales y requerimientos, propiedad intelectual (avisos y contra-avisos de derechos de autor), uso de la marca y créditos de autoría. Ejemplo: `legal@guauwoow.com`. _En: autoridades, creditos, derechos-de-autor, moderacion, quienes-somos, terminos-refugios._
- **`CORREO_DE_ACCESIBILIDAD`** — Correo para pedir ajustes razonables y reportar barreras de accesibilidad. Ejemplo: `accesibilidad@guauwoow.com`. _En: accesibilidad, quienes-somos._
- **`CORREO_ALTERNO`** — Correo de respaldo por si falla el principal (lo usan autoridades y titulares de derechos). Debe ser de otro proveedor o buzón. Ejemplo: `contacto.alterno@guauwoow.com`. _En: autoridades, derechos-de-autor, quienes-somos._
- **`CORREOS_REMITENTES_OFICIALES`** — Direcciones desde las que salen los correos automáticos (SMTP_FROM) y, si los hay, los promocionales. Sirve para reconocer correos falsos. Ejemplo: `avisos@guauwoow.com y novedades@guauwoow.com`. _En: canales-oficiales._
- **`TELEFONO`** — Teléfono de atención con lada, como lo marcaría una persona en México. Ejemplo: `55 1234 5678`. _En: 55 páginas._
- **`HORARIO_DE_ATENCION`** — Días y horario de atención telefónica y presencial (zona horaria del centro de México). Ejemplo: `lunes a viernes de 9:00 a 18:00 h (hora del centro de México)`. _En: 19 páginas._
- **`NUMERO_DE_WHATSAPP`** — Número oficial del bot de WhatsApp (el de WHATSAPP_PHONE_NUMBER_ID), con lada internacional. Ejemplo: `+52 55 9876 5432`. _En: 10 páginas._
- **`NOMBRE_VISIBLE_EN_WHATSAPP`** — Nombre visible del perfil de WhatsApp Business del número oficial, como lo aprobó Meta; debe coincidir con el texto del permiso de avisos por WhatsApp. Ejemplo: `GuauWoow`. _En: canales-oficiales, privacidad-whatsapp._
- **`REMITENTE_DE_SMS`** — Número o código corto desde el que llega el código de verificación por SMS. Ejemplo: `el remitente «GuauWoow» o el número +52 55 0000 0000`. _En: canales-oficiales._
- **`CUENTAS_OFICIALES_EN_REDES_SOCIALES`** — Perfiles oficiales en redes sociales con su usuario; si no hay, escribe «Por ahora no tenemos cuentas oficiales en redes sociales». Ejemplo: `Facebook: facebook.com/patitasfind · Instagram: @patitasfind`. _En: canales-oficiales, quienes-somos._
- **`CONTACTO_24_7_PARA_AUTORIDADES`** — Teléfono y correo dedicados, atendidos las 24 horas todos los días, solo para requerimientos de autoridades y emergencias (Decreto NNA, art. 5). Ejemplo: `55 1234 0000 y autoridades@guauwoow.com`. _En: autoridades, quienes-somos._
- **`RESPONSABLE_DE_RECLAMACIONES_DE_CONTENIDO`** — Nombre o área responsable de atender reclamaciones de contenido (honor, imagen, reseñas, derechos de autor). Ejemplo: `Equipo de Moderación, a cargo de Juan López`. _En: moderacion._

### Proveedores y países

- **`PROVEEDOR_DE_HOSTING`** — Empresa donde corren el servidor y la base de datos (encargado del tratamiento). Ejemplo: `Hetzner Online GmbH`. _En: privacidad, privacidad-whatsapp, proveedores, seguridad._
- **`PAIS_O_REGION_DEL_HOSTING`** — País o región del centro de datos contratado. Ejemplo: `Estados Unidos (Ashburn, Virginia)`. _En: privacidad, privacidad-whatsapp, proveedores, seguridad._
- **`CERTIFICACIONES_DEL_HOSTING`** — Certificaciones de seguridad del proveedor de hosting, según su sitio oficial; si no las publica, escribe «No publicadas». Ejemplo: `ISO/IEC 27001`. _En: proveedores._
- **`PROVEEDOR_DE_CORREO`** — Proveedor SMTP que envía los correos (SMTP_HOST del .env). Ejemplo: `Amazon Web Services (Amazon SES)`. _En: privacidad, proveedores._
- **`PAIS_DEL_PROVEEDOR_DE_CORREO`** — País o región donde el proveedor de correo procesa los mensajes. Ejemplo: `Estados Unidos`. _En: privacidad, proveedores._
- **`PROVEEDOR_DE_SMS`** — Proveedor que envía los códigos de verificación por SMS (SMS_PROVIDER del .env: SMS Masivos o Twilio). Ejemplo: `Twilio Inc.`. _En: privacidad, privacidad-simplificado, proveedores._
- **`PAIS_DEL_PROVEEDOR_DE_SMS`** — País donde el proveedor de SMS procesa los números y los códigos. Ejemplo: `Estados Unidos`. _En: privacidad, privacidad-simplificado, proveedores._
- **`PROVEEDOR_DE_RESPALDOS_EXTERNOS`** — Servicio donde se guarda la copia externa cifrada de los respaldos y la bóveda de evidencia (BACKUP_S3_* del .env). Ejemplo: `Cloudflare, Inc. (Cloudflare R2)`. _En: privacidad, proveedores, seguridad._
- **`PAIS_O_REGION_DE_LOS_RESPALDOS_EXTERNOS`** — País o jurisdicción del bucket externo de respaldos y evidencia. Ejemplo: `Estados Unidos (región automática de Cloudflare R2)`. _En: privacidad, proveedores, seguridad._
- **`REGION_DE_SENTRY`** — Región de datos de la organización de Sentry (no se puede cambiar después de crearla). Ejemplo: `Estados Unidos`. _En: cookies, privacidad, proveedores, seguridad._
- **`REGION_DE_POSTHOG`** — Región de datos del proyecto de PostHog (POSTHOG_HOST). Ejemplo: `Estados Unidos`. _En: cookies, privacidad, proveedores, seguridad._
- **`PAC_DE_CFDI`** — Proveedor autorizado de certificación (PAC) que timbra las facturas de GuauWoow (PAC_PROVIDER del .env); solo se usa si la comisión es mayor que 0 %. Ejemplo: `Facturama`. _En: facturacion, privacidad, privacidad-refugios, proveedores._
- **`PAIS_DEL_PROVEEDOR_DE_IMPORTACION`** — País o entidad contratante de Apify, el proveedor que haría la importación de grupos públicos de Facebook (apagada en producción). Ejemplo: `República Checa (Apify Technologies s.r.o.)`. _En: contenido-importado, privacidad._

### Plazos y políticas

- **`PLAZO_DE_PRIMERA_RESPUESTA`** — Plazo de la primera respuesta a dudas, aclaraciones y quejas. Ejemplo: `2 días hábiles`. _En: accesibilidad, atencion-y-quejas, compromisos, quienes-somos, terminos, terminos-tienda._
- **`PLAZO_DE_RESPUESTA_A_QUEJAS`** — Plazo máximo para responder y resolver aclaraciones y quejas (Términos, Condiciones de compra, Atención y quejas, Compromisos). Ejemplo: `10 días hábiles`. _En: atencion-y-quejas, compromisos, quienes-somos, terminos, terminos-tienda._
- **`PLAZO_PARA_APELAR`** — Tiempo que tiene una persona para apelar una sanción de moderación. Ejemplo: `15 días naturales`. _En: moderacion, terminos._
- **`PLAZO_PARA_RESOLVER_APELACIONES`** — Plazo máximo para que una persona distinta de quien decidió resuelva una apelación. Ejemplo: `10 días hábiles`. _En: moderacion, terminos._
- **`PLAZO_OBJETIVO_DE_REVISION_DE_REPORTES`** — Plazo objetivo general para revisar reportes de contenido y reseñas retenidas. Ejemplo: `72 horas hábiles`. _En: comunidad, moderacion, proteccion-nna, resenas._
- **`PLAZO_OBJETIVO_DE_REPORTES_URGENTES`** — Plazo objetivo para reportes urgentes: venta o cobro por animales, crueldad, zoofilia o peleas, y contenido íntimo sin consentimiento. Ejemplo: `24 horas`. _En: adopcion-responsable, autoridades, cero-venta, comunidad, moderacion, proteccion-nna._
- **`PLAZO_DE_REVISION_DE_CONTENIDO_RETENIDO`** — Plazo objetivo para que una persona revise las publicaciones de adopción y las reseñas de clínicas que el filtro automático retuvo. Ejemplo: `24 horas hábiles`. _En: adopcion-responsable, cero-venta, comunidad, moderacion, resenas._
- **`PLAZO_DE_RESPUESTA_A_REPORTES_SOBRE_MENORES`** — Plazo para responder a madres, padres o tutores que reportan la cuenta o la foto de una persona menor de edad. Ejemplo: `72 horas`. _En: proteccion-nna._
- **`PLAZO_DE_PRIMERA_RESPUESTA_A_AUTORIDADES`** — Tiempo objetivo de primera respuesta a un requerimiento de autoridad. Ejemplo: `1 hora si hay menores o riesgo para la vida y 24 horas en los demás casos`. _En: autoridades._
- **`PLAZO_OBJETIVO_DE_RETIRO_POR_DERECHOS_DE_AUTOR`** — Plazo objetivo para retirar contenido después de un aviso de derechos de autor procedente. Ejemplo: `menos de 24 horas hábiles`. _En: derechos-de-autor._
- **`PLAZO_PARA_ACLARAR_UNA_CEDULA`** — Tiempo que tiene una Clínica para aclarar una cédula reportada como falsa o prestada antes de perder la verificación. Ejemplo: `5 días hábiles`. _En: verificacion, veterinarias._
- **`PLAZO_DE_RESGUARDO_DE_PERROS_ENCONTRADOS`** — Espera mínima antes de ofrecer en adopción a un perro encontrado. Debe coincidir con FOUND_DOG_HOLD_DAYS del servidor (30 por defecto); --check lo compara. Ejemplo: `30 días naturales`. _En: canales-oficiales, glosario-y-faq, perdidos-y-encontrados, terminos, terminos-refugios._
- **`PLAZO_DE_BORRADO_PARA_ALIADOS`** — Plazo en que Refugios, Casas de paso y vendedores deben borrar los datos de adoptantes y compradores al cerrar un proceso. Ejemplo: `30 días naturales`. _En: acuerdo-datos-refugios, terminos-casas-de-paso, terminos-refugios, terminos-vendedores._
- **`PLAZO_LOCAL_DE_RESPALDOS`** — Cuánto se conserva la copia local cifrada de los respaldos en el servidor (BACKUP_RETENTION_DAYS de backup.sh; 14 por defecto); --check lo compara. Ejemplo: `14 días naturales`. _En: conservacion, privacidad, seguridad._
- **`PLAZO_DE_CONSERVACION_DE_RESPALDOS_EXTERNOS`** — Cuánto se conserva la copia externa cifrada (BACKUP_OFFSITE_RETENTION_DAYS de backup-offsite.sh; 30 por defecto); --check lo compara. Ejemplo: `30 días naturales`. _En: conservacion, privacidad, seguridad._
- **`PLAZO_DE_CONSERVACION_DE_REPORTES_DE_MODERACION`** — Cuánto se guardan los reportes de contenido resueltos y la bitácora de acciones de administradores (debe coincidir con la tabla de conservacion.html). Ejemplo: `24 meses`. _En: moderacion._
- **`PERIODICIDAD_DE_REVERIFICACION_DE_REFUGIOS`** — Cada cuánto se vuelve a verificar a los Refugios. Ejemplo: `cada año`. _En: terminos-refugios, verificacion._
- **`PERIODICIDAD_DE_LA_EVALUACION_DE_RIESGOS`** — Cada cuánto se repite la evaluación de riesgos para niñas, niños y adolescentes (Decreto NNA). Ejemplo: `cada seis meses`. _En: proteccion-nna._
- **`PERIODICIDAD_DEL_INFORME_DE_TRANSPARENCIA`** — Cada cuánto se publica un corte del informe de transparencia. Ejemplo: `semestral`. _En: informe-transparencia._

### Tienda y donativos

- **`COMISION_TIENDA`** — Comisión que GuauWoow cobra a los Refugios por cada venta de la tienda (porcentaje con el signo %). Debe coincidir con MERCADOPAGO_MARKETPLACE_FEE_PERCENT del servidor y ser 0 % mientras VERIFICAR_REGIMEN_PLATAFORMAS no sea true; --check lo compara. Ejemplo: `0 %`. _En: compromisos, glosario-y-faq, tarifas, terminos, terminos-refugios, terminos-tienda, terminos-vendedores, transparencia-fondos._
- **`COMISION_DONATIVOS`** — Comisión que GuauWoow descuenta de los donativos (porcentaje, o 0 % si no cobra). Debe coincidir con MERCADOPAGO_DONATION_FEE_PERCENT; --check lo compara. Ejemplo: `0 %`. _En: compromisos, donativos, glosario-y-faq, tarifas, terminos, terminos-refugios, transparencia-fondos._
- **`TARIFA_DE_MERCADO_PAGO`** — Tarifa estándar de Mercado Pago para cobros en línea (porcentaje más cuota fija, más IVA), tomada de tu cuenta o de mercadopago.com.mx. Ejemplo: `3.49 % + $4 MXN más IVA`. _En: donativos, tarifas, transparencia-fondos._
- **`FECHA_DE_ACTIVACION_DE_LA_COMISION`** — Fecha en que se activó una comisión mayor que 0 %, o «sin comisión» mientras siga en 0 %. Ejemplo: `sin comisión`. _En: transparencia-fondos._
- **`FECHA_DE_ADOPCION_DEL_MODELO_DE_COBRO`** — Fecha desde la que todos los cobros (tienda y donativos) usan el cobro dividido (Split) de Mercado Pago directo a la cuenta del Refugio. Ejemplo: `2026-11-20`. _En: transparencia-fondos._
- **`VERSION_DE_LOS_TERMINOS_DE_MERCADO_PAGO_ACEPTADA`** — Fecha de la versión de los Términos y Condiciones de Mercado Pago que aceptó GuauWoow. Ejemplo: `2026-09-01`. _En: transparencia-fondos._
- **`AUTORIZACION_DE_MERCADO_PAGO_PARA_DONATIVOS`** — Número de caso y fecha de la respuesta escrita de Mercado Pago que autoriza recibir donativos por GuauWoow (sus términos los prohíben salvo excepción). Ejemplo: `caso 123456789, respuesta del 30 de octubre de 2026`. _En: donativos._
- **`TOPE_POR_DONATIVO`** — Monto máximo de un solo donativo. Debe coincidir con DONATION_MAX_MXN del servidor (50,000 por defecto); --check lo compara. Ejemplo: `$50,000 MXN`. _En: donativos, prevencion-lavado, terminos-refugios._
- **`TOPE_DIARIO_DE_DONATIVOS`** — Lo máximo que una misma cuenta puede donar en un día. Debe coincidir con DONATION_DAILY_MAX_MXN; --check lo compara. Ejemplo: `$50,000 MXN`. _En: donativos, prevencion-lavado, terminos-refugios._
- **`PAQUETERIA`** — Paquetería con la que se envían los pedidos (si cada Refugio elige la suya, escribe «La paquetería que elija cada Refugio vendedor»). Ejemplo: `La paquetería que elija cada Refugio vendedor`. _En: envios-devoluciones-garantias, privacidad, proveedores, terminos-tienda._
- **`ZONAS_DE_COBERTURA`** — Aclaración de las zonas de envío dentro de México (aparece entre paréntesis después de «República Mexicana»). Ejemplo: `excepto zonas extendidas de la paquetería`. _En: terminos-tienda._
- **`COSTO_DE_ENVIO`** — Política de costo de envío de la Tienda Solidaria (cada producto muestra su costo antes de pagar). Ejemplo: `cada Refugio fija el costo de envío de sus productos`. _En: terminos-tienda._
- **`PLAZO_DE_ENTREGA`** — Plazo estimado de entrega desde la confirmación del pago. Ejemplo: `3 a 10 días hábiles`. _En: envios-devoluciones-garantias, terminos-tienda._
- **`PLAZO_DE_REEMBOLSO`** — Plazo máximo para reembolsar tras una revocación o cancelación. Ejemplo: `10 días hábiles`. _En: envios-devoluciones-garantias, terminos, terminos-tienda._
- **`ORDEN_DE_LOS_PRODUCTOS_EN_LA_TIENDA`** — Criterio real con el que la tienda ordena los productos (pregúntalo al equipo técnico). Ejemplo: `más recientes primero`. _En: transparencia-fondos._
- **`FECHA_DE_LA_OPINION_DE_CUMPLIMIENTO_DEL_SAT`** — Fecha de la última opinión positiva de cumplimiento de obligaciones fiscales del SAT (CFF, art. 32-D), o «no publicada». Ejemplo: `1 de octubre de 2026`. _En: transparencia-fondos._

### Decisiones de negocio (fechas, estados y compromisos)

- **`FECHA_DE_ENTRADA_EN_VIGOR`** — Fecha en que entra en vigor esta versión de los documentos, en formato AAAA-MM-DD. Se imprime en «Vigente desde» de cada página y se guarda en versiones.json; cuando llega, queda fija para esa versión. Para cambios importantes a personas que ya tienen cuenta, deja al menos 30 días naturales desde el aviso. Ejemplo: `2026-11-20`. _En: 55 páginas._
- **`FECHA_DE_ULTIMA_REVISION_LEGAL`** — Fecha de la última revisión de los documentos por tu abogado (y, en las páginas fiscales y de vendedores, por tu contador). Ejemplo: `10 de noviembre de 2026`. _En: 11 páginas._
- **`FECHA_DE_VALIDACION_DE_PLAZOS`** — Fecha en que tu abogado y tu contador validaron el calendario de conservación de datos. Ejemplo: `10 de noviembre de 2026`. _En: conservacion._
- **`FECHA_DE_LA_ULTIMA_EVALUACION_DE_ACCESIBILIDAD`** — Fecha de la última evaluación de accesibilidad del sitio. Ejemplo: `5 de noviembre de 2026`. _En: accesibilidad._
- **`METODO_DE_EVALUACION_DE_ACCESIBILIDAD`** — Herramientas y pruebas usadas en esa evaluación. Ejemplo: `revisión automática con axe y Lighthouse y pruebas manuales con VoiceOver y TalkBack`. _En: accesibilidad._
- **`FECHA_DE_VERIFICACION_DEL_DIRECTORIO_DE_AUTORIDADES`** — Fecha en que se comprobaron en sitios oficiales los datos del directorio para denunciar maltrato. Ejemplo: `5 de noviembre de 2026`. _En: denunciar-maltrato._
- **`FECHA_DEL_PRIMER_CORTE_DEL_INFORME_DE_TRANSPARENCIA`** — Fecha del primer corte del informe de transparencia. Ejemplo: `30 de junio de 2027`. _En: informe-transparencia._
- **`AUTORIDAD_RECEPTORA_DEL_INFORME_NNA`** — Autoridad a la que se entrega el informe del transitorio Cuarto del Decreto NNA. Ejemplo: `Agencia de Transformación Digital y Telecomunicaciones (ATDT), con copia a la Consejería Jurídica del Ejecutivo Federal`. _En: informe-transparencia, proteccion-nna._
- **`FECHA_Y_FOLIO_DEL_ENVIO_DEL_INFORME_NNA`** — Fecha y folio o acuse de entrega del informe del Decreto NNA. Mientras no lo entregues, escribe que está pendiente y su fecha límite. Ejemplo: `pendiente; lo entregaremos a más tardar el 12 de noviembre de 2026`. _En: informe-transparencia._
- **`ESTADO_DEL_DICTAMEN_NMX`** — Si hay dictamen de verificación de la NMX-COE-001-SCFI-2018 (número y vigencia) o «no contamos con dictamen todavía». Ejemplo: `no contamos con dictamen todavía`. _En: centro-legal, compromisos, marco-legal, quienes-somos._
- **`ESTADO_DE_ADHESION_AL_CODIGO_DE_ETICA`** — Estado de adhesión al Código de Ética de comercio electrónico de PROFECO, con la fecha y el enlace al padrón si te adheriste. Ejemplo: `no estamos adheridos`. _En: centro-legal, compromisos, marco-legal, quienes-somos._
- **`ESTADO_DE_AUDITORIA_EXTERNA`** — Frase sobre auditorías externas de privacidad o seguridad (con quién y cuándo). Ejemplo: `Por ahora no contamos con una auditoría externa de privacidad`. _En: compromisos._
- **`COLABORADORES_CON_MENCION_DE_AUTORIA`** — Nombres de quienes pidieron crédito como autores (LFDA, art. 83) o «Por ahora nadie lo ha solicitado». Ejemplo: `Por ahora nadie lo ha solicitado`. _En: creditos._
- **`ESTADOS_CON_IMPORTACION`** — Estados (y grupos públicos) de los que se importarían publicaciones cuando se active la importación de Facebook; mientras siga apagada, escribe «ninguno por ahora (la importación está apagada)». Ejemplo: `ninguno por ahora (la importación está apagada)`. _En: contenido-importado._
- **`CIUDAD_DE_JURISDICCION`** — Ciudad cuyos tribunales resuelven controversias con Refugios y Clínicas (convenios entre aliados; a los consumidores no se les impone). Ejemplo: `Ciudad de México`. _En: terminos-clinicas, terminos-refugios._
- **`TOPE_DE_RESPONSABILIDAD_CON_ALIADOS`** — Monto máximo en pesos de responsabilidad entre GuauWoow y cada Refugio, según decidas con tu abogado. Ejemplo: `$50,000 MXN`. _En: terminos-refugios._

### Notas VERIFICAR para tu abogado

- **`VERIFICAR_ACEPTACION_SEPARADA`** · revisa: abogado · en: terminos
  - Qué confirmar: la casilla de registro reúne la aceptación de los Términos y el acuse del Aviso de Privacidad; confirma con tu abogado si basta o si el Aviso debe tener su propia casilla
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_ADOPCION_NO_CONSUMO`** · revisa: abogado · en: terminos
  - Qué confirmar: confirma con tu abogado si la LFPC alcanza a las adopciones gratuitas que entregan los refugios; la investigación tiene confianza baja en este punto
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_APIFY`** · revisa: abogado · en: contenido-importado, privacidad, proveedores
  - Qué confirmar: contrato, entidad, país y retención de datos de Apify, y riesgo frente a los términos de Meta / entidad con la que se contrata Apify, país de procesamiento y retención de los datos; condición de no activar sin las opiniones legales
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_AUTODECLARACION_MALTRATO`** · revisa: abogado · en: privacidad
  - Qué confirmar: si se agregará la autodeclaración del adoptante sobre sanciones por maltrato y con qué base
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_AVISO_SUPRESION`** · revisa: abogado · en: conservacion, derechos-arco
  - Qué confirmar: que exista el procedimiento para avisar al titular y a los terceros receptores cuando se suprimen datos tras el bloqueo
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_CALENDARIO_CONSERVACION`** · revisa: abogado y contador · en: conservacion
  - Qué confirmar: tu abogado y tu contador deben validar este calendario, en especial los plazos marcados como propuesta y los 10 años que dependen de que el operador sea comerciante; si el operador es persona física no comerciante, el calendario cambia
  - Valor sugerido: `true` cuando tu abogado y tu contador aprueben el texto tal cual. Si piden otra redacción, escribe aquí la frase que te den.
- **`VERIFICAR_CASAS_DE_PASO_UMBRAL`** · revisa: abogado · en: terminos-casas-de-paso
  - Qué confirmar: confirmar con el abogado o con la AGATAN a partir de cuántos animales una casa de paso necesita autorización en la Ciudad de México
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_CESIONES`** · revisa: abogado · en: creditos
  - Qué confirmar: confirma que tienes por escrito la cesión de derechos de cada persona que hizo código, diseño, fotos o textos (incluido el fundador) antes de afirmar la titularidad
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_CLINICAS_LFSA`** · revisa: abogado · en: terminos-clinicas
  - Qué confirmar: el abogado sanitario confirma el alcance del aviso de inicio de funcionamiento y del médico veterinario responsable autorizado (LFSA arts. 105 y 110) para clínicas de pequeñas especies que solo dan consulta, las autorizaciones locales (LPBA CDMX art. 43; Ley Edomex art. 49) y que el art. 83 de la Ley General de Salud aplica a veterinarios
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_COMPATIBILIDAD`** · revisa: abogado · en: ia-y-algoritmos, privacidad
  - Qué confirmar: cómo se atiende la oposición al puntaje (postulación sin puntaje) y si aplica el art. 26, fr. II, de la LFPDPPP
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_CONDICION_RESOLUTORIA`** · revisa: abogado · en: modelo-carta-responsiva
  - Qué confirmar: con un abogado civilista, si esta resolución por incumplimiento de las cargas es exigible en cada estado, dado que las donaciones solo se revocan en los casos de ley (Código Civil Federal, art. 2338)
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_CONSERVACION`** · revisa: abogado y contador · en: privacidad, privacidad-refugios
  - Qué confirmar: que este resumen coincide con la configuración de conservación del sistema y que los plazos de 10 años aplican porque el operador es comerciante (CCom, arts. 38 y 49); si no, ajústalos con el abogado y el contador
  - Valor sugerido: `true` cuando tu abogado y tu contador aprueben el texto tal cual. Si piden otra redacción, escribe aquí la frase que te den.
- **`VERIFICAR_CONSERVACION_10_ANIOS`** · revisa: abogado · en: terminos, terminos-tienda
  - Qué confirmar: el plazo de 10 años aplica si el operador es comerciante (persona moral mercantil); si opera una persona física no comerciante, tu abogado debe revisar el calendario
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_CONSERVACION_ACEPTACIONES`** · revisa: abogado · en: historial
  - Qué confirmar: confirma con tu abogado el plazo de 10 años (depende de que el operador sea comerciante) y que la seudonimización al borrar la cuenta ya ocurre en el sistema
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_CONTACTO_ADOPCION`** · revisa: abogado · en: acuerdo-datos-refugios, privacidad
  - Qué confirmar: base para compartir el contacto al aprobar una adopción: casilla de consentimiento (art. 35) o contrato en interés del titular (art. 36, fr. IV y VII), o limitar el contacto al chat
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_CSAM`** · revisa: abogado · en: autoridades, proteccion-nna
  - Qué confirmar: obtén la postura penal escrita de tu abogado sobre la conservación y entrega de este material antes de operar este paso (CPF arts. 202 y 202 Bis)
  - Valor sugerido: `true` solo con la postura penal escrita de tu abogado sobre conservar y entregar ese material.
- **`VERIFICAR_CUENTA_DE_MENOR`** · revisa: abogado · en: proteccion-nna
  - Qué confirmar: confirma el procedimiento cuando se confirma que una cuenta es de una persona menor de edad (suspensión, cierre, reembolso de compras en curso y borrado salvo evidencia)
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_DECRETO_NNA`** · revisa: abogado · en: proteccion-nna
  - Qué confirmar: con tu abogado la verificación de edad por capas, la lectura «por diseño» de las fracciones III, VI y VIII del art. 4 y el canal de entrega del informe
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_DENUNCIA_POR_PATITASFIND`** · revisa: abogado · en: comunidad, denunciar-maltrato, moderacion
  - Qué confirmar: con tu abogado penalista en qué casos GuauWoow presenta la denuncia por su cuenta (propuesta: zoofilia, peleas, crueldad grave y venta reincidente) y quién la firma
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_DEPOSITO_CASAS_DE_PASO`** · revisa: abogado · en: terminos-casas-de-paso
  - Qué confirmar: el abogado confirma el encuadre del hogar temporal como depósito (Código Civil Federal, arts. 2516 a 2522), la cláusula de gratuidad (art. 2517) y la responsabilidad por daños a terceros durante la guarda (arts. 1910 y 1929), y revisa el código civil de los estados de lanzamiento
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_DESGLOSE_DONATIVO`** · revisa: abogado · en: donativos
  - Qué confirmar: la pantalla de donativo aún no muestra la comisión estimada de Mercado Pago, la de GuauWoow ni el neto para el Refugio. Decide con tu abogado si se agregan (LFPC, art. 7 Bis). Cuando la pantalla los muestre, pon como valor «En esa pantalla también ves las comisiones estimadas y cuánto recibirá el Refugio.»; si no se agregarán, pon true y la página remite a la sección 4
  - Valor sugerido: Cuando se cumpla, escribe exactamente «En esa pantalla también ves las comisiones estimadas y cuánto recibirá el Refugio.»; mientras no, `true` (no se publica nada en su lugar).
- **`VERIFICAR_DONACION_FORMA`** · revisa: abogado · en: terminos-refugios
  - Qué confirmar: el abogado confirma que la aceptación general y anticipada y la constancia electrónica de cada donativo bastan como forma de la donación (Código Civil Federal, arts. 2340 a 2344) en los estados de lanzamiento
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_FIRMA_CONVENIOS`** · revisa: abogado · en: historial, terminos-refugios, terminos-vendedores
  - Qué confirmar: decide si los convenios con Refugios se firmarán con e.firma o con constancia NOM-151 y, en su caso, descríbelo aquí; si no, borra esta nota / confirmar el método de firma del Convenio: casilla en la app con nombre y cargo de quien representa al Refugio y, si se contrata, firma electrónica con constancia NOM-151-SCFI-2016 o e.firma del SAT
  - Valor sugerido: `true` si basta la casilla en la app con nombre y cargo; si contratas firma electrónica: «Además, el Convenio se firma con e.firma del SAT (o con constancia NOM-151).»
- **`VERIFICAR_FUENTE_INDIRECTA`** · revisa: abogado · en: contenido-importado, privacidad
  - Qué confirmar: vía elegida por el abogado para la importación (aviso directo al autor, medida compensatoria autorizada por la SABG o no operar) y su estado; publica aquí el estado de la autorización o de la vía elegida / vía elegida por el abogado para la importación (aviso directo al autor, medida compensatoria autorizada por la SABG o no operar) y su estado
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_GOOGLE_MAPS`** · revisa: abogado · en: terminos-clinicas, veterinarias
  - Qué confirmar: el abogado de tecnología opina sobre el ejemplo prohibido 3.2.3(d)(iii) de los términos de Google Maps Platform aplicado al directorio y la conveniencia de pedir revisión a Google / con tu abogado de tecnología los términos de Google Maps Platform aplicados a este directorio
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_HOMOLOGACION`** · revisa: abogado · en: productos-prohibidos
  - Qué confirmar: confirma si los localizadores u otros equipos con radio requieren homologación de telecomunicaciones antes de venderse
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_IA_FOTOS_BOT`** · revisa: abogado · en: contenido-importado, privacidad-whatsapp
  - Qué confirmar: con Meta o un proveedor de soluciones de WhatsApp, que enviar a un proveedor de IA las fotos recibidas por el bot es compatible con los términos de WhatsApp Business (confianza baja)
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_IMPORTACION`** · revisa: abogado · en: terminos
  - Qué confirmar: la importación de grupos de Facebook está apagada en producción; deja este párrafo en condicional hasta que tu abogado la apruebe y actívala solo entonces
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_INE_SENSIBLE`** · revisa: abogado · en: privacidad, privacidad-refugios
  - Qué confirmar: si la imagen de la identificación debe tratarse como dato sensible y si el formulario de verificación recaba consentimiento expreso para ella
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_INFORME_NNA`** · revisa: abogado · en: historial
  - Qué confirmar: el Decreto no dice a qué autoridad ni por qué medio se entrega; confirma el canal con la ATDT y la CJEF y, al entregar el informe, registra aquí la fecha, la autoridad que lo recibió, el folio del acuse y la huella SHA-256 del PDF
  - Valor sugerido: Al entregar: «Entregado el 10-11-2026 a la ATDT, con copia a la CJEF; acuse con folio …; SHA-256 del PDF: …». Antes, `true` solo si tu abogado confirmó el canal de entrega.
- **`VERIFICAR_INFORME_NNA_ENVIADO`** · revisa: abogado · en: proteccion-nna
  - Qué confirmar: al entregar el informe, sustituye esta nota por la fecha de entrega y el folio o acuse; confirma con tu abogado la autoridad receptora y el cómputo del plazo (12 o 13 de noviembre de 2026)
  - Valor sugerido: Al entregar el informe, la frase real, p. ej. «Lo entregamos el 10 de noviembre de 2026 a la ATDT; acuse con folio ATDT-2026-0000.»
- **`VERIFICAR_JURISDICCION`** · revisa: abogado · en: terminos, terminos-tienda
  - Qué confirmar: tu abogado debe confirmar esta cláusula de jurisdicción (LFPC arts. 85 y 90; Código de Comercio art. 1093)
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_JURISDICCION_ALIADOS`** · revisa: abogado · en: terminos-clinicas, terminos-refugios
  - Qué confirmar: el abogado confirma la mediación previa (Ley General de Mecanismos Alternativos de Solución de Controversias), la conveniencia de un arbitraje y la ciudad de jurisdicción para los convenios con refugios, casas de paso, vendedores y clínicas
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_KYC_REFUGIOS`** · revisa: abogado y contador · en: terminos-refugios, terminos-vendedores
  - Qué confirmar: confirmar con el abogado y el contador qué documentos son obligatorios en cada perfil (beneficiario controlador, constancia fiscal, autorización local), que el formulario de registro los pide y el plazo de conservación del expediente fiscal
  - Valor sugerido: `true` cuando tu abogado y tu contador aprueben el texto tal cual. Si piden otra redacción, escribe aquí la frase que te den.
- **`VERIFICAR_LEYES_ESTATALES`** · revisa: abogado · en: modelo-carta-responsiva
  - Qué confirmar: con tu abogado, los artículos citados por estado; la ley de Nuevo León se tomó de una compilación no oficial y debe cotejarse con el Periódico Oficial
  - Valor sugerido: `true` cuando tu abogado coteje el texto con el periódico oficial del estado; si cambió algún artículo, pide la corrección en la plantilla.
- **`VERIFICAR_LEY_BAJA_CALIFORNIA`** · revisa: abogado · en: adopcion-responsable, denunciar-maltrato, marco-legal-bienestar-animal, perdidos-y-encontrados, verificacion
  - Qué confirmar: cotejar la ley de Baja California; se revisó la versión de 2024 y hay tres reformas de 2026 sin cotejar
  - Valor sugerido: `true` cuando tu abogado coteje el texto con el periódico oficial del estado; si cambió algún artículo, pide la corrección en la plantilla.
- **`VERIFICAR_LEY_GENERAL`** · revisa: abogado · en: marco-legal-bienestar-animal
  - Qué confirmar: antes de publicar, confirma en la Gaceta Parlamentaria, el SIL y el DOF si la comisión de Diputados ya dictaminó la minuta
  - Valor sugerido: `true` si la minuta sigue sin dictaminarse en la Cámara de Diputados; si ya se publicó en el DOF, hay que actualizar la página.
- **`VERIFICAR_LEY_JALISCO`** · revisa: abogado · en: adopcion-responsable, cero-venta, denunciar-maltrato, marco-legal-bienestar-animal, perdidos-y-encontrados, verificacion
  - Qué confirmar: cotejar la ley de Jalisco en el Periódico Oficial; solo se revisó la compilación de la CNDH con reformas hasta 2021
  - Valor sugerido: `true` cuando tu abogado coteje el texto con el periódico oficial del estado; si cambió algún artículo, pide la corrección en la plantilla.
- **`VERIFICAR_LEY_MICHOACAN`** · revisa: abogado · en: adopcion-responsable, denunciar-maltrato, marco-legal-bienestar-animal, perdidos-y-encontrados, verificacion
  - Qué confirmar: cotejar la ley de Michoacán; se revisó la versión de 2022 y hay reformas de 2024 y 2025 sin cotejar
  - Valor sugerido: `true` cuando tu abogado coteje el texto con el periódico oficial del estado; si cambió algún artículo, pide la corrección en la plantilla.
- **`VERIFICAR_LEY_NUEVO_LEON`** · revisa: abogado · en: adopcion-responsable, cero-venta, denunciar-maltrato, marco-legal-bienestar-animal, perdidos-y-encontrados, verificacion
  - Qué confirmar: cotejar la ley de Nuevo León en el Periódico Oficial; solo se revisó la compilación legismex de 2025
  - Valor sugerido: `true` cuando tu abogado coteje el texto con el periódico oficial del estado; si cambió algún artículo, pide la corrección en la plantilla.
- **`VERIFICAR_LEY_QUERETARO`** · revisa: abogado · en: denunciar-maltrato, marco-legal-bienestar-animal, perdidos-y-encontrados, verificacion
  - Qué confirmar: cotejar la ley de Querétaro en su periódico oficial; se revisó una compilación con reformas hasta 2021
  - Valor sugerido: `true` cuando tu abogado coteje el texto con el periódico oficial del estado; si cambió algún artículo, pide la corrección en la plantilla.
- **`VERIFICAR_LEY_SONORA`** · revisa: abogado · en: adopcion-responsable, cero-venta, denunciar-maltrato, marco-legal-bienestar-animal, perdidos-y-encontrados, verificacion
  - Qué confirmar: cotejar la ley de Sonora; se revisó un Boletín Oficial escaneado y la numeración de algunas fracciones puede variar
  - Valor sugerido: `true` cuando tu abogado coteje el texto con el periódico oficial del estado; si cambió algún artículo, pide la corrección en la plantilla.
- **`VERIFICAR_LEY_VERACRUZ`** · revisa: abogado · en: adopcion-responsable, denunciar-maltrato, marco-legal-bienestar-animal, perdidos-y-encontrados, verificacion
  - Qué confirmar: cotejar la ley de Veracruz; se revisó una compilación con reformas hasta 2020 y el Congreso aprobó una reforma el 15-10-2026 aún sin publicar
  - Valor sugerido: `true` cuando tu abogado coteje el texto con el periódico oficial del estado; si cambió algún artículo, pide la corrección en la plantilla.
- **`VERIFICAR_LIMITACION_RESPONSABILIDAD`** · revisa: abogado · en: terminos
  - Qué confirmar: tu abogado debe revisar que esta sección no excluya responsabilidad por incumplir la LFPDPPP ni derechos del consumidor
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_MASC`** · revisa: abogado · en: compromisos
  - Qué confirmar: revisa con tu abogado la Ley General de Mecanismos Alternativos de Solución de Controversias y si conviene ofrecer un mediador o centro concreto
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_MENSAJES`** · revisa: abogado · en: privacidad
  - Qué confirmar: si los mensajes de una cuenta eliminada se muestran como «Usuario eliminado» durante ese plazo o deben borrarse antes
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_MODELO_COMISION`** · revisa: abogado y contador · en: terminos, terminos-refugios, terminos-tienda, terminos-vendedores
  - Qué confirmar: el abogado y el contador confirman la calificación del modelo con Split (refugio que vende y cobra directamente; GuauWoow como intermediario tecnológico, Código de Comercio art. 285 o LIVA art. 18-B fr. II) y su efecto frente a PROFECO, en el CFDI y en las retenciones / con abogado y contador si GuauWoow responde frente al comprador junto con el Refugio vendedor o solo como intermediario (Código de Comercio arts. 284 y 285; LFPC art. 2), y refléjalo igual en estos Términos, en las Condiciones de compra y en los Términos para Refugios vendedores
  - Valor sugerido: `true` cuando tu abogado y tu contador aprueben el texto tal cual. Si piden otra redacción, escribe aquí la frase que te den.
- **`VERIFICAR_NATURALEZA_ADOPCION`** · revisa: abogado · en: adopcion-responsable, cero-venta, modelo-carta-responsiva, terminos-refugios
  - Qué confirmar: con tu abogado civilista la calificación de la adopción como donación con cargas y de cualquier pago ligado a la entrega como compraventa / con un abogado civilista, la calificación de la adopción con cargas como donación onerosa, el umbral de $5,000 y la forma escrita en los códigos civiles de los estados de lanzamiento / el abogado confirma la calificación de la adopción con cargas como donación onerosa y de cualquier pago ligado a la entrega como compraventa, y el alcance del art. 25 Bis de la CDMX y del art. 40 fr. V del Estado de México
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_NMX_REDES_SOCIALES`** · revisa: abogado · en: contenido-importado
  - Qué confirmar: la NMX-COE-001-SCFI-2018, numeral 8.1, inciso k), pide que el tratamiento de datos de redes sociales sea informado y consentido; la licitud de la importación está pendiente de dictamen
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_NORMAS_PRODUCTOS`** · revisa: abogado · en: terminos-vendedores
  - Qué confirmar: el abogado confirma qué normas aplican al catálogo real (alimentos y premios desregulados, NOM-050, NOM-004-SE-2021, NOM-024, NOM-012-SAG/ZOO-2020) y si los localizadores GPS requieren homologación
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_OBRAS_ASISTIDAS_IA`** · revisa: abogado · en: creditos
  - Qué confirmar: alcance de la protección de obras hechas con apoyo de IA; la investigación tiene confianza media
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_PEDIDOS_EN_CURSO`** · revisa: abogado · en: terminos
  - Qué confirmar: confirma esta regla para pedidos pagados pendientes de envío, o pide esperar la entrega antes de eliminar la cuenta
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_PERSONALIZADOS`** · revisa: abogado · en: envios-devoluciones-garantias, terminos-tienda
  - Qué confirmar: tu abogado debe confirmar si los productos personalizados pueden excluirse de la revocación; mientras tanto, no se excluyen / con tu abogado si los productos hechos a la medida pueden excluirse; hasta entonces se mantiene la revocación
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_PLAZO_ART_93`** · revisa: abogado · en: atencion-y-quejas, terminos-tienda
  - Qué confirmar: la ley no dice si los 15 días son naturales o hábiles; se usa la lectura más protectora
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_PLD`** · revisa: abogado · en: prevencion-lavado
  - Qué confirmar: estas conclusiones dependen de la forma jurídica del operador y del modelo de cobro; requieren la opinión escrita de un abogado especialista en prevención de lavado antes de publicarse
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_PLD_REFUGIOS`** · revisa: abogado · en: terminos-refugios
  - Qué confirmar: el abogado de prevención de lavado confirma el alcance de las medidas de las reglas 38 Bis a 38 Bis 2 para refugios A.C. y qué datos del donante debe entregar GuauWoow
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_PUERTO_SEGURO`** · revisa: abogado · en: seguridad
  - Qué confirmar: redacción final del compromiso de no denunciar a quien investiga de buena fe, sin prometer inmunidad penal
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_REGLA_ENCONTRADOS`** · revisa: abogado · en: perdidos-y-encontrados, terminos
  - Qué confirmar: con tu abogado la regla de espera para perros encontrados frente a los códigos civiles estatales y si habrá excepción con constancia para Refugios verificados y autoridades
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_REQUISITOS_CLINICAS`** · revisa: abogado · en: veterinarias
  - Qué confirmar: con tu abogado sanitario el alcance del aviso de funcionamiento, del responsable autorizado y de las autorizaciones locales para clínicas que solo dan consulta
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_RESENAS_RESPONSABILIDAD`** · revisa: abogado · en: terminos-clinicas
  - Qué confirmar: el abogado confirma el estándar de responsabilidad por reseñas (Código Civil Federal arts. 1910 y 1916), si GuauWoow es sujeto obligado de la Ley de réplica y si los plazos de moderación son suficientes; aprueba la insignia, el deslinde y el aviso de urgencias
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_RESPONSABILIDAD_ENVIOS`** · revisa: abogado · en: envios-devoluciones-garantias, terminos-vendedores
  - Qué confirmar: confirma con tu abogado quién responde ante la persona compradora por pérdida, daño o retraso en el envío (Refugio vendedor, GuauWoow o ambos) y ajusta la frase a lo que diga el contrato con los Refugios
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_ROL_REFUGIOS`** · revisa: abogado · en: acuerdo-datos-refugios, centro-legal, terminos-refugios
  - Qué confirmar: el abogado confirma que refugios, colectivos, rescatistas, casas de paso y refugios vendedores reciben los datos de adoptantes, donantes y compradores como responsables independientes (art. 35) y no como encargados / confirma con tu abogado si el Refugio recibe una transferencia como responsable propio o actúa como encargado de GuauWoow, y ajusta esta fila
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_RUAC`** · revisa: abogado · en: glosario-y-faq
  - Qué confirmar: obligación y gratuidad del RUAC (LPBA CDMX art. 4 BIS 1 fr. I); confianza media
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_SANCION_25_BIS`** · revisa: abogado · en: cero-venta, marco-legal-bienestar-animal
  - Qué confirmar: el art. 65 fr. IV de la ley de la CDMX cita fracciones V Bis y V Ter del art. 25 que no aparecen en el texto compilado; confírmalo con la Consejería Jurídica
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_SENASICA`** · revisa: abogado · en: productos-prohibidos
  - Qué confirmar: antes de habilitar alimentos y premios, valida con un especialista en regulación de SENASICA qué productos requieren registro o autorización
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_SUPLETORIEDAD`** · revisa: abogado · en: cookies, privacidad
  - Qué confirmar: postura sobre la aplicación supletoria del Reglamento de 2011 y los Lineamientos de 2013 (confianza media)
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_TOPE_ALIADOS`** · revisa: abogado · en: terminos-refugios
  - Qué confirmar: el abogado confirma si un tope de responsabilidad en este contrato de adhesión es válido frente a personas rescatistas y colectivos que son personas físicas y podrían considerarse consumidores (LFPC, arts. 85 y 90, fr. II), y fija el monto
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_TRANSPARENCIA_PERSONAS_FISICAS`** · revisa: abogado · en: acuerdo-datos-refugios, terminos-refugios
  - Qué confirmar: confirmar si aceptar el Convenio para Refugios y el Acuerdo de datos basta como consentimiento expreso de personas físicas para publicar sus montos en el informe de transparencia o si hace falta una casilla separada
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_VETERINARIOS`** · revisa: abogado · en: privacidad, terminos-clinicas
  - Qué confirmar: que el Registro Nacional de Profesionistas cuenta como fuente de acceso público (LFPDPPP, art. 2, fr. X) y si se enviará un aviso directo a la persona veterinaria cuando no es quien registra / el abogado de datos confirma que el Registro Nacional de Profesionistas es fuente de acceso público (LFPDPPP art. 2 fr. X) y que publicar nombre, cédula e institución con base en el art. 83 de la Ley General de Salud no requiere un consentimiento adicional
  - Valor sugerido: `true` si tu abogado aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).

### Notas VERIFICAR para tu contador

- **`VERIFICAR_CFDI_DONATIVO`** · revisa: contador · en: acuerdo-datos-refugios, donativos, terminos-refugios
  - Qué confirmar: describe cómo pide la persona donante su CFDI de donativo (casilla al donar con datos fiscales o solicitud directa al Refugio) y cómo se avisa al Refugio para que lo emita en 24 horas
  - Valor sugerido: `true` si tu contador aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_CONCILIACION`** · revisa: contador · en: terminos-vendedores, transparencia-fondos
  - Qué confirmar: confirma la frecuencia con que se concilian los pagos contra los reportes de Mercado Pago (propuesta: diaria) y escríbela aquí, o borra la frase
  - Valor sugerido: La frecuencia real, p. ej. «Conciliamos a diario los pagos con los reportes de Mercado Pago.»; o `true` para quitar la nota.
- **`VERIFICAR_DESGLOSE_IVA`** · revisa: contador · en: facturacion, terminos, terminos-tienda
  - Qué confirmar: confirma que la ficha del producto, el carrito y «Revisa tu pedido» muestran la leyenda «IVA incluido» y el monto del IVA por separado cuando la venta causa IVA, y la leyenda de venta exenta cuando el Refugio vendedor es donataria, según el régimen de cada Refugio vendedor (Ley del IVA, arts. 18-J, fr. I, y 18-K) / confirma que la ficha del producto, el carrito y «Revisa tu pedido» muestran la leyenda «IVA incluido» y el monto del IVA por separado (Ley del IVA, arts. 18-J, fr. I, y 18-K)
  - Valor sugerido: `true` si tu contador aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_FACTURACION`** · revisa: contador · en: facturacion, terminos, terminos-tienda
  - Qué confirmar: confirma con tu contador que el refugio vendedor emite el CFDI de cada venta, que GuauWoow solo factura su comisión y el plazo para pedir factura / con tu contador, el plazo para pedir la factura, el CFDI global del Refugio vendedor y la meta de 24 horas
  - Valor sugerido: `true` si tu contador aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_FISCAL_REFUGIOS`** · revisa: contador · en: terminos-refugios
  - Qué confirmar: el contador confirma la lectura de la UMA anual para la exención de personas físicas, el régimen de las asociaciones no donatarias y el efecto de las comisiones en el límite del 5 % de gastos de administración
  - Valor sugerido: `true` si tu contador aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_IVA_COMISION`** · revisa: contador · en: tarifas
  - Qué confirmar: confirma con tu contador si el porcentaje de comisión ya incluye el IVA o si el IVA se suma, y si se calcula sobre el total con envío
  - Valor sugerido: `true` si tu contador aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_REGIMEN_PLATAFORMAS`** · revisa: contador · en: facturacion, tarifas
  - Qué confirmar: no actives una comisión mayor que 0 % hasta que tu contador confirme el alta como retenedor, el CFDI de comisión y de retenciones, la declaración informativa mensual y el acceso en línea del SAT
  - Valor sugerido: `true` cuando tu contador confirme las obligaciones de plataforma. Mientras no sea true, --check exige que ambas comisiones del servidor sean 0.
- **`VERIFICAR_REGISTROS_FISCALES`** · revisa: contador · en: privacidad
  - Qué confirmar: con el contador que los registros bloqueados y anonimizados de cuentas eliminadas bastan para la contabilidad y las aclaraciones con Mercado Pago
  - Valor sugerido: `true` si tu contador aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_RETENCIONES`** · revisa: contador · en: terminos, terminos-refugios, terminos-tienda, terminos-vendedores
  - Qué confirmar: el contador confirma que con comisión de 0 % GuauWoow no retiene ISR ni IVA ni presenta la informativa como plataforma de intermediación; hoy la app retiene 2.5 % de ISR y 50 % de IVA a las personas físicas aunque la comisión sea 0 %: ajustar la app o este texto / con tu contador, si con Split de Mercado Pago y comisión mayor que 0 aplican las retenciones de ISR e IVA a plataformas (LIF 2026 art. 25 fr. VI y IX; LIVA art. 18-J) y el acceso del SAT (CFF art. 30-B) / el contador confirma, para una comisión mayor que 0 % con Split, si GuauWoow debe retener ISR e IVA (regla 12.2.5), si la retención alcanza a asociaciones y donatarias del Título III, el CFDI de la comisión y las obligaciones de los días 5, 10 y 17
  - Valor sugerido: `true` si tu contador aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_SAT_PLATAFORMAS`** · revisa: contador · en: privacidad
  - Qué confirmar: con el contador, qué información se entrega al SAT con comisión mayor a 0 y con pago dividido
  - Valor sugerido: `true` si tu contador aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).
- **`VERIFICAR_TOPE_DEDUCCIONES`** · revisa: contador · en: donativos
  - Qué confirmar: confirma con tu contador si, para personas físicas, los donativos cuentan además dentro del tope global de deducciones personales del art. 151 de la Ley del ISR; su último párrafo parece excluir la fr. III, donativos. Si cuentan, pon como valor la frase que lo explique; si no, pon true
  - Valor sugerido: `true` si tu contador aprueba el texto tal cual. Si pide otra redacción, escribe aquí la frase que te dé (sustituye la nota).

### Notas VERIFICAR para el equipo técnico (que la app haga lo que dice la página)

- **`VERIFICAR_ACEPTACION_ANEXOS`** · revisa: equipo técnico · en: acuerdo-datos-refugios, terminos-casas-de-paso, terminos-clinicas, terminos-refugios, terminos-vendedores
  - Qué confirmar: confirmar que la app pide este documento con casilla propia sin premarcar al (registrar el Refugio / la Casa de paso / la Clínica / publicar el primer producto / publicar el primer perro), que lo guarda en la bitácora de aceptaciones con su versión y su huella y que bloquea verificación, donativos y ventas sin la versión vigente
  - Estado en el código al 2026-10-18: Cierto en parte (no pongas true todavía): la app pide la casilla propia sin premarcar al registrar el Refugio, la Casa de paso (con el Acuerdo de datos), la Clínica y el primer producto; queda en la bitácora con versión y huella, y en producción (LEGAL_ANNEX_REQUIRED) bloquea verificación, donativos y ventas sin la versión vigente. No hay casilla al publicar el primer perro: acuerdo-datos-refugios 1.3 ya lo dice así; quita esa opción de la nota antes de poner true.
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_AUTODECLARACION`** · revisa: equipo técnico · en: adopcion-responsable
  - Qué confirmar: el cuestionario de adopción todavía no incluye esta autodeclaración; agrégala o quita este párrafo
  - Estado en el código al 2026-10-18: Todavía NO es cierto (no pongas true): el cuestionario de adopción no tiene esa autodeclaración.
  - Valor sugerido: `true` cuando el cuestionario de adopción incluya la autodeclaración; si no se agregará, pide quitar el párrafo de adopcion-responsable.html.
- **`VERIFICAR_AVISOS_CHAT`** · revisa: equipo técnico · en: canales-oficiales
  - Qué confirmar: cuando la app muestre avisos automáticos en el chat (al acordar un encuentro o al detectar CLABE, tarjeta, «depósito» o «anticipo»), el botón Bloquear o el mensaje de seguridad del bot al reportar un perro perdido, descríbelos aquí; si no, borra esta nota
  - Estado en el código al 2026-10-18: Todavía NO es cierto (no pongas true): el chat no muestra avisos automáticos al detectar CLABE, tarjeta, «depósito» o «anticipo», y no hay botón Bloquear; el bot no manda un mensaje de seguridad al reportar.
  - Valor sugerido: Cuando existan, descríbelos, p. ej. «El chat te muestra un aviso de seguridad al acordar un encuentro o si alguien pide un depósito.»; mientras no, `true` (se quita la nota y su párrafo).
- **`VERIFICAR_AVISOS_DE_SESION`** · revisa: equipo técnico · en: terminos
  - Qué confirmar: confirma que la app avisa por correo de los inicios de sesión desde un dispositivo nuevo y de los cambios de contraseña, correo o teléfono; si no, quita la última frase
  - Estado en el código al 2026-10-18: Todavía NO es cierto (no pongas true): no se envían correos por inicios de sesión desde un dispositivo nuevo ni por cambios de correo o teléfono.
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_AVISO_BOT`** · revisa: equipo técnico · en: privacidad, privacidad-whatsapp
  - Qué confirmar: que el bot muestra el aviso simplificado y el enlace en el primer contacto y tras 12 meses sin actividad, y que registra la versión mostrada; si no, agrégalo o ajusta esta sección / que el bot muestra el aviso simplificado y el enlace en el primer contacto y tras 12 meses sin actividad; si no, agrégalo o ajusta esta frase
  - Estado en el código al 2026-10-18: Ya es cierto: el bot manda el aviso simplificado (privacidad-simplificado §5.1) con el enlace en el primer contacto y otra vez a los 12 meses, en un mensaje aparte, y guarda su versión y fecha (services/whatsapp_bot.py, notice_v y notice_at).
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_AVISO_DE_MOTIVOS`** · revisa: equipo técnico · en: moderacion, terminos-casas-de-paso, terminos-clinicas, terminos-refugios
  - Qué confirmar: confirma que el aviso de moderación incluye el contenido afectado, la regla aplicada, el origen de la detección, la duración de la medida y cómo apelar
  - Estado en el código al 2026-10-18: Ya es cierto: el aviso de moderación (services/legal_moderation._notice_body) incluye el contenido, la regla, el origen de la detección, la duración y cómo apelar; revisa el texto final con tu abogado.
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_BAJAS_WHATSAPP`** · revisa: equipo técnico · en: comunicaciones, privacidad-whatsapp
  - Qué confirmar: que el bot reconoce STOP, ALTO, CANCELAR y frases similares como baja, y que HOLA no reactiva los avisos
  - Estado en el código al 2026-10-18: Ya es cierto: el bot reconoce BAJA, STOP, ALTO, CANCELAR y frases como «no me escriban»; HOLA no reactiva los avisos, solo ALTA.
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_BANNER_COOKIES`** · revisa: equipo técnico · en: cookies
  - Qué confirmar: que el aviso muestre Aceptar y Rechazar con el mismo peso visual y que, al rechazar o retirar el permiso, PostHog deje de enviar datos y no se vuelva a cargar
  - Estado en el código al 2026-10-18: Ya es cierto: app/legal/js/cookies.js muestra Aceptar y Rechazar con el mismo peso, no carga PostHog sin aceptación y lo detiene y borra sus claves al retirar el permiso.
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_BORRADO_CEDULA`** · revisa: equipo técnico · en: terminos-clinicas
  - Qué confirmar: hoy la app conserva la imagen de la cédula y la evidencia 12 meses después de un rechazo, una revocación o un vencimiento; ajustar el borrado de la imagen a 30 días (dejando 12 meses solo la constancia del cotejo) o cambiar este texto y la tabla de conservación
  - Estado en el código al 2026-10-18: Ya es cierto: retention.purge_verification_documents borra la imagen de la cédula 30 días después de la decisión y deja solo la constancia del cotejo.
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_BORRAR_UBICACION`** · revisa: equipo técnico · en: comunicaciones, privacidad
  - Qué confirmar: si Preferencias tendrá un botón para borrar la ubicación guardada; si no, explica aquí cómo pedir que se borre / la app no tiene todavía un botón «Borrar mi ubicación»; agrégalo o deja este párrafo así
  - Estado en el código al 2026-10-18: Ya es cierto: apagar las alertas cercanas en Perfil → Preferencias borra la ubicación guardada en la cuenta (consent.set_preference) y la app ya no la guarda con las alertas apagadas; no hay un botón aparte.
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_BOT_ACEPTACION`** · revisa: equipo técnico · en: contenido-importado, privacidad, privacidad-whatsapp, terminos
  - Qué confirmar: que el bot pide aceptar antes de publicar, que la foto se envía a la IA solo después de esa aceptación y que pregunta si quieres avisos por ese chat
  - Estado en el código al 2026-10-18: Ya es cierto: el bot muestra que el reporte será público con zona aproximada y pide PUBLICAR antes de crearlo; la foto va a la IA solo después (matching corre al publicar) y al final pregunta si quieres avisos por ese chat (sin un sí no se te escribe).
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_CAMPOS_FICHA`** · revisa: equipo técnico · en: terminos-tienda
  - Qué confirmar: que la ficha y “Revisa tu pedido” muestran garantía, perecederos y promociones antes de afirmarlo
  - Estado en el código al 2026-10-18: Cierto en parte (no pongas true todavía): la ficha y «Revisa tu pedido» muestran la garantía y si el producto es perecedero; no hay promociones en la tienda.
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_CASILLAS_DE_COMPRA`** · revisa: equipo técnico · en: terminos-tienda
  - Qué confirmar: confirma que “Revisa tu pedido” tiene casillas no marcadas de antemano para aceptar estas Condiciones (con su versión) y para autorizar el cobro antes de la entrega, y que el pedido guarda versión, huella SHA-256, fecha, IP y navegador
  - Estado en el código al 2026-10-18: Ya es cierto: «Revisa tu pedido» tiene dos casillas sin marcar (condiciones de compra y cobro antes de la entrega) y el pedido guarda la aceptación en la bitácora (versión, huella, fecha, IP y navegador).
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_COBROS_RECURRENTES`** · revisa: equipo técnico · en: seguridad
  - Qué confirmar: que la Plataforma no tenga hoy donativos ni compras recurrentes
  - Estado en el código al 2026-10-18: Ya es cierto: no existen donativos ni compras recurrentes en el código.
  - Valor sugerido: `true` mientras no existan donativos ni compras recurrentes.
- **`VERIFICAR_COMISION_CONFIGURADA`** · revisa: equipo técnico · en: tarifas
  - Qué confirmar: confirma que MERCADOPAGO_MARKETPLACE_FEE_PERCENT y MERCADOPAGO_DONATION_FEE_PERCENT del servidor coinciden con COMISION_TIENDA y COMISION_DONATIVOS; al 17-10-2026 el valor por defecto de la tienda en backend/app/config.py y .env.example era 10, no 0. Mientras VERIFICAR_REGIMEN_PLATAFORMAS no esté confirmado, ambos deben ser 0
  - Estado en el código al 2026-10-18: Ya es cierto: por defecto ambas comisiones son 0 en backend/app/config.py; render-legal --check compara COMISION_TIENDA y COMISION_DONATIVOS con el .env del servidor.
  - Valor sugerido: `true` cuando `python3 scripts/render-legal.py --check` en el servidor no reporte diferencias de comisión (compara COMISION_TIENDA y COMISION_DONATIVOS con el .env).
- **`VERIFICAR_COMISION_PRODUCTOS_INFRACTORES`** · revisa: equipo técnico · en: derechos-de-autor
  - Qué confirmar: si activas una comisión, confirma que no se cobra sobre ventas de productos retirados por infringir derechos de terceros
  - Estado en el código al 2026-10-18: No depende del código o no se puede comprobar en el repositorio: hoy la comisión es 0 %; si la activas, revisa que no se cobre sobre productos retirados.
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_COMPROBANTE_DONATIVO`** · revisa: equipo técnico · en: donativos
  - Qué confirmar: la app aún no tiene una vista «Mis donativos» que entregue a la persona donante un comprobante de operación (donativos-26). Cuando exista, pon como valor «GuauWoow también te muestra cada donativo en la app con su folio, el identificador de pago de Mercado Pago, la fecha, el Refugio y el monto, con la leyenda “Comprobante de operación: no es CFDI ni recibo deducible”.»; mientras no exista, pon true
  - Estado en el código al 2026-10-18: Cierto en parte (no pongas true todavía): al aprobarse un donativo la persona donante recibe su comprobante de operación en la app y por correo (folio, Refugio, monto, fecha e identificador de Mercado Pago; payment_flow._notify_donor_receipt), pero todavía no existe la vista «Mis donativos».
  - Valor sugerido: Cuando se cumpla, escribe exactamente «GuauWoow también te muestra cada donativo en la app con su folio, el identificador de pago de Mercado Pago, la fecha, el Refugio y el monto, con la leyenda “Comprobante de operación: no es CFDI ni recibo deducible”.»; mientras no, `true` (no se publica nada en su lugar).
- **`VERIFICAR_COOKIES_CLOUDFLARE`** · revisa: equipo técnico · en: cookies
  - Qué confirmar: qué funciones de Cloudflare están activas (protección contra robots, límites de solicitudes, Turnstile, sala de espera, balanceo de carga, Web Analytics o Zaraz) y deja en la tabla solo sus cookies
  - Estado en el código al 2026-10-18: No depende del código o no se puede comprobar en el repositorio: depende de las funciones activas en tu cuenta de Cloudflare.
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_CORREO_FACTURA`** · revisa: equipo técnico · en: proveedores
  - Qué confirmar: si el Refugio vendedor ve el correo que la persona captura al pedir factura (OrderInvoice.email aparece en InvoiceOut), escribe aquí: «También el correo que indicas para recibirla.»; si no lo ve, pon true
  - Estado en el código al 2026-10-18: El Refugio vendedor sí ve el correo que la persona captura al pedir factura (InvoiceOut.email en /refuges/me/invoice-requests): escribe el texto que propone la nota en lugar de true.
  - Valor sugerido: Cuando se cumpla, escribe exactamente «También el correo que indicas para recibirla.»; mientras no, `true` (no se publica nada en su lugar).
- **`VERIFICAR_DATOS_PAGADOR_MP`** · revisa: equipo técnico · en: terminos, terminos-tienda
  - Qué confirmar: qué datos del pagador ve el Refugio en su cuenta de Mercado Pago con Checkout Pro y Split
  - Estado en el código al 2026-10-18: No depende del código o no se puede comprobar en el repositorio: lo decide Mercado Pago (Checkout Pro con Split).
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_DATOS_VENDEDOR`** · revisa: equipo técnico · en: privacidad-refugios, terminos-vendedores
  - Qué confirmar: lista exacta de datos del Refugio vendedor que se muestran antes de pagar
  - Estado en el código al 2026-10-18: Ya es cierto: la ficha y el comprobante muestran la identidad del Refugio vendedor (reglas.seller_identity); compara la lista de la página con esos campos.
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_DECLARACION_AL_PUBLICAR`** · revisa: equipo técnico · en: cero-venta
  - Qué confirmar: la casilla de declaración todavía no está en el formulario para publicar un perro; agrégala o quita este párrafo
  - Estado en el código al 2026-10-18: Todavía NO es cierto (no pongas true): el formulario para publicar un perro no tiene esa casilla.
  - Valor sugerido: `true` cuando el formulario para publicar un perro tenga la casilla «No vendo ni cobro por este perro»; si no se agregará, pide quitar el párrafo.
- **`VERIFICAR_DOCUMENTOS_CLINICAS`** · revisa: equipo técnico · en: verificacion
  - Qué confirmar: que el alta de Clínicas pida y revise una identificación de la persona responsable y un comprobante del establecimiento, o quita este texto
  - Estado en el código al 2026-10-18: Todavía NO es cierto (no pongas true): el alta de Clínicas pide solo la cédula profesional y la declaración; no pide identificación ni comprobante del establecimiento.
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_DONATIVO_NETO`** · revisa: equipo técnico · en: terminos
  - Qué confirmar: confirma que la pantalla de donativo muestra el monto neto que recibirá el Refugio; si no, quita la última frase y deja solo la comisión
  - Estado en el código al 2026-10-18: Todavía NO es cierto (no pongas true): la pantalla de donativo no muestra el monto neto que recibirá el Refugio.
  - Valor sugerido: `true` solo si la pantalla de donar ya muestra el monto neto para el Refugio; si no, pide quitar la última frase de la sección 17.2 de terminos.html.
- **`VERIFICAR_DURACION_CONSENTIMIENTO`** · revisa: equipo técnico · en: cookies
  - Qué confirmar: si el aviso de cookies ya guarda la fecha y la versión de la elección y vuelve a preguntar a los 12 meses o al cambiar esta política, escribe aquí: «También guardamos la fecha y la versión de esta política, y te volvemos a preguntar a los 12 meses o si la política cambia.»; si no, pon true
  - Estado en el código al 2026-10-18: Ya es cierto: cookies.js guarda la versión de la política y la fecha (v y at) y vuelve a preguntar a los 12 meses o si cambia la política: escribe el texto que propone la nota.
  - Valor sugerido: Cuando se cumpla, escribe exactamente «También guardamos la fecha y la versión de esta política, y te volvemos a preguntar a los 12 meses o si la política cambia.»; mientras no, `true` (no se publica nada en su lugar).
- **`VERIFICAR_ELIMINAR_BOT`** · revisa: equipo técnico · en: eliminacion-datos
  - Qué confirmar: qué borra exactamente el comando ELIMINAR, si se aplica al momento y si responde con un número de referencia
  - Estado en el código al 2026-10-18: Ya es cierto: ELIMINAR pide confirmación, borra al momento la conversación y el contenido de los reportes creados desde ese número, apaga los avisos y responde con un folio de solicitud de cancelación.
  - Valor sugerido: La descripción real, p. ej. «ELIMINAR borra al momento tus mensajes con el bot y los reportes que enviaste por WhatsApp, y te responde con un número de referencia.»
- **`VERIFICAR_ENLACE_DE_BAJA`** · revisa: equipo técnico · en: comunicaciones, derechos-arco
  - Qué confirmar: si cada correo de alertas y cada correo promocional ya trae un enlace de baja en un clic que funciona sin iniciar sesión, escribe aquí: «También puedes usar el enlace para darte de baja en un clic que viene en esos correos.»; si no, pon true
  - Estado en el código al 2026-10-18: Los correos no traen enlace de baja en un clic (el pie dice que cambies tus avisos en tu perfil): como indica la nota, pon true; no escribas la frase opcional.
  - Valor sugerido: Cuando se cumpla, escribe exactamente «También puedes usar el enlace para darte de baja en un clic que viene en esos correos.»; mientras no, `true` (no se publica nada en su lugar).
- **`VERIFICAR_ESTADO_ACCESIBILIDAD`** · revisa: equipo técnico · en: accesibilidad
  - Qué confirmar: antes de publicar, confirma en la versión desplegada que cada punto de esta lista y de la sección 6 sigue funcionando, en especial que todas las tablas de las páginas legales tengan encabezados de fila o de columna; quita el que no
  - Estado en el código al 2026-10-18: No depende del código o no se puede comprobar en el repositorio: es una revisión manual de la versión desplegada.
  - Valor sugerido: `true` después de probar cada punto en el sitio publicado; si alguno falla, pide quitarlo de la lista.
- **`VERIFICAR_ESTADO_TABLERO`** · revisa: equipo técnico · en: estado-del-servicio
  - Qué confirmar: confirma qué componentes, qué periodos de disponibilidad (30 y 90 días), qué mantenimientos y qué resúmenes de incidentes muestra el tablero publicado; ajusta las secciones 1, 3 y 4 o quita las frases que no apliquen
  - Estado en el código al 2026-10-18: Cierto en parte (no pongas true todavía): /cumplimiento/estado muestra componentes, incidentes públicos de los últimos 90 días y mantenimientos; no calcula porcentajes de disponibilidad de 30 y 90 días: quita esa parte.
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_ETIQUETA_IA`** · revisa: equipo técnico · en: contenido-importado, ia-y-algoritmos, terminos
  - Qué confirmar: que los reportes con descripción generada por IA muestran la etiqueta «Texto generado por IA» / si la publicación ya mostrada al público debe llevar la etiqueta «descripción sugerida por IA» cuando la persona no la cambió / confirma que la app marca como “sugerida por IA” las descripciones generadas y que la persona puede corregirlas antes y después de publicar
  - Estado en el código al 2026-10-18: Todavía NO es cierto (no pongas true): los reportes con descripción generada por IA no muestran la etiqueta «Texto generado por IA».
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_EXCLUSIONES_REVOCACION`** · revisa: equipo técnico · en: envios-devoluciones-garantias
  - Qué confirmar: confirma que la ficha del producto y el paso «Revisa tu pedido» avisan cuando un producto es perecedero y no admite revocación
  - Estado en el código al 2026-10-18: Ya es cierto: la ficha y «Revisa tu pedido» avisan cuando un producto es perecedero y no admite revocación.
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_FILTRO_VENTA_IMPORTADOS`** · revisa: equipo técnico · en: contenido-importado, privacidad-whatsapp
  - Qué confirmar: que el filtro de palabras de venta o cobro se aplica a reenvíos, envíos de voluntarios e importaciones antes de guardar
  - Estado en el código al 2026-10-18: Todavía NO es cierto (no pongas true): el filtro de palabras de venta o cobro (reglas.adoption_terms) solo se aplica a las fichas de adopción, no a reenvíos, envíos de voluntarios ni importaciones.
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_FUENTE_UNICA_PROVEEDORES`** · revisa: equipo técnico · en: proveedores
  - Qué confirmar: antes de publicar, que esta lista y las secciones de encargados, transferencias y flujos internacionales del Aviso de Privacidad digan lo mismo; lo ideal es generarlas de una sola fuente
  - Estado en el código al 2026-10-18: No depende del código o no se puede comprobar en el repositorio: las listas están escritas a mano en las plantillas; compáralas antes de publicar.
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_HISTORIAL_CAMPOS`** · revisa: equipo técnico · en: historial
  - Qué confirmar: confirma que el registro publicado muestra todos estos datos para cada versión; quita de la lista lo que no muestre
  - Estado en el código al 2026-10-18: Ya es cierto: historial.js muestra de /cumplimiento/documentos la versión, la fecha de entrada en vigor, la huella SHA-256, el resumen y la dirección fija de cada versión.
  - Valor sugerido: `true` cuando historial.html muestre, para cada versión, sus fechas, el resumen, la huella SHA-256 y si pide aceptarla otra vez (los datos salen de versiones.json por /cumplimiento/documentos).
- **`VERIFICAR_IA_RECORTES`** · revisa: equipo técnico · en: contenido-importado, privacidad
  - Qué confirmar: se recomienda enviar a la IA solo recortes del perro y difuminar rostros en fotos importadas; ajusta este párrafo si se implementa
  - Estado en el código al 2026-10-18: Todavía NO es cierto (no pongas true): a la IA se envía la foto completa; no hay recortes ni difuminado de rostros.
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_IMPORTACION_VENTA`** · revisa: equipo técnico · en: cero-venta
  - Qué confirmar: que la importación de grupos de Facebook descarte las ofertas de venta antes de guardarlas
  - Estado en el código al 2026-10-18: Todavía NO es cierto (no pongas true): la importación de grupos de Facebook no descarta ofertas de venta antes de guardarlas (el filtro solo aplica a fichas de adopción).
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_INDICADORES_TRANSPARENCIA`** · revisa: equipo técnico · en: compromisos
  - Qué confirmar: confirma que el informe de transparencia publicado muestra cada indicador nombrado en esta tabla; cambia el nombre o quita el que no aparezca
  - Estado en el código al 2026-10-18: No depende del código o no se puede comprobar en el repositorio: compara los nombres de la tabla con lo que muestra transparencia.js en la versión desplegada.
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_INVENTARIO_COOKIES`** · revisa: equipo técnico · en: cookies
  - Qué confirmar: antes de publicar, compara esta tabla con las claves que realmente usan app/*.js y los scripts de app/legal/js; al 18-10-2026 la Plataforma usa sessionStorage solo para patitas_anexos_pospuestos y no usa service worker ni cookies propias
  - Estado en el código al 2026-10-18: Ya es cierto: al 2026-10-18 la tabla coincide con las claves de app/*.js y app/legal/js, incluidas patitas_legal_avisos, patitas_alertas_invite y patitas_anexos_pospuestos (sessionStorage).
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_INVENTARIO_LICENCIAS`** · revisa: equipo técnico · en: creditos
  - Qué confirmar: antes de publicar, compara esta página con las librerías de app/vendor, las fuentes y los íconos que usa la versión desplegada, y agrega el origen de los íconos de la app
  - Estado en el código al 2026-10-18: No depende del código o no se puede comprobar en el repositorio: es una revisión manual de app/vendor, fuentes e íconos.
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_LISTADO_EXCLUSION`** · revisa: equipo técnico · en: comunicaciones, derechos-arco
  - Qué confirmar: que al atender una solicitud de limitación por publicidad se apaguen todas las comunicaciones promocionales de esa persona en todos los canales y quede registrada la fecha
  - Estado en el código al 2026-10-18: Ya es cierto: al hacer efectiva una solicitud de limitación por publicidad se apagan los correos promocionales y los avisos por WhatsApp de la cuenta, con constancia y fecha en consent_records (solicitudes.apply_permission_changes).
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_METODOLOGIA_TRANSPARENCIA`** · revisa: equipo técnico · en: informe-transparencia
  - Qué confirmar: confirma que el tablero muestra la fecha de cálculo de cada cifra y aplica la regla de umbral de 5 casos; si no, ajusta o borra estas frases
  - Estado en el código al 2026-10-18: Ya es cierto: cada respuesta trae calculado_en y los desgloses con menos de 5 casos se publican como «menos de 5»; las cifras se guardan en caché hasta 1 hora.
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_MONITOREO_DONATIVOS`** · revisa: equipo técnico · en: prevencion-lavado
  - Qué confirmar: hoy el sistema no revisa los donativos acumulados por persona y por Refugio. Si se agrega una revisión en periodos de seis meses con aviso al Refugio cuando se acerquen al umbral de identificación, pon como valor «GuauWoow también revisa los donativos acumulados por persona y por Refugio en periodos de seis meses y avisa al Refugio si se acercan al umbral de identificación.»; si no, pon true
  - Estado en el código al 2026-10-18: Ya es cierto: reglas.check_aml_thresholds revisa el acumulado de 6 meses por persona y Refugio al aprobar cada donativo y avisa al Refugio y al equipo: escribe el texto que propone la nota.
  - Valor sugerido: Cuando se cumpla, escribe exactamente «GuauWoow también revisa los donativos acumulados por persona y por Refugio en periodos de seis meses y avisa al Refugio si se acercan al umbral de identificación.»; mientras no, `true` (no se publica nada en su lugar).
- **`VERIFICAR_MOTIVOS_DE_REPORTE`** · revisa: equipo técnico · en: adopcion-responsable, cero-venta, comunidad, moderacion, proteccion-nna, resenas, terminos-clinicas, veterinarias
  - Qué confirmar: que el botón Reportar y el formulario público ofrezcan los motivos que menciona esta página (venta o cobro por un animal, mi imagen o mis datos, contenido íntimo, difamación, suplantación, reseña falsa o pagada, cédula falsa, condiciones sanitarias, publicidad engañosa); si alguno falta, agrégalo o ajusta el texto
  - Estado en el código al 2026-10-18: No depende del código o no se puede comprobar en el repositorio: compara la lista de la página con los motivos de reportes.js y del botón Reportar de la app.
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_NOMINATIM`** · revisa: equipo técnico · en: cookies, privacidad
  - Qué confirmar: si la consulta a Nominatim ya se hace desde nuestro servidor con coordenadas redondeadas; si es así, actualiza este párrafo / si la geocodificación inversa pasa al servidor con coordenadas redondeadas, actualiza esta frase
  - Estado en el código al 2026-10-18: Todavía NO es cierto (no pongas true): la geocodificación inversa se hace desde el navegador (app.js llama a nominatim.openstreetmap.org con las coordenadas).
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_PIXELES`** · revisa: equipo técnico · en: cookies, privacidad
  - Qué confirmar: si en el futuro agregas un píxel de Meta, Google u otra red, actualiza esta sección y pide consentimiento en el aviso de cookies / que no hay píxeles de redes sociales en la app ni en la página de inicio y que el proveedor de correo tiene desactivado el seguimiento de aperturas y clics
  - Estado en el código al 2026-10-18: Ya es cierto: no hay píxeles de redes sociales en la app ni en la página de inicio; el seguimiento del proveedor de correo se revisa aparte (VERIFICAR_RASTREO_CORREOS).
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_PLANTILLAS_WHATSAPP`** · revisa: equipo técnico · en: comunicaciones, privacidad-whatsapp
  - Qué confirmar: qué otras plantillas de utilidad están aprobadas en Meta (por ejemplo, estado de postulaciones o pedidos); que todas terminan con «Responde BAJA para no recibir más avisos» y que no se envía mercadotecnia por WhatsApp / que las plantillas aprobadas en Meta son de categoría utilidad, terminan con «Responde BAJA para no recibir más avisos» y que no se envía mercadotecnia por WhatsApp
  - Estado en el código al 2026-10-18: No depende del código o no se puede comprobar en el repositorio: las plantillas se aprueban en Meta; en el código solo existen WHATSAPP_TEMPLATE_MATCH y la de alertas cercanas.
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_PLAZO_RECLAMACION`** · revisa: equipo técnico · en: envios-devoluciones-garantias
  - Qué confirmar: la app calcula este plazo como 60 días naturales desde la entrega; confirma que nunca resulte menor a dos meses calendario
  - Estado en el código al 2026-10-18: Todavía NO es cierto (no pongas true): la app usa 60 días naturales (RETURN_CLAIM_WINDOW_DAYS); algunos periodos de 2 meses calendario tienen 61 o 62 días.
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_POSTHOG`** · revisa: equipo técnico · en: cookies, privacidad, proveedores
  - Qué confirmar: activa en el proyecto de PostHog la opción de descartar la IP de los clientes
  - Estado en el código al 2026-10-18: No depende del código o no se puede comprobar en el repositorio: es una opción del proyecto de PostHog.
  - Valor sugerido: `true` cuando actives en PostHog «Discard client IP data».
- **`VERIFICAR_PRECISION_COORDS`** · revisa: equipo técnico · en: cookies
  - Qué confirmar: precisión real que guarda patitas_coords; al 17-10-2026 son 5 decimales, cerca de 1 metro
  - Estado en el código al 2026-10-18: Ya es cierto: app.js redondea a 5 decimales (cerca de 1 metro) antes de guardar patitas_coords.
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_PRECISION_UBICACION`** · revisa: equipo técnico · en: conservacion, privacidad
  - Qué confirmar: precisión real con la que se guarda la ubicación; si se redondea (se recomiendan 3 decimales, unos 110 m), ajusta este texto
  - Estado en el código al 2026-10-18: Ya es cierto: la ubicación de la cuenta se guarda con los 5 decimales que manda la app; solo se guarda con las alertas cercanas encendidas.
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_PRUEBAS_SEGURIDAD`** · revisa: equipo técnico · en: seguridad
  - Qué confirmar: cuando existan el escaneo de dependencias en CI y una prueba de penetración, escribe aquí el texto, p. ej. «Aplicamos actualizaciones de seguridad al software y sus dependencias, y hacemos pruebas de seguridad; la última fue el ...»; si no existen, pon true y no se publica nada
  - Estado en el código al 2026-10-18: Cierto en parte (no pongas true todavía): el CI ya corre pip-audit sobre requirements.txt; todavía no hay prueba de penetración.
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_PUNTOS_DONATIVOS`** · revisa: equipo técnico · en: donativos
  - Qué confirmar: al 17-10-2026 el código aún suma puntos por donativo (backend/app/services/payment_flow.py, PointLog «donation» y su reverso «donation_refund») y la app dice «Cada $10 suma 1 punto en el ranking» (app/app.js). No publiques esta página hasta que ese cambio esté desplegado; después pon true
  - Estado en el código al 2026-10-18: Ya es cierto: los donativos ya no suman puntos (sin PointLog «donation»; la migración 0004 descontó los anteriores) y la app dice que los donativos no suman puntos.
  - Valor sugerido: `true` solo cuando esté desplegado el cambio que quita los puntos por donativo (payment_flow.py y app.js). Antes no publiques donativos.html.
- **`VERIFICAR_RASTREO_CORREOS`** · revisa: equipo técnico · en: comunicaciones, cookies, proveedores
  - Qué confirmar: que el proveedor de correo tenga desactivado el seguimiento de aperturas y de clics
  - Estado en el código al 2026-10-18: No depende del código o no se puede comprobar en el repositorio: es una opción del proveedor de correo.
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_REGISTROS_TECNICOS`** · revisa: equipo técnico · en: conservacion, seguridad
  - Qué confirmar: que la rotación de los registros del servidor web y de la app cumpla 90 días y acorte la IP a los 30; al 17-10-2026 rotan por tamaño
  - Estado en el código al 2026-10-18: Todavía NO es cierto (no pongas true): los registros rotan por tamaño, no a 90 días, y la IP de los registros del servidor web no se acorta a los 30 días (solo la de la base de datos, retention.purge_technical_logs).
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_REGISTRO_PERMISOS`** · revisa: equipo técnico · en: comunicaciones
  - Qué confirmar: si ya se registra cada permiso que se da o se retira (avisos por WhatsApp, correos promocionales, analítica) con canal, versión del texto y fecha, escribe aquí: «También guardamos un registro de cada permiso que das o retiras: qué aceptaste, por qué canal, la versión del texto y la fecha.»; si no, pon true
  - Estado en el código al 2026-10-18: Ya es cierto: cada permiso que se da o se retira queda en consent_records (de solo inserción) con canal, versión del texto y fecha: escribe el texto que propone la nota.
  - Valor sugerido: Cuando se cumpla, escribe exactamente «También guardamos un registro de cada permiso que das o retiras: qué aceptaste, por qué canal, la versión del texto y la fecha.»; mientras no, `true` (no se publica nada en su lugar).
- **`VERIFICAR_RESPALDOS`** · revisa: equipo técnico · en: seguridad
  - Qué confirmar: cuando la llave de los respaldos esté fuera del servidor, exista una prueba periódica de restauración registrada y el procedimiento de restauración reaplique los borrados, escribe aquí: «La llave para descifrarlos se guarda fuera del servidor. Probamos que se puedan restaurar y, si restauramos un respaldo, volvemos a aplicar los borrados hechos después de su fecha para no recuperar cuentas ya eliminadas.»; si no, pon true
  - Estado en el código al 2026-10-18: Todavía NO es cierto (no pongas true): backend/scripts/restore.sh no vuelve a aplicar los borrados posteriores al respaldo; la llave externa y la prueba periódica de restauración dependen de tu operación.
  - Valor sugerido: Cuando se cumpla, escribe exactamente «La llave para descifrarlos se guarda fuera del servidor. Probamos que se puedan restaurar y, si restauramos un respaldo, volvemos a aplicar los borrados hechos después de su fecha para no recuperar cuentas ya eliminadas.»; mientras no, `true` (no se publica nada en su lugar).
- **`VERIFICAR_RESTAURACION`** · revisa: equipo técnico · en: conservacion
  - Qué confirmar: cuando el procedimiento de restauración reaplique los borrados y bloqueos posteriores a la fecha del respaldo, escribe aquí: «Si alguna vez restauramos un respaldo, volvemos a aplicar los borrados hechos después de su fecha.»; si no, pon true
  - Estado en el código al 2026-10-18: backend/scripts/restore.sh no vuelve a aplicar los borrados posteriores a la fecha del respaldo: como indica la nota, pon true; no escribas la frase opcional.
  - Valor sugerido: Cuando se cumpla, escribe exactamente «Si alguna vez restauramos un respaldo, volvemos a aplicar los borrados hechos después de su fecha.»; mientras no, `true` (no se publica nada en su lugar).
- **`VERIFICAR_REVISION_DE_CHAT`** · revisa: equipo técnico · en: seguridad, terminos
  - Qué confirmar: confirma que el panel de administración solo muestra los mensajes reportados y que cada acceso queda en la bitácora de administración
  - Estado en el código al 2026-10-18: No depende del código o no se puede comprobar en el repositorio: compara con el panel de administración desplegado (mensajes reportados y bitácora de administración).
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_SENTRY`** · revisa: equipo técnico · en: cookies, privacidad
  - Qué confirmar: que el proyecto de Sentry del navegador no tenga activada la grabación de sesiones (Session Replay)
  - Estado en el código al 2026-10-18: No depende del código o no se puede comprobar en el repositorio: es una opción del proyecto de Sentry.
  - Valor sugerido: `true` cuando confirmes que Session Replay está apagado en el proyecto de Sentry del navegador.
- **`VERIFICAR_SIMPLIFICADO_PUNTOS`** · revisa: equipo técnico · en: privacidad-simplificado
  - Qué confirmar: que cada flujo de la app muestra su variante antes de que la persona envíe sus datos; hoy está confirmado solo en el registro
  - Estado en el código al 2026-10-18: Cierto en parte (no pongas true todavía): confirmado en el registro y en el primer contacto del bot de WhatsApp; revisa los demás flujos.
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_TABLA_CANALES`** · revisa: equipo técnico · en: comunicaciones
  - Qué confirmar: que esta tabla coincida con los interruptores de Perfil → Preferencias y con los canales que usa cada aviso en el código
  - Estado en el código al 2026-10-18: No depende del código o no se puede comprobar en el repositorio: compara con Perfil → Preferencias y con services/notify.py (los mensajes del chat solo llegan dentro de la app).
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_TABLA_VISIBILIDAD`** · revisa: equipo técnico · en: seguridad
  - Qué confirmar: que esta tabla coincida con lo que muestran las respuestas públicas de la API y las pantallas de la app, en especial nombre, foto y ubicación aproximada
  - Estado en el código al 2026-10-18: Cierto en parte (no pongas true todavía): lo público de reportes y perros incluye el nombre y la foto del perfil de quien publica (UserMini.full_name) y la zona redondeada; revisa la tabla con eso.
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_TABLERO_FONDOS`** · revisa: equipo técnico · en: transparencia-fondos
  - Qué confirmar: describe solo lo que el tablero de /cumplimiento/transparencia muestre de verdad. Si además muestra la fecha de actualización, la forma jurídica de cada Refugio, desde cuándo está verificado, si es donataria, los reembolsos, contracargos y reclamaciones de la tienda atendidas en plazo por mes, o el enlace al informe de uso de fondos de cada Refugio, pon como valor la frase que lo diga; si no, pon true. Antes, confirma que los montos de Refugios que son personas físicas solo se muestran con su consentimiento (donativos-22). Si el tablero llegara a mostrar la comisión de Mercado Pago, confirma que la toma de los datos de cada pago (fee_details) y ajusta la definición de neto
  - Estado en el código al 2026-10-18: Cierto en parte (no pongas true todavía): el tablero muestra por Refugio el bruto, la comisión de GuauWoow, las retenciones y los reembolsos de ventas, el neto antes de la comisión de Mercado Pago, la forma jurídica, la fecha de verificación, si es donataria y la fecha de cálculo; no muestra la comisión de Mercado Pago.
  - Valor sugerido: `true` cuando el equipo técnico confirme en la versión desplegada que la app ya lo hace. Si todavía no, no pongas true: pide el cambio en el código o que se ajuste la frase de la página.
- **`VERIFICAR_URL_VERSIONES`** · revisa: equipo técnico · en: centro-legal, historial
  - Qué confirmar: confirma que cada versión anterior queda publicada en una dirección fija que no cambia; si no, borra la frase anterior
  - Estado en el código al 2026-10-18: Ya es cierto: scripts/render-legal.py archiva cada versión anterior en app/legal/<slug>-<versión>.html (dirección fija) y comprueba su huella SHA-256.
  - Valor sugerido: `true`: scripts/render-legal.py guarda cada versión anterior en /app/legal/<página>-<versión>.html y versiones.json apunta a esa dirección fija.

### Notas VERIFICAR que decides tú (dueño u operador)

- **`VERIFICAR_ALIBABA_REGION`** · revisa: dueño · en: ia-y-algoritmos, privacidad, proveedores, seguridad
  - Qué confirmar: entidad contratante, región del servicio y ámbito de cómputo fijado en Singapur
  - Valor sugerido: `true` cuando confirmes en tu contrato con Alibaba Cloud la entidad contratante, la región y que el cómputo queda en Singapur.
- **`VERIFICAR_APELACION_PERSONA_DISTINTA`** · revisa: dueño · en: moderacion, resenas
  - Qué confirmar: que haya al menos dos personas con rol de moderación para que la apelación la resuelva alguien distinto de quien decidió
  - Valor sugerido: `true` si hay al menos dos personas con rol de moderación.
- **`VERIFICAR_CERTIFICACIONES_PROVEEDORES`** · revisa: dueño · en: proveedores
  - Qué confirmar: si quieres publicar las certificaciones de seguridad de cada proveedor (por ejemplo, ISO/IEC 27001 o SOC 2), escribe aquí la lista con su fuente; si no, pon true
  - Valor sugerido: La lista con su fuente, p. ej. «Hetzner: ISO/IEC 27001 (hetzner.com); Cloudflare: ISO/IEC 27001 y SOC 2 (cloudflare.com/trust-hub).»; si no quieres publicarla, `true`.
- **`VERIFICAR_COBRO_REITERADAS`** · revisa: dueño · en: derechos-arco
  - Qué confirmar: decide si GuauWoow renuncia a ese cobro también en solicitudes repetidas; si es así, cambia este párrafo por «Tampoco cobramos si repites una solicitud»
  - Valor sugerido: Si GuauWoow renuncia también a ese cobro, escribe «Tampoco cobramos si repites una solicitud.»; si lo mantiene, `true`.
- **`VERIFICAR_CONCILIANET`** · revisa: dueño · en: atencion-y-quejas, privacidad
  - Qué confirmar: no menciones Concilianet hasta firmar el Convenio de Colaboración con PROFECO; cuando lo firmes, agrega aquí el enlace
  - Valor sugerido: `true` (no se menciona Concilianet). Cuando firmes el convenio con PROFECO: «También puedes conciliar en línea con Concilianet.»
- **`VERIFICAR_CONFIDENCIALIDAD`** · revisa: dueño · en: seguridad
  - Qué confirmar: cuando cada persona con acceso al panel haya firmado un acuerdo de confidencialidad antes de recibir acceso, escribe aquí: «Por eso, las personas del equipo, moderadoras y voluntarias que acceden a datos firman un acuerdo de confidencialidad.»; si no, pon true
  - Valor sugerido: Cuando se cumpla, escribe exactamente «Por eso, las personas del equipo, moderadoras y voluntarias que acceden a datos firman un acuerdo de confidencialidad.»; mientras no, `true` (no se publica nada en su lugar).
- **`VERIFICAR_CONFIDENCIALIDAD_VERIFICADORES`** · revisa: dueño · en: verificacion
  - Qué confirmar: que las personas que revisan documentos firmaron un convenio de confidencialidad
  - Valor sugerido: `true` si confirmas la regla tal como está escrita. Si decides otra cosa, escribe la frase que debe publicarse en su lugar.
- **`VERIFICAR_CONTENIDO_IA`** · revisa: dueño · en: creditos
  - Qué confirmar: lista o describe qué piezas del sitio se generaron con IA según tu inventario
  - Valor sugerido: Una frase con tu inventario, p. ej. «Las ilustraciones de perritos de la app y de la página de inicio se generaron con apoyo de IA y las revisó el equipo.»
- **`VERIFICAR_CUENTAS_INACTIVAS`** · revisa: dueño · en: conservacion
  - Qué confirmar: si adoptarás un plazo de inactividad (la investigación propone avisar y suprimir tras 24 meses sin actividad), escribe aquí el texto que sigue a «Mientras la cuenta exista», p. ej. «y, tras 24 meses sin actividad, aviso y supresión»; si no, pon true
  - Valor sugerido: Si adoptas un plazo de inactividad: «y, tras 24 meses sin actividad, aviso y supresión»; si no, `true`.
- **`VERIFICAR_DATOS_PROFECO`** · revisa: dueño · en: atencion-y-quejas, canales-oficiales, comunicaciones
  - Qué confirmar: reconfirma en gob.mx/profeco los teléfonos, el horario, el sitio y el domicilio de PROFECO antes de publicar / confirma en gob.mx/profeco los teléfonos y el domicilio vigentes de PROFECO antes de publicarlos
  - Valor sugerido: `true` después de cotejar en gob.mx/profeco; si algún dato cambió, pide corregirlo en la plantilla antes.
- **`VERIFICAR_DIRECTORIO_AUTORIDADES`** · revisa: dueño · en: autoridades, denunciar-maltrato
  - Qué confirmar: agrega teléfono, sitio y canal de cada autoridad solo después de comprobarlos en su sitio oficial, anota la fecha y define quién revisa este directorio cada trimestre
  - Valor sugerido: `true` después de agregar al directorio (en la plantilla) los datos comprobados y anotar la fecha en FECHA_DE_VERIFICACION_DEL_DIRECTORIO_DE_AUTORIDADES.
- **`VERIFICAR_DIRECTORIO_CASAS_DE_PASO`** · revisa: dueño · en: terminos-casas-de-paso
  - Qué confirmar: hoy la app solo registra y aprueba Casas de paso y no muestra un directorio; confirmar cómo se pondrán en contacto los Refugios y las Casas de paso (directorio en la app, contacto por el equipo de GuauWoow u otro medio) y ajustar las secciones 2, 3, 6 y 9
  - Valor sugerido: `true` si confirmas la regla tal como está escrita. Si decides otra cosa, escribe la frase que debe publicarse en su lugar.
- **`VERIFICAR_DOCUMENTOS_POR_ESTADO`** · revisa: dueño · en: verificacion
  - Qué confirmar: confirma que el equipo de verificación pedirá estos documentos según el estado del Refugio y qué hará si un estado no tiene registro disponible
  - Valor sugerido: `true` si confirmas la regla tal como está escrita. Si decides otra cosa, escribe la frase que debe publicarse en su lugar.
- **`VERIFICAR_DOCUMENTO_SEGURIDAD`** · revisa: dueño · en: seguridad
  - Qué confirmar: cuando exista el documento de seguridad interno con inventario de datos, análisis de riesgos y plan de trabajo, escribe aquí: «También mantenemos un documento de seguridad interno con el inventario de datos, los riesgos y las medidas.»; si no, pon true
  - Valor sugerido: Cuando se cumpla, escribe exactamente «También mantenemos un documento de seguridad interno con el inventario de datos, los riesgos y las medidas.»; mientras no, `true` (no se publica nada en su lugar).
- **`VERIFICAR_DOMICILIO_FISICO`** · revisa: dueño · en: quienes-somos
  - Qué confirmar: confirma que es un lugar físico en México donde realmente se reciben documentos; un apartado postal o una oficina virtual pueden no bastar
  - Valor sugerido: `true` cuando confirmes que en DOMICILIO_FISCAL se reciben documentos en persona.
- **`VERIFICAR_DONATARIAS`** · revisa: dueño · en: donataria-autorizada, donativos
  - Qué confirmar: hoy nadie coteja el estatus de donataria que declara el Refugio. Si el equipo de GuauWoow lo va a verificar (oficio de autorización, Anexo 14, directorio y listado de pendientes de publicar del SAT), pon como valor una frase que diga cómo y cada cuánto, por ejemplo «GuauWoow coteja ese estatus con el Anexo 14 y el directorio del SAT cada …»; si no, pon true
  - Valor sugerido: `true` si confirmas la regla tal como está escrita. Si decides otra cosa, escribe la frase que debe publicarse en su lugar.
- **`VERIFICAR_DPA_ARCHIVADOS`** · revisa: dueño · en: proveedores
  - Qué confirmar: si ya tienes archivados, con fecha, los contratos o acuerdos de tratamiento de datos de cada proveedor de la sección 2 (al 17-10-2026 no se localizó un acuerdo específico con Alibaba Cloud), escribe aquí: «Guardamos una copia fechada del contrato, los términos o el acuerdo de tratamiento de datos que aceptamos con cada uno.»; si no, pon true
  - Valor sugerido: Cuando se cumpla, escribe exactamente «Guardamos una copia fechada del contrato, los términos o el acuerdo de tratamiento de datos que aceptamos con cada uno.»; mientras no, `true` (no se publica nada en su lugar).
- **`VERIFICAR_ESCALAMIENTO`** · revisa: dueño · en: atencion-y-quejas
  - Qué confirmar: define quién revisa los escalamientos (de preferencia una persona distinta de quien respondió) y en qué plazo
  - Valor sugerido: Quién y en qué plazo, p. ej. «Si no estás de acuerdo con la respuesta, la revisa otra persona del equipo en un máximo de 5 días hábiles.»
- **`VERIFICAR_ESCALA_DE_SANCIONES`** · revisa: dueño · en: cero-venta, comunidad, moderacion, terminos-refugios
  - Qué confirmar: confirma la escala de sanciones, la duración de las suspensiones y la escala especial para Refugios verificados que cobren o vendan
  - Valor sugerido: `true` si confirmas la regla tal como está escrita. Si decides otra cosa, escribe la frase que debe publicarse en su lugar.
- **`VERIFICAR_ESTADO_DEL_REPORTE`** · revisa: dueño · en: moderacion
  - Qué confirmar: confirma si avisarás el resultado a quien reporta y si podrá consultar el estado de su reporte
  - Valor sugerido: P. ej. «Te avisamos por correo el resultado de tu reporte y puedes consultar su estado con tu folio.»; o `true` si la página ya dice lo que harás.
- **`VERIFICAR_ESTANDAR_DE_ENTREGA`** · revisa: dueño · en: adopcion-responsable
  - Qué confirmar: confirma el estándar de entrega que pedirás a los Refugios (esterilizado o fecha comprometida, vacunado, desparasitado y adopciones a otra ciudad solo con Refugios verificados)
  - Valor sugerido: `true` si confirmas la regla tal como está escrita. Si decides otra cosa, escribe la frase que debe publicarse en su lugar.
- **`VERIFICAR_EXCEPCION_MP_DONATIVOS`** · revisa: dueño · en: donativos, terminos-refugios
  - Qué confirmar: los Términos de Mercado Pago listan los donativos como actividad prohibida salvo excepción escrita; no actives los donativos sin esa respuesta y confirma si cada Refugio necesita la suya / confirmar por escrito con Mercado Pago si cada refugio necesita su propia excepción o inscripción para recibir donativos y si en Split se puede pagar con tarjeta
  - Valor sugerido: `true` solo con la excepción escrita de Mercado Pago (anota el caso en AUTORIZACION_DE_MERCADO_PAGO_PARA_DONATIVOS). Sin ella no actives los donativos.
- **`VERIFICAR_HORARIO_SILENCIOSO`** · revisa: dueño · en: comunicaciones
  - Qué confirmar: si las alertas por WhatsApp y correo respetarán un horario silencioso (propuesta: de 22:00 a 8:00) y si cada correo de alerta traerá un enlace para apagarlas en un clic; si es así, agrégalo a esta lista
  - Valor sugerido: Si se implementa: «No enviamos alertas por WhatsApp ni por correo de 22:00 a 8:00, y cada correo de alerta trae un enlace para apagarlas en un clic.»; si no, `true`.
- **`VERIFICAR_IA_ENTRENAMIENTO`** · revisa: dueño · en: ia-y-algoritmos, privacidad, proveedores
  - Qué confirmar: que el proveedor de IA contratado no use las fotos para entrenar modelos, y la entidad contratante / revisa los términos vigentes del proveedor de IA contratado sobre el uso del contenido para entrenar modelos
  - Valor sugerido: `true` si los términos del proveedor de IA contratado (AI_BASE_URL) dicen que no entrena modelos con tus fotos.
- **`VERIFICAR_IDENTIDAD_WHATSAPP`** · revisa: dueño · en: derechos-arco
  - Qué confirmar: cómo se comprueba la identidad de quien solo usó el bot
  - Valor sugerido: P. ej. «Si solo usaste el bot, comprobamos tu identidad con un código que enviamos a ese mismo número de WhatsApp.»
- **`VERIFICAR_INFORME_TRANSPARENCIA`** · revisa: dueño · en: informe-transparencia
  - Qué confirmar: confirma la periodicidad de los cortes, la fecha del primero y qué cifras del corte periódico se publicarán; ajusta la tabla de la sección 3
  - Valor sugerido: `true` si confirmas la regla tal como está escrita. Si decides otra cosa, escribe la frase que debe publicarse en su lugar.
- **`VERIFICAR_INSIGNIAS_REFUGIOS`** · revisa: dueño · en: directorio-refugios, terminos-refugios, verificacion
  - Qué confirmar: hoy el perfil del Refugio muestra una sola insignia; confirma si mostrará la fecha de verificación y si se agregarán insignias separadas (donataria autorizada comprobada en el SAT, padrón oficial), o ajusta este texto
  - Valor sugerido: `true` si confirmas la regla tal como está escrita. Si decides otra cosa, escribe la frase que debe publicarse en su lugar.
- **`VERIFICAR_INSIGNIA_WHATSAPP`** · revisa: dueño · en: canales-oficiales
  - Qué confirmar: confirma si el número oficial tiene la insignia de cuenta verificada de Meta; si la tiene, menciónalo aquí
  - Valor sugerido: Si tiene la insignia: «La cuenta muestra la insignia de cuenta verificada de Meta.»; si no, `true`.
- **`VERIFICAR_MANTENIMIENTOS`** · revisa: dueño · en: estado-del-servicio
  - Qué confirmar: define con cuánta anticipación y por qué medio se anunciarán los mantenimientos, y confirma que el tablero puede mostrarlos
  - Valor sugerido: P. ej. «Anunciamos los mantenimientos programados con al menos 48 horas de anticipación en este tablero y en la app.»
- **`VERIFICAR_MEDIDAS_FISICAS`** · revisa: dueño · en: seguridad
  - Qué confirmar: cuando definas dónde se guardan los escritos en papel que lleguen al domicilio, escribe aquí: «Los escritos en papel que nos entregues (por ejemplo, una solicitud de derechos) se guardan bajo llave y solo los consulta el personal autorizado.»; si no, pon true
  - Valor sugerido: Cuando se cumpla, escribe exactamente «Los escritos en papel que nos entregues (por ejemplo, una solicitud de derechos) se guardan bajo llave y solo los consulta el personal autorizado.»; mientras no, `true` (no se publica nada en su lugar).
- **`VERIFICAR_META_72_HORAS`** · revisa: dueño · en: seguridad
  - Qué confirmar: si el equipo puede comprometerse públicamente a un plazo, escribe aquí: «Nuestra meta interna es avisarte dentro de las 72 horas siguientes a confirmar el incidente, y antes si hay riesgo de fraude.»; si no, pon true
  - Valor sugerido: Cuando se cumpla, escribe exactamente «Nuestra meta interna es avisarte dentro de las 72 horas siguientes a confirmar el incidente, y antes si hay riesgo de fraude.»; mientras no, `true` (no se publica nada en su lugar).
- **`VERIFICAR_METRICAS_IA`** · revisa: dueño · en: ia-y-algoritmos
  - Qué confirmar: si el informe de transparencia incluirá métricas de la IA, como cuántas coincidencias sugeridas terminaron en reencuentro; si no, quita esta nota
  - Valor sugerido: `true` si no se publicarán; si sí: «El informe de transparencia incluye cuántas coincidencias sugeridas por la IA terminaron en reencuentro.»
- **`VERIFICAR_MODELO_CLINICAS`** · revisa: dueño · en: terminos-clinicas
  - Qué confirmar: el dueño confirma el modelo de la sección de clínicas: gratuita, sin cobro de consultas, sin agenda con pago, sin venta de productos y sin perfiles destacados de pago
  - Valor sugerido: `true` si confirmas la regla tal como está escrita. Si decides otra cosa, escribe la frase que debe publicarse en su lugar.
- **`VERIFICAR_MOTIVO_RECHAZO`** · revisa: dueño · en: ia-y-algoritmos
  - Qué confirmar: si la app pedirá a quien publica escribir un motivo al rechazar una solicitud y si mostrará el puntaje a quien se postula
  - Valor sugerido: `true` si confirmas la regla tal como está escrita. Si decides otra cosa, escribe la frase que debe publicarse en su lugar.
- **`VERIFICAR_NMX`** · revisa: dueño · en: centro-legal, compromisos, marco-legal, quienes-somos, terminos-tienda
  - Qué confirmar: publica esta frase solo después de completar la lista de verificación del numeral 14.3 de la NMX / publica esta frase solo después de completar la lista de verificación de la tabla 14.3 de la NMX; si aún no está completa, quítala
  - Valor sugerido: `true` cuando completes la lista de verificación del numeral 14.3 de la NMX-COE-001-SCFI-2018; si no la completarás, pide quitar la frase de la plantilla.
- **`VERIFICAR_PAIS_CARTO`** · revisa: dueño · en: privacidad, proveedores
  - Qué confirmar: país o región de los servidores de CARTO y sus términos
  - Valor sugerido: El país o región real, p. ej. «CARTO (Estados Unidos) sirve los mosaicos del mapa conforme a sus términos de uso.»
- **`VERIFICAR_PCI`** · revisa: dueño · en: seguridad
  - Qué confirmar: si ya respondiste y tienes archivado el cuestionario de seguridad de pagos PCI (SAQ A) que pide Mercado Pago, escribe aquí: «Respondemos cada año el cuestionario de seguridad de pagos (PCI) que Mercado Pago pide a los comercios.»; si no, pon true
  - Valor sugerido: Cuando se cumpla, escribe exactamente «Respondemos cada año el cuestionario de seguridad de pagos (PCI) que Mercado Pago pide a los comercios.»; mientras no, `true` (no se publica nada en su lugar).
- **`VERIFICAR_PLAZOS_DIVULGACION`** · revisa: dueño · en: seguridad
  - Qué confirmar: si el equipo puede comprometerse a acusar recibo en 3 días hábiles y a corregir las fallas críticas en 7 días; si es así, agrega esos plazos
  - Valor sugerido: Si el equipo se compromete: «Acusamos recibo en 3 días hábiles y corregimos las fallas críticas en 7 días.»; si no, `true`.
- **`VERIFICAR_PUBLICIDAD`** · revisa: dueño · en: compromisos
  - Qué confirmar: confirma que no hay anuncios ni contenido patrocinado; si los habrá, define cómo se identificará al anunciante
  - Valor sugerido: `true` si no hay anuncios ni contenido patrocinado; si los habrá, escribe cómo se identificará al anunciante.
- **`VERIFICAR_PUBLICIDAD_TELEFONICA`** · revisa: dueño · en: comunicaciones
  - Qué confirmar: confirma que no harás publicidad por llamada, SMS o WhatsApp; si la harás, pide un permiso aparte por canal y consulta el REPEP antes de cada campaña
  - Valor sugerido: `true` si no harás publicidad por llamada, SMS ni WhatsApp.
- **`VERIFICAR_REINCIDENTES`** · revisa: dueño · en: derechos-de-autor
  - Qué confirmar: confirma las cifras de la política de reincidentes
  - Valor sugerido: `true` si confirmas la regla tal como está escrita. Si decides otra cosa, escribe la frase que debe publicarse en su lugar.
- **`VERIFICAR_RESCATISTAS`** · revisa: dueño · en: terminos, terminos-refugios, verificacion
  - Qué confirmar: decidir si los colectivos y las personas rescatistas personas físicas pueden recibir donativos por la Plataforma y con qué límites / decide si habrá un tipo de cuenta propio para rescatistas independientes y si podrán recibir donativos por la Plataforma, con qué límites y transparencia / la app no tiene un tipo de cuenta separado para rescatistas independientes; define cómo se verifican y si pueden recibir donativos
  - Valor sugerido: `true` si mantienes la regla actual (las personas rescatistas se registran como Refugio); si creas otro tipo de cuenta, escribe la regla.
- **`VERIFICAR_REVISION_CONTENIDO_IMPORTADO`** · revisa: dueño · en: comunidad
  - Qué confirmar: hoy los reportes del bot, de personas voluntarias e importados se publican sin revisión humana previa; decide si deben pasar por revisión antes de mostrarse (bienestar-animal-v04) y ajusta este texto
  - Valor sugerido: `true` si confirmas la regla tal como está escrita. Si decides otra cosa, escribe la frase que debe publicarse en su lugar.
- **`VERIFICAR_REVISION_FISCAL_REFUGIOS`** · revisa: dueño · en: prevencion-lavado
  - Qué confirmar: hoy el sistema solo comprueba que el Refugio esté verificado y tenga una cuenta de Mercado Pago vinculada; no coteja quién es el titular de esa cuenta ni consulta el listado del SAT de contribuyentes con operaciones presuntamente inexistentes (Código Fiscal de la Federación, art. 69-B). Si se agregan esas revisiones para los Refugios que reciben dinero, pon como valor una frase que diga qué se revisa y cada cuánto; si no, pon true
  - Valor sugerido: `true` si confirmas la regla tal como está escrita. Si decides otra cosa, escribe la frase que debe publicarse en su lugar.
- **`VERIFICAR_REVISION_META`** · revisa: dueño · en: contenido-importado
  - Qué confirmar: responsable y calendario de la revisión semestral de las políticas de Meta y de su copia fechada
  - Valor sugerido: `true` si confirmas la regla tal como está escrita. Si decides otra cosa, escribe la frase que debe publicarse en su lugar.
- **`VERIFICAR_REVISION_PREVIA_PRODUCTOS`** · revisa: dueño · en: productos-prohibidos, terminos, terminos-tienda
  - Qué confirmar: hoy los productos de un Refugio verificado se publican sin revisión previa. Si se agrega una revisión de cada producto antes de publicarse, con lista de verificación de marcas y obras ajenas, pon como valor «También revisamos cada producto antes de publicarlo, incluida una lista de verificación de marcas y obras ajenas.»; si no, pon true / si un administrador aprueba cada producto antes de publicarlo, vuelve a decir «Revisamos cada producto antes de publicarlo»
  - Valor sugerido: Cuando se cumpla, escribe exactamente «También revisamos cada producto antes de publicarlo, incluida una lista de verificación de marcas y obras ajenas.»; mientras no, `true` (no se publica nada en su lugar).
- **`VERIFICAR_SABG_CANALES`** · revisa: dueño · en: atencion-y-quejas, derechos-arco, privacidad
  - Qué confirmar: confirma en gob.mx el sitio y los canales vigentes de la SABG antes de publicar / confirma en gob.mx el domicilio, el teléfono y los canales electrónicos vigentes de la SABG y de la PROFECO antes de publicar
  - Valor sugerido: `true` después de cotejar en gob.mx; si algún dato cambió, pide corregirlo en la plantilla antes.
- **`VERIFICAR_TELEFONO_SIN_COSTO`** · revisa: dueño · en: quienes-somos
  - Qué confirmar: el número no debe generar cargos especiales a quien llama; confirma que no es de tarificación adicional
  - Valor sugerido: `true` si TELEFONO es una línea normal o un 800 sin cargos extra para quien llama.
- **`VERIFICAR_TIPO_SOCIETARIO`** · revisa: dueño · en: quienes-somos
  - Qué confirmar: la razón social debe llevar el tipo societario o su abreviatura (por ejemplo, S.A.S. o S.A. de C.V.) y escribirse igual en todos los documentos
  - Valor sugerido: `true` cuando RAZON_SOCIAL lleve el tipo societario (p. ej. «S.A.S.») escrito igual que en tu acta constitutiva.
- **`VERIFICAR_VIGILANCIA_NORMATIVA`** · revisa: dueño · en: historial, marco-legal, marco-legal-bienestar-animal
  - Qué confirmar: confirma que tienes una persona responsable y un calendario para estas revisiones y para actualizar los documentos en 30 días / designa a la persona responsable de la vigilancia normativa y confirma este calendario
  - Valor sugerido: `true` cuando haya una persona responsable y un calendario (p. ej. revisión cada trimestre y documentos actualizados en 30 días).
<!-- claves:fin -->
