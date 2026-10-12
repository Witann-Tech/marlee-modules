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
4. Adjuntar CSV/XLSX y pulsar **Analizar**. Revisar el detalle por fila; la fila 0
   señala errores generales. El análisis no crea asientos.
5. Pulsar **Importar nuevos**. Se vuelven a comprobar los existentes y se crean
   los nuevos por lote. Errores o conflictos bloquean todo el archivo. El resultado
   muestra leídas, creadas y omitidas y permite abrir los movimientos creados.

Requiere `account.group_account_basic`, permisos contables nativos y la empresa
activa. Una colisión concurrente revierte todo el lote y pide analizar de nuevo;
los errores de serialización siguen los reintentos normales de Odoo.

## Formato

Se aceptan todos los encabezados solicitados. Obligatorios: `FECHA`,
`MONEDA`, `MOVIMIENTO` y `IMPORTE`, o `DEPÓSITOS` y `RETIROS` si no hay `IMPORTE`.
Los acentos, mayúsculas y espacios de los encabezados se normalizan.

- `MOVIMIENTO` es texto, conservando ceros; nunca un ID interno de Odoo.
- `FECHA`: **DD/MM/AAAA** o fecha nativa de Excel. No se usa FECHA DE OPERACIÓN.
- IMPORTE tiene prioridad; vacío, `-` o inválido produce error. Sin esa columna
  se calcula DEPÓSITOS menos RETIROS; sólo allí vacío y `-` equivalen a cero.
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

## Histórico y verificación

Se reconocen exclusivamente IDs exactos `__import__.MOVIMIENTO` (por ejemplo
`__import__.31984`), verificando modelo, registro, diario, empresa,
fecha e importe. Un histórico sin identificador verificable **podría duplicarse**;
el asistente advierte esta limitación y no infiere identidad por fecha/importe.
Los prefijos y registros reales deben inspeccionarse en staging.

Versión 19.0.1.0.1: se elimina toda dependencia de CUENTA y de la cuenta bancaria
del diario, incluida la búsqueda histórica con prefijos de cuenta. Las APIs y
vistas se contrastaron con la rama oficial Odoo 19. Las pruebas locales CSV/XLSX
pasan; la instalación Enterprise, pruebas ORM, conciliaciones y concurrencia real
quedan pendientes de staging. No se afirma rendimiento contable sin medirlo.
Véanse [pruebas y comandos de staging](tests/VALIDATION.md).
