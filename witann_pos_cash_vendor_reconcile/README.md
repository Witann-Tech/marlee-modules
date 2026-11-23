# Conciliación de efectivo POS con proveedores — Odoo 19

Módulo independiente: `witann_pos_cash_vendor_reconcile`. Depende de `point_of_sale`
y `account`; no requiere los módulos de suscripciones.

Actualizado en staging y producción el 23 de noviembre de 2026, versión `19.0.1.1.1`.
Ver el [reporte del hotfix de impuestos por pago](tests/CASH_BASIS_HOTFIX_2026-11-23.md),
el [reporte productivo inicial](tests/PRODUCTION_RESULTS_2026-11-23.md), el
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

## Efectivo reservado para órdenes de compra (1.2.0)

1. Registrar la salida de efectivo habitual y abrirla desde **Salidas de efectivo POS**.
2. Pulsar **Vincular con OC** y elegir una orden confirmada de la misma matriz
   y en la moneda de la salida. Se reserva el importe completo de la salida.
3. Crear la factura de proveedor desde la OC, o incorporar sus líneas mediante
   el mecanismo nativo de Compras. Mientras esté en borrador, no se aplica efectivo.
4. Al publicar la factura, se concilia automáticamente el menor importe entre
   el efectivo reservado disponible, el saldo de la factura y sus líneas de esa OC.
5. Si quedan fondos, continúan reservados para otras facturas de la OC. Si falta
   efectivo, la factura conserva el saldo pendiente. Los estados y montos se ven
   tanto en la salida como en la pestaña **Efectivo POS** de la OC.

Se admiten varias salidas para una OC y facturas parciales. Las reservas se
consumen por orden de creación; las facturas de una operación por fecha e ID.
Una factura que mezcla órdenes o conceptos ajenos recibe como máximo el importe
atribuible a las líneas de cada OC vinculada. El texto de origen o referencia,
por sí solo, no establece una relación de compra.

La vinculación no aplica pagos a facturas ya publicadas. Para ellas, o después
de deshacer aplicaciones, usar **Aplicar a facturas publicadas** desde la salida
o la pestaña de la OC. La acción es idempotente.

**Deshacer conciliación** revierte las aplicaciones de esa salida y devuelve
todo su efectivo a la reserva. Para cambiarla de destino, deshacer primero las
aplicaciones y pulsar **Desvincular OC**. Se conserva el historial; las salidas
con historial de compra no se eliminan. Se debe desvincular antes de cambiar
proveedor, moneda o empresa de la OC, o cancelarla. Una factura con efectivo
de OC aplicado debe deshacerse desde la salida antes de pasar a borrador.

La matriz y las sucursales deben estar activas, y el usuario que publica debe
tener permisos contables para aplicar su efectivo. Si hay una reserva que no
puede aplicarse, la publicación falla dentro de la misma transacción, sin dejar
la factura publicada con un pago omitido. Los totales almacenados de la reserva
se muestran en la OC bajo sus reglas de empresa; aplicar o liberar los fondos
siempre comprueba acceso a los movimientos reales de caja, sin escrituras elevadas.

La OC no puede recibir reservas superiores a su importe total. No se generan
pagos adicionales, retiros adicionales ni asientos de anticipo al vincular.
Se mantiene en suspenso el efectivo pendiente y se reclasifica únicamente el
importe aplicado al publicarse las facturas, con impuestos por pago nativos.

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
- Limitado a la moneda de la empresa. No realiza conversiones, documentos de
  anticipo, ajustes por diferencia ni asignaciones a varios proveedores.
  La conciliación directa distribuye la salida completa; el flujo de OC
  permite conservar un remanente reservado entre facturas parciales.
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

Validación inicial local del 23 de noviembre de 2026 con Odoo `19.0-20260817` y
PostgreSQL 16: **19 pruebas funcionales sin fallas y dos escenarios concurrentes
aprobados**. Los escenarios fuerzan lecturas simultáneas de una misma salida
contra dos facturas y de dos salidas contra una misma factura; en ambos solo una
operación se aplica y la otra se rechaza al reintentar con saldos actualizados.
También se validaron la instalación de las vistas y el formulario con sus
valores automáticos mediante el framework nativo de Odoo. No se instaló el módulo
en ninguna base operativa durante esa validación inicial. La versión `19.0.1.1.1`
amplía la suite a **26 pruebas funcionales**, además de los dos escenarios
concurrentes; aprobados localmente y con los runtimes de staging y producción.
