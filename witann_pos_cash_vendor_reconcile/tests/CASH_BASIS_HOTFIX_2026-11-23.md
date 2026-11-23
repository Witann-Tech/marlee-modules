# Corrección de conciliación entre matriz y sucursal con impuestos por pago

Fecha: 23 de noviembre de 2026. Versión `19.0.1.1.1`.
Commit del código: `8a345da3b4469d10ef9f84aef8124470847df0e5`.

**Resultado: corrección desplegada y validada en staging y producción.**

## Error y causa confirmada

El caso reportado corresponde a staging: factura `FACTU/2026/08/0001`
de Comercializadora Marlee y salida `CSH3/2026/01036` de Spinbike El Dorado
por $3,485. La factura utiliza el impuesto de compra 16% con exigibilidad
`on_payment`.

El contexto que abre el asistente contiene `default_statement_line_id`.
Ese valor alcanzaba la conciliación nativa y la creación automática de los
asientos de impuestos por pago. El asiento fiscal de la matriz heredaba
la referencia al movimiento de caja de la sucursal; Odoo rechazaba esa
referencia por inconsistencia de empresa.

Se reprodujo el mismo error en una base desechable antes de corregirlo.
Otra regresión detectó que, dentro de una misma empresa, el asiento fiscal
podía heredar silenciosamente la referencia incorrecta. Las pruebas
anteriores no cubrían impuestos por pago en el contexto del asistente.

La corrección utiliza `odoo.tools.clean_context` al entrar a la conciliación
y a su reversión; también coloca las facturas en el entorno limpio del
usuario que realiza la operación. Se conservan las empresas activas,
permisos y controles contables nativos. El asistente conserva su valor
predeterminado para abrirse correctamente.

## Pruebas automatizadas

| Entorno aislado | Suite funcional | Concurrencia | Base temporal |
| --- | --- | --- | --- |
| Docker local Odoo 19 | 26 aprobadas; 0 fallas, 0 errores | 2 escenarios aprobados | Contenedores eliminados |
| Runtime de staging y Enterprise | 26 aprobadas; 0 fallas, 0 errores | 2 escenarios aprobados | Eliminada |
| Runtime de producción y Enterprise | 26 aprobadas; 0 fallas, 0 errores | 2 escenarios aprobados | Eliminada |

Los gates del servidor duraron 124.53 y 124.47 segundos respectivamente.
Se ejecutaron sobre una base nueva `pos_cash_qa`, sin HTTP ni crons.
No se ejecutó la suite sobre las bases operativas.

Los dos casos nuevos verifican pago de factura matriz con impuestos desde
una sucursal, generación del asiento fiscal en la empresa correcta,
ausencia de `statement_line_id` en ese asiento, reversión y reaplicación,
y reconocimiento proporcional de impuestos en un pago parcial dentro de
una misma empresa. El helper de las pruebas ahora utiliza el contexto real
devuelto por la acción del asistente.

Las pruebas concurrentes impiden reutilizar una salida y sobrepagar una
factura. Las excepciones de serialización en sus logs son esperadas.

## Integración en staging con configuración fiscal existente

Se utilizaron documentos ficticios identificados como `QA CASH TAX 20261123`
y el impuesto 16% por pago existente en Comercializadora. Se ejecutó la
conciliación como administrador normal, sin modo superusuario.

| Dato | Resultado |
| --- | --- |
| Factura ficticia de Comercializadora | `QT1/2026/11/0001`, id 11663, total $5,800 |
| Salida ficticia de Spinbike El Dorado | id 4714, asiento 11664, importe $3,485 |
| Sesión | Cerrada |
| Aplicación | Conciliada; factura pagada parcialmente |
| Saldo pendiente | $2,315 |
| IVA reconocido por aplicación | $480.69 |
| Deshacer y reaplicar | Aprobado; saldo restaurado a $5,800 y después a $2,315 |
| Asientos fiscales y reversión | Empresa matriz correcta; sin vínculo a la línea de caja |
| Caja | Mismo asiento, importe, fecha, motivo y saldo de sesión |
| Pagos `account.payment` nuevos | 0 |
| Documentos anteriores a la prueba | Huellas idénticas en las ocho tablas verificadas |

La interfaz muestra la salida de Spinbike conciliada con la factura ficticia
y el saldo parcial correcto. Los documentos ficticios permanecen identificados
en staging para revisión.

Los documentos reales reportados no se conciliaron: la factura id 6518
conserva saldo $4,380 y la salida id 3933 conserva importe -$3,485 y estado
pendiente. No se encontraron asientos de impuestos previos con una referencia
a línea de caja en ninguno de los dos ambientes.

## Actualización de staging

Repositorio actualizado desde CloudPepper y módulo actualizado por CLI.
Interrupción controlada de respaldo, actualización y arranque: 55.37 segundos.
Las huellas y conteos completos de asientos, apuntes, líneas de caja,
pagos, conciliaciones parciales/completas, sesiones y pagos POS coincidieron
antes y después. Producción mantuvo su proceso activo durante esta operación.

## Validación productiva

Se promovió el mismo commit a `main` y CloudPepper actualizó el repositorio
productivo. Se completó una actualización CLI controlada del módulo con
respaldo previo. La ventana CLI terminó a las 13:57 del 23 de noviembre,
hora de Ciudad de México; duró 59.54 segundos incluyendo respaldo y arranque.

| Control | Resultado |
| --- | --- |
| Módulo instalado / disponible | `19.0.1.1.1` / `19.0.1.1.1` |
| Código desplegado | SHA-256 de código, XML y seguridad coincidentes con el candidato probado |
| Core | Huellas coincidentes con las usadas en cada gate |
| Otros módulos | Versiones instaladas conservadas |
| Menús y vistas | Verificados por ORM |
| Asistentes sin guardar | Padel, El Dorado y Santa Mónica; matriz resuelta correctamente |
| Navegador | Módulo instalado visible después de recargar; sin errores en la consola observada |
| Servicios staging / producción | Activos; `/web/login` HTTP 200 |
| Logs después de actualizar | 0 líneas ERROR/CRITICAL hasta el cierre de salud de las 13:57:36 |
| Bases temporales restantes | 0 |
| Pagos reales aplicados durante QA productivo | 0 |

La validación funcional con pagos se ejecutó en las bases desechables y con
documentos ficticios en staging. En producción se verificaron vistas y
asistentes por lectura, sin crear documentos ni aplicar conciliaciones.

Con el servicio detenido, se compararon todos los campos y conteos antes
y después de la actualización CLI:

| Tabla | Registros | Integridad |
| --- | ---: | --- |
| `account_move` | 12,013 | Huella completa idéntica |
| `account_move_line` | 33,117 | Huella completa idéntica |
| `account_bank_statement_line` | 4,851 | Huella completa idéntica |
| `account_payment` | 3,205 | Huella completa idéntica |
| `account_partial_reconcile` | 4,866 | Huella completa idéntica |
| `account_full_reconcile` | 4,856 | Huella completa idéntica |
| `pos_session` | 1,503 | Huella completa idéntica |
| `pos_payment` | 18,310 | Huella completa idéntica |

El respaldo previo a la actualización CLI permanece en el servidor:
`/tmp/pos-cash-tax-20261123/production-upgrade/before-upgrade.dump`.
Tamaño 294,142,725 bytes, modo `0600`, catálogo validado con `pg_restore --list`.
También se conservó respaldo de staging. No se descargaron bases ni respaldos.
Staging conservó su proceso activo durante la actualización de producción.

## Uso después de actualizar

Recargar Odoo, cerrar y volver a abrir el asistente. Activar la matriz y
las sucursales involucradas; seleccionar proveedor, facturas e importes
y conciliar mediante el flujo habitual. El cambio aplica a cualquier
empresa y sus sucursales de la misma matriz.

La asociación con órdenes de compra queda fuera del alcance de este hotfix.
