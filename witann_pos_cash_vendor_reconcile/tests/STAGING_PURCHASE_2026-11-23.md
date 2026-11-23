# Efectivo POS reservado para órdenes de compra: validación de staging

Versión `19.0.1.2.0`, 23 de noviembre de 2026.
Implementación funcional: `88994b4b1c6ff7498b36ab8bf242111a8a2cf635`.
Revisión de presentación: `355fce70ad14bd3ded01c74bc5186469f3727137`.

**Resultado: implementado, desplegado y validado en staging.**

## Flujo implementado

1. Abrir una salida pendiente en **Salidas de efectivo POS**.
2. Pulsar **Vincular con OC**, elegir una orden confirmada y reservar la salida completa.
3. Crear las facturas desde la OC o incorporar sus líneas mediante Compras.
4. Publicar la factura. En esa misma transacción se aplica automáticamente el efectivo disponible.
5. Consultar el importe aplicado y el remanente en la salida o en **OC → Efectivo POS**.

Una salida se reserva para una OC; una OC admite varias salidas. Se aplican
reservas por orden de creación. En una publicación por lotes, las facturas se
procesan por fecha e ID. Solo se aplican facturas publicadas del proveedor de
la OC, relacionadas por `purchase_line_id`; el texto de origen no es suficiente.

Si una factura es menor que la reserva, queda efectivo para facturas posteriores.
Si la reserva es menor que la factura, esta conserva su saldo pendiente. En
facturas con varias órdenes o conceptos ajenos, cada reserva está limitada al
importe atribuible a sus líneas de compra. No se permite reservar por encima
del total de la OC ni asignar dos veces una salida.

Se conserva el flujo directo contra facturas de la versión anterior. La nueva
reserva no crea un retiro, pago contable ni asiento de anticipo adicional:
mantiene en suspenso el importe pendiente y reclasifica lo aplicado.

Para facturas ya publicadas, o después de deshacer aplicaciones, se ofrece
**Aplicar a facturas publicadas**. **Deshacer conciliación** restaura la reserva;
**Desvincular OC** la libera si no hay aplicaciones. Se conserva el historial.
Antes de cancelar la OC o cambiar proveedor, moneda o empresa deben liberarse
sus reservas. Una factura con efectivo aplicado debe deshacerse desde la salida
antes de devolverla a borrador.

## Alcance y permisos

- Cualquier matriz y sus sucursales, mediante la jerarquía nativa de empresas.
- Moneda de empresa; sin conversión de divisas.
- Matriz y sucursales involucradas activas en el selector de empresas.
- Usuario de Contabilidad con acceso a los documentos reales de caja.
- Facturas en borrador sin aplicación de efectivo.
- Sin escrituras elevadas durante reserva, aplicación o reversión.
- Impuestos por pago, bloqueos fiscales y conciliaciones nativas de Odoo.
- Si una reserva no puede aplicarse, la publicación falla de forma atómica;
  no se omite silenciosamente el pago de la factura publicada.

Los totales almacenados de las reservas se muestran en la OC bajo sus reglas
de empresa. Aplicar o liberar fondos exige acceso a la sucursal de caja.
Compras mantiene sus permisos nativos; confirmar y cancelar una OC sin reserva
se incluyó como regresión.

## Pruebas automatizadas

| Gate | Pruebas funcionales | Concurrencia | Resultado |
| --- | ---: | ---: | --- |
| Odoo 19 local aislado | 46 | 5 escenarios | 0 fallas y 0 errores |
| Runtime Enterprise de staging, base nueva | 46 | 5 escenarios | 0 fallas y 0 errores |

La suite conserva 26 pruebas anteriores y agrega 20 de Compras. Cubre reserva
sin factura, borrador, aplicación al publicar, facturación parcial, varias
salidas de sucursales, otra matriz con su sucursal, facturas mixtas, límites
por líneas de OC, impuestos por pago, reversión, reaplicación, cancelación,
reasignación con historial, permisos, empresas inactivas, cambios RPC y
proveedor incorrecto. También verifica formulario y vista heredada de Compras.

Los cinco escenarios concurrentes usan transacciones reales:

1. Una salida contra dos facturas.
2. Dos salidas contra una factura.
3. Dos reservas contra el presupuesto de una OC.
4. Una salida intentando reservarse para dos OC.
5. Dos facturas publicadas simultáneamente con una sola reserva disponible.

Los reintentos por serialización son esperados. En el último caso se publican
ambas facturas y solo una recibe el efectivo; la otra conserva su saldo.
El gate del servidor duró 163.54 segundos y eliminó su base `pos_cash_qa`.
No se ejecutó la suite sobre la base operativa de staging.

Después de los gates se ajustaron cuatro etiquetas de campos en dos vistas.
La comparación estructural XML confirma que solo cambiaron atributos `string`;
la lógica, dominios, permisos y código contable coinciden con el candidato probado.

## Prueba operativa en la interfaz de staging

Datos ficticios identificados como `QA PURCHASE CASH 20261123`.
Se creó primero la OC y la salida; la reserva se realizó desde el asistente.
Las facturas se crearon después desde Compras y se publicaron usando
**Confirmar** en la interfaz, sin ejecutar la acción manual de aplicación.

| Paso | Resultado verificado |
| --- | --- |
| OC matriz | `P00533`, id 533, Comercializadora Marlee, total $5,800 |
| Salida de sucursal | `QPOC/2026/00001`, id 4715, Spinbike El Dorado, $3,485 |
| Sesión POS | Cerrada, id 2264 |
| Después de vincular | Aplicado $0; reservado $3,485; sin facturas |
| FP 1 | `QPO1/2026/11/0001`, id 11671, total $2,320 |
| Al publicar FP 1 | Pagada; reserva restante $1,165 |
| FP 2 | `QPO1/2026/11/0002`, id 11673, total $3,480 |
| Al publicar FP 2 | Aplicados $1,165; saldo pendiente $2,315; pago parcial |
| Salida al terminar | Aplicados $3,485; reserva restante $0 |
| IVA por pago | Dos asientos nativos, reconocimiento total $480.69 |
| Repetir aplicación | Sin pagos ni asientos fiscales duplicados |
| Caja | Mismo asiento 11669, partida de liquidez 30791, importe y saldo de sesión |
| Pagos `account.payment` nuevos | 0 |
| Datos anteriores a la prueba | Huellas completas idénticas en diez tablas |

Los asientos de impuestos conservan la empresa matriz y no heredan la línea
de caja de la sucursal. Los documentos ficticios permanecen en staging para
revisión. No se aplicaron pagos a documentos reales del cliente.

## Despliegue e integridad

Solo se actualizó la rama y la instancia de staging. El módulo agrega la
dependencia de Compras, ya instalada en este ambiente. Las versiones de los
otros módulos se conservaron.

Se detuvo staging y se tomó respaldo antes de actualizar fuentes y esquema.
La ventana inicial de despliegue fue de 107.94 segundos, desde las 17:47:18
hasta las 17:49:06, hora de Ciudad de México.

Los conteos y huellas de todos los campos existentes coincidieron en nueve
tablas: asientos, apuntes, pagos, conciliaciones parciales/completas, sesiones,
pagos POS, órdenes y líneas de compra. En líneas de caja también coincidieron
todos los campos existentes salvo `write_uid` y `write_date`: la inicialización
de los campos calculados nuevos actualizó esa auditoría. Los importes, empresas,
fechas de movimiento, relaciones y estados previos se conservaron.

El módulo inició con cero reservas; no vinculó salidas históricas ni aplicó
pagos a facturas existentes durante la actualización.

Respaldo conservado exclusivamente en el servidor:
`/tmp/pos-cash-purchase-staging-20261123/deployment/before-deployment.dump`.
Tamaño 271,739,118 bytes, permisos `0600`, catálogo validado por `pg_restore --list`.
No se descargaron bases ni respaldos.

## Cierre

El ajuste final de etiquetas se registró y compiló correctamente en ambas
vistas. Su actualización CLI duró 28.75 segundos; antes y después coincidieron
las huellas y conteos completos de once tablas, incluida la reserva de QA.
No cambió ningún campo financiero, de auditoría o de trazabilidad en esa fase.

En la revisión de salud de las 17:55:59, hora de Ciudad de México:

- Staging activo, `/web/login` HTTP 200 y módulo instalado `19.0.1.2.0`.
- Cero líneas ERROR/CRITICAL nuevas entre el reinicio final y ese cierre.
- Código desplegado coincidente con la revisión final; código contable
  coincidente con el gate y diferencias de vistas limitadas a etiquetas.
- Core coincidente con las huellas del gate Enterprise.
- Base de QA eliminada; cero bases temporales `pos_cash_qa` restantes.
- Factura real id 6518 con saldo $4,380 y salida real id 3933 por -$3,485
  todavía pendiente, sin pagos aplicados durante las pruebas.
- Producción activa, HTTP 200, módulo `19.0.1.1.1`; mismo PID y hora de inicio
  que antes del despliegue. La versión `1.2.0` no se promovió a `main`.

La pestaña **Efectivo POS** de la OC se abrió en la interfaz después de la
actualización final: muestra Spinbike El Dorado, reservado $3,485,
aplicado $3,485 y por aplicar $0.

Acceso al caso ficticio:
[salida de efectivo](https://staging-portal.spinbike.mx/odoo/action-1546/4715)
y [orden de compra](https://staging-portal.spinbike.mx/odoo/purchase.order/533).
