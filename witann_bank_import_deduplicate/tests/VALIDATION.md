# Validación técnica y pruebas

## Resultado local — 12 de octubre de 2026

- 32 pruebas del lector/clasificador aprobadas, incluyendo CSV/XLSX reales,
  fechas, importes, CUENTA ignorada/opcional, MXP/MXN, conflictos, repeticiones
  y 280 filas XLSX con CUENTA vacía, numérica, CLABE y errores/fórmulas ignorados.
- Sintaxis Python, XML y archivos del manifiesto verificados. El script de
  concurrencia inicia y muestra su ayuda sin requerir bibliotecas adicionales.
- 24 pruebas ORM preparadas, **sin ejecutar**: no hay Odoo ni PostgreSQL locales.
  La prueba RPC simultánea y los tiempos contables también están pendientes.
- Corrección local 19.0.1.0.1; las pruebas ORM y RPC quedan pendientes de staging.

## Permisos e identidad

La lectura de `ir.model.data` requiere elevación para un contador normal en
Odoo 19. La consulta se limita al modelo, módulo `__import__` y nombres exactos.
Las comprobaciones de existencia en movimientos se limitan al diario/empresa
previamente autorizados; se reponen el entorno y permisos del usuario antes de
leer los campos del candidato. Un registro oculto por reglas bloquea la operación
en vez de clasificarse como nuevo. No se crean ni actualizan asientos con `sudo`.

La búsqueda histórica usa exclusivamente `__import__.MOVIMIENTO`, sin CUENTA
ni prefijos de cuenta, conforme a la aclaración del usuario sobre su histórico.
El módulo `__import__` se contrastó con el importador estándar. Varios registros
para una identidad o un registro que reclama varias identidades producen
conflicto. La suite ORM cubre históricos sin cuenta, un diario con CLABE y
un diario sin cuenta bancaria configurada; no se ejecutó en este entorno.

## Transacciones


`witann_bank_movement` tiene índice y restricción SQL
`UNIQUE(journal_id, witann_bank_movement)` con la API `models.Constraint` de
Odoo 19. Los registros antiguos con NULL siguen permitidos; el campo es
`copy=False`. No se sobrescriben `load`, `write`, `base_import` ni conciliación.

La creación de todos los nuevos se hace en una llamada ORM por lote dentro de un
savepoint. Si otro proceso insertó la misma identidad, se revierte todo el lote,
incluidos asientos/líneas, y se pide analizar de nuevo en una petición nueva.
No se intenta releer dentro del snapshot obsoleto de PostgreSQL. Errores de
serialización/deadlock se propagan al servicio de reintentos nativo de Odoo.
No hay commits manuales, importaciones parciales ni creación durante el análisis.
Si el ORM nativo ajusta fecha o importe al publicar, se revierte el lote con un
error que pide revisar el período/configuración; no se altera silenciosamente
la identidad financiera del archivo.

## Pruebas y estado de validación

Desarrollado localmente por indicación del usuario. En este entorno no están
instalados Odoo, Enterprise ni PostgreSQL. Se verificaron las APIs y XML IDs
contra las fuentes oficiales de la rama `19.0`, **no contra la instalación de
CloudPepper**. El usuario instaló la versión inicial en staging; esta corrección
no se ha probado contra esa instalación. No se ha desplegado en producción.

Pruebas locales del lector y clasificador (requieren `openpyxl`):

```bash
python3 -m unittest discover -s tests/standalone -p test_bank_import.py -v
```

La suite ORM cubre primera carga y reimportación sin ninguna llamada de
creación/escritura/borrado contable; traslapes; análisis sin efectos contables;
reconciliaciones parciales/full y snapshots de tablas; conflictos y repeticiones;
diarios independientes; IDs históricos y referencias inválidas; permisos y
multiempresa; restricción única y carrera reproducida después de la consulta,
con reversión completa y cursor utilizable. Incluye 280 creaciones, 280 omisiones
y traslape de 140 filas; registra tiempos únicamente cuando se ejecuta en Odoo.

Ejecutar en una **copia desechable de staging** con la misma revisión de Odoo y
addons, usando las rutas/configuración reales del servicio:

```bash
odoo-bin -c /ruta/real/odoo.conf -d COPIA_STAGING \
  -i witann_bank_import_deduplicate --test-enable \
  --test-tags /witann_bank_import_deduplicate --stop-after-init
```

Si ya está instalado, usar `-u` en lugar de `-i`. La suite contable utiliza los
fixtures oficiales de `account`; revisar que el plan contable de prueba requerido
por `AccountTestInvoicingCommon` esté instalado y que no aparezcan tests omitidos.

La prueba de dos transacciones RPC reales se ejecuta por separado contra esa
copia, en un diario bancario configurado **vacío**, con credenciales de contador:

```bash
python3 witann_bank_import_deduplicate/scripts/staging_concurrency.py \
  --url https://HOST-STAGING --db COPIA_STAGING --login CONTADOR \
  --journal ID_DIARIO_PRUEBAS --disposable-staging
```

Pide la clave sin mostrarla (alternativamente `WITANN_STAGING_API_KEY`), ejecuta
dos importaciones simultáneas de 280 filas y dos traslapadas, comprueba 420
identidades/asientos únicos y reporta tiempos de RPC, incluyendo reintentos.
Conserva esas 420 operaciones en la copia desechable; no borra contabilidad.
La prueba determinista ORM ejercita la colisión exacta aunque el planificador
serialice las llamadas RPC. No se afirma rendimiento de Odoo hasta medirlo allí.

Antes de instalar en staging: comprobar los campos `journal_id`, `company_id`,
`date`, `amount`, `ref` y `payment_ref`; inspeccionar
los módulos/nombres/modelos/res_id reales en `ir.model.data`; verificar ambas
herencias de vistas con las personalizaciones Enterprise instaladas. Después:
ejecutar la suite, prueba concurrente y una reimportación de un movimiento
conciliado del histórico, comparando IDs y valores de asiento/líneas/conciliaciones.

Fuentes consultadas: [movimientos bancarios](https://github.com/odoo/odoo/blob/19.0/addons/account/models/account_bank_statement_line.py),
[asiento y referencia](https://github.com/odoo/odoo/blob/19.0/addons/account/models/account_move.py),
[formulario del diario](https://github.com/odoo/odoo/blob/19.0/addons/account/views/account_journal_views.xml),
[tablero del diario](https://github.com/odoo/odoo/blob/19.0/addons/account/views/account_journal_dashboard_view.xml),
[restricciones SQL](https://github.com/odoo/odoo/blob/19.0/odoo/orm/table_objects.py),
[importación estándar](https://github.com/odoo/odoo/blob/19.0/odoo/orm/models.py),
[reintentos transaccionales](https://github.com/odoo/odoo/blob/19.0/odoo/service/model.py).
