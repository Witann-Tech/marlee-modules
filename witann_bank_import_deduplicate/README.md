# Witann Bank Import Deduplicate — Odoo 19

Importa únicamente movimientos bancarios nuevos mediante el ORM nativo.
Identidad estable: **diario + MOVIMIENTO**, con índice y restricción SQL única.
Los existentes se leen y omiten sin actualizarlos ni rellenar campos históricos.

## Instalación y uso

1. Agregar el repositorio al `addons_path` de CloudPepper y actualizar la lista
   de aplicaciones. Instalar **Witann Bank Import Deduplicate** en staging.
   Dependencias: `account` y `openpyxl`; sin servicios adicionales.
2. Configurar cuenta contable de banco, transitoria y moneda
   del diario. Si no tiene moneda específica, se usa la de su empresa.
3. Desde el menú del diario bancario en el tablero de Contabilidad, o desde su
   formulario, abrir **Importar movimientos sin duplicados**.
4. Adjuntar CSV/XLSX tal como lo entrega el banco, sin agregar IMPORTE, y pulsar
   **Analizar**. Revisar el detalle por fila; la fila 0
   señala errores generales. El análisis no crea asientos.
5. Pulsar **Importar nuevos**. Se vuelven a comprobar los existentes y se crean
   los nuevos por lote. Errores o conflictos bloquean todo el archivo. El resultado
   muestra leídas, creadas y omitidas y permite abrir los movimientos creados.

Requiere `account.group_account_basic`, permisos contables nativos y la empresa
activa. Una colisión concurrente revierte todo el lote y pide analizar de nuevo;
los errores de serialización siguen los reintentos normales de Odoo.

## Formato

Se aceptan todos los encabezados solicitados. Obligatorios: `FECHA`,
`MONEDA`, `MOVIMIENTO`, `DEPÓSITOS` y `RETIROS`. También se mantienen compatibles
los archivos anteriores que sólo tienen `IMPORTE` en lugar de depósitos/retiros.
Los acentos, mayúsculas y espacios de los encabezados se normalizan.

- `MOVIMIENTO` es texto, conservando ceros; nunca un ID interno de Odoo.
- `FECHA`: **DD/MM/AAAA** o fecha nativa de Excel. No se usa FECHA DE OPERACIÓN.
- El importe se calcula automáticamente como **DEPÓSITOS − RETIROS**: abonos
  positivos y cargos negativos. Vacío y `-` equivalen a cero en esas columnas.
  Si ambas existen, se ignora cualquier IMPORTE manual. Para archivos anteriores
  sin ambas columnas se usa IMPORTE; vacío, `-` o inválido allí produce error.
  Se aceptan números y `$18,872.11`; comparación/redondeo con precisión de moneda.
- CUENTA se ignora completamente y es opcional. No se consulta el número de
  cuenta ni la CLABE del diario; el destino es el diario seleccionado.
- MONEDA debe coincidir con el diario. MXP se reconoce como MXN.
- REFERENCIA se conserva en `ref`; ambas descripciones se combinan en
  `payment_ref`. SALDO es informativo y no modifica saldos ni importes.
- Repeticiones compatibles por fecha/importe se omiten; diferencias o identidades
  ambiguas bloquean el archivo. CSV UTF-8/BOM o CP1252; coma, punto y coma o tabulador.
  XLSX: una hoja con datos, sin fórmulas en campos utilizados. Límites: 10 MiB,
  10,000 filas, 100 columnas y 50 MiB descomprimidos. Se ignoran filas vacías.

## Contactos automáticos

La asignación es opcional e invisible: no agrega pasos, preguntas ni bloqueos.
Se buscan contactos existentes al importar, únicamente para movimientos nuevos.
Nunca se crean, modifican ni archivan contactos; las reimportaciones tampoco
rellenan el contacto de movimientos existentes.

- Se extraen nombres explícitos `CLIENTE`, `BENEF`, TEF y cobranza domiciliada
  desde DESCRIPCIÓN DETALLADA; no se adivina el contacto a partir del concepto.
  También se aprovecha el RFC aunque no haya nombre. Una contradicción entre
  la dirección del movimiento y el rol explícito descarta esa extracción.
- Primero se busca RFC exacto y único, normalizando espacios y prefijo MX.
  RFC genéricos, CURP, formatos o fechas inválidos se ignoran sin error. Esta
  comprobación es local y no consulta ni verifica la inscripción ante el SAT.
  Un RFC duplicado o una contradicción fuerte con el nombre dejan la línea sin
  contacto; no se fuerza una alternativa.
- Sin match por RFC, se comparan nombres normalizados y sus componentes.
  Se conservan las diferencias Ñ/N. Se admiten coincidencias exactas con al menos
  dos componentes útiles; para una diferencia pequeña se exigen al menos tres,
  dos componentes completos iguales, similitud global mínima de 96% y distancia
  mínima de 5 puntos frente al segundo candidato. No se usa coincidencia parcial
  por un solo nombre/apellido. RFC distintos conocidos descartan la asignación.
- Se leen sólo contactos comerciales activos y visibles para el usuario,
  compartidos o de la empresa del diario. Se excluyen direcciones de entrega,
  facturación y personas subordinadas a otra entidad comercial. No se usa sudo.
- La consulta se hace una vez por importación y los matches se reutilizan dentro
  de esa petición. Si hay más de 20,000 candidatos visibles, más de 1,000
  candidatos por nombre, falta de permisos o registros inaccesibles, se omite
  la asignación. Nunca se decide unicidad usando una lista truncada.
- Sin evidencia suficiente o con ambigüedad, se importa sin `partner_id`.
  El nombre explícito extraído se conserva en el campo nativo `partner_name`,
  como información. Repeticiones compatibles con datos de contacto distintos
  también se importan sin contacto y mantienen la deduplicación financiera.

## Histórico y verificación

Se reconocen exclusivamente IDs exactos `__import__.MOVIMIENTO` (por ejemplo
`__import__.31984`), verificando modelo, registro, diario, empresa,
fecha e importe. Un histórico sin identificador verificable **podría duplicarse**;
el asistente advierte esta limitación y no infiere identidad por fecha/importe.
Los prefijos y registros reales deben inspeccionarse en staging.

Versión 19.0.1.1.0: asignación automática y opcional de contactos existentes por
RFC/nombre. Se mantienen los importes automáticos y CUENTA ignorada.
Las APIs y vistas se contrastaron con la rama oficial Odoo 19. Las pruebas
locales CSV/XLSX pasan; pruebas ORM, conciliaciones y concurrencia real
quedan pendientes de staging. No se afirma rendimiento contable sin medirlo.
Véanse [pruebas y comandos de staging](tests/VALIDATION.md).
