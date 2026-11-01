# Investigación legal de GuauWoow (México): documento consolidado

**Fecha de corte:** 17 de octubre de 2026 · **Alcance:** web app, landing, bot de WhatsApp, ingesta de grupos públicos de Facebook, tienda de refugios con cobro, donativos, clínicas veterinarias · **Público:** dueño, equipo, abogado y contador · **Archivo legible por máquina:** [requisitos.json](requisitos.json) · **Índice de la carpeta:** [README.md](README.md)

> **Esto no es asesoría legal ni fiscal.** Es la consolidación de una investigación verificada contra fuentes primarias (DOF, Cámara de Diputados, periódicos y congresos estatales, SAT, Banxico, PROFECO) y contra los términos publicados por Meta, Google y Mercado Pago, con fecha de corte **17 de octubre de 2026**. Antes de publicar cualquier página o activar cobros, un abogado mexicano (datos personales, consumo, regulación financiera y PLD, bienestar animal local y penal, según el tema) y un contador deben revisar los puntos marcados. Todo lo que tenga confianza **baja**, veredicto **no_verificable**, **no_revisado** o **agregado_por_verificador**, y toda interpretación marcada como **media**, requiere su confirmación expresa. Las cifras en pesos usan la UMA 2026 ($117.31).

**Cómo leer este documento.**

- **Prioridad:** *obligatorio* (lo exige una norma vigente o un contrato con un tercero del que depende el servicio), *recomendado* (reduce un riesgo real o anticipa una obligación), *buena práctica*.
- **Confianza:** *alta* (texto oficial vigente cotejado), *media* (texto verificado pero su aplicación a GuauWoow es interpretación, o la fuente es una compilación), *baja* (solo prensa, fuente no accesible o sin criterio de autoridad). Con *media* o *baja* no se publica sin abogado.
- **Estado actual:** *existe*, *parcial* o *falta*, según la lectura de `app/legal/` y del código el 17-10-2026. Otro flujo está editando el código en paralelo: reconfirmar cada estado contra la versión final antes del lanzamiento.
- **Hallazgos:** identificadores de la investigación. Abreviaturas: DP datos-personales, CE consumidor-ecommerce, FT fiscal-tienda, DON donativos, BA bienestar-animal, CP contenido-plataforma, CC comunicaciones-cookies, SI seguridad-incidentes, IC identidad-contratos, BP buenas-practicas, NNA gap del Decreto NNA, CF gap de custodia de fondos y Mercado Pago, AD gap de naturaleza jurídica de la adopción y cuotas, VET gap de veterinarias y reseñas, EST gap de cobertura estatal de bienestar animal. Ejemplo: `CF-05` = `gap-custodia-fondos-transmisor-dinero-y-terminos-mercado-pago-05`.
- El detalle de cada tema (citas textuales, procedimientos y textos propuestos) está en los archivos de `secciones/`, enlazados en cada apartado.

## Contenido

1. Resumen ejecutivo
2. Marco legal vigente al 2026-10-17
3. Páginas del Centro Legal y de Transparencia
4. Matriz de cumplimiento consolidada
5. Modelo fiscal y operativo recomendado para tienda y donativos
6. Calendario de retención
7. Proveedores, encargados y transferencias
8. Reglas de comunicaciones y consentimiento
9. Reglas de adopción y bienestar animal
10. Procedimiento de retiro de contenido y reportes
11. Seguridad e incidentes
12. Veterinarias y reseñas
13. Ingesta de grupos públicos de Facebook
14. Conflictos resueltos
15. Fechas clave
16. Riesgos principales
17. Datos que debe aportar el dueño
18. Puntos para abogado y contador
19. Archivos de detalle por sección
20. Aviso: no es asesoría legal

## 1. Resumen ejecutivo

GuauWoow lanzará para unas 5,000 personas con adopción, perdidos y encontrados con IA, chat, bot de WhatsApp, ingesta de grupos públicos de Facebook, tienda de refugios con cobro, envíos, CFDI y comisión, donativos y un directorio de clínicas veterinarias. Hoy el centro legal tiene **dos documentos** (`app/legal/terminos.html` y `app/legal/privacidad.html`, más el aviso simplificado) con **todos los datos de identidad vacíos** en `app/legal/datos-legales.json`. Este documento define **56 páginas públicas** (de ellas **39 bloqueantes** para el lanzamiento) y **3 documentos internos**, y una matriz de **134 requisitos** (99 obligatorios; 56 faltan por completo y 66 están parciales).

**Diez decisiones y acciones que no pueden esperar:**

1. **Identidad del operador.** Constituir (o confirmar) una persona moral mercantil y llenar razón social, RFC, domicilio físico, contactos y departamento de datos personales. Sin esto no se puede cobrar ni publicar el aviso (LFPC art. 76 Bis fr. III; LFPDPPP arts. 15 y 29). `backend/scripts/deploy.sh` ya revisa los marcadores con `scripts/render-legal.py --check` (en CI esa revisión no bloquea): no desplegar a producción con `--allow-legal-placeholders`.
2. **Decreto de entornos digitales seguros para NNA (DOF 14-10-2026).** Aplica aunque GuauWoow sea 18+. Entregar el informe a más tardar el **12-11-2026** (confirmar el canal con la ATDT antes del 05-11-2026), con verificación de edad por capas (la casilla 18+ ya no basta), criterios de retiro publicados, reporte sin cuenta, contacto 24/7 para autoridades y bóveda de evidencia de 90 días hábiles.
3. **Dinero sin custodia.** No recibir donativos ni ventas de refugios en la cuenta de Mercado Pago de la plataforma para luego dispersarlos: choca con la cláusula 9.6 de Mercado Pago y su lista de actividades prohibidas («Donativos»), y se parece a un transmisor de dinero (LGOAAC art. 81-A Bis). Usar **Split 1:1** por refugio: ya está en desarrollo para tienda y donativos (`services/mercadopago_oauth.py`, con renovación de tokens); el respaldo que cobra con la cuenta de la plataforma (`DONATIONS_FALLBACK_TO_PLATFORM_ACCOUNT`) debe quedar apagado en producción. Pedir por escrito la excepción de Mercado Pago antes de cobrar donativos.
4. **Comisión.** El código trae `MERCADOPAGO_MARKETPLACE_FEE_PERCENT=10` por defecto para la tienda (0 % en donativos) y ya prepara CFDI de comisión y de retenciones (`services/invoicing.py`). Con comisión mayor que 0 se activa desde el primer cobro todo el régimen de plataformas: además de esos CFDI, alta como retenedor, informativa mensual y acceso en línea del SAT (CFF art. 30-B), que aún no existen. Recomendación: **comisión 0 hasta que el contador libere la puerta fiscal**.
5. **Adopción gratuita, sin cuotas.** Ninguna cuota, reembolso, apartado ni «donativo sugerido» ligado a la entrega del perro (regla de cuatro niveles). El bot de WhatsApp no gestiona adopciones.
6. **Tienda.** Antes de `SHOP_ENABLED=true`: precio total, paso «Revisa tu pedido», comprobante, revocación de 5 días hábiles y devoluciones (en desarrollo), defectos con bonificación de 20 %, política de envíos, CFDI en 24 horas (el refugio emite el de venta; la plataforma, el de comisión), productos prohibidos y cláusulas abusivas eliminadas.
7. **Ingesta de grupos de Facebook.** El código ya depura teléfonos, correos, @usuarios y enlaces y marca como expirados los reportes a los 30 días. Falta: dictamen sobre la base jurídica (no son fuente de acceso público) y sobre el riesgo contractual con Meta; quitar nombres y rostros; borrado real a los 30 días; botón de retiro para el autor. No activar en producción sin el dictamen.
8. **Datos personales.** Alertas cercanas solo con opt-in (hoy `notify_nearby=True` por defecto); compartir contacto del adoptante solo con cláusula y casilla; INE y actas cifradas y borradas a 30 días (el aviso dice 24 meses); bitácora inmutable de aceptaciones; banner de cookies exacto y siempre visible.
9. **Clínicas veterinarias.** El código ya aplica lo esencial de la investigación (cédula cotejada y caducidad anual, deslinde y aviso de urgencias en el perfil, solo `place_id` de Google en tiempo real, reseñas con teléfono verificado, etiqueta de incentivo y respuesta de la clínica, retención para revisión humana). Faltan las páginas públicas, el anexo de Términos, los plazos de moderación publicados, la aclaración y el formulario público.
10. **Conservación.** Calendario único: 10 años para contratos, aceptaciones, pedidos, donativos y ledger (operador comerciante, CCom arts. 38 y 49); 5 años fiscales desde la declaración (CFF art. 30), cubiertos por lo anterior; 10 años LFPIORPI; al menos 90 días hábiles para evidencia de retiros (Decreto NNA); máximo 72 meses para datos de incumplimientos (LFPDPPP art. 10); y purgas automáticas que hoy no existen.

**Fechas duras:** 05-11-2026 (canal del informe NNA), 12-11-2026 (informe NNA), 30-11-2026 (reglas LFPIORPI para asociaciones), 01-01-2027 (reforma fiscal 2027 si se publica), alrededor del 03-02-2027 (formulario obligatorio de derechos de autor).

## 2. Marco legal vigente al 2026-10-17

Estado verificado en los textos oficiales (Cámara de Diputados, DOF, congresos y periódicos oficiales estatales, SAT, Banxico) y en los términos publicados por los proveedores. Las fechas de «última reforma» son las de la ficha oficial. Detalle por tema en la sección «Marco legal vigente» de cada archivo de `secciones/`.

### Constitución, datos y menores

| Norma | Estado al 17-10-2026 | Qué regula para GuauWoow | Enlace oficial |
|---|---|---|---|
| Constitución Política de los Estados Unidos Mexicanos (CPEUM) | Vigente. Última reforma DOF 07-10-2026 (decreto que reformó los arts. 82, 116 y 122). El art. 16 no cambió: su última reforma es DOF 30-09-2024 (último párrafo). Art. 4 (prohibición del maltrato animal) adicionado DOF 02-12-2024. | Art. 16: protección de datos, actos de autoridad fundados y motivados, inviolabilidad de comunicaciones privadas (chat). Art. 4: base de las reglas de bienestar animal. Arts. 6 y 7: libertad de expresión (reseñas). | https://www.diputados.gob.mx/LeyesBiblio/pdf/CPEUM.pdf |
| Ley Federal de Protección de Datos Personales en Posesión de los Particulares (LFPDPPP) | Nueva ley DOF 20-03-2025, vigente desde el 21-03-2025; única reforma DOF 14-11-2025 (art. 4, supletoriedad del CNPCF). Autoridad: Secretaría Anticorrupción y Buen Gobierno (SABG). Sin reglamento nuevo. | Aviso de privacidad (arts. 14-17), consentimiento (7-9), fuentes de acceso público (2 fr. X), encargados y transferencias (2 fr. XII y XX, 35, 36), ARCO (21-34), seguridad y vulneraciones (18-20), conservación (10, 24, 25), sanciones (58-64). | https://www.diputados.gob.mx/LeyesBiblio/pdf/LFPDPPP.pdf |
| Reglamento de la LFPDPPP | DOF 21-12-2011, sin reformas; expedido para la ley abrogada de 2010. Sin sustituto pese al transitorio Décimo Segundo de la ley de 2025. Postura unificada: aplicable en lo que no se oponga a la ley de 2025 (ver Conflictos resueltos). | Referencia para cookies (art. 14), medidas compensatorias (32-35), encargados (49-55), vulneraciones (63-66), ARCO (87-111). | https://www.diputados.gob.mx/LeyesBiblio/regley/Reg_LFPDPPP.pdf |
| Lineamientos del Aviso de Privacidad (Secretaría de Economía) | DOF 17-01-2013, sin derogación expresa; misma postura que el Reglamento. | Forma del aviso: lenguaje claro, sin «por ejemplo», casillas no premarcadas, cookies (Trigésimo primero), cambios (Trigésimo segundo y tercero). | https://www.economia.gob.mx/files/marco_normativo/LIN6.pdf |
| Criterios Generales para la Instrumentación de Medidas Compensatorias (IFAI) | DOF 18-04-2012, formalmente vigentes; solo eximen de autorización en supuestos acotados. | Ingesta de publicaciones de Facebook cuando no es posible dar el aviso al autor. | https://dof.gob.mx/nota_detalle.php?codigo=5244229&fecha=18/04/2012 |
| Recomendaciones en materia de seguridad de datos personales (IFAI) | DOF 30-10-2013; orientativas. | SGSDP y documento de seguridad; su cumplimiento puede atenuar sanciones. | https://www.dof.gob.mx/nota_detalle.php?codigo=5320179&fecha=30/10/2013 |
| Reglamento Interior de la SABG (reforma DOF 21-03-2025) | Vigente. Crea la Unidad de Protección de Datos Personales y la Dirección General de Datos Personales en el Sector Privado. | Autoridad de quejas, verificaciones y autorización de medidas compensatorias. | https://dof.gob.mx/nota_detalle.php?codigo=5752650&fecha=21/03/2025 |
| Decreto de entornos digitales seguros para niñas, niños y adolescentes (Decreto NNA) | DOF 14-10-2026, edición vespertina; vigente desde el 14-10-2026. Decreto presidencial (CPEUM art. 89 fr. I) que no reforma la LGDNNA; sin sanciones propias. Informe de implementación en 30 días naturales. | Verificación de edad que no se limite a la autodeclaración (art. 4 fr. I), criterios publicados y retiro inmediato (art. 4), contacto 24/7 para autoridades, evidencia 90 días hábiles y alerta inmediata (art. 5). | https://dof.gob.mx/nota_detalle.php?codigo=5801237&fecha=14/10/2026 |
| Ley General de los Derechos de Niñas, Niños y Adolescentes (LGDNNA) | Vigente; última reforma DOF 15-01-2026 (el Decreto NNA no la reformó). | Art. 5 (presunción de adolescencia en caso de duda), art. 76 (intimidad e imagen de NNA), arts. 101 Bis 2 y 101 Bis 3 (fundamento del decreto). | https://www.diputados.gob.mx/LeyesBiblio/pdf/LGDNNA.pdf |
| Código Nacional de Procedimientos Penales (CNPP) | Vigente; última reforma DOF 28-11-2025. | Arts. 222 (denuncia), 291 (extracción de información almacenada solo con autorización judicial) y 303 (localización y datos conservados con orden del juez de control). | https://www.diputados.gob.mx/LeyesBiblio/pdf/CNPP.pdf |
| Código Penal Federal (CPF) | Vigente; última reforma DOF 13-03-2026. | Arts. 177 (intervención de comunicaciones), 202 y 202 Bis (material de abuso infantil), 211 bis 1-7 (delitos informáticos), 250 fr. II (usurpación de profesión), 382 (abuso de confianza), 419 Bis y 420 fr. IV (peleas de perros, fauna). | https://www.diputados.gob.mx/LeyesBiblio/pdf/CPF.pdf |
| Ley en Materia de Telecomunicaciones y Radiodifusión (LMTR) y Ley del Sistema Nacional de Investigación e Inteligencia en Materia de Seguridad Pública (LSNIIMSP) | Ambas DOF 16-07-2025 (la LMTR abrogó la LFTR). | LMTR art. 182 (colaboración de proveedores de aplicaciones y contenidos); LSNIIMSP art. 26 (colaboración observando la LFPDPPP). | https://www.diputados.gob.mx/LeyesBiblio/pdf/LMTR.pdf |
| Ley Federal de Procedimiento Administrativo (LFPA) | Vigente; última reforma DOF 14-11-2025; supletoria de la LFPDPPP. | Art. 28 (días hábiles, referencia para plazos ARCO y para los 90 días hábiles del Decreto NNA); art. 79 (prescripción de la facultad sancionadora en 5 años). | https://www.diputados.gob.mx/LeyesBiblio/pdf/LFPA.pdf |

### Consumo, comercio y contratación

| Norma | Estado al 17-10-2026 | Qué regula para GuauWoow | Enlace oficial |
|---|---|---|---|
| Ley Federal de Protección al Consumidor (LFPC) | Vigente; última reforma DOF 12-12-2025 (art. 76 Bis fr. VIII y IX: cobros recurrentes y cancelación inmediata). Montos de multas 2026: Acuerdo DOF 23-12-2025. | Precio total (7 Bis), publicidad (32-35), promociones (46-50), venta a distancia y revocación (51-56), garantías (77-84), adhesión y cláusulas abusivas (85-90), reclamaciones (92-93), comercio electrónico (76 Bis y 76 Bis 1), publicidad directa y REPEP (16-18 Bis). | https://www.diputados.gob.mx/LeyesBiblio/pdf/LFPC.pdf |
| Reglamento de la LFPC | DOF 19-12-2019, vigente. | Precio total con envío (arts. 5-6), comprobante electrónico, REPEP (60-61). | https://www.diputados.gob.mx/LeyesBiblio/regley/Reg_LFPC_191219.pdf |
| NMX-COE-001-SCFI-2018, Comercio electrónico | Vigente (declaratoria DOF 30-04-2019). Norma voluntaria, pero el art. 76 Bis 1 LFPC (adicionado DOF 11-01-2018) ordena al proveedor «guiarse» por ella. | Contenido mínimo de términos, información del producto, resumen y aceptación, pagos, entregas, atención, devoluciones, reseñas, declaración de cumplimiento. | https://platiica.economia.gob.mx/normalizacion/wp-content/uploads/sites/2/PDF_Normas_Publicas/NMX-COE-001-SCFI-2018.pdf |
| Código de Ética en materia de Comercio Electrónico (PROFECO) | Acuerdo DOF 26-02-2021; adhesión voluntaria y vinculante una vez adoptado. | Autorregulación opcional y Distintivo Digital. | https://dof.gob.mx/nota_detalle.php?codigo=5612351&fecha=26/02/2021 |
| Código de Comercio (CCom) | Vigente; última reforma DOF 14-11-2025. | Comerciantes (art. 3), conservación 10 años de comprobantes y contratos (38 y 49), mensajes de datos (89 bis-93 bis), comisión mercantil (273-285, 298), prescripción (1047). | https://www.diputados.gob.mx/LeyesBiblio/pdf/CCom.pdf |
| NOM-151-SCFI-2016 (conservación de mensajes de datos) | Vigente; DOF 30-03-2017. | Constancias opcionales de conservación de versiones legales y aceptaciones. | https://platiica.economia.gob.mx/normalizacion/nom-151-scfi-2016/ |
| NOM de etiquetado: NOM-050-SCFI-2004, NOM-004-SE-2021, NOM-024-SCFI-2013 y NOM-012-SAG/ZOO-2020 | Vigentes (NOM-004-SE-2021 desde 14-01-2023; NOM-012-SAG/ZOO-2020 DOF 06-11-2023). | Etiquetado de accesorios, ropa para perro, electrónicos y alimentos o premios para animales que se vendan en la tienda. | https://platiica.economia.gob.mx/normalizacion/nom-050-scfi-2004/ |
| Ley Federal de Sanidad Animal (LFSA) y su Reglamento | LFSA última reforma DOF 21-05-2024; Reglamento DOF 21-05-2012. | Registro de productos para uso o consumo animal (art. 92); establecimientos veterinarios, aviso de inicio de funcionamiento y médico veterinario responsable autorizado. | https://www.diputados.gob.mx/LeyesBiblio/pdf/LFSA.pdf |
| NOM-148-SCFI-2018 (comercialización de animales de compañía) | Vigente (DOF 28-03-2019; revisión 2024 «Confirmación»). | Solo alcanza a proveedores con establecimiento abierto al público que cobran precio; refuerza que GuauWoow no aloje ventas ni cuotas. | https://www.dof.gob.mx/nota_detalle.php?codigo=5555453&fecha=28/03/2019 |
| Ley Federal de Juegos y Sorteos y su Reglamento | LFJS DOF 31-12-1947; Reglamento con última reforma DOF 16-11-2023. | Rifas y sorteos solo con permiso de SEGOB: se prohíben en la plataforma. | https://www.diputados.gob.mx/LeyesBiblio/pdf/LFJS.pdf |

### Civil, propiedad intelectual y profesiones

| Norma | Estado al 17-10-2026 | Qué regula para GuauWoow | Enlace oficial |
|---|---|---|---|
| Código Civil Federal (CCF) y Código Civil para el Distrito Federal (CDMX) | CCF última reforma DOF 14-11-2025; Código Civil CDMX última reforma G.O. 20-08-2026 (art. 855 Bis: animales como seres sintientes, desde 29-10-2025). La materia civil es local. | Adopción como donación con cargas (2332, 2336, 2337) frente a compraventa (2248); forma (2341-2344); hallazgo de animales (774, 775, 874); daño moral (1916); mayoría de edad (646); contratación electrónica (1803, 1834 bis). | https://www.diputados.gob.mx/LeyesBiblio/pdf/CCF.pdf |
| Ley Federal del Derecho de Autor (LFDA) | Vigente; última reforma DOF 14-05-2026 (art. 87 reformado). | Puerto seguro, aviso y contra-aviso, staydown y reincidentes (114 Septies y 114 Octies), multas (232 Quinquies), cesiones por escrito (30, 83, 84, 103). | https://www.diputados.gob.mx/LeyesBiblio/pdf/LFDA.pdf |
| Reglamento de la LFDA, adición de los arts. 37 Bis a 37 Nonies | Publicado DOF 24-09-2026; entra en vigor a los 90 días hábiles (alrededor del 03-02-2027). Los avisos previos se tramitan con las reglas vigentes al presentarse. | Formulario claro y accesible de aviso, prohibición de exigir certificados, contra-aviso. | https://dof.gob.mx/nota_detalle.php?codigo=5799437&fecha=24/09/2026 |
| Ley Federal de Protección a la Propiedad Industrial (LFPPI) | Vigente; última reforma DOF 03-04-2026. | Registro de la marca GuauWoow; prohibición de usar ® sin registro; órdenes del IMPI sobre productos. | https://www.diputados.gob.mx/LeyesBiblio/pdf/LFPPI.pdf |
| Ley de Responsabilidad Civil para la Protección del Derecho a la Vida Privada, el Honor y la Propia Imagen en el Distrito Federal | Vigente en la CDMX; última reforma G.O. 28-11-2014. En otros estados rige su código civil. | Daño moral por reseñas y acusaciones; estándar de negligencia inexcusable (art. 32); prescripción de 2 años (art. 38). | https://www.congresocdmx.gob.mx/media/documentos/020734b421dbff59f4d3fc5c7381375f853b091d.pdf |
| Ley Reglamentaria del Artículo 6o. constitucional en materia del Derecho de Réplica | Vigente; última reforma DOF 14-11-2025. | Probablemente no obliga a GuauWoow (interpretación); se adopta un procedimiento voluntario de aclaración. | https://www.diputados.gob.mx/LeyesBiblio/pdf/LRArt6_MDR.pdf |
| Ley General de Salud (arts. 79 y 83) y Ley Reglamentaria del Artículo 5o. Constitucional (profesiones) | LGS últimas reformas DOF 15-01-2026; Ley de Profesiones última reforma DOF 19-01-2018. | Cédula para ejercer la medicina veterinaria y mostrarla en la publicidad; responsabilidad del profesionista. | https://www.diputados.gob.mx/LeyesBiblio/pdf/LGS.pdf |
| Ley General de Acceso de las Mujeres a una Vida Libre de Violencias (Ley Olimpia) | Vigente (nuevo nombre desde DOF 15-01-2026). | Arts. 20 Quáter a 20 Sexies: órdenes de retiro de contenido íntimo, aviso y resguardo. | https://www.diputados.gob.mx/LeyesBiblio/pdf/LGAMVLV.pdf |
| Accesibilidad: LFPED, LGIPD y LFPC art. 58 | Vigentes. | No discriminación y ajustes razonables en el sitio. | https://www.diputados.gob.mx/LeyesBiblio/pdf/LFPED.pdf |

### Fiscal, pagos y prevención de lavado

| Norma | Estado al 17-10-2026 | Qué regula para GuauWoow | Enlace oficial |
|---|---|---|---|
| Código Fiscal de la Federación (CFF) | Vigente; última reforma DOF 09-04-2026 (solo art. 141); decreto de fondo DOF 07-11-2025 (art. 30-B en vigor 01-04-2026). | CFDI en 24 h (29, 29-A), conservación 5 años desde la declaración (30), acceso en línea del SAT para plataformas (30-B), presunción de ingresos por depósitos (59 fr. III), facturas falsas (113 Bis), beneficiario controlador (32-B Ter a Quinquies). | https://www.diputados.gob.mx/LeyesBiblio/pdf/CFF.pdf |
| Ley del Impuesto sobre la Renta (LISR) | Vigente; última reforma DOF 01-04-2024. Alerta: reforma 2027 aprobada por Diputados el 14-10-2026, pendiente de Senado y DOF. | Donatarias (79 fr. XIX y XXV inciso e, 80, 82, 82-Quáter), deducibilidad (27 fr. I, 151 fr. III), retenciones a vendedores por plataformas (113-A, 113-C). | https://www.diputados.gob.mx/LeyesBiblio/pdf/LISR.pdf |
| Ley del Impuesto al Valor Agregado (LIVA) | Vigente; última reforma DOF 12-11-2021. | Intermediación digital (1o.-A Bis, 18-B fr. II, 18-J), tasa por producto y exclusión de los perros de la tasa 0 % (2o.-A fr. I a), comisión como servicio (14 fr. IV). | https://www.diputados.gob.mx/LeyesBiblio/pdf/LIVA.pdf |
| Ley de Ingresos de la Federación 2026 (LIF 2026) | DOF 07-11-2025; vigente en 2026. La LIF 2027 fue aprobada por Diputados el 15-10-2026 (pendiente). | Art. 25 fr. VI y IX: tasas de retención de ISR e IVA por plataformas, incluidas personas morales. | https://www.diputados.gob.mx/LeyesBiblio/pdf/LIF_2026.pdf |
| Resolución Miscelánea Fiscal 2026 (RMF 2026) y sus modificaciones | DOF 28-12-2025; 1a modificación DOF 09-07-2026; 2a modificación DOF 01-10-2026 (reglas 9.4.4 y 11.7.3, transitorio Vigésimo Noveno sobre vigencia 2027 de donatarias); 3a modificación DOF 02-10-2026 (Anexo 7, en vigor 31-12-2026). Ninguna toca las reglas 2.7.1.3, 2.7.1.21, 2.7.1.23, 2.7.1.35, 2.9.21 ni el capítulo 12. | Factura a cuenta de terceros (2.7.1.3), factura global (2.7.1.21), cancelación (2.7.1.35), acceso del SAT (2.9.21), plataformas (12.2.x, 12.3.x), donatarias (3.10.x). | https://www.sat.gob.mx/minisitio/NormatividadRMFyRGCE/documentos2026/rmf/rmf/RMF_2026-DOF-28122025.pdf |
| Ley Federal para la Prevención e Identificación de Operaciones con Recursos de Procedencia Ilícita (LFPIORPI), su Reglamento y Reglas de Carácter General | Ley: última reforma DOF 16-07-2025. Reglamento: DOF 27-03-2026. Acuerdo 115/2026 (DOF 07-08-2026) entra en vigor el 30-11-2026; evaluación de riesgo y manual exigibles desde 01-03-2027. | Donativos a asociaciones (17 fr. XIII: identificación desde 1,605 UMA, aviso desde 3,210 UMA), administración de recursos de terceros (17 fr. XI), sorteos (17 fr. I), conservación 10 años (18 fr. IV). | https://www.diputados.gob.mx/LeyesBiblio/pdf/LFPIORPI.pdf |
| Ley General de Organizaciones y Actividades Auxiliares del Crédito (LGOAAC) | Vigente; última reforma DOF 14-11-2025. | Transmisor de dinero (81-A Bis), registro ante la CNBV (81-B), suspensión y clausura (64), régimen antilavado (95 Bis): riesgo de la cuenta concentradora. | https://www.diputados.gob.mx/LeyesBiblio/pdf/LGOAAC.pdf |
| Ley para Regular las Instituciones de Tecnología Financiera (LRITF) y Ley de Instituciones de Crédito (LIC) | Ambas con última reforma DOF 14-11-2025. | Fondos de pago electrónico reservados a IFPE (LRITF 22-24, 124), denominaciones reservadas (12), captación (LIC 2 y 103): sin saldos, monederos ni puntos canjeables. | https://www.diputados.gob.mx/LeyesBiblio/pdf/LRITF.pdf |
| Disposiciones de carácter general aplicables a las Redes de Medios de Disposición (CNBV y Banxico) | DOF 11-03-2014, modificadas DOF 02-04-2015 y 27-04-2026; nuevas Disposiciones en consulta (agosto-septiembre de 2026). | GuauWoow como receptor de pagos; cobrar para terceros es aceptación indirecta. | https://www.banxico.org.mx/marco-normativo/normativa-emitida-por-el-banco-de-mexico/reglas-conjuntas-redes-de-medios-de-disposicion/%7B794002B6-5DA6-BEBA-08AD-F210963C1E11%7D.pdf |
| Ley Federal de Fomento a las Actividades Realizadas por Organizaciones de la Sociedad Civil (LFFAOSC) | Vigente; última reforma DOF 01-04-2024. | Art. 5 fr. XII (protección del ambiente, la flora y la fauna): coincide con LISR 79 fr. XXV inciso e). | https://www.diputados.gob.mx/LeyesBiblio/pdf/LFFAOSC.pdf |
| Unidad de Medida y Actualización (UMA) 2026 | $117.31 diarios, vigente del 01-02-2026 al 31-01-2027 (DOF 09-01-2026). | Umbrales LFPIORPI (1,605 UMA = $188,282.55; 3,210 UMA = $376,565.10) y multas. | https://www.inegi.org.mx/temas/uma/ |

### Bienestar animal

| Norma | Estado al 17-10-2026 | Qué regula para GuauWoow | Enlace oficial |
|---|---|---|---|
| Ley de Protección y Bienestar de los Animales de la Ciudad de México | Vigente; última reforma G.O. CDMX 23-07-2026 (art. 25 Bis en vigor desde el 24-07-2026; persona rescatista independiente; art. 24 Ter). | Solo comerciantes con registro pueden anunciar perros y gatos en plataformas digitales (25 Bis); prohibiciones de rifa, regalo y venta en vía pública (25); deber de informar maltrato (26). | https://data.consejeria.cdmx.gob.mx/images/leyes/2025/2026/190126/LEY_DE_PROTECCION_Y_BIENESTAR_DE_LOS_ANIMALES_DE_LA_CDMX_1.2.pdf |
| Ley de Protección, Cuidado y Bienestar Animal del Estado de México | Vigente desde el 17-06-2026 (Gaceta del Gobierno 16-06-2026, Decreto 333). | Prohibida la venta desde domicilios particulares (40 fr. V); registros; plazos de reclamo (34, 57). | https://legislacion.edomex.gob.mx/sites/legislacion.edomex.gob.mx/files/files/pdf/ley/vig/leyvig295.pdf |
| Leyes de Jalisco y Nuevo León | Cotejadas en compilaciones (CNDH 2021; legismex 2025): confianza media, cotejar con el periódico oficial. | Eventos de adopción, albergues, registros, plazos de reclamo. | https://normas.cndh.org.mx/Documentos/Jalisco/Ley_PCAE_Jal.pdf |
| Leyes de Puebla, Guanajuato, Veracruz, Querétaro, Baja California, Chihuahua, Yucatán, Quintana Roo, Michoacán, Sonora y Coahuila | Vigentes con distintos grados de cotejo (texto oficial, compilación o boletín escaneado); Veracruz, Baja California y Michoacán tienen reformas recientes sin cotejar. | Venta en internet (Coahuila 20 fr. III, Sonora 44 fr. VII, Chihuahua 21 Ter), requisitos de entrega en adopción, padrones de refugios, plazos de reclamo, autoridades de denuncia. | [ver secciones/gap-cobertura-estatal-bienestar-animal-y-ley-general.md](secciones/gap-cobertura-estatal-bienestar-animal-y-ley-general.md) (un enlace oficial por estado) |
| Ley General en Materia de Bienestar, Cuidado y Protección de los Animales | NO vigente. Minuta aprobada por el Senado el 29-09-2026; pendiente en la Cámara de Diputados; sin publicación en el DOF al 17-10-2026. | Si se publica: prohibición de difundir ventas sin registro en plataformas (art. 52 fr. III), Registro Nacional, padrón de infractores. | http://sil.gobernacion.gob.mx/Archivos/Documentos/2026/09/asun_5145795_20260929_1790696792.pdf |

### Contratos de terceros (no son ley)

| Norma | Estado al 17-10-2026 | Qué regula para GuauWoow | Enlace oficial |
|---|---|---|---|
| Términos y Condiciones de Mercado Pago Standard y Actividades Prohibidas | Vigentes desde el 07-06-2025; consultados el 17-10-2026. Términos para Desarrolladores: última modificación 14-08-2024. | Uso solo en nombre propio (9.6), excepciones expresas (4.7), «Donativos» como actividad prohibida sin excepción, retenciones y contracargos (5.2-5.9), aviso de incidentes en 24 h. | https://www.mercadopago.com.mx/ayuda/terminos-y-condiciones_299 |
| Meta: Platform Terms, Automated Data Collection Terms, WhatsApp Business Messaging Policy, Meta Terms for WhatsApp Business Platform y Commerce Policies | Platform Terms 03-02-2026; Automated Data Collection Terms 07-10-2024; WhatsApp Business Messaging Policy y Terms for WhatsApp Business Platform 23-09-2026. | Opt-in y bajas, animales vivos como categoría restringida, no compartir datos del bot con terceros, eliminación de datos, reporte de vulnerabilidades, prohibición de recolección automatizada sin permiso escrito. | https://whatsappbusiness.com/policy/ |
| Google: API Services User Data Policy, Google Maps Platform Terms of Service, Service Specific Terms y políticas de Places API | User Data Policy 15-02-2024; Maps ToS 26-08-2026; Service Specific Terms 15-10-2026; políticas de Places 15-10-2026. | Inicio de sesión con Google; reseñas de Google solo en tiempo real, con atribución, sin caché y nunca junto a un mapa que no sea de Google. | https://cloud.google.com/maps-platform/terms |
| PCI DSS v4.0.1 y SAQ A | Estándar contractual vigente desde 31-03-2025. | Checkout Pro sin almacenar datos de tarjeta. | https://blog.pcisecuritystandards.org/important-updates-announced-for-merchants-validating-to-self-assessment-questionnaire-a |

**Lo que no existe en el derecho vigente** (para no prometerlo ni temerlo):

- No existe ley federal o general de ciberseguridad (índice de LeyesBiblio revisado el 17-10-2026).
- No existe ley general de inteligencia artificial publicada en el DOF; hay una iniciativa del 22-09-2026 para informar sobre IA en la LFPDPPP (no vigente).
- La LFPDPPP 2025 no reconoce portabilidad a particulares, no obliga a notificar vulneraciones a la SABG ni exige consentimiento previo para cookies (sí informar y explicar cómo deshabilitarlas).
- La Ley General de bienestar animal no está vigente.

**Normas en trámite que se vigilan** (no vigentes):

| Tema | Estado | Acción |
|---|---|---|
| Reforma a la LISR 2027 y LIF 2027 | Aprobadas por Diputados el 14 y 15-10-2026; Senado debe resolver a más tardar el 31-10-2026; vigor previsto 01-01-2027. | Retenciones a plataformas pasarían a la LISR; actualizar tasas en diciembre de 2026. |
| Minuta de reforma a los arts. 18 Bis y 127 de la LFPC | Aprobada por el Senado el 07-10-2026; no publicada. | Endurecería el contacto comercial no autorizado. |
| Ley General de bienestar animal | Pendiente en Diputados. | Revisión semanal del DOF y de la Gaceta. |
| Nuevas Disposiciones de Redes de Medios de Disposición | Consulta pública cerrada el 24-09-2026. | Repetir el análisis de receptor de pagos al publicarse. |
| Actualización de la LFPDPPP y reglamento nuevo | Proceso anunciado por la SABG (28-01-2026, fuente secundaria); sin borrador. | Revisión trimestral. |
| Mesa de Trabajo del Decreto NNA (CJEF) | Transitorio Tercero; posible regulación adicional. | Revisión mensual de DOF, gob.mx/atdt y gob.mx/cjef. |
| Reforma de Veracruz (15-10-2026) y reformas de Baja California 2026 | Aprobadas o reportadas sin publicación cotejada. | Cotejo con abogado local. |

## 3. Páginas del Centro Legal y de Transparencia

Conjunto completo de páginas para el «centro legal y de transparencia» pedido por el dueño, deduplicado a partir de las propuestas de todas las secciones (el contenido mínimo de cada página, con su fundamento y las secciones de origen, está en `requisitos.json` → `pages`). Prioridad: *bloqueante* = antes del lanzamiento; *lanzamiento* = recomendada al lanzar; *posterior* = primeros meses. El enlace «Legal y transparencia» va en el pie de la landing, de la app, de la página 404, de todos los correos, del checkout y en el menú del bot; todas las rutas públicas se agregan a `sitemap.xml`.

### Hub e identidad

| Página | Ruta | Para quién | Prioridad | Estado actual | Qué debe contener (mínimo) | Requisitos de la matriz |
|---|---|---|---|---|---|---|
| Centro Legal y de Transparencia | `/legal/` | todos | bloqueante | falta | Portada con índice de todas las páginas, «lo esencial en un minuto», identidad del operador, versión vigente de cada documento con fecha «vigente al», enlazada desde landing, app, correos, checkout y bot. | B01, L01 |
| Quiénes somos: identidad del proveedor y contacto | `/legal/quienes-somos` | todos | bloqueante | parcial (Términos §2 con marcadores vacíos) | Razón social con tipo societario, RFC, domicilio físico en México, teléfono, correos (contacto, privacidad, facturación, legal, seguridad), WhatsApp oficial, horario, dominio y cuentas oficiales. | A01, A02, A10 |
| Atención a usuarios, quejas y PROFECO | `/legal/atencion` | compradores, donantes, usuarios | bloqueante | parcial (Términos §30) | Canales, horarios y plazos de respuesta; procedimiento de reclamación; datos verificados de PROFECO; Concilianet solo con convenio firmado; quejas de datos ante la SABG. | A01, G12 |
| Marco legal y vigilancia normativa | `/legal/marco-legal` | todos | lanzamiento | falta | Normas que sigue GuauWoow con su estado y fecha de corte, normas en trámite que se vigilan, calendario de vigilancia y bitácora de cambios. | A12 |
| Compromisos y código de buenas prácticas | `/legal/compromisos` | todos | lanzamiento | falta | Compromisos verificables (cero venta, privacidad, transparencia de fondos), declaración sobre la NMX-COE-001-SCFI-2018 y, si se adopta, adhesión al Código de Ética de Comercio Electrónico de PROFECO. | A08 |
| Historial de versiones y política de cambios | `/legal/historial` | todos | bloqueante | parcial (sección H de terminos.html y privacidad.html) | Versiones de cada documento con fecha de vigencia, resumen de cambios, PDF y SHA-256; aviso previo de 30 días y reaceptación expresa; registro de informes entregados (Decreto NNA). | A02, A03, A04, A05, A07, A12, C07, D05 |
| Glosario y preguntas frecuentes legales | `/legal/preguntas-frecuentes` | todos | posterior | falta | Definiciones en lenguaje llano y respuestas cortas (adoptar es gratis, qué significa «verificado», a dónde va mi dinero). | — |
| Declaración de accesibilidad | `/legal/accesibilidad` | todos | lanzamiento | falta | Nivel objetivo (WCAG 2.2 AA como estándar técnico), limitaciones conocidas y canal de ajustes razonables. | A09 |
| Créditos, licencias y marcas | `/legal/creditos` | todos | posterior | falta | Licencias de software y mapas (OSM, CARTO), atribuciones, titularidad del contenido propio y estado de la marca. | A10, A11 |

### Términos

| Página | Ruta | Para quién | Prioridad | Estado actual | Qué debe contener (mínimo) | Requisitos de la matriz |
|---|---|---|---|---|---|---|
| Términos y condiciones generales | `/legal/terminos` | todos | bloqueante | parcial (app/legal/terminos.html con marcadores y cláusulas por corregir) | Contrato de uso por clickwrap: requisitos (18+), adopción gratuita, perdidos y encontrados, IA, chat, bot, contenido importado, tienda, donativos, clínicas, conductas prohibidas, moderación, responsabilidad, cambios, ley aplicable. | A01, A03, A04, A05, A06, D01, E06, F01, F03 |
| Términos y convenio para refugios y rescatistas | `/legal/terminos-refugios` | refugios, rescatistas | bloqueante | parcial (Términos §10) | Convenio de adhesión: verificación, no cobro por adopción, datos de adoptantes, donativos y pagos (Split/OAuth, contracargos, compensación), confidencialidad, sanciones y réplica. | B16, F01, H06, H12 |
| Términos para casas de paso y convenio de hogar temporal | `/legal/terminos-casas-de-paso` | casas de paso | lanzamiento | parcial (Términos §12) | Obligaciones durante la guarda, responsabilidad por daños, datos del hogar, entrega y devolución del animal. | F10 |
| Términos para refugios vendedores (tienda) | `/legal/terminos-vendedores` | refugios vendedores | bloqueante | falta | Modelo jurídico de la venta, alta y KYC fiscal, comisión, CFDI, retenciones, devoluciones, garantías, confidencialidad del comprador, productos prohibidos. | G11, G13, H02, H03 |
| Términos para clínicas veterinarias | `/legal/terminos-clinicas` | clínicas | bloqueante | falta | Declaraciones (cédula, LFSA, ley local, RPBI), reglas de contenido y publicidad, reseñas, deslinde del acto médico, verificación y revocación. | J01, J03, J04, J09 |
| Condiciones de compra de la tienda | `/legal/terminos-tienda` | compradores | bloqueante | parcial (Términos §14) | Proveedor responsable, precio total, pedido y aceptación, pago, comprobante, revocación de 5 días hábiles, defectos y bonificación, promociones, atención y PROFECO. | A06, A08, C12, G01, G02, G03, G04, G09, G10, G13, G14, G15 |

### Privacidad

| Página | Ruta | Para quién | Prioridad | Estado actual | Qué debe contener (mínimo) | Requisitos de la matriz |
|---|---|---|---|---|---|---|
| Aviso de privacidad integral | `/legal/privacidad` | todos | bloqueante | parcial (app/legal/privacidad.html con marcadores) | Todos los elementos del art. 15 LFPDPPP: identidad, datos, finalidades, transferencias, encargados, ARCO, revocación, conservación, cookies, IA, fuentes indirectas, cambios. | A01, A02, A04, A05, B01, B04, B05, B06, B08, B17, C10, D01, D03, D07, J08 |
| Aviso de privacidad simplificado | `/legal/privacidad/simplificado` | todos | bloqueante | parcial (app/legal/aviso-simplificado.txt y sección A del aviso) | Texto corto para cada punto de recolección (registro, Google, bot, checkout, donativo, refugios, clínicas) con enlace al integral. | B02 |
| Aviso de privacidad para refugios, rescatistas, casas de paso y clínicas | `/legal/privacidad/refugios` | refugios, clínicas | bloqueante | falta | Datos de verificación (INE, CURP, acta, cédula), datos bancarios y fiscales, finalidades, conservación corta de documentos. | B03, B06, B07 |
| Aviso y reglas del asistente de WhatsApp | `/legal/privacidad/whatsapp` | usuarios del bot | bloqueante | parcial (sección 21.3 del aviso) | Qué hace y qué no hace el bot, aviso al primer contacto, opt-in, BAJA/ALTA/ELIMINAR/PERSONA, sin documentos ni pagos, sin gestión de adopciones. | B02, B03, C03, C04 |
| Publicaciones importadas de grupos de Facebook y envíos de voluntarios | `/legal/privacidad/facebook` | autores de publicaciones, público | bloqueante | parcial (secciones 21.2 a 21.4 del aviso) | Fuente, método (proveedor externo, sin cuenta de Facebook), qué se guarda y qué no, caducidad de 30 días, botón «Soy el autor: retirar», etiqueta en cada reporte. | B03, B14, C11, K01, K02, K03, K04, K05, K06, K07 |
| Acuerdo de datos con refugios, publicadores y casas de paso | `/legal/refugios/acuerdo-de-datos` | refugios, publicadores | bloqueante | falta | Reparto de responsabilidades (art. 35 LFPDPPP), uso permitido de datos de adoptantes y compradores, plazos, confidencialidad, aviso de incidentes. | B04, G11 |
| Política de cookies y tecnologías similares | `/legal/cookies` | todos | bloqueante | parcial (sección 10 del aviso; banner existe) | Inventario completo (propias, Cloudflare, PostHog, Sentry, mapas), finalidad, duración, cómo aceptar, rechazar y revocar. | C01, C02 |
| Centro de privacidad: derechos ARCO, revocación y quejas | `/legal/centro-de-privacidad` | todos | bloqueante | parcial (descargar y eliminar cuenta en el perfil; sección 15 del aviso) | Autoservicio (descargar, corregir, eliminar, revocar), solicitud formal con folio, plazos (20 y 15 días), identidad, costos, negativa, queja ante la SABG. | B11, B12, B13, C06 |
| Eliminación de datos (WhatsApp y Facebook) | `/legal/eliminacion-datos` | usuarios del bot, autores | bloqueante | falta | URL de instrucciones de eliminación que pide Meta; comando ELIMINAR del bot; plazos. | I10 |
| Encargados, terceros y transferencias | `/legal/proveedores` | todos | bloqueante | parcial (secciones 11 a 13 del aviso, incompletas) | Lista de encargados con país, finalidad y datos; terceros independientes; transferencias a refugios, autoridades y SAT; registro de cambios. | B09, B10, C02, J05, K05 |
| Conservación y eliminación de datos | `/legal/conservacion` | todos | bloqueante | parcial (sección 17 del aviso; purgas no automatizadas) | Calendario por categoría con plazo, punto de inicio y fundamento; bloqueo y supresión; respaldos. | B07, B15, D07, I07, I08, I09, K03 |
| IA y algoritmos | `/legal/ia-y-algoritmos` | todos | lanzamiento | parcial (sección 8 del aviso) | Qué hace la IA (comparación de fotos, descripciones, filtros), proveedor y región, compatibilidad, ranking, revisión humana y oposición. | B08, B10, E05, E07 |
| Comunicaciones y centro de preferencias | `/legal/comunicaciones` | todos | bloqueante | parcial (Términos §29) | Categorías y canales (app, correo, WhatsApp, SMS), opt-in, bajas, listado de exclusión propio, REPEP, plantillas de WhatsApp. | B05, B12, C03, C05, C06, C07, C08, C09 |
| Canales oficiales, encuentros seguros y prevención de fraudes | `/legal/canales-oficiales` | todos | lanzamiento | parcial (Términos §20) | Números, correos y remitentes oficiales; qué nunca pedimos; extorsión con perros perdidos; encuentros seguros en persona. | C09, C13 |
| Seguridad, divulgación responsable y avisos de vulneración | `/legal/seguridad` | todos | bloqueante | parcial (secciones 18 y 19 del aviso) | Medidas reales (solo lo que existe), pagos con Mercado Pago, cómo reportar vulnerabilidades, avisos de seguridad publicados. | B07, B16, G14, I01, I02, I03, I04, I05, I06, I08, I11, I12, I13 |
| security.txt | `/.well-known/security.txt` | investigadores de seguridad | bloqueante | falta | Contacto, política, idioma y caducidad conforme a RFC 9116. | I06 |

### Comunidad y animales

| Página | Ruta | Para quién | Prioridad | Estado actual | Qué debe contener (mínimo) | Requisitos de la matriz |
|---|---|---|---|---|---|---|
| Lineamientos de la comunidad | `/legal/comunidad` | todos | bloqueante | parcial (Términos §17) | Contenido prohibido con ejemplos y criterios de retiro: venta o cobro por animales, maltrato, menores, contenido sexual, acusaciones, estafas, facturas falsas, suplantación, reseñas falsas. | D02, D09, E04, F02, F09, G10, H05 |
| Moderación, reportes, sanciones y apelaciones | `/legal/moderacion` | todos | bloqueante | parcial (Términos §19; reportes y bitácora de administración existen) | Cómo reportar (con y sin cuenta), plazos, filtros automáticos, declaración de motivos, escala de sanciones, apelación, conservación de evidencia. | B17, D02, D07, E01, E03, E04, E05, F02, J07 |
| Protección de niñas, niños y adolescentes e imagen de personas | `/legal/proteccion-nna` | todos, autoridades, madres y padres | bloqueante | falta | Servicio 18+, verificación de edad por capas, cumplimiento del Decreto DOF 14-10-2026, configuración segura, canal para madres, padres y tutores, imagen de personas y menores. | D01, D02, D03, D04, D05, D08, D09 |
| Política de adopción responsable | `/legal/adopcion-responsable` | adoptantes, publicadores | bloqueante | parcial (Términos §6) | Adoptar es gratis, qué sí y qué no puede pedir un refugio, estándar de entrega, seguimiento, registros oficiales, selector por estado. | F01, F05, F11 |
| Adoptar no es comprar: cero venta y cero cuotas | `/legal/cero-venta` | todos | bloqueante | parcial (Términos 6.2) | Regla de cuatro niveles, por qué no hay cuotas, qué dice la ley de cada estado sobre venta en internet, cómo reportar. | F01, F02, H09 |
| Modelo de carta responsiva de adopción | `/legal/modelo-carta-responsiva` | adoptantes, publicadores | lanzamiento | falta | Modelo orientativo de donación con cargas, sin precio ni cuota, con cláusulas de bienestar y leyenda de validación por estado. | F04 |
| Guía legal de perros perdidos y encontrados | `/legal/perdidos-y-encontrados` | todos | bloqueante | falta | Quien encuentra no se vuelve dueño, plazos de reclamo por estado, regla de 30 días, microchip, recompensas y extorsión. | F06 |
| Cómo denunciar maltrato animal | `/legal/denunciar-maltrato` | todos | lanzamiento | falta | Directorio verificado de autoridades por estado y cómo reportar dentro de la app. | F07 |
| Bienestar animal: la ley en tu estado | `/legal/marco-legal-bienestar-animal` | todos | lanzamiento | parcial (Términos §16 con citas por corregir) | Ficha por estado (ley, última reforma, estado de cotejo), Ley General no vigente, tabla de sanciones. | A12, F03, F12 |
| Verificación de refugios, casas de paso, rescatistas y clínicas | `/legal/verificacion` | todos | bloqueante | parcial (revisión de INE y acta por administradores) | Qué significa cada insignia y qué no garantiza, documentos por estado, reverificación, revocación. | B07, F08, J01, J09 |
| Directorio de refugios verificados | `/refugios` | todos | posterior | parcial (listado de refugios en la app) | Refugios con insignias, fecha de verificación y estatus de donataria verificado en el SAT. | — |

### Dinero

| Página | Ruta | Para quién | Prioridad | Estado actual | Qué debe contener (mínimo) | Requisitos de la matriz |
|---|---|---|---|---|---|---|
| Política y condiciones de donativos | `/legal/donativos` | donantes, refugios | bloqueante | parcial (Términos §15) | Quién recibe el dinero según la fase, comisiones y neto, deducibilidad, reembolsos y contracargos, topes; los donativos nunca condicionan adopciones. | C12, H06, H07, H08, H09, H10, H11, H12, H13 |
| Guía para refugios: donataria autorizada | `/legal/ayuda-refugios-donataria` | refugios | posterior | falta | Requisitos generales, fracciones posibles del art. 79 LISR, CFDI de donativo en 24 horas, obligaciones de transparencia. | H08 |
| Prevención de fraude y lavado de dinero | `/legal/prevencion-lavado` | donantes, refugios | lanzamiento | falta | Topes, identificación, umbrales LFPIORPI, autodonaciones, rifas, cooperación con autoridades. | H10 |
| Tarifas y comisiones | `/legal/tarifas` | compradores, donantes, refugios | bloqueante | falta | Comisión de la plataforma (con IVA), comisiones de Mercado Pago, quién las paga, ejemplos de neto. | G01, H02, H06, H08, H15 |
| A dónde va tu dinero: donativos, ventas y liquidaciones | `/transparencia/donativos` | todos | lanzamiento | falta | Flujo del dinero por fase, bloque fijo «no somos entidad financiera», tablero agregado por refugio. | G09, H06, H13, H14 |

### Tienda

| Página | Ruta | Para quién | Prioridad | Estado actual | Qué debe contener (mínimo) | Requisitos de la matriz |
|---|---|---|---|---|---|---|
| Envíos, devoluciones, reembolsos y garantías | `/legal/envios-devoluciones-garantias` | compradores | bloqueante | parcial (Términos 14.4 a 14.6) | Cobertura, costos y plazos, rastreo, revocación de 5 días hábiles, defectos, bonificación mínima de 20 %, garantías, exclusiones. | G05, G06, G07, H04 |
| Facturación (CFDI) | `/legal/facturacion` | compradores, donantes, refugios | bloqueante | parcial (Términos 14.7) | Quién emite el CFDI, datos que se piden (sin exigir la Constancia de Situación Fiscal), plazo para pedir factura, factura global, CFDI de egreso, CFDI de donativo. | H01, H02, H04, H11 |
| Productos permitidos y prohibidos | `/legal/productos-prohibidos` | refugios vendedores, compradores | bloqueante | falta | Animales nunca; medicamentos; alimentos sin registro SENASICA; productos sin NOM de etiquetado; marcas ajenas; rifas. | E08, G08, H05 |

### Clínicas veterinarias

| Página | Ruta | Para quién | Prioridad | Estado actual | Qué debe contener (mínimo) | Requisitos de la matriz |
|---|---|---|---|---|---|---|
| Clínicas veterinarias: qué verificamos y qué no | `/legal/veterinarias` | todos, clínicas | bloqueante | falta | Directorio que no presta servicios veterinarios, insignia «Cédula verificada», urgencias, medicamentos, qué deben cumplir las clínicas, bloque de Google. | J01, J02, J03, J05, J08 |
| Política de reseñas (clínicas y productos) | `/legal/resenas` | todos | bloqueante | falta | Quién puede reseñar, qué sí y qué no, incentivos, respuesta de la clínica, aclaración, retiro, reseñas de Google sin almacenar. | G16, J04, J05, J06, J07 |

### Terceros y autoridades

| Página | Ruta | Para quién | Prioridad | Estado actual | Qué debe contener (mínimo) | Requisitos de la matriz |
|---|---|---|---|---|---|---|
| Propiedad intelectual: aviso, contra-aviso e imagen | `/legal/propiedad-intelectual` | titulares de derechos | bloqueante | parcial (Términos §18 y §21) | Formularios conforme al Reglamento de la LFDA (arts. 37 Bis a 37 Nonies), staydown, reincidentes, marcas, imagen de personas. | E01, E02, E08, K04 |
| Solicitudes de autoridades y contacto 24/7 | `/legal/autoridades` | autoridades | bloqueante | falta | Contacto 24/7, requisitos del requerimiento, tres niveles de entrega, emergencias, aviso al usuario, informe anual. | D06, D08, E09 |

### Transparencia

| Página | Ruta | Para quién | Prioridad | Estado actual | Qué debe contener (mínimo) | Requisitos de la matriz |
|---|---|---|---|---|---|---|
| Informe de transparencia | `/transparencia` | todos | posterior | falta | Cifras semestrales disociadas: ARCO, autoridades, retiros, importados, menores, reseñas, incidentes, sanciones a refugios. | B15, D04, L02 |
| Estado del servicio | `/estado` | todos | posterior | falta | Disponibilidad e historial de incidentes. | — |

### Internos (no públicos)

| Página | Ruta | Para quién | Prioridad | Estado actual | Qué debe contener (mínimo) | Requisitos de la matriz |
|---|---|---|---|---|---|---|
| Documento de seguridad (SGSDP) | `docs/interno/documento-de-seguridad.md` | interno | bloqueante | falta | Inventario, análisis de riesgo, medidas, responsables y revisión. | — |
| Plan de respuesta a incidentes | `docs/interno/runbook-incidentes.md` | interno | bloqueante | falta | Roles, severidad, plazos, contactos y plantillas. | — |
| Políticas internas y carpeta de evidencias | `docs/interno/` | interno | lanzamiento | falta | Acceso, respaldos, logs, vulnerabilidades, NDA, verificaciones de la SABG, vigilancia normativa. | — |

Formato de cada documento (buenas-practicas, procedimiento 2): encabezado con versión, fecha de vigencia, última actualización y a quién aplica; «Lo esencial en un minuto» (máximo seis viñetas; prevalece el texto completo); índice con anclas; PDF con SHA-256; enlace a versiones anteriores; leyenda «Documento base preparado con apoyo de IA» hasta que el abogado lo apruebe.

## 4. Matriz de cumplimiento consolidada

Cada fila agrupa hallazgos verificados de una o más secciones. *Confianza* es la de la fila; `requisitos.json` incluye además la confianza mínima de los hallazgos citados y las banderas de revisión (`agregado_por_verificador`, `no_verificable`, `confianza_baja`). Resumen: 134 requisitos, 99 obligatorios, 56 sin implementar y 66 parciales.

### A. Identidad, contratación y gobierno documental

| ID | Requisito | Fundamento | Acción | Página(s) | Prioridad | Estado actual | Confianza | Hallazgos |
|---|---|---|---|---|---|---|---|---|
| A01 | Publicar la identidad completa del proveedor antes de cualquier transacción: razón social con tipo societario, RFC, domicilio físico en México, teléfono, correo y horario. | LFPC art. 76 Bis fr. III; LFPDPPP art. 15 fr. I; LGSM arts. 88 y 261; NMX-COE-001 num. 5.2.1.1 | Llenar app/legal/datos-legales.json; bloque de identidad en checkout, donativo, correos y pie; impedir el despliegue con marcadores vacíos. | quienes-somos, terminos, privacidad, atencion-y-quejas | obligatorio | falta (datos-legales.json vacío; deploy.sh revisa los marcadores con render-legal.py --check) | alta | IC-01 IC-02 IC-03 CE-02 DP-04 BP-02 |
| A02 | Constituir una persona moral operadora, poner los activos a su nombre y llevar el expediente de beneficiario controlador. | CCom art. 3 fr. II; CFF arts. 32-B Ter a 32-B Quinquies; LGSM arts. 260-272 | Elegir S.A.S. o S.A. de C.V.; dominio, cuentas de Mercado Pago, Meta y Google a nombre de la sociedad; aviso de privacidad nuevo si cambia el responsable. | quienes-somos, privacidad, historial | recomendado (necesario en la práctica para tienda y retenciones) | falta | media | FT-13 FT-v04 IC-06 IC-28 DP-32 |
| A03 | Contratar por clickwrap: casillas separadas para Términos, Aviso y declaración 18+; nunca «aceptación por el uso». | CCF arts. 1803 fr. I, 1811 y 1834 bis; CCom arts. 89 bis, 90 bis y 93; LFPC art. 76 Bis 1 fr. II a IV | Quitar «o al usar la Plataforma» (cláusula 1.2); separar la casilla 18+ de la de Términos y Aviso. | terminos, historial | obligatorio | parcial (una sola casilla reúne 18+, Términos y Aviso en index.html) | alta | CP-14 BP-03 CP-v03 |
| A04 | Bitácora inmutable de aceptaciones y consentimientos: documento, versión, fecha, IP, user-agent, canal y hash. | CCom arts. 49 y 93 bis; LFPC art. 76 Bis 1 fr. IV; LFPDPPP art. 7; Reglamento LFPDPPP art. 20 (prueba del consentimiento, como referencia) | Tablas legal_acceptances y consent_events de solo inserción; seudonimizar al borrar la cuenta; constancias NOM-151 opcionales. | historial, terminos, privacidad | obligatorio | parcial (User.terms_version y privacy_version se sobrescriben) | alta | CP-15 CP-16 BP-05 CC-16 IC-15 |
| A05 | Cambios a Términos y avisos con aviso previo (30 días propuesto), aceptación expresa de cambios materiales y derecho a terminar sin costo. | LFPC art. 90 fr. I; CCF art. 1797; LFPDPPP art. 15 fr. VI; Lineamientos Trigésimo segundo y tercero | Política de cambios pública; modal de reaceptación; versión futura publicada en /legal/historial. | historial, terminos, privacidad | obligatorio | falta (la cláusula 27.2 prevé aceptación tácita) | media | CP-17 BP-04 BP-v05 IC-14 |
| A06 | Eliminar cláusulas abusivas o inexigibles: renuncia de fuero, cancelación por «error de precio», video de desempaque, exclusión de responsabilidad por datos. | LFPC arts. 1, 85 y 90 fr. I a VI; LFPDPPP art. 53; CCom art. 1093; SCJN 1a./J. 93/2025 (apoyo) | Reescribir las cláusulas señaladas en terminos.html; jurisdicción del domicilio del consumidor. | terminos, terminos-tienda | obligatorio | parcial (terminos.html las contiene) | media | CE-15 CP-18 CP-19 IC-14 IC-27 SI-26 |
| A07 | Historial público de versiones con PDF y SHA-256 y conservación íntegra de cada versión por 10 años. | CCom art. 49 párr. 2; NOM-151-SCFI-2016 (opcional) | Página /legal/historial; tabla legal_document_versions; constancias NOM-151 si hay presupuesto. | historial | obligatorio (conservación) / recomendado (publicación) | parcial (sección H en cada documento) | media | BP-05 CP-16 IC-15 |
| A08 | Declarar si se cumple la NMX-COE-001-SCFI-2018 y delimitar responsabilidades entre plataforma y refugio vendedor. | LFPC art. 76 Bis 1; NMX num. 4.1, 4.4, 5.1.7 y 5.3.6 | Texto en Condiciones de compra y en Compromisos. | terminos-tienda, compromisos | recomendado | falta | alta | IC-04 BP-v01 CE-32 |
| A09 | Accesibilidad: canal de ajustes razonables y declaración con WCAG 2.2 AA como estándar técnico. | LFPC art. 58; LGIPD art. 32 fr. IV; LFPED art. 9 fr. XXII Bis | Página de accesibilidad, correo de ajustes, revisión básica de contraste y teclado. | accesibilidad | recomendado | falta | media | IC-19 IC-20 BP-34 |
| A10 | Registrar la marca GuauWoow ante el IMPI y no usar ® sin registro. | LFPPI arts. 170-172 y 386 fr. XVI | Búsqueda fonética y solicitud por clase. | creditos, quienes-somos | recomendado | falta | media | IC-16 |
| A11 | Ceder por escrito los derechos sobre código, diseño y contenidos (fundador, freelance, voluntarios). | LFDA arts. 30, 31, 83, 84 y 103 | Contratos de cesión y obra por encargo; créditos y licencias de terceros. | creditos | recomendado | falta | media | IC-17 IC-v03 IC-22 |
| A12 | Vigilancia normativa con responsable, calendario y bitácora (DOF, Gaceta, periódicos oficiales y contratos de Meta, Google y Mercado Pago). | Buena práctica; normas en movimiento (Decreto NNA, Ley General de bienestar animal, RMF, LFPC, Reglamento LFDA) | Revisión semanal DOF/Gaceta, mensual estatal, semestral de contratos; actualizar páginas en 30 días. | marco-legal, marco-legal-bienestar-animal, historial | recomendado | falta | alta | BP-35 IC-29 EST-22 CF-16 |

### B. Datos personales

| ID | Requisito | Fundamento | Acción | Página(s) | Prioridad | Estado actual | Confianza | Hallazgos |
|---|---|---|---|---|---|---|---|---|
| B01 | Aviso de privacidad integral completo, sin marcadores ni expresiones vagas, con domicilio completo y persona o departamento de datos personales. | LFPDPPP arts. 14, 15, 29 y 58 fr. V; Lineamientos Vigésimo a Vigésimo cuarto | Completar la plantilla; nombrar el departamento de datos (art. 29). | privacidad, centro-legal | obligatorio | parcial (existe con marcadores) | alta | DP-04 DP-24 DP-34 |
| B02 | Aviso simplificado en cada punto de recolección: registro, Google, bot, refugios, checkout, donativo y clínicas. | LFPDPPP art. 16 fr. II; Reglamento arts. 27-28 (referencia) | Componente reutilizable; registrar la versión mostrada. | privacidad-simplificado, privacidad-whatsapp | obligatorio | parcial (registro web sí; bot, checkout y donativo no) | alta | DP-05 DP-27 CC-11 |
| B03 | Avisos por público: refugios y casas de paso, bot de WhatsApp y publicaciones importadas. | LFPDPPP arts. 15, 16 y 17 | Páginas propias con finalidades específicas. | privacidad-refugios, privacidad-whatsapp, contenido-importado | obligatorio | falta | alta | BP-08 |
| B04 | Compartir correo y teléfono del adoptante con el publicador o refugio solo con cláusula de transferencia y casilla, o limitarlo al chat. | LFPDPPP arts. 35, 36 fr. IV y VII y 58 fr. X | Casilla al postular; tabla de transferencias; acuerdo de datos con refugios. | privacidad, acuerdo-datos-refugios | obligatorio | falta (el código comparte al aprobar y el aviso no lo describe así) | alta | DP-06 DP-16 BP-11 IC-10 |
| B05 | Ubicación: zona redondeada; «ver cerca» sin guardar en el servidor; alertas cercanas de 5 km solo con opt-in. | LFPDPPP arts. 6, 11, 12 y 15 fr. III; WhatsApp Business Messaging Policy §1 | notify_nearby en false por defecto; zona con 3 decimales o geohash 6; botón «Borrar mi ubicación». | privacidad, comunicaciones | obligatorio | falta (notify_nearby=True por defecto en backend/app/models.py) | alta | DP-07 CC-07 CC-08 |
| B06 | Datos patrimoniales y fiscales (CLABE, presupuesto, RFC) con consentimiento expreso cuando la ley lo exige. | LFPDPPP arts. 7 (quinto párrafo), 9 fr. I y IV y 36 fr. IV y VII | Casilla específica; cifrado; acceso mínimo. | privacidad, privacidad-refugios | obligatorio | parcial | alta | DP-09 SI-16 |
| B07 | INE, CURP, acta y cédula: minimización, cifrado en reposo, conservación corta (constancia sin imagen) y sin tratamiento biométrico. | LFPDPPP arts. 8, 10, 12 y 18; criterio SABG (Comunicado 078, 12-07-2026); LGP art. 91 Sexies (CURP) | Verificar por videollamada o borrar la imagen a 30 días o menos; aceptar CURP biométrica; cifrar uploads/private. | privacidad-refugios, verificacion, seguridad, conservacion | obligatorio | parcial (almacenamiento privado sí; cifrado y purga no; el aviso dice 24 meses) | media | DP-10 DP-11 SI-10 SI-11 SI-12 SI-23 |
| B08 | Puntaje de compatibilidad e IA: informar, permitir oposición y revisión humana; ninguna decisión solo automatizada. | LFPDPPP arts. 14 y 26 fr. II; Reglamento art. 112 (referencia) | Página de IA; botón «solicitar revisión humana»; advertencia junto al puntaje. | ia-y-algoritmos, privacidad | obligatorio | parcial (sección 8 del aviso) | media | DP-12 BP-12 |
| B09 | Encargados con contrato o términos adecuados, registro interno y lista pública (incluye Cloudflare, Nominatim, Apify, Places, PAC y paquetería). | LFPDPPP arts. 2 fr. XII, 13 y 20; Reglamento arts. 49-55 (referencia) | Expediente por proveedor (DPA, región, retención); /legal/proveedores con historial de cambios. | proveedores | obligatorio | parcial (sección 11 del aviso incompleta) | alta | DP-14 CC-22 SI-09 BP-10 |
| B10 | Flujos internacionales informados (DashScope en Singapur, Meta, Cloudflare, Sentry, PostHog) y sin entrenamiento de modelos con datos de usuarios. | LFPDPPP arts. 2 fr. XX, 35 y 36 | Fijar región; contratar sin uso para entrenamiento; no activar el proveedor alterno en China sin evaluación y aviso nuevo. | proveedores, ia-y-algoritmos | obligatorio | parcial | media | DP-13 DP-15 |
| B11 | Derechos ARCO: autoservicio y solicitud formal; respuesta en 20 días y efecto en 15; ampliación única; acreditación de identidad. | LFPDPPP arts. 21 a 34 (en particular 28, 31 y 34) | Centro de privacidad con folio y seguimiento; exportación completa, incluidas comunicaciones. | derechos-arco | obligatorio | parcial (exportar y eliminar existen en el perfil) | alta | DP-17 DP-18 BP-07 BP-v07 |
| B12 | Revocación del consentimiento y listado de exclusión propio. | LFPDPPP arts. 7 (último párrafo) y 26; LFPC arts. 16 y 18 | Botones en Preferencias; constancia con folio. | derechos-arco, comunicaciones | obligatorio | parcial | alta | DP-20 CC-14 |
| B13 | Informar cómo presentar quejas ante la SABG con canales verificados. | LFPDPPP arts. 38 a 55; Reglamento Interior de la SABG art. 30-F | Publicar el canal solo tras confirmarlo en gob.mx/buengobierno. | derechos-arco | obligatorio | parcial (aviso §24 con datos por confirmar) | media | DP-03 |
| B14 | Fuentes indirectas (Facebook, WhatsApp, voluntarios): dar a conocer el aviso; medida compensatoria solo si es imposible o desproporcionado, con autorización de la SABG cuando no aplican los Criterios de 2012. | LFPDPPP arts. 2 fr. X, 9, 17 y 26; Criterios Generales (DOF 18-04-2012) | Página de contenido importado; etiqueta en cada reporte; retiro sin cuenta; dictamen o trámite ante la Unidad de Protección de Datos Personales. | contenido-importado | obligatorio | parcial (aviso §21.2 a 21.4; base jurídica sin dictamen) | media (baja en la vía de la medida compensatoria) | DP-26 DP-v01 DP-v05 BP-15 |
| B15 | Disociación para estadísticas, analítica y caché de IA. | LFPDPPP arts. 2 fr. IX, 9 fr. III y 10 | Seudonimizar al vencer los plazos; métricas agregadas. | conservacion, informe-transparencia | buena práctica | parcial | alta | DP-v04 |
| B16 | Confidencialidad de personal, moderadores, voluntarios y refugios que acceden a datos. | LFPDPPP arts. 20 y 58 fr. VIII | Acuerdos de confidencialidad; cláusula en el convenio; capacitación. | seguridad, terminos-refugios | obligatorio | falta | alta | SI-08 BP-v06 |
| B17 | Chat privado: ninguna lectura humana sin reporte de un participante; los filtros solo marcan y avisan. | CPEUM art. 16; CPF art. 177; LFPDPPP arts. 11, 12 y 58 fr. VIII | Casilla «autorizo compartir este mensaje» al reportar; bitácora de cada acceso. | moderacion, privacidad | recomendado | parcial | media | CP-12 DP-31 NNA-12 |

### C. Comunicaciones, cookies y consentimiento

| ID | Requisito | Fundamento | Acción | Página(s) | Prioridad | Estado actual | Confianza | Hallazgos |
|---|---|---|---|---|---|---|---|---|
| C01 | Banner de cookies visible siempre (aunque no haya PostHog), exacto («seudónimo», no «anónimo», si hay identify), con botones de igual peso y revocable. | LFPDPPP arts. 7, 15 fr. II y III y 58 fr. XV; Reglamento art. 14 y Lineamientos Trigésimo primero (referencia) | Nuevo texto; patitas_consent con versión y fecha; enlace permanente «Preferencias de cookies». | cookies | obligatorio | parcial (banner en index.html con texto inexacto y que no se muestra sin PostHog) | alta | CC-02 CC-03 CC-04 |
| C02 | Inventario completo de cookies y almacenamiento local, incluidos terceros que reciben IP o coordenadas (Cloudflare, OSM/Nominatim, CARTO, Google Fonts). | LFPDPPP art. 15 fr. II y III; Lineamientos Trigésimo primero | Página de cookies con tabla; mover la geocodificación inversa al backend. | cookies, proveedores | obligatorio | falta | alta | CC-05 CC-06 CC-24 |
| C03 | WhatsApp: opt-in explícito que nombre a la empresa, opt-in de marketing separado, BAJA y ALTA, plantillas bien categorizadas. | WhatsApp Business Messaging Policy §1 a §4 (23-09-2026); LFPDPPP arts. 2 fr. IV y 7 | can_whatsapp() exige opt-in registrado; ampliar OPT_OUT_WORDS; HOLA no reactiva plantillas. | comunicaciones, privacidad-whatsapp | obligatorio | parcial (BAJA existe; HOLA reactiva; opt-in no registrado) | alta | CC-09 CC-10 CC-12 |
| C04 | Bot: aviso simplificado al primer contacto, escalamiento a una persona, sin pedir identificadores sensibles ni datos de pago, sin gestionar adopciones. | WhatsApp Business Messaging Policy §2 a §4; LFPDPPP art. 16 fr. II | Mensaje inicial; comando PERSONA; filtro de documentos; «Quiero adoptar» solo envía el enlace. | privacidad-whatsapp | obligatorio | parcial | media | CC-11 CP-23 CP-24 AD-09 |
| C05 | Publicidad identificada con datos del proveedor (y del refugio) y de PROFECO; respetar la negativa, el listado propio y el REPEP. | LFPC arts. 16, 17, 18, 18 Bis y 76 Bis fr. VI | Pie de publicidad; lista de supresión global; REPEP solo si hay publicidad a teléfonos. | comunicaciones | obligatorio | falta | alta | CC-13 CC-14 CE-19 |
| C06 | Derecho a saber qué información se usa con fines mercadotécnicos. | LFPC art. 16; LFPDPPP art. 31 | Exportación «Comunicaciones» en 20 días hábiles. | derechos-arco, comunicaciones | obligatorio | falta | alta | CC-15 BP-v12 |
| C07 | Prueba del consentimiento por finalidad y canal (fecha, versión, origen) y aviso coherente con la interfaz. | LFPDPPP arts. 7, 14 y 15 fr. III | consent_events; cambiar «tácito» por casilla expresa en el aviso. | comunicaciones, historial | obligatorio | falta (solo un booleano marketing_opt_in) | alta | CC-16 CC-17 DP-08 |
| C08 | Correo con baja en un clic, SPF, DKIM y DMARC, y sin píxeles de seguimiento. | LFPC art. 76 Bis fr. VI; requisitos de remitentes de Google (contractual) | Encabezados List-Unsubscribe; DNS; desactivar aperturas y clics. | comunicaciones | recomendado | falta | alta | CC-18 CC-19 |
| C09 | SMS solo para el código OTP, sin enlaces ni promociones. | LFPC arts. 16 a 18 Bis | Texto fijo; remitente publicado en Canales oficiales. | comunicaciones, canales-oficiales | recomendado | existe (OTP) / falta publicarlo | alta | CC-20 |
| C10 | Google OAuth: divulgar los datos recibidos de Google, verificación de marca y URLs en el mismo dominio. | Google API Services User Data Policy (contractual) | Sección «Datos que recibimos de Google»; consola de Google Cloud completa. | privacidad | obligatorio (contractual) | parcial | alta | CP-25 CC-23 |
| C11 | No contactar teléfonos de terceros importados o reenviados. | WhatsApp Business Messaging Policy §1; LFPDPPP art. 17 | Eliminar teléfonos antes de guardar; ningún envío saliente. | contenido-importado | obligatorio | existe (strip_pii en services/facebook_groups.py) | alta | CC-27 |
| C12 | Cobros recurrentes (si se habilitan): consentimiento expreso, aviso 5 días antes y cancelación inmediata. | LFPC art. 76 Bis fr. VIII y IX (DOF 12-12-2025) | No habilitar donativos mensuales sin el flujo completo. | donativos, terminos-tienda | obligatorio (condicional) | no aplica hoy | alta | CE-27 DON-17 |
| C13 | Canales oficiales y prevención de fraudes (extorsión con perros perdidos, phishing de OTP, refugios falsos, cambio de CLABE). | LFPC art. 76 Bis fr. III; LFPDPPP art. 18 | Página con números, correos y remitentes oficiales; avisos de seguridad de cuenta. | canales-oficiales | buena práctica | parcial (Términos §20) | media | CC-25 SI-27 IC-13 |

### D. Niñas, niños y adolescentes (Decreto NNA)

| ID | Requisito | Fundamento | Acción | Página(s) | Prioridad | Estado actual | Confianza | Hallazgos |
|---|---|---|---|---|---|---|---|---|
| D01 | Verificación de edad por capas: casilla 18+ separada, fecha de nacimiento y OTP; señales de riesgo; verificación reforzada sin copia en momentos de riesgo; nunca biometría. | Decreto NNA art. 4 fr. I; LGDNNA art. 5; LFPDPPP arts. 6, 11 y 12; CCF art. 640 | Implementar las capas 1 a 4 de la sección del gap NNA (3.2). | proteccion-nna, terminos, privacidad | obligatorio | parcial (casilla 18+ combinada; sin fecha de nacimiento ni señales) | media | NNA-02 NNA-03 CP-v03 DP-28 |
| D02 | Publicar criterios de identificación y retiro de las siete categorías del art. 3; retiro inmediato; reporte visible y permanente, también sin cuenta. | Decreto NNA arts. 3 y 4 fr. II, IV y V | Lineamientos con las siete categorías; motivo «involucra a un menor»; formulario público además de POST /reports. | comunidad, moderacion, proteccion-nna | obligatorio | parcial (POST /reports exige cuenta verificada; faltan motivos) | alta | NNA-04 CP-11 |
| D03 | Configuración predeterminada más estricta en cuentas nuevas y seguridad desde el diseño. | Decreto NNA art. 4 fr. VI a VIII; LGDNNA art. 76 | Ubicación aproximada, contacto oculto, chat tras match, alertas apagadas, sin EXIF, perfil no indexable. | proteccion-nna, privacidad | recomendado | parcial (EXIF y ubicación pública aproximada sí; alertas encendidas por defecto) | media | NNA-05 |
| D04 | Evaluación periódica de riesgos y reportes estadísticos a la autoridad. | Decreto NNA art. 4 fr. IX | Primera evaluación como anexo del informe; repetir cada 6 meses. | proteccion-nna, informe-transparencia | obligatorio | falta | media | NNA-06 |
| D05 | Entregar el informe de implementación del transitorio Cuarto a más tardar el 12-11-2026 (fecha interna) a la ATDT, con copia a la CJEF. | Decreto NNA transitorios Segundo a Cuarto | Confirmar canal antes del 05-11-2026; PDF firmado con 12 apartados; acuse; versión pública. | proteccion-nna, historial | obligatorio | falta | media (alta en el plazo) | NNA-07 |
| D06 | Punto de contacto 24/7/365 para autoridades con capacidad técnica inmediata. | Decreto NNA art. 5 fr. I | Titular y suplente; teléfono y correo dedicados; guardia; acceso de emergencia con MFA. | autoridades | obligatorio | falta | alta | NNA-08 |
| D07 | Conservar la evidencia de cuentas y contenidos retirados al menos 90 días hábiles. | Decreto NNA art. 5 fr. II; LFPA art. 28; LFPDPPP art. 25 fr. II y III | Bóveda en bucket R2 separado y cifrado, índice con hash encadenado, retención legal. | moderacion, conservacion, privacidad | obligatorio | falta | alta | NNA-09 |
| D08 | Protocolo «menores en riesgo»: alerta inmediata, denuncia al Ministerio Público; material de abuso nunca reproducido ni enviado a IA. | Decreto NNA art. 5 fr. III; CNPP art. 222; CPF arts. 202 y 202 Bis | Protocolo escrito; postura penal del abogado antes de operar. | proteccion-nna, autoridades | obligatorio | falta | media | NNA-10 |
| D09 | Imagen de personas y de menores en fotos: no publicar menores reconocibles, difuminar y retirar a petición. | LFDA arts. 87 y 231 fr. II (reforma DOF 14-05-2026); CCF art. 1916; LGDNNA art. 76 | Detección o difuminado de rostros; retiro preventivo. | proteccion-nna, comunidad | recomendado | falta | media | CP-08 CP-09 IC-v04 |

### E. Contenido, moderación y propiedad intelectual

| ID | Requisito | Fundamento | Acción | Página(s) | Prioridad | Estado actual | Confianza | Hallazgos |
|---|---|---|---|---|---|---|---|---|
| E01 | Conservar el puerto seguro de derechos de autor: retiro expedito, aviso al usuario, política de reincidentes, staydown y ningún beneficio del contenido infractor. | LFDA arts. 114 Septies, 114 Octies fr. II a V y 232 Quinquies | Flujo con estados; hash perceptual de lo retirado; contador por usuario. | derechos-de-autor, moderacion | obligatorio | falta | alta | CP-01 CP-04 BP-17 IC-18 |
| E02 | Formularios de aviso y contra-aviso conforme al Reglamento de la LFDA, sin exigir certificados. | Reglamento LFDA arts. 37 Bis a 37 Nonies (DOF 24-09-2026; vigor alrededor del 03-02-2027) | Formularios públicos sin cuenta, listos desde el lanzamiento. | derechos-de-autor | obligatorio (desde la entrada en vigor) | falta | alta | CP-02 CP-03 |
| E03 | Debido proceso: declaración de motivos, apelación ante una persona distinta y ARCO disponible aun con la cuenta suspendida. | LFPC arts. 10 y 90 fr. I; LFDA art. 114 Octies fr. II b); Decreto NNA art. 4 fr. II | Correo de motivos; POST /appeals con token; plazos publicados. | moderacion | recomendado | parcial (resolución de reportes y aviso al ocultar existen; sin apelación) | media | CP-13 BP-16 |
| E04 | Retirar acusaciones contra personas identificables y contenido íntimo sin consentimiento (Ley Olimpia). | CCF arts. 1916 y 1916 Bis; Ley de Responsabilidad Civil CDMX; LGAMVLV arts. 20 Quáter a 20 Sexies | Retiro tras revisión; contenido íntimo oculto en menos de 24 h y resguardado. | comunidad, moderacion | obligatorio | falta | media | CP-07 CP-10 |
| E05 | Filtros automáticos acotados (estafas, venta de animales, sexual o menores, maltrato) con registro de cada acción. | LFDA art. 114 Octies fr. IV; Decreto NNA art. 4 fr. IV | Registrar detection_source; texto público sobre filtros. | moderacion, ia-y-algoritmos | recomendado | parcial (services/moderation.py) | alta | CP-v01 |
| E06 | Licencia sobre el contenido de usuarios por escrito y con alcance definido. | LFDA arts. 30, 31 y 33 | Reescribir la cláusula 18.2. | terminos | recomendado | parcial | media | CP-20 |
| E07 | El texto generado por IA es contenido propio: etiquetarlo y permitir corregirlo. | CCF arts. 1910 y 1916; LFPC art. 76 Bis fr. IV | Etiqueta «descripción generada por IA». | ia-y-algoritmos | buena práctica | parcial | media | CP-27 |
| E08 | Revisión previa de productos con marcas o personajes ajenos. | LFDA art. 114 Octies fr. II e); LFPPI arts. 344 fr. VII y 386 | Lista de verificación de propiedad intelectual al dar de alta productos. | productos-prohibidos, derechos-de-autor | recomendado | falta | media | CP-05 |
| E09 | Solicitudes de autoridades con tres niveles de entrega y registro: datos de cuenta con oficio fundado; chats solo con orden judicial; ubicación con orden del juez de control. | CPEUM art. 16; CNPP arts. 291 y 303; LFPDPPP arts. 9 fr. V y VII y 36 fr. I y V; LSNIIMSP art. 26 | Procedimiento interno, página pública y tabla authority_requests. | autoridades | recomendado | falta | alta | NNA-12 SI-21 BP-18 |

### F. Adopción y bienestar animal

| ID | Requisito | Fundamento | Acción | Página(s) | Prioridad | Estado actual | Confianza | Hallazgos |
|---|---|---|---|---|---|---|---|---|
| F01 | Adopción gratuita: prohibida cualquier cuota, reembolso, apartado o «donativo sugerido» ligado a la entrega del perro. | CCF arts. 2248, 2332, 2336 y 2337; LPBA CDMX art. 25 Bis; Ley Edomex art. 40 fr. V; LIVA art. 2o.-A fr. I a); LISR arts. 27 fr. I y 151 fr. III | Regla de cuatro niveles en todas las páginas; sin campo de precio; casilla «No vendo ni cobro por este perro». | adopcion-responsable, cero-venta, terminos, terminos-refugios | obligatorio | parcial (Términos 6.2 «cero venta»; faltan la regla de cuotas y los controles) | media | AD-01 AD-03 AD-04 AD-06 AD-07 BA-10 DON-v02 |
| F02 | Detector de venta y cobro en publicaciones, chat, bot e importación; motivos «venta_animales» y «cobro_por_adopcion»; escala de sanciones a verificados. | LPBA CDMX arts. 25 Bis y 65 fr. IV; WhatsApp Business Messaging Policy §4; Meta Commerce Policies | Diccionario único; revisión humana en 24 h; descarte previo en la importación. | comunidad, moderacion, cero-venta | obligatorio | falta (ContentReport no tiene esos motivos) | media | AD-12 BA-04 BA-v04 |
| F03 | Corregir la sección 16 de los Términos: ley de la CDMX reformada (G.O. 23-07-2026), ley del Edomex 2026 y Ley General «no vigente». | LPBA CDMX art. 25 fr. V, VI y XXI y 25 Bis; Ley Edomex (Gaceta 16-06-2026) | Reescritura con fecha de corte. | terminos, marco-legal-bienestar-animal | obligatorio | parcial (cita errónea del art. 28 Bis) | alta | BA-05 CP-v02 |
| F04 | Carta responsiva modelo: donación con cargas, sin precio, con condición resolutoria «sujeta al código civil del estado». | CCF arts. 1929 y 2332 a 2344; Código Civil CDMX art. 855 Bis | PDF con selector de estado y leyenda «modelo orientativo». | modelo-carta-responsiva | recomendado | falta | media | BA-11 AD-02 IC-12 |
| F05 | Estándar único de entrega en adopción: esterilizado o compromiso fechado, vacunado, desparasitado, manual de cuidados, seguimiento y 18+ estricto. | Leyes estatales (Puebla art. 33, QRoo art. 48, Coahuila art. 65 A, Michoacán art. 37, Sonora art. 17 fr. XI); LPBA CDMX art. 4 BIS 1 | Campos en la ficha y recordatorios. | adopcion-responsable | recomendado | parcial | alta | EST-21 BA-12 BA-13 EST-20 |
| F06 | Perros encontrados: 30 días naturales con reporte activo, lectura de microchip y aviso a la autoridad antes de poder ofrecerlos en adopción; nunca menos que el plazo del estado. | CCF arts. 774, 775 y 874; leyes estatales (tabla de 15 entidades) | Bloqueo de «publicar en adopción»; excepción con constancia para refugios verificados o autoridades. | perdidos-y-encontrados | obligatorio (regla de producto) | falta | media | EST-16 BA-15 |
| F07 | Denuncia de maltrato: directorio verificado por estado y deber de informar en la CDMX. | LPBA CDMX art. 26; leyes estatales | Botón «Denunciar ante la autoridad» por estado. | denunciar-maltrato | obligatorio (CDMX) | falta | alta | BA-18 EST-18 BP-v03 |
| F08 | Verificación de refugios según el estado (padrón, autorización, MVZ) con insignias separadas y de alcance claro. | Leyes estatales; LPBA CDMX arts. 13 Bis y 42; LFPC arts. 32 y 76 Bis fr. IV | Formulario condicionado por estado; reverificación anual. | verificacion | obligatorio | parcial (revisión de INE y acta por administradores) | alta | BA-21 EST-17 IC-24 BP-27 |
| F09 | Contenido prohibido sobre animales: crueldad, peleas, zoofilia, mutilaciones, especies silvestres, rifas o premios con animales. | CPEUM art. 4; CP DF arts. 350 Bis a 350 Quinquies; CPF arts. 419 Bis y 420 fr. IV; LPBA CDMX art. 25 | Lineamientos de la comunidad; clasificador previo en la importación. | comunidad | obligatorio | parcial | alta | BA-06 BA-17 BA-26 BA-27 |
| F10 | Casas de paso: términos propios, convenio de hogar temporal y responsabilidad durante la guarda. | CCF arts. 1929 y 2516 a 2522; leyes estatales | Términos y convenio. | terminos-casas-de-paso | recomendado | parcial (Términos §12) | media | BA-23 IC-11 |
| F11 | Registros oficiales del perro (RUAC de la CDMX gratuito, padrones) como dato privado; nunca cobrarlos. | LPBA CDMX arts. 4 fr. XXXIV Bis 1 y 4 BIS 1 fr. I | Campo de folio privado. | adopcion-responsable | recomendado | falta | alta | BA-14 BA-v01 |
| F12 | No presentar como vigente la Ley General de bienestar animal y preparar cláusulas para su art. 52 fr. III. | Minuta aprobada por el Senado el 29-09-2026 (no vigente) | Vigilancia semanal y texto preparado. | marco-legal-bienestar-animal | recomendado | no aplica aún | media | EST-01 EST-02 BA-02 |

### G. Tienda (consumidor y comercio electrónico)

| ID | Requisito | Fundamento | Acción | Página(s) | Prioridad | Estado actual | Confianza | Hallazgos |
|---|---|---|---|---|---|---|---|---|
| G01 | Precio total (producto, envío, IVA) y vigencia visibles antes de pagar. | LFPC art. 7 Bis; Reglamento LFPC arts. 5 y 6; LIVA art. 18-J fr. I | Desglose en ficha y checkout; leyenda de IVA según quién emite. | terminos-tienda, tarifas | obligatorio | parcial | alta | CE-03 FT-06 BP-23 |
| G02 | Información del producto y del refugio vendedor en cada ficha. | LFPC arts. 33, 34 y 76 Bis fr. IV; NMX num. 5.3 | Campos mínimos e identificación del refugio. | terminos-tienda | obligatorio | parcial | alta | CE-04 IC-05 |
| G03 | Paso «Revisa tu pedido»: resumen, corrección, aceptación de condiciones y consentimiento de cobro anticipado. | LFPC arts. 15 y 76 Bis 1 fr. II y III | Pantalla de confirmación antes de ir a Mercado Pago. | terminos-tienda | obligatorio | falta | alta | CE-05 CE-06 BP-v08 |
| G04 | Comprobante del pedido y prueba de la transacción. | LFPC arts. 12, 52, 55 y 76 Bis 1 fr. IV; CCom art. 93 | Correo y «Mis pedidos» (HTML y PDF) con la versión de las condiciones aceptadas. | terminos-tienda | obligatorio | parcial | alta | CE-07 |
| G05 | Revocación en 5 días hábiles sin responsabilidad. | LFPC arts. 51 y 56 | Botón «Revocar» y reembolso. | envios-devoluciones-garantias | obligatorio | parcial (en desarrollo: order_flow.py calcula el plazo en días hábiles y Order admite devolución por «arrepentimiento»; faltan textos y validación legal) | alta | CE-09 |
| G06 | Defectos o producto distinto: reposición, devolución o bonificación de al menos 20 %; garantía no menor de 90 días si se ofrece. | LFPC arts. 77 a 84, 92, 92 Ter y 93 | Flujo «Tengo un problema con mi pedido»; póliza digital. | envios-devoluciones-garantias | obligatorio | parcial (devoluciones con motivos defectuoso, no corresponde y no llegó en desarrollo; falta bonificación mínima de 20 % y póliza) | alta | CE-10 CE-11 CE-12 |
| G07 | Envíos: plazos, cobertura, rastreo y responsabilidad del operador frente a la paquetería. | LFPC arts. 7, 42, 53 y 90 fr. III; NMX num. 9.2 | Política de envíos; guía y rastreo visibles. | envios-devoluciones-garantias | obligatorio | parcial (carrier y tracking_number existen en Order) | alta | CE-13 BP-21 |
| G08 | Catálogo sin productos prohibidos o regulados sin permiso: animales, medicamentos, alimentos sin registro SENASICA, productos sin NOM de etiquetado. | LFSA art. 92; NOM-012-SAG/ZOO-2020; NOM-050-SCFI-2004; NOM-004-SE-2021; NOM-024-SCFI-2013 | Categorías cerradas y revisión previa. | productos-prohibidos | obligatorio | falta | media | CE-24 CE-25 BA-25 |
| G09 | Publicidad veraz y marketing con causa comprobable («X % llega al refugio»). | LFPC arts. 32 a 35, 128 Bis y 128 Ter fr. VI; Lineamientos PROFECO (DOF 24-07-2012) | Expediente de sustento; tablero de fondos. | transparencia-fondos, terminos-tienda | obligatorio | falta | alta | CE-17 CE-v01 CE-31 |
| G10 | Promociones con vigencia y condiciones; rifas y sorteos solo con permiso de SEGOB (se prohíben en la plataforma). | LFPC arts. 46 a 50; LFJS arts. 2 a 4 | Bloquear rifas en tienda, campañas y bot. | terminos-tienda, comunidad | obligatorio | falta | media | CE-18 CE-v03 DON-23 |
| G11 | Confidencialidad del comprador frente a los refugios vendedores: datos mínimos de envío, ocultos al vencer el plazo de reclamación. | LFPC art. 76 Bis fr. I y II; LFPDPPP art. 35 | Panel del refugio con datos mínimos. | terminos-vendedores, acuerdo-datos-refugios | obligatorio | parcial | alta | CC-v02 BP-v02 CE-20 |
| G12 | Atención a clientes, PROFECO y Concilianet (prometer Concilianet solo con convenio). | LFPC arts. 76 Bis fr. III y 97 a 117 | Página de atención con plazos. | atencion-y-quejas | obligatorio | parcial | alta | CE-21 CE-22 CE-v04 |
| G13 | Modelo jurídico único de la tienda (comisión en nombre propio o del refugio) reflejado igual en Términos, convenio y CFDI. | CCom arts. 273 y 283 a 285; LFPC art. 2 fr. II | Decisión del abogado y del contador; reescribir Términos 4.2, 14.1 y 14.7. | terminos-tienda, terminos-vendedores | obligatorio | parcial (los Términos mezclan modelos) | media | CE-23 IC-07 FT-08 |
| G14 | Pago sin almacenar tarjetas (Checkout Pro, SAQ A) e información previa de las medidas de seguridad. | LFPC art. 76 Bis fr. II; Términos de Mercado Pago para Desarrolladores sección 10; PCI DSS v4.0.1 | Texto de seguridad de pagos; nunca guardar datos de tarjeta. | seguridad, terminos-tienda | recomendado | existe (Checkout Pro) / falta el texto | media | SI-14 SI-15 BP-v09 |
| G15 | No discriminar ni condicionar la venta. | LFPC art. 58 | Revisar criterios de venta y de cuestionarios. | terminos-tienda | obligatorio | por revisar | alta | CE-v02 |
| G16 | Reseñas de productos solo de compradores verificados y sin ocultar negativas legítimas. | LFPC art. 32; NMX num. 5.3.3 | Política de reseñas común. | resenas | recomendado | por revisar | alta | CE-29 |

### H. Fiscal, pagos y donativos

| ID | Requisito | Fundamento | Acción | Página(s) | Prioridad | Estado actual | Confianza | Hallazgos |
|---|---|---|---|---|---|---|---|---|
| H01 | CFDI por cada venta en 24 horas; datos del receptor sin exigir la Constancia; factura global. | CFF arts. 29, 29-A fr. IV y 83 fr. IX; RCFF art. 39; RMF 2026 reglas 2.7.1.21 y 2.7.1.23 | Contratar PAC; timbrar en el webhook; global mensual. | facturacion | obligatorio | parcial (en desarrollo: services/invoicing.py con PAC Facturama; el refugio sube su CFDI de venta; claves SAT por confirmar con el contador) | alta | FT-02 FT-03 FT-04 |
| H02 | Con comisión mayor que 0, régimen de plataforma de intermediación: CFDI de comisión, retenciones, CFDI de retenciones (día 5), informativa (día 10), entero (día 17), acceso del SAT (30-B) y alta como retenedor. | LIVA arts. 1o.-A Bis, 18-B fr. II y 18-J; LISR arts. 113-A y 113-C; LIF 2026 art. 25 fr. VI y IX; CFF art. 30-B; RMF 2026 reglas 2.9.21 y 12.2.x | Puerta de salida a producción completa o marketplace_fee = 0 hasta tenerla. | facturacion, tarifas, terminos-vendedores | obligatorio | parcial (config.py trae MERCADOPAGO_MARKETPLACE_FEE_PERCENT=10 por defecto; CFDI de comisión y de retenciones mensuales en desarrollo; faltan alta como retenedor, informativa mensual y acceso del SAT 30-B) | alta (media en el alcance de la retención con Split) | FT-07 FT-09 FT-10 FT-11 FT-12 FT-17 FT-v02 IC-v01 |
| H03 | KYC fiscal de refugios vendedores; sin RFC no venden. | LIVA art. 18-J fr. III; RMF 2026 reglas 12.2.7 y 12.2.10 | Alta fiscal en el panel del refugio. | terminos-vendedores | obligatorio | parcial (endpoint de datos fiscales del refugio en routers/refuges.py) | alta | FT-19 FT-21 |
| H04 | Devoluciones documentadas con CFDI de egreso o cancelación y ajuste de retenciones. | CFF arts. 29 y 29-A; RMF 2026 regla 2.7.1.35 | Procedimiento fiscal de reembolsos. | facturacion, envios-devoluciones-garantias | obligatorio | falta | alta | FT-18 |
| H05 | Moderar anuncios de compraventa de facturas. | CFF arts. 29-A fr. IX y 113 Bis | Patrones de bloqueo y denuncia. | comunidad, productos-prohibidos | obligatorio | falta | alta | FT-26 |
| H06 | Flujo de fondos sin custodia: Split 1:1 por refugio; nunca saldos, monederos ni puntos canjeables; cuenta concentradora solo transitoria y con condiciones. | LGOAAC arts. 64, 81-A Bis y 81-B; LRITF arts. 12, 22 a 24 y 124; LFPIORPI art. 17 fr. XI; CFF art. 59 fr. III; Términos MP Standard 4.7 y 9.6 | PAYMENTS_MODE por producto; OAuth con renovación a 180 días. | donativos, tarifas, transparencia-fondos, terminos-refugios | obligatorio | parcial (Split 1:1 por OAuth en desarrollo para tienda y donativos, con renovación de tokens; los donativos caen a la cuenta de la plataforma solo con DONATIONS_FALLBACK_TO_PLATFORM_ACCOUNT o en desarrollo) | media | CF-01 CF-02 CF-03 CF-05 CF-09 CF-12 CF-13 FT-16 FT-22 DON-01 |
| H07 | Obtener la excepción escrita de Mercado Pago para donativos y para el modelo marketplace. | Términos MP Standard 4.7 y 9.6; Actividades Prohibidas («Donativos») | Escrito con número de caso y respuesta archivada. | donativos | obligatorio (contractual) | falta | alta | CF-05 CF-06 |
| H08 | Donativos: monto bruto, comisiones y neto antes de pagar; deducibilidad solo con donataria vigente. | LFPC arts. 7 Bis, 32 y 76 Bis fr. IV; LISR arts. 27 fr. I y 151 fr. III; CFF art. 29-A fr. V b) | Pantalla Donar con desglose; insignia de donataria verificada en el SAT. | donativos, tarifas, donataria-autorizada | obligatorio | parcial (Donation guarda comisión y neto; comisión de donativos 0 por defecto; faltan desglose en pantalla y verificación de donataria) | alta | DON-07 DON-10 DON-04 DON-06 |
| H09 | Donativos no onerosos: separados de la tienda, de la adopción y de beneficios; ranking sin puntos por donar. | LISR arts. 27 fr. I, 151 fr. III y 82-Quáter A fr. II; CCF art. 2336; LFPC art. 32 | Quitar los puntos por donativo o mostrarlos aparte como «Apoyo recibido». | donativos, cero-venta | obligatorio | parcial (autodonación bloqueada; los puntos por donativo siguen en services/payment_flow.py) | alta | DON-08 DON-16 AD-07 |
| H10 | Prevención de lavado: tope por donativo y acumulado por debajo de 1,605 UMA; aviso a refugios A.C. sujetos obligados; medidas de la UIF para asociaciones sin fines de lucro (RCG en vigor 30-11-2026). | LFPIORPI arts. 17 fr. XIII y 18; Acuerdo 115/2026 (DOF 07-08-2026) | Topes en código; página de prevención. | prevencion-lavado, donativos | obligatorio | falta | alta | DON-11 DON-v01 |
| H11 | El CFDI de donativo lo emite la donataria en 24 horas; resolver el desfase con la dispersión. | CFF art. 29-A fr. V b); RCFF arts. 39 y 40; RMF 2026 regla 3.10.1.2 | Con Split el refugio recibe directo; notificarle de inmediato. | donativos, facturacion | obligatorio | falta | alta | DON-04 DON-05 |
| H12 | Contracargos y retenciones de Mercado Pago: dispersar solo fondos liberados; reserva y compensación en el convenio. | Términos MP Standard 5.2, 5.4, 5.7 y 5.9 | Cláusulas del convenio; ledger. | terminos-refugios, donativos | obligatorio | falta | alta | CF-07 CF-08 DON-18 |
| H13 | No usar denominaciones reservadas (wallet, monedero, saldo, «regulada por la CNBV», transmisor de dinero). | LRITF art. 12; LGOAAC art. 81-B fr. I | Lista de palabras prohibidas en interfaz, correos y publicidad. | donativos, transparencia-fondos | obligatorio | por revisar en los textos | alta | CF-15 |
| H14 | Tablero público de a dónde va el dinero (agregado, sin datos personales). | Buena práctica; LFPC art. 32 (veracidad) | /transparencia/donativos con liquidaciones por refugio. | transparencia-fondos | recomendado | falta | alta | BP-20 DON-22 CE-31 |
| H15 | Tarifas y comisiones en una sola página, con IVA. | LFPC arts. 7 Bis y 76 Bis fr. V | Página de tarifas. | tarifas | obligatorio | falta | alta | BP-26 |

### I. Seguridad e incidentes

| ID | Requisito | Fundamento | Acción | Página(s) | Prioridad | Estado actual | Confianza | Hallazgos |
|---|---|---|---|---|---|---|---|---|
| I01 | Medidas de seguridad administrativas, técnicas y físicas documentadas (documento de seguridad interno). | LFPDPPP art. 18; Recomendaciones DOF 30-10-2013 (orientativas) | SGSDP con inventario y análisis de riesgo. | seguridad | obligatorio | parcial (TLS con HSTS, CSP, bcrypt, sin EXIF y respaldos cifrados existen) | alta | SI-02 SI-03 DP-21 |
| I02 | MFA para administradores, mínimo privilegio y revisión de accesos. | LFPDPPP art. 18 | TOTP o WebAuthn para admin y superadmin. | seguridad | recomendado | falta | media | SI-22 |
| I03 | Cifrado en reposo de uploads/private y de sus instantáneas. | LFPDPPP art. 18 | Cifrar documentos y no copiarlos en claro. | seguridad | recomendado | falta | media | SI-23 |
| I04 | Aviso inmediato a titulares ante vulneraciones que los afecten de forma significativa; plantillas y bitácora. | LFPDPPP art. 19; Reglamento arts. 63 a 66 (referencia) | Plan de respuesta; botón de aviso masivo; tabla security_incidents. | seguridad | obligatorio | parcial (sección 19 del aviso conforme; sin plan ni herramienta) | alta | SI-04 SI-05 DP-22 |
| I05 | Avisos contractuales de incidentes (Mercado Pago 24 h; Meta tan pronto como sea posible), preservación de evidencia y denuncia. | Términos MP para Desarrolladores 1.6, 6.6 y sección 10; Meta Platform Terms 6.b; CPF arts. 211 bis 1 a 7 | Directorio de contactos de incidentes. | seguridad | obligatorio | falta | alta | SI-06 SI-v01 |
| I06 | Canal de reporte de vulnerabilidades: /.well-known/security.txt y política de divulgación. | Meta Platform Terms 6.a.ii (contractual); RFC 9116 (estándar) | Publicar archivo y política. | security-txt, seguridad | obligatorio (contractual) | falta | alta | SI-07 |
| I07 | Ejecutar de verdad los plazos de conservación: purgas automáticas, bloqueo y «modo incidente». | LFPDPPP arts. 10, 24, 25 y 58 fr. IV y VI | Tareas programadas de purga por categoría. | conservacion | obligatorio | parcial (solo expiración de reportes y de importados en celery_app.py) | alta | SI-18 SI-v03 |
| I08 | Respaldos cifrados con plazo publicado y reaplicación de supresiones al restaurar. | LFPDPPP arts. 10, 13 y 18 | Fijar PLAZO_DE_CONSERVACION_DE_RESPALDOS (local 14 días, externo 30). | conservacion, seguridad | obligatorio | parcial (respaldos cifrados existen; plazo sin publicar) | alta | SI-19 |
| I09 | Registros técnicos e IP: 90 días o menos, IP truncada a 30 días, rotación por tiempo. | LFPDPPP arts. 2 fr. V, 10 y 12; LMTR art. 182 | Rotación de Nginx por tiempo. | conservacion | obligatorio | parcial (rotación por tamaño) | media | SI-20 |
| I10 | Eliminación de datos de la plataforma de Meta y URL de instrucciones. | Meta Platform Terms 3.d (contractual) | Página de eliminación de datos; comando ELIMINAR del bot. | eliminacion-datos | obligatorio (contractual) | falta | alta | SI-v02 |
| I11 | Procedimiento para atender verificaciones de la SABG y carpeta de evidencias de cumplimiento. | LFPDPPP arts. 54, 55, 58 fr. XIV y 60 | Procedimiento interno y carpeta de evidencias. | seguridad | recomendado | falta | alta | SI-v04 SI-24 |
| I12 | Gestión de vulnerabilidades: escaneo de dependencias en CI, imágenes fijadas y prueba de penetración. | LFPDPPP art. 18 | CI y pentest antes de afirmarlo en la página pública. | seguridad | recomendado | parcial (imágenes fijadas; BACKEND_TAG por defecto latest) | media | SI-28 |
| I13 | La página pública de seguridad solo afirma medidas que existen. | LFPDPPP arts. 5 y 14; LFPC art. 76 Bis fr. II | Redactar desde el estado final del código. | seguridad | recomendado | parcial | alta | SI-29 |

### J. Clínicas veterinarias y reseñas

| ID | Requisito | Fundamento | Acción | Página(s) | Prioridad | Estado actual | Confianza | Hallazgos |
|---|---|---|---|---|---|---|---|---|
| J01 | Sin cédula no hay perfil: cotejo en el Registro Nacional de Profesionistas y reverificación anual. | LGS arts. 79 y 83; Ley Reglamentaria del art. 5o. constitucional arts. 24, 25, 62 y 63; CPF art. 250 fr. II | Verificación manual con captura privada; insignia con fecha. | veterinarias, verificacion, terminos-clinicas | obligatorio | existe (modelo Veterinary con cédula, verified_at y verification_expires_at; tarea de caducidad de verificaciones) | alta | VET-01 VET-03 VET-16 |
| J02 | Publicar nombre, cédula e institución del médico veterinario responsable. | LGS art. 83 | Perfil público. | veterinarias | obligatorio | existe (campos cedula_profesional y cedula_institution) | media | VET-02 |
| J03 | GuauWoow no presta el servicio veterinario: deslinde, aviso de urgencias y ninguna venta o intermediación de medicamentos. | LFPC arts. 1, 2 y 5; Ley Reglamentaria del art. 5o. arts. 33, 34 y 71; CCF art. 1910; LFSA art. 92 | Textos de la sección; prohibición en perfiles, chat y bot. | veterinarias, terminos-clinicas | obligatorio | parcial (deslinde y aviso de urgencias en cada perfil según routers/veterinaries.py; falta la página pública y el anexo de Términos) | media | VET-09 VET-05 |
| J04 | El perfil es publicidad del proveedor: solo afirmaciones comprobables, sin superlativos ni garantías; contenido pagado marcado «Patrocinado». | LFPC arts. 32, 35 fr. I, 128 Bis y 128 Ter fr. VI | Validación de contenido y expediente de sustento. | terminos-clinicas, resenas | obligatorio | parcial (sin superlativos ni «sin receta» y lista cerrada de servicios; faltan expediente de sustento y etiqueta «Patrocinado») | alta | VET-08 VET-17 |
| J05 | Google Places: guardar solo place_id; reseñas en tiempo real (máximo 5) con atribución del autor, enlace a Google Maps y reporte; nunca junto a un mapa que no sea de Google; sin IA. | Google Maps Platform ToS 3.2.2 y 3.2.3; Service Specific Terms A.3 y 14.x; políticas de Places (15-10-2026) | Bloque separado; consulta desde el servidor. | veterinarias, resenas, proveedores | obligatorio (contractual) | existe (google_places.py sin caché y desde el servidor) / revisar que no se muestre con el mapa OSM | alta | VET-10 VET-11 |
| J06 | Reseñas propias: usuarios verificados, experiencia propia, etiqueta de incentivo, sin ocultar negativas, una respuesta pública de la clínica. | LFPC art. 32; NMX num. 5.3.3 | Reglas públicas; campos incentivized y owner_reply. | resenas | obligatorio | existe en código (teléfono verificado, una reseña por cuenta, nunca la propia clínica, orden cronológico, etiqueta de incentivo, respuesta única de la clínica); falta la política pública | media | VET-12 |
| J07 | Moderación diligente de reseñas (opinión frente a imputación de hechos), aclaración voluntaria y responsable de reclamaciones publicado. | CCF arts. 1916 y 1916 Bis; Ley de Responsabilidad Civil CDMX arts. 25, 32 y 38; Ley de réplica (probablemente no obliga) | Flujo de reportes con plazos y formulario público. | resenas, moderacion | obligatorio | parcial (filtro de datos personales y retención para revisión humana de imputaciones o insultos; faltan plazos publicados, aclaración y formulario público) | media | VET-13 VET-14 |
| J08 | Datos mínimos del veterinario y del reseñador; aviso al veterinario registrado por un tercero. | LFPDPPP arts. 2 fr. X, 7, 8, 9 fr. II, 12 y 17 | Finalidades en el aviso integral. | privacidad, veterinarias | obligatorio | parcial | alta | VET-15 |
| J09 | Cédula falsa o ajena: despublicación inmediata, 5 días hábiles para aclarar, revocación y evaluación de denuncia. | CPF art. 250 fr. II; Ley Reglamentaria del art. 5o. arts. 62, 63 y 73 | Procedimiento documentado. | verificacion, terminos-clinicas | obligatorio | falta | alta | VET-16 |

### K. Ingesta de grupos públicos de Facebook

| ID | Requisito | Fundamento | Acción | Página(s) | Prioridad | Estado actual | Confianza | Hallazgos |
|---|---|---|---|---|---|---|---|---|
| K01 | Base jurídica de la ingesta: las publicaciones de grupos no son fuente de acceso público; aviso por fuente indirecta o medida compensatoria con autorización. | LFPDPPP arts. 2 fr. X, 9, 17 y 26; Criterios Generales (DOF 18-04-2012) | Dictamen antes de activar en producción; página de contenido importado. | contenido-importado | obligatorio | parcial (código activo; dictamen pendiente) | media | DP-26 DP-v01 CP-22 |
| K02 | Minimización: solo fotos y texto sin teléfonos, correos, nombres ni enlaces; zona aproximada; enlace al original; difuminar rostros. | LFPDPPP art. 12 | Ampliar strip_pii a nombres; filtro de rostros; descarte de ventas. | contenido-importado | obligatorio | parcial (strip_pii quita teléfonos, correos, @usuarios y enlaces; nombres y rostros no) | media | CP-22 CC-27 AD-12 |
| K03 | Caducidad de 30 días con borrado real de fotos y texto (no solo estado «expired») y retención cero en Apify. | LFPDPPP arts. 10 y 12; Meta Platform Terms 3.d | Tarea que borre archivos; datasets de Apify sin retención. | contenido-importado, conservacion | obligatorio | parcial (expire_imported_reports solo cambia el estado) | media | SI-v02 DP-19 |
| K04 | Retiro a petición del autor sin cuenta (menos de 72 h) y oposición. | LFPDPPP arts. 26 y 31; LFDA art. 114 Octies | Botón «Soy el autor: retirar o reclamar». | contenido-importado, derechos-de-autor | obligatorio | falta | media | CP-22 BP-15 |
| K05 | Riesgo contractual con Meta por recolección automatizada (Apify) para una app que depende de WhatsApp Cloud API y Pages API. | Meta Automated Data Collection Terms §2 y §3; Meta Platform Terms; Términos de servicio de Meta 3.2 | Dictamen del abogado de tecnología y contrato con Apify antes de operar. | contenido-importado, proveedores | obligatorio (decisión) | falta | baja | CP-21 CC-v03 |
| K06 | Derechos de autor de las fotos importadas: GuauWoow «inicia» la conducta y no tiene puerto seguro. | LFDA arts. 114 Octies (primer párrafo) y 148 fr. II | Miniatura con atribución y enlace; retiro rápido. | contenido-importado | obligatorio | parcial | media | CP-22 |
| K07 | Envíos de voluntarios tratados como contenido importado salvo autorización del autor. | LFPDPPP art. 17; LFDA art. 30 | Leyenda de aceptación del voluntario y archivo de la autorización. | contenido-importado | recomendado | parcial (endpoint de voluntarios existe) | baja | CP-21 |

### L. Transparencia

| ID | Requisito | Fundamento | Acción | Página(s) | Prioridad | Estado actual | Confianza | Hallazgos |
|---|---|---|---|---|---|---|---|---|
| L01 | Centro legal y de transparencia enlazado desde landing, app, correos, checkout y bot. | Lineamientos Decimoprimero; NMX num. 5.2.1; buena práctica | Hub /legal/ con índice y fecha «vigente al». | centro-legal | recomendado | falta (app/legal/ solo tiene Términos y Aviso) | alta | BP-01 DP-34 IC-25 CP-28 |
| L02 | Informe de transparencia semestral con datos disociados. | Buena práctica; Decreto NNA art. 4 fr. IX (reportes estadísticos) | Primer informe a los 6 meses de operar. | informe-transparencia | buena práctica | falta | alta | BP-32 CP-13 |

Además de esta matriz, `requisitos.json` contiene **312 requisitos de producto** y **150 requisitos de tienda** fusionados (sin duplicados) de todas las secciones, clasificados por área.

## 5. Modelo fiscal y operativo recomendado para tienda y donativos

Detalle: [fiscal-tienda](secciones/fiscal-tienda.md), [donativos](secciones/donativos.md), [gap de custodia de fondos y Mercado Pago](secciones/gap-custodia-fondos-transmisor-dinero-y-terminos-mercado-pago.md), [consumidor-ecommerce](secciones/consumidor-ecommerce.md), [identidad-contratos](secciones/identidad-contratos.md).

### Recomendación

1. **Operador: persona moral mercantil** (S.A.S. o S.A. de C.V.; el abogado corporativo elige). Razones: es comerciante (calendario de 10 años claro, CCom arts. 3 y 38), puede ser retenedor en el régimen de plataformas (LISR art. 113-A), separa el patrimonio del dueño, y las cuentas de Mercado Pago, Meta y Google quedan a nombre de la empresa. Si los donativos crecen, una **A.C. separada** puede gestionar programas de apoyo (decisión posterior, con contador).
2. **Tienda: el refugio vende; GuauWoow intermedia con Split 1:1** (modelo B operado con Split). Cada refugio vendedor cobra con **su propia cuenta de Mercado Pago verificada**, vinculada por OAuth (token de 180 días, renovación automática); GuauWoow solo recibe `marketplace_fee`. La plataforma no custodia dinero de terceros, no dispersa ni concilia ventas ajenas.
3. **Comisión 0 al lanzar** y comisión mayor que 0 solo cuando el contador confirme la puerta fiscal: alta como retenedor (ficha 28/CFF), CFDI de comisión con IVA, motor de retenciones preparado (hasta que el contador confirme si con Split hay «cobro por cuenta del enajenante», regla 12.2.5), CFDI de retenciones el día 5, informativa el día 10, entero el día 17, acceso en línea del SAT (CFF art. 30-B, ficha 168/CFF) y monitoreo del CSD.
4. **CFDI de venta:** lo emite el refugio si factura; si no, la plataforma lo emite a cuenta del refugio (regla 2.7.1.3) con autorización expresa en el contrato de vendedor. **Refugios sin RFC no venden** (sí pueden recibir donativos por la vía que se defina). Datos del comprador sin exigir la Constancia de Situación Fiscal (CFF art. 29-A fr. IV).
5. **Donativos: Split por refugio (fase 2) o cobro directo del refugio (fase 3)**, con comisión 0 recomendada y la **excepción escrita de Mercado Pago** para «Donativos» (por la plataforma y, si Mercado Pago lo pide, por cada refugio). La cuenta concentradora (hoy solo como respaldo configurable) se admite únicamente como **transición corta**: comisión 0, sin saldos, dispersión en N días hábiles desde la liberación de Mercado Pago, cuenta separada, conciliación diaria, convenio con mandato y compensación de contracargos, expediente de identificación de cada refugio, dictamen financiero y de PLD (y, si se mantiene, consulta a la UIF) y fecha de migración publicada.
6. **Nunca, en ninguna fase:** saldos o monederos, puntos de ranking canjeables, «fondo común», campañas con meta y devolución automática, recargos por pagar con Mercado Pago, ni las palabras «wallet», «monedero», «saldo», «regulada por la CNBV», «transmisor de dinero» (LRITF art. 12; LGOAAC art. 81-B).
7. **Deducibilidad:** solo los refugios **donatarias autorizadas vigentes** emiten CFDI de donativo (en 24 horas desde que reciben). La plataforma verifica el estatus contra el padrón del SAT, muestra «deducible» solo en esos casos y no codifica la fracción del art. 79 LISR (la toma del oficio de cada refugio).

### Opciones evaluadas

| Opción | Cómo funciona | A favor | En contra | Decisión |
|---|---|---|---|---|
| A. Venta propia | GuauWoow compra al refugio y revende | Control total; CFDI propio | Inventario, IVA propio, el refugio debe facturar a la plataforma; refugios sin RFC quedan fuera | Solo para mercancía propia de GuauWoow |
| B1. Intermediación con cuenta concentradora | Todo cobra la cuenta de la plataforma y luego dispersa (era el flujo original de donativos; hoy queda como respaldo con DONATIONS_FALLBACK_TO_PLATFORM_ACCOUNT) | Simple; un solo ledger | Términos de Mercado Pago 9.6 y «Donativos» prohibidos sin excepción; riesgo de transmisor de dinero (LGOAAC 81-A Bis) si hay comisión; LFPIORPI 17 fr. XI; presunción de ingresos (CFF 59 fr. III); contracargos después de dispersar; bloqueo de la única pasarela | Solo transitoria y con condiciones; nunca con comisión sin dictamen |
| B2. Intermediación con Split 1:1 y comisión 0 | Cada refugio cobra con su cuenta; GuauWoow integra | Sin custodia; muy baja exposición regulatoria; probablemente fuera del régimen de plataformas (LIVA art. 18-B exige contraprestación: confirmar con contador) | Sin ingreso por comisión; refugios necesitan cuenta verificada (KYC) | **Recomendada al lanzar** |
| B3. Split 1:1 con comisión mayor que 0 | Igual que B2, con `marketplace_fee` | Ingreso para la plataforma; sin custodia | Régimen completo de plataformas; posible doble retención con Mercado Pago; CFDI de comisión a cada refugio | Cuando la puerta fiscal esté lista |
| C. Cobro directo del refugio | El refugio publica su propio enlace o botón verificado | La menor exposición | Sin conciliación ni prueba de destino; verificar enlaces cada semestre | Para donativos de refugios sin Split |

### Datos que hay que recabar de cada refugio o vendedor (KYC)

| Dato o documento | Para qué | Conservación |
|---|---|---|
| Tipo de contribuyente (persona física o rescatista, A.C. no donataria, donataria autorizada) | Reglas fiscales, deducibilidad, retenciones | R09 |
| Nombre o razón social exacto como en el SAT, RFC, CURP (persona física), régimen fiscal, CP y domicilio fiscal | CFDI, informativa mensual (LIVA art. 18-J fr. III), retenciones | R09 |
| Constancia de Situación Fiscal reciente (solo como respaldo KYC del vendedor) | Validación; nunca condicionar a ella la factura del comprador | R09 |
| Representante legal, poder e identificación (verificación en vivo o copia borrada a 30 días) | Firma del convenio; identificación (LFPIORPI art. 18) | R15 y R16 |
| Acta constitutiva (páginas esenciales) y beneficiario controlador | Identificación del cliente | R09 |
| Cuenta de Mercado Pago verificada a nombre del refugio (user_id por OAuth) | Split 1:1 | R13 |
| CLABE y banco a su nombre con estado de cuenta (solo en fase 1 o 3) | Dispersión o cobro directo | R18 |
| Correo para CFDI y autorización expresa para que la plataforma emita CFDI a su nombre (regla 2.7.1.3) | Facturación a cuenta de terceros | R03 |
| Si es donataria: número y fecha del oficio, rubro, ejercicio autorizado y verificación en el padrón del SAT | Insignia de donataria y CFDI de donativo | R16 |
| Opción de pago definitivo (persona física) y declaración de cuentas en el extranjero (regla 12.2.10) | Retenciones de plataformas | R09 |
| Constancia de padrón, registro o autorización estatal; nombre y cédula del MVZ responsable si hay albergue | Verificación por estado | R16 |
| Revisión en la lista del art. 69-B del CFF (EFOS) | Evitar operaciones simuladas | R16 |
| Excepción o inscripción propia en Mercado Pago para donativos, si la pide Mercado Pago | Contrato con Mercado Pago | R47 |
| Aceptación del convenio (versión, fecha, IP) con las cláusulas de no cobro por adopción, compensación de contracargos y confidencialidad | Exigibilidad | R03 |

### Puerta de salida a producción (`SHOP_ENABLED=true` y activación de donativos)

1. Persona moral constituida con RFC, CSD en gestor de secretos, régimen y CP; expediente de beneficiario controlador.
2. Fase de cobro por producto registrada en configuración (`PAYMENTS_MODE` por producto) y reflejada igual en Términos 4, 14.1, 15.1 y 15.3, convenio, tarifas y transparencia.
3. Respuesta escrita de Mercado Pago (número de caso) sobre donativos, modelo marketplace y retenciones de ISR e IVA en Checkout Pro.
4. Split: aplicación Marketplace, Redirect URL, tokens cifrados y renovación, webhook filtrado por `collector_id`, prueba en sandbox con tarjeta.
5. Si hay comisión: aviso de obligaciones como retenedor, PAC verificado en la lista del SAT, `tax_rates` 2026 con fundamento, tareas de CFDI de retenciones, informativa y entero, acceso de solo lectura para el SAT.
6. Catálogo con claves del SAT y categorías prohibidas bloqueadas; alta fiscal de cada vendedor; contrato de vendedor firmado.
7. Flujos de consumidor (sección G de la matriz) y textos sin marcadores.
8. Confirmar que el modo simulado solo existe en desarrollo (hoy `payments_simulated` lo exige) y que `DONATIONS_FALLBACK_TO_PLATFORM_ACCOUNT` queda apagado en producción salvo fase transitoria documentada.
9. Puntos por donativo retirados del ranking o mostrados aparte (la autodonación ya está bloqueada); topes de donativo por debajo de 1,605 UMA.
10. Dictamen escrito del abogado financiero y de PLD si existe cualquier fase transitoria.

## 6. Calendario de retención

Regla única (resuelve el conflicto 4): **el plazo más largo aplicable a cada categoría, con su punto de inicio**; al vencer, bloqueo y luego supresión o anonimización. Supone operador persona moral mercantil (comerciante). Los plazos marcados como propuesta los fija el abogado; los fiscales, el contador. Este calendario sustituye los «5 años» del aviso y de la cláusula 28.1 actuales y debe ejecutarse con tareas automáticas (hoy solo existen la expiración de reportes y de importados).

| ID | Categoría | Plazo | Inicio | Al vencer | Fundamento | Confianza |
|---|---|---|---|---|---|---|
| R01 | Cuenta y perfil activos | Mientras la cuenta exista; aviso y supresión tras 24 meses sin actividad (propuesta) | Última actividad | Supresión; solo los mínimos de R02 quedan bloqueados | LFPDPPP arts. 10 y 12 | media |
| R02 | Cuenta eliminada: mínimos bloqueados (id, hash de correo y teléfono, fechas, versiones aceptadas) | Supresión general en 30 días o menos; mínimos bloqueados 10 años si hubo compra, donativo o contrato; si no, 1 año | Fecha de eliminación | Supresión definitiva | LFPDPPP arts. 24 y 25 fr. I a III; CCom art. 1047; LFPC art. 14 | media |
| R03 | Bitácora de aceptaciones y consentimientos (Términos, Aviso, 18+ y fecha de nacimiento, condiciones de compra, convenios, opt-in de WhatsApp, licencias de imagen) | 10 años | La aceptación o el fin de la relación, lo que ocurra después | Seudonimizada al borrar la cuenta; supresión al vencer | CCom arts. 49 y 1047; LFPC art. 76 Bis 1 fr. IV; CCF art. 640 | media |
| R04 | Versiones publicadas de documentos legales (HTML, PDF, SHA-256, constancias NOM-151) | Mientras exista una aceptación vigente y 10 años después de la última; la publicación del historial es permanente | Fin de vigencia de la versión | Archivo | CCom art. 49 párr. 2; NOM-151-SCFI-2016 | alta |
| R05 | Pedidos, comprobantes, aceptación de condiciones, reclamaciones, revocaciones, reembolsos, garantías y requerimientos de PROFECO | 10 años | Fecha de la operación | Bloqueo con datos mínimos; supresión al vencer | CCom arts. 38 y 49 (operador comerciante); LFPC arts. 13, 14 y 55; cubre los 5 años del CFF art. 30 | media |
| R06 | Domicilio y teléfono de envío del comprador | Visibles para el refugio hasta 2 meses después de la entrega; anonimizar al vencer la garantía más 1 año, salvo lo que conste en el comprobante o CFDI | Entrega | Ocultar y luego anonimizar | LFPC arts. 14, 76 Bis fr. I y 93; LFPDPPP art. 12 | media |
| R07 | CFDI emitidos y recibidos, contabilidad y datos fiscales del comprador que pidió factura | 5 años desde la declaración relacionada (CFF) y no menos que el expediente del pedido (10 años) | Presentación de la declaración relacionada / fecha de la operación | Bloqueo; fuera del borrado ARCO mientras corre el plazo | CFF art. 30; CCom art. 38 | alta |
| R08 | Base por transacción para el acceso en línea del SAT (solo si hay comisión) | 5 años, disponible de forma permanente | Registro de la transacción | Sin borrado por ARCO durante el plazo | CFF arts. 30 y 30-B; RMF 2026 regla 2.9.21 | alta |
| R09 | Expediente fiscal y KYC del refugio vendedor o receptor de fondos (RFC, constancia, CLABE, oficio de donataria, beneficiario controlador) | 10 años | Última operación | Bloqueo y supresión | CFF art. 30; LFPIORPI art. 18 fr. IV (si aplica la fr. XI o XIII) | media |
| R10 | Ledger de pagos, liquidaciones, comisiones, contracargos y conciliaciones de Mercado Pago | 10 años | Cada operación | Bloqueo | CFF art. 30; CCom arts. 38, 49 y 298; LFPIORPI art. 18 fr. IV | media |
| R11 | Donativos (folio, ID de pago, monto, refugio, comisiones, neto) y datos fiscales del donante que pidió CFDI | 10 años; si el donante borra su cuenta, datos bloqueados sin uso operativo | Fecha del donativo | Supresión | CFF art. 30; CCom arts. 38 y 49; LFPIORPI art. 18 fr. IV | media |
| R12 | Expediente de identificación de donantes de 1,605 UMA o más (a cargo del refugio sujeto obligado) | 10 años | Fecha de la actividad vulnerable | Lo conserva el refugio | LFPIORPI arts. 17 fr. XIII y 18 fr. IV | alta |
| R13 | Credenciales OAuth de refugios en Mercado Pago (tokens cifrados) | Mientras la vinculación esté activa; borrado inmediato al revocarse; bitácora de vinculación y revocación 10 años | Revocación | Borrado seguro | Términos de Mercado Pago para Desarrolladores; LFPDPPP arts. 12 y 18 | alta |
| R14 | Comprobantes de entrega y evidencia presentada en contracargos | Mínimo 1 año (Mercado Pago 5.7); se conservan con el pedido (10 años) | Liberación o retiro de los fondos | Con el expediente del pedido | Términos MP Standard 5.7; CCom art. 49 | alta |
| R15 | Imagen de INE, CURP, pasaporte, acta o cédula usada para verificar | 30 días o menos tras aprobar o rechazar (7 días si es verificación reforzada de edad); se conserva solo la constancia | Decisión de verificación | Borrado seguro de la imagen | LFPDPPP arts. 8, 10, 12 y 18 | media |
| R16 | Constancias de verificación de refugios, rescatistas y clínicas (quién, cuándo, método, resultado, vigencia; captura del Registro Nacional de Profesionistas) | Mientras la verificación esté vigente y 2 años después (12 meses para clínicas) | Pérdida de la verificación o baja | Supresión | LFPDPPP art. 12; CCF art. 1910 | media |
| R17 | Documentos de solicitudes de verificación rechazadas | 90 días | Rechazo | Borrado documentado | LFPDPPP art. 12 | media |
| R18 | CLABE y datos bancarios del refugio | Mientras haya pagos; después, bloqueo con el ledger (R10) | Último pago | Supresión al vencer R10 | LFPDPPP art. 7; CFF art. 30 | media |
| R19 | Cuestionarios de adopción | 12 meses tras cerrar la postulación (en poder del refugio, el plazo del acuerdo de datos) | Cierre de la postulación | Supresión | LFPDPPP arts. 10, 12 y 35 | media |
| R20 | Constancia de la carta responsiva de adopción | Mientras dure el seguimiento y el plazo de prescripción civil del estado que fije el abogado | Entrega del animal | Supresión | CCF arts. 2341 a 2344 y códigos estatales | baja |
| R21 | Chats entre usuarios | 90 días tras eliminar la cuenta; con reporte, hasta resolverlo más 12 meses; si hay retiro, lo que pida la bóveda (R30) | Eliminación de la cuenta o resolución del reporte | Supresión | LFPDPPP arts. 10, 12 y 25 fr. III | media |
| R22 | Zona de ubicación guardada (redondeada) | Hasta que la persona la cambie o la borre, o elimine la cuenta | — | Supresión inmediata | LFPDPPP art. 12 | alta |
| R23 | Reportes de perdidos y encontrados resueltos o caducados | Según la tarea de expiración vigente; luego anonimizar conservando ciudad, fecha y resultado | Resolución o caducidad | Anonimización | LFPDPPP arts. 9 fr. III y 10 | media |
| R24 | Evidencia del flujo «encontrado» (microchip, aviso a la autoridad, excepción de refugio) | 5 años (propuesta) | Cierre del caso | Supresión | CCF arts. 775 y 874 y códigos estatales | baja |
| R25 | Reportes importados de grupos de Facebook, reenvíos y envíos de voluntarios (foto, texto depurado, enlace) | 30 días con borrado real (antes si el autor lo pide); nunca más de 12 meses; queda solo el registro de existencia y de retiros | Importación | Borrado de fotos y texto; purga en Apify | LFPDPPP arts. 10, 12 y 17; Meta Platform Terms 3.d | media |
| R26 | Prueba de autorización del autor en envíos de voluntarios | Mientras esté publicado y 2 años después | Retiro de la publicación | Supresión | Ley de Responsabilidad Civil CDMX art. 38 | media |
| R27 | Interacciones del bot de WhatsApp | Al cumplir la finalidad y máximo 12 meses; de inmediato si la persona lo pide | Última interacción | Anonimización | Meta Platform Terms 3.d; LFPDPPP arts. 10 y 24 | media |
| R28 | Mensajes procesados por Meta (WhatsApp Cloud API) | Hasta 30 días en Meta | Recepción | Los borra Meta | Documentación de Meta Cloud API (contractual) | alta |
| R29 | Caché de IA (análisis de fotos, firmas) | Vida del reporte más 30 días, sin identificadores de usuario | Cierre del reporte | Supresión | LFPDPPP arts. 9 fr. III y 12 | media |
| R30 | Bóveda de evidencia de cuentas y contenidos retirados | Al menos 90 días hábiles (135 naturales como margen); más con retención legal, apelación u orden de conservación | Retiro | Borrado con registro | Decreto NNA art. 5 fr. II; LFPA art. 28; LFPDPPP art. 25 fr. II y III; CNPP art. 303 | alta |
| R31 | Material de abuso sexual infantil detectado | Solo el original, con acceso bloqueado, hasta recibir instrucciones de la autoridad | Detección | Según instrucción de la autoridad | Decreto NNA art. 5 fr. II y III; CNPP art. 222; CPF arts. 202 y 202 Bis (tensión pendiente de postura penal) | media |
| R32 | Reportes de moderación, decisiones, apelaciones, acciones automatizadas y evidencias de retiro por venta o cobro | 24 meses; 10 años si involucra a menores o hubo remisión a una autoridad | Resolución | Supresión o anonimización | Ley de Responsabilidad Civil CDMX art. 38 (2 años); LFPC art. 14 (10 años si afecta a NNA) | media |
| R33 | Expedientes de derechos de autor (aviso, contra-aviso, acuses) y hashes de bloqueo | 10 años los expedientes; hashes mientras opere el servicio | Cierre del procedimiento | Supresión | CCom art. 1047 (por analogía); LFDA arts. 114 Octies y 232 Quinquies | media |
| R34 | Requerimientos y alertas a autoridades, denuncias presentadas | 10 años (propuesta) | Respuesta | Supresión | Propuesta operativa; CCom art. 1047 por analogía | baja |
| R35 | Expedientes ARCO, contratos con encargados, bitácora de vulneraciones y evidencias de cumplimiento | 5 años | Cierre de la solicitud, fin del contrato o cierre del incidente | Supresión | LFPA art. 79 (prescripción de la facultad sancionadora); LFPDPPP arts. 13 y 18 | media |
| R36 | Bitácora de administración (AdminAuditLog) | 5 años | Registro | Supresión | LFPDPPP arts. 13 y 18 | media |
| R37 | Registros técnicos con IP y registros de OTP | 90 días; IP truncada o seudonimizada a los 30 días; los ligados a incidentes, hasta el cierre más 12 meses | Registro | Supresión | LFPDPPP arts. 2 fr. V, 10 y 12 | media |
| R38 | Respaldos cifrados | Copia local 14 días; copia externa 30 días; reaplicar supresiones al restaurar | Fecha del respaldo | Caducidad automática | LFPDPPP arts. 10, 13 y 18 | alta |
| R39 | Analítica (PostHog) y errores (Sentry) | PostHog 12 meses; Sentry según la retención del plan; identificador borrado al revocar el consentimiento | Evento | Purga del proveedor | LFPDPPP art. 12 | media |
| R40 | Elección de cookies (patitas_consent) | 12 meses o hasta un cambio de versión de la política | Elección | Volver a preguntar | Buena práctica | alta |
| R41 | Datos de incumplimientos contractuales (fraude, sanciones) | Máximo 72 meses | Fecha del incumplimiento | Eliminación obligatoria | LFPDPPP art. 10, último párrafo (texto verificado) | alta |
| R42 | Cuentas sancionadas (hash de correo y teléfono para impedir el re-registro) | 24 meses | Sanción | Supresión | LFPDPPP arts. 10 y 12 | media |
| R43 | Reseñas internas de clínicas | Mientras exista la cuenta o hasta que su autor la borre; anonimizar al eliminar la cuenta; las retiradas, con R32 | Publicación | Anonimización | LFPDPPP arts. 24 y 26 | media |
| R44 | Contenido de Google Places (reseñas, calificación, autores) | No se almacena; place_id indefinido | — | — | Google Maps Platform ToS 3.2.3 (contractual) | alta |
| R45 | Datos de tarjeta | Nunca se almacenan; solo identificador, monto y estado del pago | — | — | NMX num. 8.1 d) y e); PCI DSS (contractual) | alta |
| R46 | Informe del Decreto NNA, evaluaciones de riesgo, reportes estadísticos y acuses | 10 años (propuesta) | Entrega | Archivo | Propuesta; CCom art. 1047 por analogía | baja |
| R47 | Copias fechadas de contratos de terceros (Mercado Pago, Meta, Google, Apify), excepciones y dictámenes | 10 años desde que dejen de estar vigentes | Fin de vigencia | Archivo | Propuesta; CCom art. 1047 por analogía | baja |
| R48 | Comprobantes de descarga del REPEP (solo si hay publicidad a teléfonos) | Conservar cada comprobante mientras se haga publicidad telefónica (plazo final: abogado) | Descarga | — | Reglas del REPEP arts. 28 y 30 | media |

## 7. Proveedores, encargados y transferencias

Lista deduplicada para `/legal/proveedores` y para la sección de encargados del aviso. Cada encargado necesita contrato o términos que cumplan, región confirmada y registro interno; los cambios se anuncian en el historial (LFPDPPP arts. 2 fr. XII y XX, 13, 20, 35 y 36).

| Proveedor o tercero | Tipo | Finalidad | Datos | País o región | Estado o pendiente |
|---|---|---|---|---|---|
| Proveedor de hosting VPS [por definir] | encargado | Alojamiento de la aplicación, la API, la base de datos y los archivos | Todos los datos de la plataforma | Por definir (PAIS_O_REGION_DEL_HOSTING) | Pendiente: nombre, región, contrato o DPA, certificaciones ISO 27001 o SOC 2 |
| Cloudflare, Inc. (CDN, WAF, proxy y terminación TLS; R2 para respaldos y bóveda de evidencia) | encargado | Entrega de contenido, protección contra ataques, respaldos cifrados, evidencia de retiros | Tráfico en claro (incluidas subidas), IP, cookies técnicas; respaldos y evidencia cifrados | Estados Unidos y red global; jurisdicción de los buckets R2 por definir | Falta en la sección 11 del aviso; DPA y funciones activas por confirmar |
| Alibaba Cloud Model Studio / DashScope (Qwen3-VL) | encargado (transferencia internacional) | Comparación de fotos de perros, descripciones y clasificación previa de contenido | Fotos de perros y texto de reportes; sin identificadores de usuario | Singapur (dashscope-intl); ámbito de cómputo por fijar | Sin DPA específico localizado; contratar sin entrenamiento; el dominio DashScope no recibe funciones nuevas desde 30-09-2026 |
| Zhipu / Z.ai (proveedor alterno de IA) | encargado (no activar) | Alternativa de análisis de fotos | Fotos | China (posible) | No activar sin evaluación y aviso de privacidad nuevo |
| Meta Platforms, Inc. (WhatsApp Cloud API) | encargado y proveedor con términos propios | Bot de reportes, plantillas, alertas con opt-in | Número, mensajes, fotos enviadas al bot | Estados Unidos (procesamiento global) | Retención de mensajes hasta 30 días en Meta; no compartir datos del bot con terceros (Terms for WhatsApp Business Platform §4.1) |
| Meta Platforms, Inc. (Facebook Pages Graph API) | proveedor de API | Publicación en páginas propias (adopciones gratuitas, nunca como productos) | Contenido publicado por GuauWoow | Estados Unidos | Platform Terms 03-02-2026; sin Shops, Marketplace ni catálogo |
| Apify (ingesta de grupos públicos de Facebook) | encargado o fuente externa (licitud pendiente de dictamen) | Lectura de publicaciones públicas de grupos de perros perdidos por estado | Texto y fotos de publicaciones (se depuran antes de guardar) | Por confirmar (entidad contratante y región; fuera de México) | Revisar contrato, retención de datasets y riesgo frente a los términos de Meta |
| Google LLC (Google Identity / OAuth) | proveedor de identidad (responsable independiente) | Inicio de sesión con Google | Nombre, correo, foto, identificador sub | Estados Unidos | Verificación de marca y URLs de privacidad en el mismo dominio |
| Google LLC (Google Maps Platform, Places API New) | proveedor de contenido de terceros (no encargado si se consulta desde el servidor) | Calificación y hasta 5 reseñas de Google en el perfil de clínicas, en tiempo real | place_id; Google no recibe IP ni identificadores de usuarios | Estados Unidos | ToS 26-08-2026; Service Specific Terms 15-10-2026; nada se almacena salvo place_id |
| Google Fonts (si no se autohospedan) | tercero que recibe IP | Tipografías | IP y user-agent | Estados Unidos | Recomendado autohospedar |
| OpenStreetMap Foundation (teselas y Nominatim) | tercero que recibe IP y coordenadas | Mapa y geocodificación inversa | IP; coordenadas si la geocodificación se hace desde el navegador | Reino Unido / servidores fuera de México | Mover Nominatim al backend; declararlo en el aviso |
| CARTO (teselas Voyager) | tercero que recibe IP | Teselas del mapa | IP | Por confirmar | Revisar términos |
| MP Agregador, S. de R.L. de C.V. (Mercado Pago, México) | responsable independiente y encargado en lo que procesa por instrucción | Cobro de compras y donativos (Checkout Pro), Split 1:1, reembolsos, prevención de fraude, contracargos | Datos de pago, monto, identificadores | México | Términos Standard 07-06-2025; excepción escrita para donativos pendiente; aviso de incidentes en 24 h |
| Mercado Pago W, S.A. de C.V., IFPE (Mercado Pago Wallet) | entidad financiera independiente | Solo si GuauWoow o un refugio reciben liquidaciones en Wallet | Los de su contrato | México | Mencionarlo en transparencia: los saldos son de otra entidad |
| Proveedor de SMS para OTP (SMS Masivos o Twilio) | encargado | Verificación obligatoria del teléfono | Número y código | México (SMS Masivos) o Estados Unidos (Twilio) | Definir proveedor y firmar DPA |
| Proveedor SMTP [por definir] | encargado | Correos transaccionales, verificación y, con opt-in, promocionales | Correo, nombre, contenido del mensaje | Por definir (PAIS_DEL_PROVEEDOR_DE_CORREO) | Desactivar aperturas y clics; SPF, DKIM y DMARC |
| Functional Software, Inc. (Sentry) | encargado | Monitoreo de errores (datos personales depurados) | Eventos técnicos | Estados Unidos (Iowa) o Unión Europea (Fráncfort), según la organización | Confirmar región |
| PostHog, Inc. | encargado (solo con consentimiento) | Analítica de producto | Identificador seudónimo, eventos | Estados Unidos o Unión Europea | Confirmar región, descartar IP, retención 12 meses |
| PAC de CFDI (Facturama, SW Sapien o Finkok, por elegir) | encargado | Timbrado, validación y cancelación de CFDI 4.0 | Datos fiscales de compradores, refugios y operador | México | Verificar que siga en la lista vigente del SAT |
| Paquetería(s) [por definir] | encargado o tercero según contrato | Entrega y devolución de pedidos con rastreo | Nombre, domicilio y teléfono de entrega | México | El operador responde ante el consumidor (LFPC art. 90 fr. III) |
| Prestador de Servicios de Certificación NOM-151 (opcional) | encargado | Constancias de conservación de versiones, aceptaciones y evidencias | Hashes | México | Decisión de presupuesto |
| Servicios push del navegador (Apple, Google FCM, Mozilla) | tercero (condicional) | Notificaciones push, solo si se implementan | Endpoint de suscripción | Estados Unidos | No implementado |
| Refugios, rescatistas, casas de paso, publicadores y clínicas | terceros receptores (responsables propios) | Adopciones, reencuentros, donativos, verificación | Cuestionarios, contacto del adoptante (con cláusula), nombre del donante (con casilla) | México | Acuerdo de datos obligatorio (art. 35 LFPDPPP) |
| Refugios vendedores | terceros proveedores y comitentes | Preparar y enviar pedidos, garantías, CFDI propio | Datos mínimos de envío | México | Contrato de comisión con confidencialidad |
| Autoridades por obligación legal (SAT, ATDT y CJEF, Ministerio Público y Guardia Nacional, PROFECO, SABG, UIF) | transferencias por ley (no encargados) | Obligaciones fiscales, informe NNA, denuncias, requerimientos | Lo estrictamente requerido | México | Registro en authority_requests |
| SEP, Registro Nacional de Profesionistas | fuente consultada (no proveedor) | Cotejo de cédulas de veterinarios | Nombre y cédula | México | Consulta manual |

## 8. Reglas de comunicaciones y consentimiento

Detalle: [comunicaciones-cookies](secciones/comunicaciones-cookies.md) (P1 a P16).

| ID | Regla | Fundamento | Hallazgos |
|---|---|---|---|
| CR01 | Toda comunicación no esencial requiere opt-in por canal y por finalidad, con casillas sin premarcar y botones de alta y baja del mismo peso visual. | LFPDPPP arts. 7 y 15 fr. III; LFPC arts. 16 a 18 Bis y 76 Bis fr. VI | CC-16 CC-17 CE-28 |
| CR02 | Las comunicaciones esenciales (código OTP, seguridad de la cuenta, recibos de pedidos y donativos, cambios al aviso de privacidad) no se pueden apagar; la página de comunicaciones explica por qué. | LFPDPPP art. 15 fr. VI | CC-17 |
| CR03 | Alertas de perritos perdidos cerca: solo con opt-in (notify_nearby en false por defecto), radio de 5 km (15 km para refugios y casas de paso), máximo 5 avisos al día, horario silencioso de 22:00 a 8:00 para WhatsApp y correo, y baja en un clic en cada aviso. | LFPDPPP arts. 6, 11, 12 y 15 fr. III; WhatsApp Business Messaging Policy §1 | DP-07 CC-07 CC-08 |
| CR04 | WhatsApp: opt-in con casilla que nombra a la empresa exactamente como aparece en el perfil de WhatsApp Business; opt-in de marketing separado; can_whatsapp() exige el primero y las plantillas de marketing el segundo; se guardan fecha, origen y versión del texto. | WhatsApp Business Messaging Policy §1 (23-09-2026); LFPDPPP art. 2 fr. IV | CC-09 |
| CR05 | Plantillas de WhatsApp por categoría (utilidad, marketing, autenticación); nunca promoción dentro de una plantilla de utilidad; pie fijo «Responde BAJA para no recibir más avisos». | Guía de categorización de plantillas de Meta | CC-12 |
| CR06 | Bajas: BAJA, STOP, ALTO, CANCELAR, «no me escriban», «dar de baja» y similares surten efecto de inmediato; HOLA reabre la conversación pero no reactiva plantillas proactivas: solo ALTA o el botón «Sí, quiero avisos». | WhatsApp Business Messaging Policy §1; LFPDPPP art. 7 último párrafo | CC-10 |
| CR07 | Bot de WhatsApp: aviso simplificado al primer contacto y tras 12 meses sin actividad; opción PERSONA; nunca pide ni acepta INE, CURP, pasaporte ni datos de tarjeta; no gestiona adopciones (solo envía el enlace); no reenvía contenido de un chat a otro cliente; la foto se analiza con IA solo después de que la persona acepta publicar. | LFPDPPP art. 16 fr. II; WhatsApp Business Messaging Policy §2 a §4; Meta Terms for WhatsApp Business Platform §4.1 | CC-11 CP-23 CP-24 CP-v04 AD-09 |
| CR08 | Nunca se contacta por WhatsApp, SMS o llamada a teléfonos de terceros que aparezcan en publicaciones importadas o reenviadas. | WhatsApp Business Messaging Policy §1; LFPDPPP art. 17 | CC-27 |
| CR09 | Correo transaccional con pie de identidad del operador y motivo del envío; correo publicitario con pie adicional del proveedor (y del refugio cuyo producto se promueve) y de PROFECO, enlace de baja en un clic y encabezados List-Unsubscribe y List-Unsubscribe-Post. | LFPC arts. 17 y 76 Bis fr. VI | CC-13 CC-18 |
| CR10 | Dominio de correo con SPF, DKIM y DMARC alineados; subdominio separado para envíos promocionales; seguimiento de aperturas y clics desactivado («No usamos píxeles de seguimiento en correos»). | Requisitos de remitentes de Google; Lineamientos Trigésimo primero (referencia) | CC-18 CC-19 |
| CR11 | SMS solo para el código OTP, sin enlaces ni promociones; texto fijo «GuauWoow: tu código es {code}. Vence en {N} min. No lo compartas con nadie.» | LFPC arts. 16 a 18 Bis | CC-20 |
| CR12 | Notificaciones push solo si se implementan, con explicación propia antes del aviso del navegador y las mismas categorías del centro de preferencias. | LFPDPPP arts. 7 y 15 | CC-21 |
| CR13 | Listado de exclusión propio con constancia por correo (folio, fecha y hora); lista de supresión global por correo y teléfono consultada antes de cada envío promocional; REPEP solo si habrá publicidad a teléfonos (SMS, WhatsApp de marketing o llamadas) y, si no, declararlo. | LFPC arts. 18 y 18 Bis; Reglas del REPEP | CC-14 CC-v01 |
| CR14 | Derecho a saber qué información se usa con fines mercadotécnicos: exportación «Comunicaciones» (consentimientos, envíos, refugios que recibieron datos) en 20 días hábiles. | LFPC art. 16; LFPDPPP art. 31 | CC-15 BP-v12 |
| CR15 | Registro inmutable consent_events: persona o teléfono, finalidad, canal, acción (otorgó o revocó), origen, versión del texto, versión del aviso y fecha. | LFPDPPP arts. 7, 14 y 15 | CC-16 |
| CR16 | Cookies: banner en la primera visita a app, landing y páginas legales (aunque no haya analítica), botones «Aceptar analítica», «Rechazar» y «Configurar» con el mismo peso; PostHog solo con analytics:true; revocación que borra ph_* y no vuelve a cargar el script; se pregunta de nuevo a los 12 meses o al cambiar la política. | LFPDPPP arts. 7 y 15; Reglamento art. 14 (referencia) | CC-02 CC-03 CC-04 |
| CR17 | Geolocalización: explicación previa al permiso del navegador; «ver cerca» sin guardar en el servidor; «guardar mi zona» con confirmación y redondeo (unos 100 m); alta precisión solo al crear un reporte; botón para borrar la zona. | LFPDPPP arts. 6, 11 y 12 | CC-07 DP-07 |
| CR18 | Los refugios no reciben listas de contactos para enviar publicidad; los mensajes salen desde la plataforma con la lista de supresión aplicada; el nombre del donante solo se comparte con casilla expresa. | LFPDPPP art. 35; LFPC arts. 17, 18 Bis y 76 Bis fr. I | CC-26 DON-21 |
| CR19 | Campañas de adopción y solicitudes de donativo se tratan como comunicaciones promocionales (opt-in) mientras el abogado no defina otra cosa. | LFPC art. 16 último párrafo | CC-13 CC-15 |
| CR20 | Google OAuth: texto junto al botón sobre los datos que comparte Google; sección del aviso «Datos que recibimos de Google»; desvinculación en el perfil. | Google API Services User Data Policy | CC-23 CP-25 |
| CR21 | Donativos o compras recurrentes solo con consentimiento expreso, aviso 5 días naturales antes de cada renovación y cancelación inmediata. | LFPC art. 76 Bis fr. VIII y IX | CE-27 DON-17 |
| CR22 | Canales oficiales publicados; todas las comunicaciones se identifican como «GuauWoow – [razón social]»; GuauWoow nunca pide códigos, contraseñas ni pagos por chat. | LFPC arts. 17 y 76 Bis fr. III | CC-25 SI-27 |

**Centro de preferencias (categorías):** A esenciales (siempre); B actividad de mis trámites; C alertas cercanas (opt-in); D recordatorios que programa la persona; E novedades y campañas de adopción (opt-in); F promociones de la tienda y de refugios (opt-in); G encuestas (opt-in); H compartir mi nombre con los refugios a los que dono (casilla expresa); I historias de adopción o reencuentro (casilla expresa); J cookies.

## 9. Reglas de adopción y bienestar animal

Detalle: [bienestar-animal](secciones/bienestar-animal.md), [gap de naturaleza jurídica de la adopción y cuotas](secciones/gap-naturaleza-juridica-adopcion-y-cuotas.md), [gap de cobertura estatal y Ley General](secciones/gap-cobertura-estatal-bienestar-animal-y-ley-general.md).

### Regla de cuatro niveles (se repite igual en Términos, políticas, convenio, bot y moderación)

| Nivel | Situación | Naturaleza | Regla en GuauWoow |
|---|---|---|---|
| 1 | Adopción gratuita con cargas a favor del perro (esterilizar, vacunar, no vender, no abandonar, seguimiento, devolución) | Donación onerosa (CCF arts. 2332, 2336 y 2337; Código Civil CDMX art. 855 Bis) | **Permitida.** Única forma de adopción |
| 2 | Donativo voluntario a un refugio verificado | Donación pura, no onerosa ni remunerativa (LISR arts. 27 fr. I y 151 fr. III) | Permitido solo en el módulo de donativos; nunca en el flujo de adopción ni con monto «sugerido» en la ficha |
| 3 | Cualquier pago obligatorio o esperado ligado a la entrega (cuota de recuperación, reembolso de esterilización o vacunas, apartado, anticipo, «gastos de envío» del animal, donativo obligatorio o sugerido) | Precio: compraventa (CCF art. 2248); enajenación gravada al 16 % (LIVA art. 2o.-A fr. I a)); «venta» para LPBA CDMX art. 25 Bis y Ley Edomex art. 40 fr. V | **Prohibido**, aunque se cobre fuera de la app o en efectivo; la adopción no se tramita en GuauWoow; reincidir quita la verificación |
| 4 | Venta, intercambio o «cambio por» bienes o servicios | Compraventa o permuta | **Prohibido** |

**Qué sí puede pedir un refugio o rescatista:** cuestionario, identificación oficial para la carta responsiva, visita o videollamada al hogar, compromiso de esterilización con fecha, fotos de seguimiento, devolución si no se puede cuidar al perro. **Qué no:** dinero, depósitos, «reembolsos», compras en su tienda, donativos como condición, datos bancarios.

**Controles técnicos:** sin campo de precio en fichas y reportes; casilla obligatoria «No vendo ni cobro por este perro; la adopción es gratuita»; diccionario único de venta y cobro aplicado a publicaciones, descripciones, chat, bot y texto importado, con retención para revisión humana en 24 horas o menos; motivos de reporte `venta_animales` y `cobro_por_adopcion`; escala de sanciones a publicadores verificados (retiro y aviso; suspensión de 30 días; retiro de la verificación y de los donativos); el bot responde «Quiero adoptar» solo con un enlace; la Página de Facebook publica solo adopciones gratuitas, nunca como productos; la importación descarta ofertas de venta antes de guardar.

### Estándar único de entrega en adopción

Perro esterilizado o con compromiso de esterilización con fecha; vacunado y desparasitado; manual de cuidados; seguimiento pactado; adoptante mayor de 18 años verificado (en Sonora y Quintana Roo no se admite ni siquiera acompañado); en Chihuahua, entrega en centros, veterinarias, asociaciones o espacios de adopción, no en viviendas; registro en el padrón oficial cuando el estado lo prevé (RUAC de la CDMX gratuito; padrón de Puebla). La carta responsiva modelo es orientativa: GuauWoow no es parte del contrato.

### Perros perdidos y encontrados

Quien encuentra un perro no se vuelve dueño: la ley civil manda entregarlo a la autoridad municipal (CCF arts. 774, 775 y 874 y códigos estatales). **Regla de producto:** un perro reportado como encontrado por un particular no puede publicarse en adopción hasta cumplir **30 días naturales** con el reporte activo, lectura de microchip documentada y aviso a la autoridad registrado en la app; nunca menos que el plazo del estado; solo un refugio verificado o una autoridad pueden acortarlo dejando constancia.

| Entidad | Plazo legal de reclamo | Fundamento |
|---|---|---|
| Ciudad de México | 5 días hábiles | LPBA CDMX arts. 32 y 32 Bis |
| Estado de México | 8 días | Ley Edomex arts. 34 y 57 |
| Jalisco | 5 días | art. 11 (compilación) |
| Nuevo León | 10 días naturales; 20 si se reportó el extravío | art. 74 (compilación) |
| Puebla | 10 días hábiles; después 30 días hábiles para adopción | arts. 31 y 32 |
| Guanajuato | 3 días hábiles con placa; 5 sin placa | arts. 52 y 53 |
| Veracruz | Sin plazo en la ley | art. 74 |
| Querétaro | 3 días hábiles con placa; bien mostrenco | arts. 87, 91 y 92 (compilación) |
| Baja California | 72 horas | art. 48 (copia del Congreso) |
| Chihuahua | 10 días, luego adopción inmediata | art. 36 |
| Yucatán | Sin plazo en la ley | arts. 34, 63 y 64 |
| Quintana Roo | 7 días naturales | art. 66 |
| Michoacán | 72 horas | art. 19 fr. V (texto 2022) |
| Sonora | Observación de 72 horas a 10 días naturales | art. 17 fr. XXV (boletín escaneado) |
| Coahuila | 120 horas; difusión en redes oficiales | art. 61 |

### Venta de animales en internet, por estado

| Entidad | Regla | Fundamento |
|---|---|---|
| Ciudad de México | Solo comerciantes con registro pueden ofrecer, promover, publicar o difundir la venta de perros y gatos en plataformas digitales (multa PAOT de 150 a 3,000 UMA) | LPBA CDMX art. 25 Bis (vigente desde 24-07-2026) |
| Estado de México | Venta desde domicilios particulares prohibida | Ley Edomex art. 40 fr. V |
| Coahuila | Venta ambulante «en cualquier medio de red social o páginas de comercialización» prohibida | art. 20 fr. III |
| Sonora | Venta ilegal en medios digitales y redes sociales prohibida | art. 44 fr. VII |
| Chihuahua | Exhibición, venta y adopción por medios remotos permitidas, nunca en vía pública ni desde viviendas | arts. 21, 21 Ter y 22 |
| Yucatán | La Fiscalía monitorea plataformas digitales | arts. 6 Bis y 6 Sexies fr. IV |
| Nación (minuta, no vigente) | Prohibido difundir ventas de animales en plataformas digitales sin registro | Minuta de Ley General art. 52 fr. III |
| Puebla, Guanajuato, Veracruz, Querétaro, Baja California, Quintana Roo, Michoacán | Sin cláusula digital; venta solo en establecimientos autorizados, nunca en vía pública | Leyes estatales citadas en el gap |

En GuauWoow la regla es una sola para todo el país: solo adopción gratuita; toda oferta de venta, cuota o intercambio se retira y se responde citando el artículo del estado del publicador.

### Denuncia, verificación y contenido

- **Denuncia de maltrato:** botón «Denunciar ante la autoridad» que abre la ficha del estado del usuario con datos verificados en sitios oficiales (revisión trimestral). En la CDMX existe deber de informar (LPBA CDMX art. 26).
- **Verificación de refugios por estado:** además de acta y RFC, constancia del padrón o autorización que exige cada estado (por ejemplo, SEDIF en Puebla, CEDES en Sonora, padrón municipal en Coahuila y Quintana Roo, organismo auxiliar en Chihuahua); rescatistas con identidad, domicilio y referencia de un refugio verificado. Insignias separadas («identidad verificada», «registro estatal», «donataria autorizada») con fecha y alcance; ninguna garantiza el bienestar del animal ni el uso de los fondos.
- **Contenido prohibido:** crueldad, peleas, zoofilia, mutilaciones estéticas, especies silvestres, rifas o premios con animales (CPEUM art. 4; CP DF arts. 350 Bis a 350 Quinquies; CPF arts. 419 Bis y 420 fr. IV; LPBA CDMX art. 25), con clasificador previo en la importación.
- **Ley General de bienestar animal:** no está vigente; se informa como «aprobada por el Senado, pendiente en Diputados» y se vigila cada semana.

## 10. Procedimiento de retiro de contenido y reportes

Detalle: [contenido-plataforma](secciones/contenido-plataforma.md) (3.4 a 3.10), [gap NNA](secciones/gap-nna-decreto-entornos-digitales-2026.md) (3.3 a 3.6), [gap de veterinarias](secciones/gap-veterinarias-y-resenas.md) (P6), [gap de adopción](secciones/gap-naturaleza-juridica-adopcion-y-cuotas.md) (P6). Los plazos propuestos se vuelven exigibles al publicarse: el dueño debe confirmar que el equipo puede cumplirlos.

| Paso | Flujo | Acción | Plazo | Registro | Fundamento |
|---|---|---|---|---|---|
| 1 | Reporte general | Botón «Reportar» visible y permanente en todo contenido, perfil, producto, reseña y mensaje; formulario público para personas sin cuenta; motivos: venta o cobro por animales, maltrato, involucra a un menor, contenido íntimo, difamación o acusación, mi imagen o mis datos, derechos de autor o marca, estafa, suplantación, reseña falsa, facturas. | Inmediato (disponible siempre) | ContentReport con motivo, origen y detection_source | Decreto NNA art. 4 fr. V; LFDA art. 114 Octies |
| 2 | Reporte general | Triage: riesgo inminente o menores primero; retiro preventivo de lo manifiestamente ilícito; revisión humana del resto. | 72 horas hábiles (propuesta); menores e íntimo menos de 24 h | AdminAuditLog: regla, decisión, persona | Decreto NNA art. 4 fr. IV; LGAMVLV art. 20 Sexies |
| 3 | Reporte general | Declaración de motivos al autor (regla incumplida, cómo se detectó, cómo apelar) y aviso del resultado a quien reportó. | Al resolver | Correo y notificación; plantilla versionada | LFPC art. 10; LFDA art. 114 Octies fr. II b) |
| 4 | Reporte general | Conservación de la evidencia del retiro en la bóveda. | Al menos 90 días hábiles | Hash SHA-256 encadenado | Decreto NNA art. 5 fr. II |
| 5 | Apelación | Apelación con token aunque la cuenta esté suspendida; la resuelve un administrador distinto; respuesta razonada; derechos ARCO disponibles durante la suspensión. | 15 días para apelar; respuesta en 10 días hábiles | appeal_resolved_by distinto de resolved_by | LFPC art. 90 fr. I; LFPDPPP arts. 21 a 24 |
| 6 | Menores (art. 3 del Decreto NNA) | Retiro inmediato y bloqueo por hash; si hay indicios de delito: suspensión, evidencia con acceso bloqueado, denuncia al Ministerio Público y orientación en el 088 el mismo día; el material de abuso nunca se reproduce, descarga ni envía a IA. | Minutos a 24 h | Folio de denuncia en authority_requests | Decreto NNA arts. 3, 4 y 5; CNPP art. 222; CPF arts. 202 y 202 Bis |
| 7 | Contenido íntimo (Ley Olimpia) | Ocultar con reporte creíble, bloquear por hash, resguardar cifrado para la autoridad y avisar al usuario con la leyenda legal. | Menos de 24 h | Bóveda y bitácora | LGAMVLV arts. 20 Quáter a 20 Sexies |
| 8 | Venta o cobro por animales | Diccionario único de venta y cobro aplicado a publicaciones, chat, bot e importación; retención para revisión humana; retiro y respuesta citando el artículo del estado del publicador; escala: 1) retiro y aviso, 2) suspensión de publicaciones 30 días, 3) retiro de la verificación y de los donativos. | Revisión en 24 h o menos | Motivos venta_animales y cobro_por_adopcion; sanción en bitácora | LPBA CDMX arts. 25 Bis y 65 fr. IV; Ley Edomex art. 40 fr. V |
| 9 | Derechos de autor | Formulario público de aviso (campos del Reglamento LFDA art. 37 Quáter, sin exigir certificados); acuse con folio; si faltan requisitos se pide completar sin retirar. | Acuse inmediato | Aviso íntegro con SHA-256 | LFDA art. 114 Octies fr. III; Reglamento LFDA arts. 37 Quáter a 37 Sexies |
| 10 | Derechos de autor | Retiro o inhabilitación expedita y notificación a quien subió el contenido con copia del aviso y enlace al contra-aviso. | Menos de 24 h hábiles (propuesta) | Estado removed | LFDA art. 114 Octies fr. II |
| 11 | Derechos de autor | Contra-aviso; copia inmediata a quien avisó; restauración entre el día hábil 10 y el 15 salvo prueba de procedimiento iniciado. | 10 a 15 días hábiles | Estados counter_notice, restored, final | LFDA art. 114 Octies fr. III; Reglamento LFDA art. 37 Septies |
| 12 | Derechos de autor | Staydown por hash perceptual y política pública de reincidentes (propuesta: 2 avisos procedentes en 12 meses = suspensión de 30 días; 3 = cancelación). | Permanente | Contador por usuario | LFDA art. 114 Octies fr. II a) |
| 13 | Contenido importado de Facebook | Botón «Soy el autor: retirar o reclamar» sin cuenta; retiro de la publicación importada; oposición y ARCO en los plazos del aviso. | Menos de 72 h (retiro); 20 días hábiles (ARCO) | Registro de la solicitud; solo se conserva la constancia | LFPDPPP arts. 17, 26 y 31 |
| 14 | Contenido importado de Facebook | Caducidad automática con borrado real de fotos y texto y purga en el proveedor. | 30 días desde la importación | Registro de existencia y de retiros | LFPDPPP arts. 10 y 12; Meta Platform Terms 3.d |
| 15 | Reseñas de clínicas | Filtro previo de insultos, imputaciones de delitos y datos personales; lo retenido pasa a revisión humana. | 24 horas hábiles | Bitácora con regla y persona | CCF art. 1916; Ley de Responsabilidad Civil CDMX art. 32 |
| 16 | Reseñas de clínicas | Reporte (honor, falsa o pagada, datos personales, cédula falsa, publicidad engañosa) con formulario público; retiro preventivo de lo manifiestamente ilícito; aviso al autor y al reportante. | 72 horas hábiles | Bitácora | LFPC art. 32; CCF art. 1916 |
| 17 | Reseñas de clínicas | Aclaración o réplica voluntaria de la clínica o persona aludida, publicada gratis y sin comentarios si procede; nunca se retira una reseña solo por ser negativa. | 5 días hábiles | Conteo en transparencia | Ley de réplica (aplicación voluntaria); CPEUM arts. 6 y 7 |
| 18 | Cédula falsa | Despublicación preventiva inmediata; 5 días hábiles para aclarar; revocación definitiva; aviso a quienes interactuaron; evaluación de denuncia. | Inmediato / 5 días hábiles | Evidencia 12 meses | CPF art. 250 fr. II; Ley de Profesiones arts. 62, 63 y 73 |
| 19 | Órdenes de autoridad | Solo por escrito; verificar autenticidad, competencia y fundamentación; revisión del abogado (salvo emergencia); entregar lo mínimo; avisar al usuario salvo prohibición; registrar. | 1 h primera respuesta en casos de menores o riesgo de vida; 24 h el resto | authority_requests | CPEUM art. 16; CNPP arts. 291 y 303; LFPDPPP arts. 9 fr. V y VII y 36 |

**Texto público sobre filtros automáticos:** «GuauWoow usa filtros automáticos únicamente para detectar estafas o solicitudes de dinero, venta o cobro por animales, maltrato, contenido sexual o que involucre a menores, y apología de delitos. No revisamos de forma general el contenido en busca de infracciones de derechos de autor; para eso existe el procedimiento de aviso. Cada acción automática queda registrada y se te informa.»

**Chat privado:** ninguna persona lee conversaciones sin el reporte de un participante que autoriza compartir el mensaje y los inmediatamente anteriores y posteriores (CPEUM art. 16); cada acceso queda en bitácora; ante una autoridad, chats solo con autorización judicial (CNPP art. 291).

## 11. Seguridad e incidentes

Detalle: [seguridad-incidentes](secciones/seguridad-incidentes.md) (P1 a P21), [datos-personales](secciones/datos-personales.md) (P12, P18).

**Lo que ya existe en el código** (según la verificación de la sección de seguridad; reconfirmar en la versión final): TLS con HSTS, CSP estricta, contraseñas con bcrypt, OTP por SMS con límites, eliminación de EXIF, coordenadas públicas aproximadas, documentos en `uploads/private/` fuera del acceso público, bitácora de administración (incluye `refuge_document.view`), firma HMAC de webhooks de Mercado Pago, respaldos de PostgreSQL cifrados (14 días locales, 30 días externos cifrados con rclone crypt), imágenes Docker fijadas por versión, filtrado de datos personales en Sentry, «Cerrar sesión en todos los dispositivos», aceptación de términos con versión, sección 19 del aviso conforme al art. 19, tokens OAuth de Mercado Pago cifrados con Fernet.

**Lo que falta:** MFA para administradores; cifrado en reposo de `uploads/private/` y de sus instantáneas; tareas de purga por conservación; `/.well-known/security.txt` y política de divulgación responsable; Cloudflare y Nominatim en la lista de encargados; marcadores de hosting y plazo de respaldos; reducir la conservación de INE (el aviso dice 24 meses); rotación de logs por tiempo; escaneo de dependencias en CI; prueba de penetración; `BACKEND_TAG` distinto de `latest`; plan de respuesta a incidentes, bitácora `security_incidents` y herramienta de aviso masivo.

**Regla para la página pública de seguridad:** describir solo lo que exista en producción; lo demás se anuncia como plan con fecha o no se menciona (LFPDPPP arts. 5 y 14; LFPC art. 76 Bis fr. II).

### Procedimiento ante vulneraciones

| Paso | Fase | Plazo | Acción | Fundamento |
|---|---|---|---|---|
| 1 | Detección | Continuo | Alertas de Sentry y monitoreo, reportes a seguridad@, avisos de proveedores (Mercado Pago, Meta, Cloudflare, hosting), revisión de la bitácora de administración, comunicados de la SABG. | LFPDPPP art. 18 |
| 2 | Apertura y preservación | Hora 0 | Abrir el incidente en la bitácora; activar «modo incidente» (congela purgas); snapshot del VPS y copia de registros con SHA-256 y cadena de custodia. | LFPDPPP arts. 18 y 25 fr. III |
| 3 | Clasificación y severidad | Primeras horas | Tipo (pérdida, robo o copia, acceso no autorizado, alteración); severidad S1 (identificaciones, credenciales, CLABE, chats, cuestionarios, ubicación exacta, tokens), S2 (datos de contacto), S3 (sin datos personales). | Reglamento art. 63 (referencia) |
| 4 | Contención | Primeras 4 horas | Revocar sesiones, rotar secretos y tokens (Mercado Pago, Meta, SMS, SMTP, OAuth de refugios), bloquear IP o cuentas, aislar el servicio. | LFPDPPP art. 18 |
| 5 | Avisos contractuales | Hasta 24 horas | Mercado Pago por su formulario si toca pagos, webhooks o tokens (y privacidad@mercadolibre.com si afecta datos de compradores o donantes); Meta «tan pronto como sea posible» si hay datos de la plataforma. | Términos MP para Desarrolladores 1.6, 6.6 y sección 10; Meta Platform Terms 6.b |
| 6 | Aviso a titulares | De inmediato al confirmar; meta interna 72 horas o menos (antes si hay riesgo de fraude) | Correo y notificación con: qué pasó, datos afectados, qué hicimos, qué recomendamos, dónde informarse; publicación en «Avisos de seguridad» si es amplio; registro por usuario. | LFPDPPP art. 19; Reglamento arts. 64 y 65 (referencia) |
| 7 | Autoridades | Según dictamen | El abogado decide el aviso voluntario a la SABG (la ley de particulares no lo exige) y la denuncia ante la FGR o fiscalía estatal. | LFPDPPP art. 19; CPF arts. 211 bis 1 a 7 |
| 8 | Recuperación | Tras contener | Corregir la causa, restaurar desde respaldo reaplicando supresiones posteriores, verificar. | LFPDPPP arts. 10 y 18 |
| 9 | Cierre | Al terminar | Análisis de causa raíz, acciones correctivas, actualización del documento de seguridad, cierre en la bitácora (conservar 5 años), reanudar purgas sin borrar evidencia necesaria. | Reglamento art. 66 (referencia); LFPDPPP art. 13 |
| 10 | Simulacro | Anual | Ejercicio sobre un escenario (fuga de uploads/private o toma de cuenta de superadmin) con registro. | Buena práctica |

Plantilla de aviso a titulares (sección seguridad-incidentes, P8): qué pasó; qué datos se afectaron y cuáles no; qué hicimos; qué te recomendamos (incluida la advertencia de extorsiones con perros perdidos y que GuauWoow nunca pide códigos); dónde informarte y cómo ejercer tus derechos ARCO.

## 12. Veterinarias y reseñas

Detalle: [gap de veterinarias y reseñas](secciones/gap-veterinarias-y-resenas.md).

### Seis reglas

| # | Regla | Fundamento | Qué significa en GuauWoow |
|---|---|---|---|
| 1 | Sin cédula no hay perfil | LGS arts. 79 y 83; Ley Reglamentaria del art. 5o. constitucional arts. 24, 25, 62, 63 y 73; CPF art. 250 fr. II | Cédula del médico veterinario responsable cotejada en el Registro Nacional de Profesionistas, identificación y prueba del establecimiento; nombre, cédula e institución visibles; insignia «Cédula verificada» con fecha; reverificación anual; cédula falsa = despublicación inmediata |
| 2 | GuauWoow no es la clínica | LFPC arts. 1, 2 y 5; Ley de Profesiones arts. 33, 34 y 71; CCF art. 1910 | Sin cobro de consultas, sin agenda con pago, sin venta de medicamentos; deslinde sin limitar derechos del consumidor frente a la clínica; aviso de urgencias |
| 3 | El perfil es publicidad del proveedor | LFPC arts. 32 y 35; 128 Bis y 128 Ter fr. VI | Solo afirmaciones comprobables; sin avales, superlativos ni garantías; especialidades con constancia; «Patrocinado»; expediente de sustento; canal para órdenes de PROFECO |
| 4 | Google es complemento, nunca base | Google Maps Platform ToS 3.2.2 y 3.2.3; Service Specific Terms A.3 y 14.x; políticas de Places | Solo `place_id` almacenado; hasta 5 reseñas en tiempo real con autor, enlace a Google Maps y reporte; nunca en el mapa OSM ni mezcladas con las calificaciones propias; sin resúmenes con IA |
| 5 | Opina, no acuses | CPEUM arts. 6 y 7; CCF arts. 1916 y 1916 Bis; Ley de Responsabilidad Civil CDMX arts. 14, 25 y 32 | Reseñas de usuarios verificados sobre experiencia propia; imputaciones de delitos, insultos y datos de terceros no; respuesta pública de la clínica; aclaración voluntaria |
| 6 | Datos mínimos | LFPDPPP arts. 2 fr. X, 7, 9 fr. II, 12 y 17 | Del veterinario: nombre, cédula e institución; del reseñador: nombre de usuario, edición y borrado; de Google: nada almacenado; aviso al veterinario registrado por un tercero |

### Qué se verifica, qué se declara y qué se muestra

| Dato | Tratamiento | Se muestra |
|---|---|---|
| Nombre, cédula e institución del responsable | Cotejo en el Registro Nacional de Profesionistas o QR de la Constancia de Situación Profesional; captura privada; reverificación anual | Sí, con fecha de cotejo |
| Identificación del responsable y prueba del establecimiento | Revisión; almacenamiento privado; 12 meses tras la baja | No (sí el domicilio comercial) |
| Aviso de inicio de funcionamiento ante SENASICA, MVRA, autorización local, manejo de RPBI | Autodeclaración, no se verifica | Como «declarado por la clínica» o no se muestra |
| Especialidades | Revisión de la constancia | Sí, con insignia «Especialidad acreditada» |
| Reseñas propias | Reglas de contenido, moderación, respuesta de la clínica | Sí, en orden cronológico, con promedio y conteo |
| Contenido de Google | Consulta en tiempo real desde el servidor; nunca almacenado | Sí, bloque separado con atribución |

### Reseñas: sí y no

| Sí | No |
|---|---|
| Contar la experiencia propia como cliente en los últimos 12 meses | Reseñar la clínica propia, donde se trabaja, de un familiar o de la competencia |
| Calificar de 1 a 5 y explicar por qué | Reseñas pagadas o regaladas sin marcar «recibí descuento o regalo» |
| Narrar hechos propios verificables | Acusar de delitos o conductas graves sin denuncia o resolución |
| Mencionar el nombre comercial | Publicar nombres completos, fotos o teléfonos de empleados u otros clientes |
| Editar o borrar la propia reseña | Insultar o amenazar |
| La clínica verificada responde una vez por reseña | Que la clínica edite, oculte, retrase o pague por posicionar reseñas |

Texto de cierre recomendado: «Opinar está protegido por la Constitución. Imputar hechos falsos o insultar puede generar responsabilidad civil para quien lo escribe. Retiramos reseñas solo por estas reglas; nunca por ser negativas.»

### Estado en el código (17-10-2026)

`backend/app/models.py` tiene `Veterinary` (cédula, institución, documento privado, `google_place_id`, `verified_at`, `verification_expires_at`, `is_hidden`) y `VeterinaryReview` (una por cuenta, `incentivized`, `owner_reply`, `is_hidden`); `backend/app/routers/veterinaries.py` aplica cotejo previo, caducidad a 12 meses, deslinde y aviso de urgencias, lista cerrada de servicios, reseñas con teléfono verificado y retención para revisión humana; `backend/app/services/google_places.py` consulta desde el servidor sin guardar reseñas ni calificaciones y muestra el aviso de orden por relevancia. Pendiente: confirmar que el bloque de Google no aparece en una vista con mapa OSM o CARTO, páginas `/legal/veterinarias` y `/legal/resenas`, anexo de Términos para clínicas, plazos de moderación y aclaración publicados, formulario público y procedimiento de cédula falsa.

## 13. Ingesta de grupos públicos de Facebook

Detalle: [datos-personales](secciones/datos-personales.md) (hallazgos 26, v01, v05), [contenido-plataforma](secciones/contenido-plataforma.md) (3.10), [comunicaciones-cookies](secciones/comunicaciones-cookies.md) (P14).

### Base legal

1. **No es fuente de acceso público.** La LFPDPPP 2025 (art. 2 fr. X) solo considera así a las bases consultables «por disposición de ley». Un grupo de Facebook no lo es. Por eso no se usa la excepción de consentimiento del art. 9 fr. II.
2. **Datos obtenidos de forma indirecta.** El art. 17 obliga a dar a conocer el aviso de privacidad al titular; si es imposible o exige esfuerzos desproporcionados, permite medidas compensatorias «en términos del Reglamento». Los Criterios Generales de 2012 solo eximen de autorización en supuestos acotados; para datos nuevos la medida compensatoria requiere autorización de la Unidad de Protección de Datos Personales de la SABG (confianza media; decide el abogado). La excepción de emergencia del art. 9 fr. V (riesgo para una persona o sus bienes) tiene confianza baja como base general.
3. **Derechos de autor.** Al importar sin que un usuario lo suba, GuauWoow «inicia» la conducta y no tiene puerto seguro (LFDA art. 114 Octies, primer párrafo); responde como editor por las fotos. La excepción de fotografías de actualidad (art. 148 fr. II) es incierta.
4. **Contrato con Meta.** Los Automated Data Collection Terms de Meta prohíben la recolección automatizada sin permiso escrito, y los Términos de servicio de Meta prohíben el acceso automatizado. Que lo haga un tercero (Apify) sin cuenta de GuauWoow no se analizó con certeza; GuauWoow sigue siendo desarrollador de Meta (WhatsApp Cloud API y Pages API), por lo que el riesgo es perder la app, la API o el número de WhatsApp (confianza baja; dictamen del abogado de tecnología).

**Decisión recomendada:** mantener el código, pero **no activar la ingesta automática de grupos en producción** hasta tener (a) dictamen del abogado de datos sobre la vía del art. 17 (o la autorización de la medida compensatoria) y (b) dictamen del abogado de tecnología sobre Meta y el contrato con Apify. Mientras tanto, operar solo con envíos de voluntarios con autorización del autor y con el bot de WhatsApp.

### Minimización (qué se guarda y qué no)

| Se guarda | No se guarda |
|---|---|
| Fotos del perro (miniatura con atribución) | Teléfonos, correos, @usuarios, enlaces de pago (hoy los quita `strip_pii`) |
| Descripción depurada | Nombres de personas (falta implementarlo) |
| Zona aproximada | Dirección exacta |
| Enlace a la publicación original y fecha | Rostros de personas, sobre todo de menores (difuminar; falta) |
| Etiqueta «Importado de una publicación pública; su autor no es usuario de GuauWoow» | Ofertas de venta o cobro (descartadas antes de guardar) |

Nunca se contacta a los teléfonos de la publicación. El texto generado por IA se etiqueta como propio y se puede corregir.

### Caducidad y retiro

- **30 días** desde la importación, con **borrado real** de fotos y texto (hoy `expire_imported_reports` solo cambia el estado a «expired»: falta borrar archivos) y retención cero en los datasets de Apify; solo queda el registro de existencia y de solicitudes de retiro.
- Botón **«Soy el autor: retirar o reclamar»** en cada reporte importado, sin cuenta, con retiro en menos de 72 horas y respuesta ARCO en los plazos del aviso.
- Página `/legal/privacidad/facebook` con fuente, método, qué se guarda, caducidad, retiro y cómo se usa la IA.
- Envíos de voluntarios: se tratan como contenido importado salvo autorización del autor (captura o mensaje guardado en el expediente) y con la leyenda «Confirmo que la publicación es pública, que no incluyo datos de contacto de otras personas y que entiendo que GuauWoow puede retirarla a petición de su autor».
- Informe de transparencia: publicaciones importadas, descartadas, retiradas a petición y tiempo medio de atención.

## 14. Conflictos resueltos

El revisor crítico detectó 12 conflictos entre secciones. Cada uno se resolvió con la fuente primaria; los marcados se volvieron a leer en el texto oficial al ensamblar este documento (LFPDPPP, LISR, LFFAOSC, LFPC, CCom y CFF en diputados.gob.mx; DOF del 24-09-2026, 01-10-2026 y 02-10-2026). Se agrega un conflicto 13 con erratas encontradas al ensamblar.

### 1. Fuerza del Reglamento LFPDPPP 2011 y de los Lineamientos 2013

- **Conflicto:** Datos personales y comunicaciones los aplican como norma supletoria; seguridad e incidentes y buenas prácticas, solo como referencia.
- **Resolución:** Se leyó el texto vigente de la LFPDPPP 2025: el transitorio Segundo abroga solo la ley de 2010 (no el Reglamento); el Cuarto traslada las menciones del INAI a los nuevos entes; el Décimo Segundo ordenó adecuar los reglamentos en 90 días y no se ha cumplido; ningún transitorio conserva expresamente el Reglamento, pero la ley sigue definiéndolo (art. 2 fr. XIII) y remitiendo a él (arts. 17 y 55). Postura única para todas las páginas: «aplicable en lo que no se oponga a la LFPDPPP vigente»; ninguna obligación pública se funda solo en el Reglamento o en los Lineamientos, siempre se cita primero el artículo de la ley de 2025; donde chocan (art. 7 fr. I del Reglamento frente al art. 2 fr. X de la ley) prevalece la ley.
- **Fuente primaria:** https://www.diputados.gob.mx/LeyesBiblio/pdf/LFPDPPP.pdf (transitorios Segundo, Cuarto y Décimo Segundo; art. 2 fr. X y XIII)
- **Confianza:** media (interpretación; el texto está verificado)

### 2. Fracción del art. 79 LISR aplicable a refugios donatarias

- **Conflicto:** Donativos usa la fr. XIX (rubro ecológico) con un ejemplo real del SAT; identidad-contratos sostiene la fr. XXV inciso e) y descarta la XIX y la XX; donativos había quitado la cita de la LFFAOSC art. 5 fr. XII.
- **Resolución:** Texto vigente leído: la fr. XIX cubre la investigación o preservación de flora o fauna silvestre en áreas definidas por el SAT y la promoción de la protección al ambiente y del equilibrio ecológico; la fr. XX, especies en peligro con opinión de SEMARNAT; la fr. XXV inciso e) cubre literalmente «la protección del ambiente, la flora y la fauna», igual que la LFFAOSC art. 5 fr. XII (confirmada en fuente primaria). Resolución: la XX no aplica a refugios de perros; tanto la XIX como la XXV e) han servido para autorizar refugios (el SAT listó uno en el rubro F); la plataforma no elige la fracción: registra la del oficio o del Anexo 14 de cada refugio y verifica su vigencia; para orientar a refugios nuevos, la XXV e) es el encuadre natural, con decisión final del contador y del SAT. La cita de la LFFAOSC art. 5 fr. XII se mantiene.
- **Fuente primaria:** https://www.diputados.gob.mx/LeyesBiblio/pdf/LISR.pdf (art. 79 fr. XIX, XX y XXV); https://www.diputados.gob.mx/LeyesBiblio/pdf/LFFAOSC.pdf (art. 5 fr. XII)
- **Confianza:** media

### 3. Cuotas de adopción

- **Conflicto:** Bienestar animal admitía una cuota de recuperación; fiscal y donativos la tratan como enajenación gravada; identidad la califica como donación onerosa; WhatsApp prohíbe facilitar el intercambio de animales vivos.
- **Resolución:** Se adopta la regla de cuatro niveles del gap de adopción: (1) adopción gratuita con cargas no pecuniarias = donación onerosa, permitida; (2) donativo voluntario solo en el módulo de donativos, nunca en el flujo de adopción; (3) cualquier pago obligatorio o esperado ligado a la entrega = compraventa, prohibido aunque se cobre fuera de la app; (4) venta o intercambio, prohibido. El bot no gestiona adopciones; la Página de Facebook solo publica adopciones gratuitas; la importación descarta ofertas de venta antes de guardar.
- **Fuente primaria:** CCF arts. 2248, 2332, 2336 y 2337; LPBA CDMX art. 25 Bis; Ley Edomex art. 40 fr. V; LIVA art. 2o.-A fr. I a); WhatsApp Business Messaging Policy §4
- **Confianza:** media (calificación civil por interpretación)

### 4. Plazo de conservación de contratos, aceptaciones y transacciones

- **Conflicto:** El aviso actual dice 5 años; cuatro dominios sostienen 10 (CCom); fiscal y donativos usan 5 (CFF); LFPIORPI pide 10; el Decreto NNA pide 90 días hábiles.
- **Resolución:** Se leyeron CCom arts. 3, 38 y 49 (10 años para comprobantes y contratos del comerciante; una sociedad mercantil es comerciante) y CFF art. 30 (5 años desde la presentación de la declaración relacionada). Regla única: el plazo más largo aplicable con su punto de inicio. Con operador persona moral mercantil: 10 años desde la operación para contratos, aceptaciones, pedidos, donativos y ledger (cubre los 5 años fiscales); 10 años LFPIORPI para expedientes de identificación; al menos 90 días hábiles para la bóveda de evidencia; 72 meses máximo para datos de incumplimientos (LFPDPPP art. 10). Si el operador fuera persona física no comerciante, el abogado debe revisar el calendario. Ver Calendario de retención.
- **Fuente primaria:** https://www.diputados.gob.mx/LeyesBiblio/pdf/CCom.pdf (arts. 3, 38 y 49); https://www.diputados.gob.mx/LeyesBiblio/pdf/CFF.pdf (art. 30); LFPDPPP art. 10
- **Confianza:** media

### 5. Valor normativo de la NMX-COE-001-SCFI-2018

- **Conflicto:** Consumidor, identidad y buenas prácticas la tratan como guía obligada; contenido-plataforma, como referencia voluntaria no verificada.
- **Resolución:** Texto vigente de la LFPC art. 76 Bis 1 (adicionado DOF 11-01-2018): el proveedor que vende por medios electrónicos «se guiará por las disposiciones de la Norma Mexicana expedida por la Secretaría de Economía», que contendrá al menos siete mecanismos (características, verificación de la intención, aceptación, prueba de la transacción, seguridad, quejas, identidad, pago y entrega). Resolución: es norma voluntaria por naturaleza, pero la LFPC remite a ella; los siete mecanismos son obligatorios por ley y la NMX se trata como obligatoria en la práctica para la tienda. No hay contradicción de fondo.
- **Fuente primaria:** https://www.diputados.gob.mx/LeyesBiblio/pdf/LFPC.pdf (art. 76 Bis 1)
- **Confianza:** alta en el texto; media en la exigibilidad de cada numeral

### 6. Versión de la ley de animales de la CDMX

- **Conflicto:** Contenido-plataforma citó la versión con última reforma de 2024; bienestar animal y buenas prácticas documentan la reforma de la G.O. CDMX del 23-07-2026.
- **Resolución:** Se usa el texto con última reforma G.O. CDMX 23-07-2026 (art. 25 Bis vigente desde el 24-07-2026, art. 24 Ter, persona rescatista independiente). La sección 16 de los Términos debe corregirse (cita errónea al art. 28 Bis).
- **Fuente primaria:** https://data.consejeria.cdmx.gob.mx/images/leyes/2025/2026/190126/LEY_DE_PROTECCION_Y_BIENESTAR_DE_LOS_ANIMALES_DE_LA_CDMX_1.2.pdf
- **Confianza:** alta

### 7. Procedimiento de aviso y contra-aviso de derechos de autor

- **Conflicto:** Identidad y buenas prácticas describen el procedimiento de 2020 sin el Reglamento nuevo.
- **Resolución:** Se verificó en el DOF del 24-09-2026 el «Decreto por el que se adicionan diversas disposiciones al Reglamento de la Ley Federal del Derecho de Autor»: capítulo V con arts. 37 Bis a 37 Nonies (formulario que el proveedor debe poner a disposición, prohibición de condicionar el retiro a certificados, contenido del contra-aviso); entra en vigor a los 90 días hábiles (alrededor del 03-02-2027) y los avisos previos se tramitan con las reglas vigentes al presentarse. La página de propiedad intelectual sigue ese formulario desde el lanzamiento, junto con la LFDA reformada el 14-05-2026.
- **Fuente primaria:** https://dof.gob.mx/nota_detalle.php?codigo=5799437&fecha=24/09/2026
- **Confianza:** alta

### 8. Verificación de edad y fecha de la LGDNNA

- **Conflicto:** Contenido-plataforma dice que el Decreto NNA exige más que la autodeclaración; otros dominios dan por suficiente la casilla 18+; dudas sobre si la LGDNNA se reformó el 14-10-2026.
- **Resolución:** El gap NNA leyó el decreto íntegro: es un decreto presidencial que no reforma la LGDNNA (sigue con última reforma DOF 15-01-2026); su art. 4 fr. I exige mecanismos que «no deberán limitarse a la autodeclaración» y aplica aunque el servicio sea 18+. Resolución: la casilla 18+ es necesaria pero ya no suficiente; se adopta la verificación por capas sin biometría (fecha de nacimiento y OTP, señales de riesgo, verificación reforzada sin copia en momentos de riesgo).
- **Fuente primaria:** https://dof.gob.mx/nota_detalle.php?codigo=5801237&fecha=14/10/2026
- **Confianza:** media (el decreto no dice cuánto es suficiente)

### 9. Publicaciones de Facebook como «fuente de acceso público»

- **Conflicto:** Datos personales lo concluye con confianza media; comunicaciones y buenas prácticas lo afirman de forma categórica.
- **Resolución:** Texto vigente de la LFPDPPP art. 2 fr. X: fuente de acceso público son las bases «que por disposición de ley puedan ser consultadas públicamente». Un grupo de Facebook no es consultable por disposición de ley. Mensaje único en todas las páginas: «Las publicaciones de grupos de Facebook no son fuentes de acceso público en términos de la LFPDPPP; por eso no usamos la excepción de consentimiento del art. 9 fr. II y aplicamos las reglas de datos obtenidos de forma indirecta (art. 17)». Certeza: alta sobre el texto; media sobre la vía para cumplir (aviso directo, medida compensatoria autorizada o no operar), que decide el abogado. El art. 7 fr. I del Reglamento de 2011 (sitios abiertos de internet) no prevalece sobre la ley.
- **Fuente primaria:** https://www.diputados.gob.mx/LeyesBiblio/pdf/LFPDPPP.pdf (arts. 2 fr. X, 9 y 17)
- **Confianza:** alta en el texto; media en la aplicación

### 10. Modificaciones a la RMF 2026

- **Conflicto:** El resumen fiscal habla solo de la 1a modificación; el hallazgo corregido menciona una 2a y una 3a sin decir qué cambiaron.
- **Resolución:** Verificado en el DOF: la Segunda Resolución de Modificaciones (DOF 01-10-2026, nota 5800157) reforma la regla 9.4.4, adiciona fracciones a la 11.7.3 (diésel) y el transitorio Vigésimo Noveno (vigencia 2027 de autorizaciones de donatarias); la Tercera (DOF 02-10-2026, nota 5800260) da a conocer la primera modificación al Anexo 7 y entra en vigor el 31-12-2026. Ninguna toca las reglas 2.7.1.3, 2.7.1.21, 2.7.1.23, 2.7.1.35, 2.9.21 ni el capítulo 12. Lo dicho sobre la tienda sigue vigente; el contador debe revisar el transitorio Vigésimo Noveno para los refugios donatarias.
- **Fuente primaria:** https://dof.gob.mx/nota_detalle.php?codigo=5800157&fecha=01/10/2026; https://dof.gob.mx/nota_detalle.php?codigo=5800260&fecha=02/10/2026
- **Confianza:** alta

### 11. Art. 16 constitucional y la reforma del 07-10-2026

- **Conflicto:** Contenido-plataforma cita la última reforma DOF 07-10-2026; seguridad y buenas prácticas no la consideran.
- **Resolución:** El gap NNA verificó que el decreto del 07-10-2026 reformó los arts. 82, 116 y 122 (nacionalidad); el art. 16 no cambió (su última reforma, DOF 30-09-2024, solo tocó el último párrafo). Los párrafos sobre comunicaciones privadas siguen intactos: chats solo con autorización judicial o aportados por un participante; se incorporan los arts. 291 y 303 del CNPP a la página de autoridades.
- **Fuente primaria:** https://www.diputados.gob.mx/LeyesBiblio/pdf/CPEUM.pdf
- **Confianza:** alta

### 12. Régimen que activa la custodia de fondos de terceros

- **Conflicto:** Cuatro teorías distintas: LRITF art. 22 (confianza baja), Ley Fintech no aplica, LFPIORPI art. 17 fr. XI, LGOAAC art. 81-A Bis.
- **Resolución:** El gap de custodia las ordena por fase: con cuenta concentradora, habitualidad y comisión, el riesgo principal es LGOAAC 81-A Bis (transmisor de dinero; suspensión y clausura por art. 64); LRITF 22 solo si hay saldos, monederos o fondos reembolsables (no se crean); LFPIORPI 17 fr. XI si se cobra «en nombre y representación» de los refugios y se administra su dinero; además, los Términos de Mercado Pago prohíben usar la cuenta por cuenta de terceros (9.6) y listan «Donativos» como actividad prohibida sin excepción escrita. Resolución: Split 1:1 por refugio para la tienda y los donativos; cuenta concentradora solo transitoria, con comisión 0, sin saldos, dispersión desde la liberación, dictamen y fecha de migración.
- **Fuente primaria:** https://www.diputados.gob.mx/LeyesBiblio/pdf/LGOAAC.pdf; https://www.diputados.gob.mx/LeyesBiblio/pdf/LRITF.pdf; https://www.mercadopago.com.mx/ayuda/terminos-y-condiciones_299
- **Confianza:** media

### 13. Erratas de citas detectadas al ensamblar

- **Conflicto:** Algunas secciones citan la LFPDPPP «art. 3 fr. X» (fuente de acceso público) y «art. 3 fr. XX» (transferencia); el informe NNA aparece con fecha 12 y 13-11-2026.
- **Resolución:** En el texto vigente las definiciones están en el art. 2 (fr. X fuente de acceso público, fr. XII persona encargada, fr. XX transferencia); el art. 3 trata de los límites de los principios. Toda página debe citar el art. 2. Para el informe del Decreto NNA se usa la fecha interna 12-11-2026 (cubre ambos cómputos).
- **Fuente primaria:** https://www.diputados.gob.mx/LeyesBiblio/pdf/LFPDPPP.pdf (arts. 2 y 3)
- **Confianza:** alta

## 15. Fechas clave

| Fecha | Qué vence o cambia | Responsable | Hallazgos |
|---|---|---|---|
| Antes del lanzamiento | Completar identidad (datos-legales.json), páginas bloqueantes y checklist de cobros; sin marcadores vacíos. | Dueño y abogado | IC-01 DP-04 BP-02 |
| 2026-10-31 | El Senado debe resolver la LISR y la LIF 2027; vence la regla 10ª Bis de Redes de Medios de Disposición (señal para revisar las nuevas Disposiciones). | Contador / vigilancia | FT-v01 CF-16 |
| 2026-11-05 | Confirmar con la ATDT y la CJEF el canal y formato del informe del Decreto NNA (fecha interna). | Dueño y abogado | NNA-07 |
| 2026-11-12 | Entregar el informe de implementación del Decreto NNA (fecha interna; el cómputo alternativo llega al 13-11-2026). | Representante legal | NNA-07 |
| 2026-11-30 | Entran en vigor las Reglas de Carácter General de la LFPIORPI modificadas (Acuerdo 115/2026): medidas para asociaciones sin fines de lucro. | Refugios A.C. / abogado de PLD | DON-v01 |
| Noviembre-diciembre de 2026 | Publicación en el DOF de la LISR y LIF 2027; actualizar tasas de retención para el 01-01-2027. | Contador | FT-01 FT-v01 |
| 2026-12-31 | Entra en vigor la Tercera modificación a la RMF 2026 (Anexo 7). | Contador | FT-01 |
| 2027-01-31 | Termina la vigencia de la UMA 2026 ($117.31); recalcular umbrales y multas con la UMA 2027. | Contador | DON-11 |
| Alrededor del 2027-02-03 | Entra en vigor el capítulo V del Reglamento de la LFDA (formulario obligatorio de aviso y contra-aviso). | Producto y abogado | CP-02 CP-03 |
| 2027-03-01 | Exigibles la evaluación de riesgo y el manual de políticas PLD para sujetos obligados. | Refugios A.C. sujetos obligados | DON-11 |
| 2027-04-01 | Aplicación automática del Código Nacional de Procedimientos Civiles y Familiares como supletorio (LFPDPPP art. 4). | Abogado | DP-01 CP-15 |
| Cada 180 días por refugio | Renovar el token OAuth de Mercado Pago de cada refugio vinculado (Split 1:1). | Sistema | CF-09 |
| Mensual | Revisar Términos de Mercado Pago (cambios en vigor a los 10 días; rechazo en 5), DOF, gob.mx/atdt y gob.mx/cjef. | Vigilancia normativa | CF-16 NNA-11 |
| Semestral | Evaluación de riesgos del Decreto NNA, reporte estadístico, informe de transparencia, revisión de políticas de Meta y Google. | Dueño | NNA-06 BP-32 VET-17 AD-10 |
| Rodante | Evidencia de cada retiro: al menos 90 días hábiles. | Moderación | NNA-09 |

## 16. Riesgos principales

| ID | Riesgo | Consecuencia | Mitigación | Severidad | Hallazgos |
|---|---|---|---|---|---|
| K01 | Lanzar con identidad, domicilio o datos legales vacíos (hoy datos-legales.json está vacío). | LFPDPPP art. 58 fr. V: 100 a 160,000 UMA ($11,731 a $18,769,600); LFPC art. 128: hasta $4,274,960.73; quejas sin domicilio para notificar. | Bloquear el despliegue con marcadores vacíos; llenar O01 a O08. | crítica | DP-04 IC-01 CE-02 BP-02 |
| K02 | No entregar el informe del Decreto NNA a más tardar el 12-11-2026 o hacerlo sin verificación de edad más allá de la casilla, criterios publicados, contacto 24/7 y conservación de evidencia. | Seguimiento de la ATDT y daño reputacional (el decreto no tiene sanciones propias, pero una ley con sanciones fue anunciada). | Plan de la sección D; confirmar canal antes del 05-11-2026. | crítica (plazo) | NNA-07 NNA-11 CP-11 |
| K03 | Recibir donativos y ventas en la cuenta de Mercado Pago de la plataforma y dispersarlos (cuenta concentradora). | Bloqueo de la única pasarela (cláusula 9.6 y «Donativos» como actividad prohibida); encuadre como transmisor de dinero (suspensión y clausura, LGOAAC 64); LFPIORPI 17 fr. XI; presunción de ingresos (CFF 59 fr. III); abuso de confianza. | Split 1:1 por refugio; excepción escrita de Mercado Pago; si hay fase transitoria, comisión 0, sin saldos, dictamen y fecha de migración. | crítica | CF-01 CF-02 CF-05 CF-06 FT-16 DON-01 |
| K04 | Activar comisión (el código trae 10 % por defecto) sin el régimen de plataformas listo. | Retenciones omitidas con responsabilidad solidaria; bloqueo del servicio por no dar acceso al SAT (CFF 30-B); restricción del CSD; Términos 14.1 que reconocen obligaciones incumplidas. | Comisión 0 hasta cumplir la puerta de salida fiscal; dictamen del contador. | alta | FT-09 FT-12 FT-29 FT-v03 |
| K05 | Cuotas, reembolsos o «donativos sugeridos» ligados a la adopción. | GuauWoow como plataforma que difunde venta de perros (CDMX 25 Bis: 150 a 3,000 UMA; Edomex: arresto de 36 horas al vendedor); IVA 16 %; suspensión del bot de WhatsApp; pérdida de la defensa de «cero venta». | Regla de cuatro niveles con controles técnicos y sanciones a verificados. | alta | AD-01 AD-03 AD-04 AD-09 BA-10 |
| K06 | Ingesta de grupos de Facebook vía Apify sin base jurídica ni dictamen contractual. | Tratamiento sin aviso de datos de terceros; responsabilidad como editor por fotos y textos (sin puerto seguro); riesgo de perder la app de Meta, la API de Páginas y el número de WhatsApp. | No activar en producción sin dictamen; minimización, caducidad real, retiro sin cuenta. | alta | DP-26 CP-21 CP-22 CC-v03 |
| K07 | Tienda sin flujos de consumidor (revisión del pedido, revocación de 5 días, bonificación de 20 %, envíos, CFDI en 24 h) y con cláusulas abusivas. | Multas LFPC 127 y 128; publicidad engañosa hasta 10 % de ingresos en reincidencia; CFF 83 y 84. | Sección G y H de la matriz antes de SHOP_ENABLED=true. | alta | CE-05 CE-09 CE-11 CE-15 FT-02 |
| K08 | Alertas cercanas activas por defecto y plantillas de WhatsApp sin opt-in registrado. | Infracción a LFPDPPP (finalidad no necesaria); degradación o bloqueo del número de WhatsApp Business. | notify_nearby en false; opt-in con texto y fecha; BAJA y ALTA. | alta | DP-07 CC-08 CC-09 CC-10 |
| K09 | Documentos de identidad de refugios en claro, sin MFA de administradores y sin plan de respuesta a incidentes. | Vulneración imputable: 200 a 320,000 UMA ($23,462 a $37,539,200), duplicable con datos sensibles; verificaciones de oficio de la SABG; incumplir 24 h de aviso a Mercado Pago. | Cifrar uploads/private, MFA, borrar imágenes a 30 días, runbook y plantillas. | alta | SI-10 SI-22 SI-23 SI-04 DP-22 |
| K10 | Prometer plazos de conservación o medidas de seguridad que el código no ejecuta (purgas inexistentes, MFA, cifrado, pentest). | Práctica engañosa y art. 58 fr. IV y VI LFPDPPP. | Publicar solo lo que existe; tareas de purga. | media | SI-18 SI-29 |
| K11 | Perfiles de clínicas con cédula no verificada, superlativos o reseñas de Google almacenadas o junto al mapa OSM. | Usurpación de profesión (CPF 250 fr. II) con responsabilidad propia por la insignia; órdenes de PROFECO al medio; suspensión del servicio de Google e indemnización. | Sección J de la matriz. | media | VET-01 VET-08 VET-10 VET-16 |
| K12 | Reseñas o publicaciones que acusan a personas identificables sin moderación diligente. | Daño moral contra el autor y contra GuauWoow (negligencia inexcusable en CDMX); sin puerto seguro fuera de derechos de autor. | Reglas «opina, no acuses», filtro previo, retiro y aclaración. | media | VET-13 CP-07 |
| K13 | Perder el puerto seguro de derechos de autor o no tener el formulario del Reglamento LFDA en febrero de 2027. | Multa de 1,000 a 20,000 UMA por no retirar o no entregar información; responsabilidad directa. | Procedimiento de aviso, contra-aviso, staydown y reincidentes. | media | CP-01 CP-02 CP-03 |
| K14 | Entregar chats o ubicación a una autoridad sin orden judicial. | Violación del art. 16 constitucional y de CNPP 291 y 303; posible delito del CPF art. 177. | Tres niveles de entrega y revisión del abogado. | media | NNA-12 SI-21 BP-18 |
| K15 | Términos inexigibles: aceptación por uso, cambios por uso continuado, bitácora que se sobrescribe, renuncia de fuero. | Cláusulas por no puestas (LFPC 90) y prueba débil en litigio. | Clickwrap, bitácora inmutable, aceptación expresa de cambios. | media | CP-14 CP-15 CP-17 IC-14 |
| K16 | Dar en adopción perros encontrados antes del plazo de reclamo (72 horas a 10 días según el estado). | Reclamaciones civiles del tutor original contra el publicador y señalamientos a la plataforma. | Regla de 30 días con microchip y aviso a la autoridad. | media | EST-16 BA-15 |
| K17 | Verificar como refugio a quien no tiene el registro que exige su estado, o presentar «verificado» como garantía. | Información engañosa (LFPC 32 y 76 Bis fr. IV); cooperar con operaciones irregulares. | Verificación por estado e insignias con alcance claro. | media | EST-17 IC-24 BA-21 |
| K18 | Publicidad y correos sin identificación del proveedor, de PROFECO o enviados a quien se negó o está en el REPEP. | LFPC 127 ($760.89 a $2,434,847.42) y 128 ($1,093.02 a $4,274,960.73). | Pies de publicidad, lista de supresión, REPEP si hay publicidad telefónica. | media | CC-13 CC-14 CE-19 |
| K19 | Donativos sin topes ni separación de beneficios (puntos de ranking por donar, autodonaciones). | Actividad vulnerable desde 1,605 UMA para el refugio; información engañosa; vehículo para mover dinero de forma opaca. | Topes, sin puntos por donar, monitoreo. | media | DON-11 DON-16 |
| K20 | Rifas, sorteos o animales como premio en campañas, tienda, bot o Página de Facebook. | LFJS art. 4 (ilegal sin permiso); LPBA CDMX art. 25 fr. III; actividad vulnerable. | Bloqueo en moderación y lineamientos. | media | DON-23 CE-v03 BA-06 EST-02 |
| K21 | Normas en movimiento sin vigilancia (Ley General de bienestar animal, reforma fiscal 2027, RCG LFPIORPI 30-11-2026, Reglamento LFDA, contratos de Meta, Google y Mercado Pago). | Centro legal desactualizado desde el primer mes. | Calendario de vigilancia y responsable. | media | BP-35 EST-22 CF-16 FT-v01 |
| K22 | Material de abuso sexual infantil conservado sin postura penal ni denuncia inmediata. | Riesgo penal (CPF 202 y 202 Bis). | Protocolo D08 y dictamen penal previo. | media (baja probabilidad, impacto muy alto) | NNA-10 |

## 17. Datos que debe aportar el dueño

Lista única (deduplicada de todas las secciones). Marcar cada casilla al entregar el dato al equipo y al abogado; muchos se cargan en `app/legal/datos-legales.json`.

### Identidad y forma jurídica

- [ ] **O01.** Forma jurídica del operador (S.A.S., S.A. de C.V., A.C. o persona física) y, si aún no existe, fecha prevista de constitución; acta y folio mercantil. *Para qué:* Define si es comerciante (10 años de conservación), si aplica el régimen de retención de plataformas y el encuadre de LGOAAC 81-A Bis. *Cuándo:* Antes del lanzamiento.
- [ ] **O02.** Razón social completa con tipo societario, nombre comercial, RFC, régimen fiscal, constancia de situación fiscal y código postal. *Para qué:* Aviso de privacidad, Términos, checkout, CFDI, informe NNA. *Cuándo:* Antes del lanzamiento.
- [ ] **O03.** Domicilio fiscal y domicilio físico en México para reclamaciones y notificaciones (calle, número, colonia, alcaldía o municipio, CP, entidad). *Para qué:* LFPC art. 76 Bis fr. III y aviso de privacidad. *Cuándo:* Antes del lanzamiento.
- [ ] **O04.** Representante legal con poder (PROFECO, contratos con refugios, informe NNA) y expediente de beneficiarios controladores. *Para qué:* Firmas, Concilianet, CFF 32-B Ter. *Cuándo:* Antes del lanzamiento.
- [ ] **O05.** Dominio definitivo y titular registrante; cuentas oficiales (WhatsApp, Facebook, Instagram, TikTok) a nombre del operador. *Para qué:* security.txt, OAuth, canales oficiales, SPF/DKIM/DMARC. *Cuándo:* Antes del lanzamiento.
- [ ] **O06.** Estatus de la marca GuauWoow ante el IMPI (búsqueda, solicitud, clases, logo final). *Para qué:* Uso correcto de la marca. *Cuándo:* Primer trimestre.

### Contacto y responsables

- [ ] **O07.** Teléfono de atención, horario, correos: contacto y quejas, privacidad, facturación, legal (autoridades y propiedad intelectual), seguridad, accesibilidad; número oficial de WhatsApp y nombre visible del perfil. *Para qué:* Páginas de identidad, atención, ARCO, cookies, bot, security.txt. *Cuándo:* Antes del lanzamiento.
- [ ] **O08.** Persona o departamento de datos personales y su suplente (art. 29 LFPDPPP). *Para qué:* Aviso integral y centro de privacidad. *Cuándo:* Antes del lanzamiento.
- [ ] **O09.** Titular y suplente del punto de contacto 24/7 para autoridades (nombre, cargo, teléfono dedicado, correo) y calendario de guardias realista. *Para qué:* Decreto NNA art. 5 fr. I e informe del 12-11-2026. *Cuándo:* Antes del 05-11-2026.
- [ ] **O10.** Responsable de moderación y de reclamaciones de contenido (reseñas, réplica) y horario de moderación. *Para qué:* Compromisos de retiro y responsable publicado. *Cuándo:* Antes del lanzamiento.
- [ ] **O11.** Responsable de vigilancia normativa (DOF, Gaceta, periódicos oficiales, contratos de Meta, Google y Mercado Pago) y lugar de la bitácora. *Para qué:* Mantener vigente el centro legal. *Cuándo:* Antes del lanzamiento.
- [ ] **O12.** Abogado externo (datos, consumo, financiero y PLD, penal, bienestar animal local) y contador; directorio de contactos de incidentes (hosting, Mercado Pago, Meta, Apify, PAC, Google, aseguradora). *Para qué:* Revisión previa y respuesta a incidentes. *Cuándo:* Antes del lanzamiento.

### Proveedores e infraestructura

- [ ] **O13.** Proveedor del VPS, país o región del centro de datos y certificaciones; región del bucket R2 y custodio de la llave de respaldos; plazos reales de respaldo. *Para qué:* Aviso de privacidad (encargados y flujos internacionales) y página de conservación. *Cuándo:* Antes del lanzamiento.
- [ ] **O14.** Proveedor SMTP y país; dominios de envío; acceso al DNS; confirmación de que el seguimiento de aperturas y clics está desactivado. *Para qué:* Comunicaciones y cookies. *Cuándo:* Antes del lanzamiento.
- [ ] **O15.** Proveedor de SMS (SMS Masivos, Twilio o ambos) y contratos o DPA firmados. *Para qué:* Lista de encargados. *Cuándo:* Antes del lanzamiento.
- [ ] **O16.** Región configurada en Sentry y PostHog, retención y DPA; funciones activas de Cloudflare (WAF, Bot Management, Turnstile, Web Analytics, Zaraz). *Para qué:* Inventario de cookies y encargados. *Cuándo:* Antes del lanzamiento.
- [ ] **O17.** Cuenta de Alibaba Cloud: entidad contratante, región del endpoint, ámbito de cómputo, términos aceptados, plan de migración de DashScope; decisión sobre el proveedor alterno en China. *Para qué:* Transferencias internacionales y página de IA. *Cuándo:* Antes del lanzamiento.
- [ ] **O18.** Datos del proyecto de Google Cloud (correo de soporte, logo, dominio verificado, URLs finales) y cuenta de facturación de Google Maps Platform con dirección en México. *Para qué:* Verificación de marca OAuth; términos de Maps no EEA. *Cuándo:* Antes del lanzamiento.
- [ ] **O19.** Proveedor de teselas (OSM o CARTO) y decisión de mover la geocodificación inversa al backend. *Para qué:* Cookies y terceros que reciben IP. *Cuándo:* Antes del lanzamiento.
- [ ] **O20.** Prestador de Servicios de Certificación NOM-151 o de firma electrónica (si se contrata) y presupuesto. *Para qué:* Prueba de aceptaciones y del informe NNA. *Cuándo:* Primer trimestre.
- [ ] **O21.** Seguro de responsabilidad civil o ciberriesgos (cobertura de contenido de terceros, verificación y daño moral). *Para qué:* Página de seguridad y mitigación de riesgos. *Cuándo:* Primer trimestre.

### Pagos, tienda y donativos

- [ ] **O22.** Fase de cobro por producto (tienda y donativos): Split 1:1, cuenta concentradora transitoria o cobro directo; fecha de migración si hay transitoria. *Para qué:* Términos 14.1 y 15.1, convenio, páginas de dinero. *Cuándo:* Antes de activar cobros.
- [ ] **O23.** Comisión de la tienda y de los donativos (porcentaje o 0 %), si incluye IVA, quién absorbe la comisión de Mercado Pago y tarifa contratada. *Para qué:* Tarifas, régimen de plataformas, neto al donante. *Cuándo:* Antes de activar cobros.
- [ ] **O24.** Tipo y estado de la cuenta de Mercado Pago del operador; credenciales de la aplicación Marketplace; respuesta escrita de Mercado Pago (número de caso) sobre donativos, marketplace y retenciones. *Para qué:* Excepción de la cláusula 4.7 y Split. *Cuándo:* Antes de activar cobros.
- [ ] **O25.** Tope por donativo y acumulado a 6 meses por donante y refugio (sugerido por debajo de 1,605 UMA = $188,282.55). *Para qué:* LFPIORPI y página de prevención. *Cuándo:* Antes de activar donativos.
- [ ] **O26.** Decisión sobre donativos recurrentes y sobre una «aportación voluntaria a GuauWoow». *Para qué:* LFPC 76 Bis fr. VIII y IX; tratamiento fiscal. *Cuándo:* Antes de activar donativos.
- [ ] **O27.** Decisión sobre el ranking: quitar los puntos por donativo o mostrarlos aparte; confirmación de que los puntos nunca se canjean por algo con valor económico. *Para qué:* Información engañosa y LRITF. *Cuándo:* Antes del lanzamiento.
- [ ] **O28.** Modelo jurídico de la tienda (comisión en nombre propio, en nombre del refugio o intermediación) y quién emite cada CFDI; si GuauWoow venderá mercancía propia. *Para qué:* Términos, convenio de vendedores, facturación. *Cuándo:* Antes de activar la tienda.
- [ ] **O29.** PAC elegido (verificado en la lista del SAT), CSD vigente para el gestor de secretos, presupuesto de folios. *Para qué:* CFDI en 24 horas. *Cuándo:* Antes de activar la tienda.
- [ ] **O30.** Política de envíos: paqueterías, cobertura, cálculo del costo, plazo de despacho y de entrega, seguro, quién genera las guías, domicilio de devoluciones. *Para qué:* Página de envíos y devoluciones. *Cuándo:* Antes de activar la tienda.
- [ ] **O31.** Plazo de reembolso publicado (propuesta: 10 días hábiles o menos), exclusiones de devolución y garantías por tipo de producto. *Para qué:* Revocación y garantías. *Cuándo:* Antes de activar la tienda.
- [ ] **O32.** Catálogo previsto por categoría (ropa, accesorios, juguetes, alimento, premios, electrónicos, personalizados) y si hay productos importados o que requieren registro SENASICA. *Para qué:* Productos prohibidos y NOM de etiquetado. *Cuándo:* Antes de activar la tienda.
- [ ] **O33.** Periodicidad de liquidación a refugios, monto mínimo y reserva para contracargos; plazo para pedir factura. *Para qué:* Convenio y transparencia de fondos. *Cuándo:* Antes de activar cobros.
- [ ] **O34.** Volumen esperado de donativos y ventas (número y monto promedio). *Para qué:* Dimensionar reservas y umbrales PLD. *Cuándo:* Antes de activar cobros.
- [ ] **O35.** Si habrá meses sin intereses, promociones, descuentos, rifas o sorteos de refugios dentro de la plataforma. *Para qué:* Promociones y rifas (prohibidas sin permiso). *Cuándo:* Antes de activar la tienda.
- [ ] **O36.** Decisión sobre el convenio de Concilianet y la adhesión futura al Código de Ética y al Distintivo Digital de PROFECO. *Para qué:* Página de atención y compromisos. *Cuándo:* Primer semestre.

### Refugios, rescatistas y clínicas

- [ ] **O37.** Lista de refugios iniciales por estado: forma jurídica, RFC, si son donatarias (oficio, rubro, ejercicio), CLUNI, padrón o autorización local, nombre y cédula del MVZ, cuenta de Mercado Pago verificada a su nombre. *Para qué:* Verificación, Split y fiscal. *Cuándo:* Antes del lanzamiento.
- [ ] **O38.** Decisión sobre quién puede recibir donativos: solo personas morales, donatarias, o también rescatistas personas físicas (con límites). *Para qué:* Política de donativos y LISR art. 93 fr. XXIII. *Cuándo:* Antes de activar donativos.
- [ ] **O39.** Si los refugios aliados cobran hoy cuotas de adopción, cuánto, y cuáles aceptarán la regla de cero cuotas. *Para qué:* Regla de cuatro niveles. *Cuándo:* Antes del lanzamiento.
- [ ] **O40.** Método de verificación de refugios: conservar copia de INE o acta (y por qué) o solo constancia con videollamada. *Para qué:* Minimización y conservación. *Cuándo:* Antes del lanzamiento.
- [ ] **O41.** Para clínicas: confirmar modelo gratuito (sin cobro de consultas, agenda con pago, venta de productos ni perfiles destacados de pago), mapa de la sección, documentos para especialidades, antigüedad mínima de cuenta y ventana de experiencia para reseñar. *Para qué:* Encuadre de no proveedor y reseñas. *Cuándo:* Antes de abrir la sección.
- [ ] **O42.** Estados en los que se abren clínicas y refugios al lanzar, y si se aceptan los de estados con ficha «pendiente de revisión». *Para qué:* Tabla por estado. *Cuándo:* Antes del lanzamiento.

### Decisiones de producto

- [ ] **O43.** Estados de lanzamiento y orden de apertura (para cotejar leyes locales). *Para qué:* Selector de estado y fichas. *Cuándo:* Antes del lanzamiento.
- [ ] **O44.** Esquema de verificación de edad por capas y quién hace la verificación reforzada (videollamada sin copia o carga cifrada con borrado a 7 días). *Para qué:* Decreto NNA art. 4 fr. I. *Cuándo:* Antes del 12-11-2026.
- [ ] **O45.** Configuraciones predeterminadas que el producto puede garantizar (ubicación aproximada, contacto oculto, chat tras match, alertas apagadas, sin EXIF, no indexable). *Para qué:* Decreto NNA art. 4 fr. VIII. *Cuándo:* Antes del 12-11-2026.
- [ ] **O46.** Plazos que el equipo puede cumplir: ocultar contenido del art. 3 del Decreto (menos de 24 h), revisar reportes (72 h hábiles), derechos de autor (menos de 24 h hábiles), apelaciones (10 días hábiles), retiro de importados (72 h), respuesta a madres y padres (72 h). *Para qué:* Compromisos públicos exigibles. *Cuándo:* Antes del lanzamiento.
- [ ] **O47.** Escala de sanciones y reincidencia (propuesta: 2 avisos procedentes en 12 meses = 30 días; 3 = cancelación). *Para qué:* Moderación y derechos de autor. *Cuándo:* Antes del lanzamiento.
- [ ] **O48.** Compartir correo y teléfono al aprobar una adopción o limitarlo al chat; precisión de la zona y radio de alertas; puntaje de compatibilidad visible y a quién. *Para qué:* Transferencias y ubicación. *Cuándo:* Antes del lanzamiento.
- [ ] **O49.** Confirmación de la regla de 30 días para perros encontrados y del estándar único de entrega en adopción. *Para qué:* Guía de perdidos y política de adopción. *Cuándo:* Antes del lanzamiento.
- [ ] **O50.** Si habrá filtro de desnudos o lista de bloqueo por hash, y si el chat seguirá siendo solo texto. *Para qué:* Protocolo de menores. *Cuándo:* Antes del 12-11-2026.
- [ ] **O51.** Si habrá publicidad o boletines y por qué canales (correo, WhatsApp de marketing, SMS, push); si se contratará el REPEP o se declarará que no habrá publicidad telefónica; píxeles de marketing en la landing. *Para qué:* Comunicaciones y cookies. *Cuándo:* Antes del lanzamiento.
- [ ] **O52.** Horario silencioso, topes de frecuencia y radio de alertas para usuarios, refugios y casas de paso. *Para qué:* Centro de preferencias. *Cuándo:* Antes del lanzamiento.
- [ ] **O53.** Periodicidad del informe de transparencia, fecha del primero y página de estado del servicio. *Para qué:* Transparencia. *Cuándo:* Primer semestre.
- [ ] **O54.** Fecha de entrada en vigor del paquete legal y periodo de aviso de cambios (propuesta: 30 días naturales). *Para qué:* Historial y reaceptación. *Cuándo:* Antes del lanzamiento.
- [ ] **O55.** Fechas objetivo de MFA para administradores, cifrado de documentos privados y pentest externo (condicionan lo que puede afirmar la página de Seguridad). *Para qué:* Seguridad. *Cuándo:* Antes del lanzamiento.
- [ ] **O56.** Lista de personas con rol admin o superadmin y de voluntarios o moderadores con acceso a datos; quién desarrolló el código y qué partes se generaron con IA. *Para qué:* Acuerdos de confidencialidad, MFA, cesiones de derechos. *Cuándo:* Antes del lanzamiento.

### Ingesta de Facebook y bot

- [ ] **O57.** Decisión final sobre mantener la ingesta de grupos vía Apify tras el dictamen; lista de estados y grupos; contrato, entidad, país y retención de datasets de Apify; si la caducidad de 30 días aplica también a voluntarios y bot. *Para qué:* Base jurídica y página de contenido importado. *Cuándo:* Antes de activar la ingesta en producción.
- [ ] **O58.** Páginas de Facebook administradas (page_id), estado de verificación en Meta Business, URL de eliminación de datos configurada en Meta for Developers; confirmación de que la Página no usa Shops, Marketplace ni catálogo. *Para qué:* Contratos de Meta. *Cuándo:* Antes del lanzamiento.
- [ ] **O59.** Datos del perfil de WhatsApp Business (nombre, correo, sitio, horario) y canal para hablar con una persona. *Para qué:* Política de WhatsApp. *Cuándo:* Antes del lanzamiento.

### Autoridades y denuncia

- [ ] **O60.** Datos oficiales verificados de las autoridades de denuncia de maltrato en cada estado de lanzamiento (teléfono, sitio, domicilio). *Para qué:* Página de denuncia. *Cuándo:* Antes del lanzamiento.
- [ ] **O61.** Correo y domicilio desde los que se enviará el informe NNA y quién gestiona el acuse con la ATDT y la CJEF. *Para qué:* Informe del 12-11-2026. *Cuándo:* Antes del 05-11-2026.
- [ ] **O62.** Confirmación en gob.mx de los canales vigentes de la SABG y de PROFECO (domicilio y teléfonos) antes de publicarlos. *Para qué:* Atención, ARCO y pie de publicidad. *Cuándo:* Antes del lanzamiento.

## 18. Puntos para abogado y contador

Consolidados sin duplicados (las secciones listaban 252 puntos). Además: todo hallazgo con confianza baja, veredicto `no_verificable`, `no_revisado` o `agregado_por_verificador` requiere confirmación expresa antes de usarse en un texto público.

| ID | Revisor | Tema | Punto | Urgencia | Confianza o motivo | Hallazgos |
|---|---|---|---|---|---|---|
| L01 | Abogado de datos personales | Fuerza del Reglamento 2011 y Lineamientos 2013 | Confirmar la postura unificada de este documento (aplicables en lo que no se opongan a la LFPDPPP 2025, nunca como único fundamento de una obligación) y buscar criterio judicial que la respalde. | Antes del lanzamiento | media; no hay transitorio que los conserve expresamente | DP-02 SI-01 BP-01 CC-01 |
| L02 | Abogado de datos personales | Ingesta de Facebook vía Apify | Base jurídica: aviso directo al autor, medida compensatoria con autorización de la SABG o no operar; si eliminar nombres y teléfonos sigue siendo «reproducción fiel» (CCF 1916); suficiencia de la página de contenido importado y del retiro sin cuenta. | Antes de activar la ingesta en producción | media-baja | DP-26 DP-v01 CP-22 BP-15 |
| L03 | Abogado de tecnología | Riesgo contractual con Meta y contrato con Apify | Evaluar Automated Data Collection Terms §2 y §3 y Platform Terms frente a una app que usa WhatsApp Cloud API y Pages API; revisar términos, país y retención de Apify; si las plantillas con enlace al reporte cumplen la regla de no compartir información de un chat con otro cliente. | Antes de activar la ingesta en producción | baja | CP-21 CC-v03 CP-v04 |
| L04 | Abogado de datos personales y penalista | Decreto NNA | Validar la verificación de edad por capas frente a «no deberán limitarse a la autodeclaración», la lectura «por diseño» de las fr. III, VI y VIII, el destinatario y canal del informe (ATDT y CJEF), el cómputo de los 90 días hábiles y la postura penal sobre conservar material de abuso (CPF arts. 202 y 202 Bis). | Antes del 05-11-2026 | media | NNA-02 NNA-03 NNA-07 NNA-09 NNA-10 |
| L05 | Abogado de datos personales | Comunicaciones privadas | Si los mensajes almacenados son «comunicaciones privadas» según la SCJN y si GuauWoow es «proveedor de servicios de aplicaciones y contenidos» (CNPP 303, LMTR 182); confirmar el art. 16 sin cambios (ya verificado). | Antes de publicar la página de autoridades | media | NNA-12 CP-12 SI-21 |
| L06 | Abogado de datos personales | Transferencias y roles | Calificar a refugios como responsables receptores (art. 35) o encargados; cláusula y casilla para compartir contacto del adoptante; acuerdo de datos con tres perfiles (refugio formal, rescatista, particular). | Antes del lanzamiento | media | DP-06 DP-16 DP-v02 IC-10 BP-11 |
| L07 | Abogado de datos personales | INE, CURP y cédula | Si la copia de la credencial (foto, firma, huella) es dato sensible; si debe pedirse CURP por la Ley General de Población; plazo de conservación de imagen y constancia. | Antes del lanzamiento | media | SI-11 SI-12 DP-10 DP-11 |
| L08 | Abogado de datos personales | Alertas cercanas, compatibilidad y mercadotecnia | Si las alertas son finalidad primaria (se recomienda opt-in en todo caso); si el puntaje de compatibilidad activa el art. 26 fr. II; alinear la finalidad de mercadotecnia del aviso (dice tácita) con el opt-in. | Antes del lanzamiento | media | DP-07 DP-12 DP-08 CC-07 |
| L09 | Abogado de datos personales | ARCO y quejas | Si los 20 días del art. 31 son hábiles; canales vigentes de la SABG; política de aviso voluntario a la SABG ante vulneraciones; matriz de «afectación significativa». | Antes del lanzamiento | media | DP-17 DP-03 DP-22 SI-04 |
| L10 | Abogado de datos personales | Encargados en el extranjero | Suficiencia de los términos de Alibaba Cloud (sin DPA específico), Apify, Meta, Sentry y PostHog; si puede activarse el proveedor alterno en China. | Antes del lanzamiento | media | DP-13 DP-14 SI-09 |
| L11 | Abogado de datos personales | Clínicas y Google | Confirmar que el Registro Nacional de Profesionistas es fuente de acceso público (art. 2 fr. X; las secciones citan por error «art. 3 fr. X») y que publicar nombre, cédula e institución no requiere consentimiento adicional; si mostrar reseñas de Google sin almacenarlas exige aviso a sus autores. | Antes de abrir la sección | media-baja | VET-02 VET-03 VET-15 |
| L12 | Abogado de consumo | Valor de la NMX-COE-001 | Confirmar el tratamiento como obligatoria en la práctica (LFPC 76 Bis 1 «se guiará») y la declaración de cumplimiento. | Antes de activar la tienda | media | CE-32 IC-04 BP-v01 CP-14 |
| L13 | Abogado de consumo | Cláusulas y jurisdicción | Revisar cláusulas 14.2 (error de precio), 15.3, 19.5, 24, 25, 27.2, 30.1 y 31.2 frente a LFPC 85 y 90; jurisdicción del domicilio del consumidor; aceptación expresa de cambios. | Antes del lanzamiento | media | CE-15 CP-17 CP-18 CP-19 IC-14 |
| L14 | Abogado de consumo | Revocación, devoluciones y perfección | Exclusiones de revocación (personalizados, perecederos), días naturales o hábiles del art. 93, flete en revocación y garantía, perfección del contrato (CCom 80 frente a LFPC 56), cobro anticipado por pasarela (LFPC 15). | Antes de activar la tienda | media | CE-06 CE-09 CE-10 CE-11 CE-v05 |
| L15 | Abogado de consumo | Domicilio y oficina virtual | Si una oficina virtual cumple «domicilio físico» (LFPC 76 Bis fr. III). | Antes del lanzamiento | media | CE-02 IC-03 |
| L16 | Abogado regulatorio (SENASICA y NOM) | Catálogo | Qué alimentos, premios y productos veterinarios están desregulados; alcance de NOM-050, NOM-004-SE-2021 y NOM-024 al catálogo real; homologación de localizadores GPS. | Antes de activar la tienda | media | CE-24 CE-25 BA-25 |
| L17 | Abogado mercantil y contador | Modelo de la tienda | Comisión en nombre propio (CCom 284) o del comitente (285) o intermediación; efecto en el proveedor ante PROFECO, en el CFDI y en las retenciones; reflejarlo igual en Términos 4.2, 14.1, 14.7 y en el convenio. | Antes de activar la tienda | media | CE-23 IC-07 FT-08 FT-07 |
| L18 | Abogado financiero y de PLD | Custodia de fondos | Opinión escrita única: cuenta concentradora frente a LGOAAC 81-A Bis (con comisión y con comisión 0), LRITF 22 (sin saldos), LIC 2 y 103, Redes de Medios de Disposición y LFPIORPI 17 fr. XI; conveniencia de consulta formal a la UIF si se mantiene la fase 1. | Antes de activar cobros | media; sin criterio público de CNBV o UIF | CF-01 CF-02 CF-03 CF-04 CF-11 DON-12 IC-v02 |
| L19 | Abogado de contratos | Mercado Pago | Escrito de excepción de la cláusula 4.7 (donativos, marketplace o cobro por cuenta de terceros); cláusulas de compensación de contracargos y reservas en el convenio; textos sin denominaciones reservadas (LRITF 12, LGOAAC 81-B). | Antes de activar cobros | alta en el texto contractual; media en su aplicación | CF-05 CF-06 CF-07 CF-08 CF-15 AD-14 |
| L20 | Abogado de PLD | Donativos y asociaciones sin fines de lucro | Alcance de la definición de asociaciones sin fines de lucro y de las medidas de los arts. 38 Bis a 38 Bis 2 de las RCG (vigor 30-11-2026) para refugios A.C.; obligaciones del art. 18 si se opta por la fase 1. | Antes del 30-11-2026 | media | DON-11 DON-v01 CF-11 |
| L21 | Abogado civilista | Naturaleza de la adopción | Confirmar la calificación de la adopción con cargas como donación onerosa y de cualquier pago ligado a la entrega como compraventa; exigibilidad de la condición resolutoria y del seguimiento (CCF 2338); forma y umbral de $5,000 (2343-2344); efecto del art. 855 Bis del Código Civil de la CDMX; códigos de los estados de lanzamiento. | Antes del lanzamiento | media | AD-01 AD-02 BA-11 IC-12 |
| L22 | Abogado administrativo CDMX y Edomex | Venta digital de perros | Si una ficha con cuota es «publicar o difundir la venta» (LPBA CDMX 25 Bis) y si «difundir» alcanza a la plataforma; si un reembolso es venta desde domicilio (Ley Edomex 40 fr. V); existencia de las fr. V Bis y V Ter del art. 25 citadas por el art. 65 fr. IV. | Antes del lanzamiento | media | AD-03 AD-04 BA-04 BA-v03 |
| L23 | Abogado de consumo | LFPC y adopciones | Si la LFPC alcanza a adopciones gratuitas de refugios y si un domicilio con horario de visitas es «establecimiento abierto al público» para la NOM-148. | Primer trimestre | baja | AD-05 AD-08 IC-12 |
| L24 | Abogado de tecnología | WhatsApp y Meta en adopciones | Confirmar por escrito con Meta que el bot de perdidos y encontrados y el enlace informativo de adopción no son «facilitating the exchange» de animales vivos; cotejar Commerce Policies y Normas comunitarias. | Antes del lanzamiento | media | AD-09 AD-10 CC-11 |
| L25 | Abogado civilista | Perros encontrados | Validar la regla de 30 días frente a bienes mostrencos (CCF 774, 775, 874) y códigos estatales. | Antes del lanzamiento | media | EST-16 BA-15 |
| L26 | Abogados locales | Cotejo estatal | Cotejar Jalisco y Nuevo León con su periódico oficial; reformas de Veracruz (15-10-2026), Baja California (2026), Michoacán (2024-2025), Sonora (numeración del boletín escaneado), Querétaro («Ley Oli»), Puebla (SEDIF); umbral para que un rescatista se considere refugio en CDMX; entregas desde viviendas en Chihuahua. | Según estados de lanzamiento | media-baja | BA-08 BA-09 EST-05 EST-07 EST-08 EST-09 EST-10 EST-13 EST-14 |
| L27 | Abogado legislativo | Ley General de bienestar animal | Confirmar si la minuta se dictaminó el 14-10-2026 y, al publicarse, texto final, transitorios y armonización; no publicar como hecho lo que solo dice la prensa. | Seguimiento semanal | baja en el resultado del 14-10-2026 | EST-01 BA-02 |
| L28 | Abogado de datos y bienestar animal | Padrones de maltratadores | Si GuauWoow puede consultar el Registro de Personas Maltratadoras de la CDMX (art. 24 Ter) o padrones futuros, con qué base y finalidad; tratamiento de la autodeclaración del adoptante. | Primer trimestre | media | BA-20 EST-04 |
| L29 | Abogado penalista y civilista | Responsabilidad como intermediario | Responsabilidad por contenido delictivo importado en automático (CP DF 22 fr. V y 350 Quinquies; CP Edomex 235 Ter y 235 Quinquies) y por reseñas (CCF 1910 y 1916, negligencia inexcusable en CDMX); estado del caso Richter contra Google; plazos de moderación propuestos. | Antes del lanzamiento | media | BA-28 BA-v04 VET-13 CP-07 |
| L30 | Abogado de propiedad intelectual | Derechos de autor y marcas | Fecha exacta de entrada en vigor del Reglamento LFDA (03 o 04-02-2027); confirmar con sentencias el puerto seguro antes de citarlas (AI 217/2020, AR 556/2022); inciso e) del art. 114 Octies frente a la tienda con comisión; imagen de personas tras la reforma del art. 87; cesiones de derechos y obras con IA. | Antes del lanzamiento | media | CP-01 CP-02 CP-05 CP-08 IC-17 |
| L31 | Abogado de propiedad intelectual | Licencia de contenido | Si el carácter oneroso del art. 30 LFDA aplica a licencias no exclusivas sobre contenido de usuarios; redacción de la cláusula 18.2. | Antes del lanzamiento | media | CP-20 |
| L32 | Abogado sanitario y regulatorio | Clínicas | Que el art. 83 LGS aplica a veterinarios; que su publicidad no requiere autorización de COFEPRIS; alcance del aviso de inicio de funcionamiento y del MVRA para clínicas que solo dan consulta; autorizaciones locales (LPBA CDMX 43; Ley Edomex 49). | Antes de abrir la sección | media | VET-02 VET-04 VET-06 |
| L33 | Abogado de tecnología | Google Maps Platform | Opinión sobre el ejemplo prohibido 3.2.3(d)(iii) («listings or directory service») aplicado a un directorio con datos propios verificados y Google como complemento; conveniencia de pedir revisión a Google. | Antes de abrir la sección | media | VET-10 |
| L34 | Abogado de consumo y civilista | Reseñas y réplica | Si las reseñas son «información o publicidad» imputable al medio (LFPC 32 y 35); si GuauWoow es sujeto obligado de la Ley de réplica; aprobar la insignia «Cédula verificada», el deslinde médico y el aviso de urgencias; cuándo denunciar una cédula falsa. | Antes de abrir la sección | media | VET-08 VET-14 VET-16 VET-17 |
| L35 | Abogado corporativo | Forma jurídica | S.A.S. frente a S.A.P.I. de C.V. y tope de ingresos de la S.A.S. (LGSM 260); A.C. separada para donativos; efectos de lanzar como persona física y luego constituir sociedad (aviso nuevo). | Antes del lanzamiento | media | IC-06 FT-13 DP-32 |
| L36 | Abogado mercantil | Convenios | Redacción del convenio con refugios (mandato o comisión, datos, pagos, sanciones y réplica), términos de casas de paso (depósito; CCF 1929), convenio de voluntariado (LFT 291-A) y mediación previa (LGMASC no analizada). | Antes del lanzamiento | media | IC-09 IC-11 IC-22 IC-27 DON-02 |
| L37 | Abogado de seguridad | Divulgación responsable y Términos | Compromiso de no denunciar a investigadores sin prometer inmunidad penal (CPF 211 bis 1); sección 24 de Términos sin excluir responsabilidad por LFPDPPP; plazos de la LFPA en verificaciones de la SABG; obligatoriedad del documento de seguridad y de la bitácora. | Antes del lanzamiento | media | SI-07 SI-26 SI-v04 SI-03 SI-05 |
| L38 | Abogado de accesibilidad | Accesibilidad | Alcance de LFPC 58, LGIPD 32 fr. IV y LFPED 9 fr. XXII Bis para un sitio privado. | Primer semestre | media | IC-19 |
| L39 | Abogado y contador | Calendario de conservación | Validar el calendario único de este documento (10 años para contratos y operaciones si el operador es comerciante; 5 años CFF desde la declaración; 10 años LFPIORPI; 90 días hábiles del Decreto NNA; 72 meses para incumplimientos) y los plazos de bloqueo de cuentas eliminadas. | Antes del lanzamiento | media | CE-08 FT-12 DON-20 SI-17 CP-15 IC-15 BP-05 |
| L40 | Contador | Régimen de plataformas | Confirmar que con comisión mayor que 0 aplican LIVA 18-B fr. II, 18-J y CFF 30-B, y si con Split hay «cobro por cuenta del enajenante» (regla 12.2.5) y retención; alcance de la retención a personas morales del Título III y donatarias (LIF 2026 art. 25); alta como retenedor (ficha 28/CFF); complemento de plataformas revisión E. | Antes de activar comisiones | media | FT-07 FT-09 FT-10 FT-20 FT-v02 CF-13 |
| L41 | Contador | CFDI de la tienda | Llenado del CFDI global, CFDI a cuenta de terceros (regla 2.7.1.3), clave de forma de pago para Mercado Pago, CFDI de egreso en devoluciones y bonificaciones, exención de bienes usados de A.C. | Antes de activar la tienda | media | FT-04 FT-14 FT-18 FT-05 |
| L42 | Contador | Donativos | Tratamiento de fondos en tránsito (CFF 59 fr. III) en la fase transitoria; facturación de la comisión y del costo de Mercado Pago; momento en que la donataria «recibe» el donativo para el CFDI de 24 h; efecto de comisiones en el 5 % de gastos de administración; régimen de A.C. no donatarias y rescatistas personas físicas. | Antes de activar donativos | media | DON-01 DON-03 DON-05 DON-09 DON-14 |
| L43 | Contador | Fracción del art. 79 LISR para refugios | Confirmar en cada caso la fracción con la que el SAT autorizó a cada refugio (XIX o XXV inciso e) y orientar a los que la soliciten; no codificar la fracción en la plataforma. | Antes de activar donativos | media | DON-25 IC-23 |
| L44 | Contador | Reforma 2027 y RMF | Leer la LISR y la LIF 2027 al publicarse (noviembre-diciembre de 2026) y actualizar tasas; revisar cada enero el Anexo 5 (multas); confirmar el transitorio Vigésimo Noveno (2a modificación) para refugios donatarias. | Diciembre de 2026 | alta en lo ya publicado | FT-01 FT-v01 DON-07 |
| L45 | Contador | Cuotas de adopción | Confirmar que la adopción gratuita no causa IVA (LIVA 8) y que una cuota obligatoria es enajenación gravada al 16 % (LIVA 2o.-A fr. I a); que un «donativo sugerido» es remuneratorio y no deducible. | Antes del lanzamiento | media | AD-06 AD-07 DON-v02 |
| L46 | Contador | Beneficiario controlador y PAC | Integrar el expediente de beneficiario controlador (reglas 2.8.1.20 a 2.8.1.23, números no verificados); comprobar el PAC en la lista oficial del SAT. | Antes de activar la tienda | media | FT-v04 FT-24 |
| L47 | Abogado de datos | Hallazgos agregados por verificadores | Confirmar todos los hallazgos con veredicto «agregado_por_verificador» (sin segunda revisión) y los de confianza baja o «no_verificable» antes de usarlos en textos públicos. | Antes del lanzamiento | variable | BP-v01 BP-v13 DON-12 DON-19 AD-08 AD-14 IC-v02 |

## 19. Archivos de detalle por sección

| Sección (texto) | Sección (datos) | Tema | Hallazgos |
|---|---|---|---|
| [bienestar-animal.md](secciones/bienestar-animal.md) | [bienestar-animal.json](secciones/bienestar-animal.json) | Bienestar animal federal, CDMX, Edomex, Jalisco y NL; adopción, perdidos, denuncia | 35 |
| [buenas-practicas.md](secciones/buenas-practicas.md) | [buenas-practicas.json](secciones/buenas-practicas.json) | Estructura del centro legal, gobierno documental, transparencia | 50 |
| [comunicaciones-cookies.md](secciones/comunicaciones-cookies.md) | [comunicaciones-cookies.json](secciones/comunicaciones-cookies.json) | Cookies, banner, geolocalización, WhatsApp, correo, SMS, REPEP, OAuth | 32 |
| [consumidor-ecommerce.md](secciones/consumidor-ecommerce.md) | [consumidor-ecommerce.json](secciones/consumidor-ecommerce.json) | LFPC, NMX-COE, tienda, revocación, garantías, publicidad, PROFECO | 39 |
| [contenido-plataforma.md](secciones/contenido-plataforma.md) | [contenido-plataforma.json](secciones/contenido-plataforma.json) | Responsabilidad por contenido, derechos de autor, moderación, contratación electrónica, importación | 32 |
| [datos-personales.md](secciones/datos-personales.md) | [datos-personales.json](secciones/datos-personales.json) | LFPDPPP 2025, aviso, consentimiento, ARCO, encargados, fuentes indirectas, sanciones | 40 |
| [donativos.md](secciones/donativos.md) | [donativos.json](secciones/donativos.json) | Donativos, donatarias, CFDI de donativo, PLD, convenio con refugios | 29 |
| [fiscal-tienda.md](secciones/fiscal-tienda.md) | [fiscal-tienda.json](secciones/fiscal-tienda.json) | CFDI, IVA, régimen de plataformas, retenciones, PAC, liquidaciones | 34 |
| [gap-cobertura-estatal-bienestar-animal-y-ley-general.md](secciones/gap-cobertura-estatal-bienestar-animal-y-ley-general.md) | [gap-cobertura-estatal-bienestar-animal-y-ley-general.json](secciones/gap-cobertura-estatal-bienestar-animal-y-ley-general.json) | Ley General (no vigente) y 11 estados adicionales | 22 |
| [gap-custodia-fondos-transmisor-dinero-y-terminos-mercado-pago.md](secciones/gap-custodia-fondos-transmisor-dinero-y-terminos-mercado-pago.md) | [gap-custodia-fondos-transmisor-dinero-y-terminos-mercado-pago.json](secciones/gap-custodia-fondos-transmisor-dinero-y-terminos-mercado-pago.json) | Custodia de fondos, transmisor de dinero, Fintech, LFPIORPI, Términos de Mercado Pago | 16 |
| [gap-naturaleza-juridica-adopcion-y-cuotas.md](secciones/gap-naturaleza-juridica-adopcion-y-cuotas.md) | [gap-naturaleza-juridica-adopcion-y-cuotas.json](secciones/gap-naturaleza-juridica-adopcion-y-cuotas.json) | Adopción como donación con cargas, cuotas, venta digital, WhatsApp y Meta | 14 |
| [gap-nna-decreto-entornos-digitales-2026.md](secciones/gap-nna-decreto-entornos-digitales-2026.md) | [gap-nna-decreto-entornos-digitales-2026.json](secciones/gap-nna-decreto-entornos-digitales-2026.json) | Decreto NNA del 14-10-2026, verificación de edad, informe, contacto 24/7 | 12 |
| [gap-veterinarias-y-resenas.md](secciones/gap-veterinarias-y-resenas.md) | [gap-veterinarias-y-resenas.json](secciones/gap-veterinarias-y-resenas.json) | Clínicas, cédula, Google Places, reseñas, daño moral | 17 |
| [identidad-contratos.md](secciones/identidad-contratos.md) | [identidad-contratos.json](secciones/identidad-contratos.json) | Identidad del operador, contratos con refugios y casas de paso, PI, accesibilidad, seguros | 34 |
| [seguridad-incidentes.md](secciones/seguridad-incidentes.md) | [seguridad-incidentes.json](secciones/seguridad-incidentes.json) | Seguridad, vulneraciones, conservación, respaldos, autoridades, SABG | 34 |

## 20. Aviso: no es asesoría legal

Este documento y los archivos de `secciones/` son material de trabajo preparado con apoyo de IA a partir de fuentes primarias consultadas al 17 de octubre de 2026. **No son asesoría legal, fiscal ni contable** y no sustituyen la revisión de un abogado y de un contador con cédula en México. Las leyes, reglamentos, criterios de autoridad y términos de terceros cambian: antes de publicar, verifique cada fuente en su versión vigente. Los textos propuestos deben llevar la leyenda «Documento base preparado con apoyo de IA» hasta que un abogado los apruebe, y ninguna versión no revisada debe desplegarse en producción.

