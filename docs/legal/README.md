# Carpeta legal de GuauWoow

Fecha de corte de la investigación: **17 de octubre de 2026**. Material de trabajo en español de México para el dueño, el equipo, el abogado y el contador. **No es asesoría legal ni fiscal.**

## Por dónde empezar

| Archivo | Qué es | Para quién |
|---|---|---|
| [investigacion-legal-mx.md](investigacion-legal-mx.md) | Documento consolidado: resumen ejecutivo, marco legal vigente, páginas del centro legal, matriz de cumplimiento, modelo fiscal, calendario de retención, reglas, procedimientos, conflictos resueltos, datos del dueño y puntos para abogado y contador | Dueño, abogado, contador |
| [requisitos.json](requisitos.json) | Especificación legible por máquina: páginas (con contenidos mínimos y fundamento), requisitos de producto y de tienda, conservación, proveedores, datos del dueño, puntos legales, riesgos, reglas de comunicaciones, procedimientos de retiro y de vulneraciones, matriz, conflictos y fechas | Equipo de producto e ingeniería |
| [secciones/](secciones/) | Investigación detallada por dominio y por brecha, con citas, procedimientos y textos propuestos (un .md legible y un .json por sección) | Abogado y equipo |

## Secciones

| Sección | Tema | Hallazgos |
|---|---|---|
| [bienestar-animal.md](secciones/bienestar-animal.md) | Bienestar animal federal, CDMX, Edomex, Jalisco y NL; adopción, perdidos, denuncia | 35 |
| [buenas-practicas.md](secciones/buenas-practicas.md) | Estructura del centro legal, gobierno documental, transparencia | 50 |
| [comunicaciones-cookies.md](secciones/comunicaciones-cookies.md) | Cookies, banner, geolocalización, WhatsApp, correo, SMS, REPEP, OAuth | 32 |
| [consumidor-ecommerce.md](secciones/consumidor-ecommerce.md) | LFPC, NMX-COE, tienda, revocación, garantías, publicidad, PROFECO | 39 |
| [contenido-plataforma.md](secciones/contenido-plataforma.md) | Responsabilidad por contenido, derechos de autor, moderación, contratación electrónica, importación | 32 |
| [datos-personales.md](secciones/datos-personales.md) | LFPDPPP 2025, aviso, consentimiento, ARCO, encargados, fuentes indirectas, sanciones | 40 |
| [donativos.md](secciones/donativos.md) | Donativos, donatarias, CFDI de donativo, PLD, convenio con refugios | 29 |
| [fiscal-tienda.md](secciones/fiscal-tienda.md) | CFDI, IVA, régimen de plataformas, retenciones, PAC, liquidaciones | 34 |
| [gap-cobertura-estatal-bienestar-animal-y-ley-general.md](secciones/gap-cobertura-estatal-bienestar-animal-y-ley-general.md) | Ley General (no vigente) y 11 estados adicionales | 22 |
| [gap-custodia-fondos-transmisor-dinero-y-terminos-mercado-pago.md](secciones/gap-custodia-fondos-transmisor-dinero-y-terminos-mercado-pago.md) | Custodia de fondos, transmisor de dinero, Fintech, LFPIORPI, Términos de Mercado Pago | 16 |
| [gap-naturaleza-juridica-adopcion-y-cuotas.md](secciones/gap-naturaleza-juridica-adopcion-y-cuotas.md) | Adopción como donación con cargas, cuotas, venta digital, WhatsApp y Meta | 14 |
| [gap-nna-decreto-entornos-digitales-2026.md](secciones/gap-nna-decreto-entornos-digitales-2026.md) | Decreto NNA del 14-10-2026, verificación de edad, informe, contacto 24/7 | 12 |
| [gap-veterinarias-y-resenas.md](secciones/gap-veterinarias-y-resenas.md) | Clínicas, cédula, Google Places, reseñas, daño moral | 17 |
| [identidad-contratos.md](secciones/identidad-contratos.md) | Identidad del operador, contratos con refugios y casas de paso, PI, accesibilidad, seguros | 34 |
| [seguridad-incidentes.md](secciones/seguridad-incidentes.md) | Seguridad, vulneraciones, conservación, respaldos, autoridades, SABG | 34 |

## Cómo usar los archivos

1. Leer el **resumen ejecutivo** y las **fechas clave** del documento consolidado.
2. Entregar al equipo los **datos del dueño** (sección 17) y cargarlos en `app/legal/datos-legales.json`.
3. Enviar al abogado y al contador la sección 18 (**puntos de revisión**) junto con los archivos de `secciones/` que correspondan.
4. Ingeniería trabaja desde `requisitos.json` (`pages`, `product_requirements`, `shop_requirements`, `compliance_matrix`, `retention`).
5. Cada cambio normativo o de contrato de terceros se registra en la página de historial y se actualiza aquí con nueva fecha de corte.

## Convenciones

- **Prioridad:** obligatorio, recomendado, buena práctica. **Confianza:** alta, media, baja (media o baja requieren abogado).
- **Estado actual** de la matriz: lectura de `app/legal/` y del código el 17-10-2026; otro flujo edita el código en paralelo, así que hay que reconfirmar antes del lanzamiento.
- **Identificadores de hallazgos:** abreviaturas DP, CE, FT, DON, BA, CP, CC, SI, IC, BP, NNA, CF, AD, VET y EST (ver el documento consolidado).

## Aviso

Este documento y los archivos de `secciones/` son material de trabajo preparado con apoyo de IA a partir de fuentes primarias consultadas al 17 de octubre de 2026. **No son asesoría legal, fiscal ni contable** y no sustituyen la revisión de un abogado y de un contador con cédula en México. Las leyes, reglamentos, criterios de autoridad y términos de terceros cambian: antes de publicar, verifique cada fuente en su versión vigente. Los textos propuestos deben llevar la leyenda «Documento base preparado con apoyo de IA» hasta que un abogado los apruebe, y ninguna versión no revisada debe desplegarse en producción.

