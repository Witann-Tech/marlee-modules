# Conciliación de efectivo POS con proveedores — Odoo 19

Módulo independiente: `witann_pos_cash_vendor_reconcile`. Depende de `point_of_sale`
y `account`; no requiere los módulos de suscripciones.

Desplegado en producción el 23 de noviembre de 2026, versión `19.0.1.1.0`.
Ver el [reporte productivo](tests/PRODUCTION_RESULTS_2026-11-23.md), el
[reporte de matrices y sucursales en staging](tests/STAGING_BRANCHES_2026-11-23.md)
y la [validación inicial de 1.0.0](tests/STAGING_RESULTS_2026-11-23.md).

## Uso

1. Instalar el módulo en Odoo 19.
2. Registrar la salida manual de efectivo en el POS mediante el flujo habitual.
3. Entrar como usuario de Contabilidad en **Proveedores → Salidas de efectivo POS**,
   **POS → Informes → Salidas de efectivo a proveedores**, o abrir la sesión y
   pulsar **Efectivo a proveedores**.
4. Abrir una salida pendiente y pulsar **Conciliar con proveedor**.
5. Activar en el selector de empresas la matriz y las sucursales involucradas.
   Elegir proveedor y facturas publicadas. Ajustar los importes hasta asignar
   exactamente el total de la salida y confirmar.

Una salida puede aplicarse a varias facturas del mismo proveedor; una factura puede
recibir varias salidas. Una aplicación menor que el saldo deja la factura con pago
parcial. Solo el saldo completamente conciliado produce el estado nativo `paid`.
Se admiten sesiones abiertas y cerradas y salidas históricas que sigan en suspenso.
Desde la versión `19.0.1.1.0` se permiten conciliaciones entre la matriz y sus
sucursales, o entre sucursales de una misma matriz, usando la jerarquía nativa
`res.company.root_id`. Esta regla se aplica a cualquier empresa, sin nombres o
IDs fijos. La salida conserva su sucursal y la factura conserva su empresa.
La versión `19.0.1.1.1` elimina los valores predeterminados del asistente al
ejecutar la conciliación y su reversión. Así, los asientos nativos de impuestos
por pago no heredan una referencia incorrecta a la salida de caja de la sucursal.

## Contabilidad y trazabilidad

La salida ya acredita caja. El módulo sustituye su contrapartida de suspenso por
partidas por pagar y las concilia con las facturas mediante `account.move.line.reconcile()`.
No registra otro retiro ni crea otro pago. Los impuestos de flujo de efectivo
generan sus asientos fiscales mediante el mecanismo nativo de Odoo.
Conserva la partida de caja original,
importe, fecha, motivo, sesión y contacto original del movimiento (que puede
identificar al cajero). El proveedor queda en la contrapartida por pagar.

Las facturas relacionadas y el estado se derivan de las conciliaciones reales.
El asiento de la salida y las facturas reciben notas con el usuario, importe,
sesión y referencia.
**Deshacer conciliación** utiliza el mecanismo nativo para reabrir los saldos y
restaurar el suspenso, sin reingresar efectivo. También se refleja una anulación
realizada desde la interfaz contable nativa. Una salida vinculada a facturas no
puede eliminarse directamente desde el POS.

## Alcance y controles

- Solo usuarios de `account.group_account_user`; se mantienen las reglas de
  acceso contables y multiempresa, sin `sudo()` en el proceso de conciliación.
  Este grupo recibe acceso de lectura a sesiones y configuraciones POS, sin
  permisos para crearlas, modificarlas ni eliminarlas.
- Facturas publicadas del mismo proveedor comercial, la misma empresa matriz
  (incluidas sus sucursales) y moneda. Las cuentas por pagar deben estar
  disponibles para la sucursal de la salida. Se conservan las reglas de acceso
  y la selección de empresas activas; no se cruzan empresas matrices distintas.
  Importes positivos, sin duplicados, sobrepagos ni diferencias.
- Primera versión limitada a la moneda de la empresa. No realiza conversiones,
  anticipos, ajustes por diferencia, asignaciones a varios proveedores ni deja
  parte de una salida sin asignar.
- Salidas con destino contable ya asignado (gastos, reembolsos de clientes o
  diferencias de caja) se muestran para revisión y no se reaplican.
- Se respetan los bloqueos fiscales y asientos protegidos de Odoo; no se
  restablecen asientos a borrador ni se omiten controles de integridad.
- Se versionan las partidas contables antes de validar saldos para que Odoo
  reintente las solicitudes concurrentes con datos vigentes.
- No crea `account.payment` ni documentos fiscales de pago adicionales.

## Validación

La suite ORM está en `tests/test_cash_vendor_reconcile.py` y se ejecuta con:

```sh
odoo -d BASE_LOCAL_DE_PRUEBAS -i witann_pos_cash_vendor_reconcile \
  --test-enable --test-tags=/witann_pos_cash_vendor_reconcile \
  --without-demo --stop-after-init --no-http
```

Usar una base desechable, no una base operativa.

Para ejecutar instalación, suite ORM y concurrencia en contenedores locales
aislados de Odoo/PostgreSQL, desde la raíz del repositorio:

```sh
bash tests/run_cash_vendor_isolated.sh
```

El script no expone puertos, usa datos ficticios y elimina sus contenedores y red
al terminar. Imprime la carpeta temporal que contiene los registros completos.

Validado localmente el 23 de noviembre de 2026 con Odoo `19.0-20260817` y
PostgreSQL 16: **19 pruebas funcionales sin fallas y dos escenarios concurrentes
aprobados**. Los escenarios fuerzan lecturas simultáneas de una misma salida
contra dos facturas y de dos salidas contra una misma factura; en ambos solo una
operación se aplica y la otra se rechaza al reintentar con saldos actualizados.
También se validaron la instalación de las vistas y el formulario con sus
valores automáticos mediante el framework nativo de Odoo. No se instaló el módulo
en ninguna base operativa.
