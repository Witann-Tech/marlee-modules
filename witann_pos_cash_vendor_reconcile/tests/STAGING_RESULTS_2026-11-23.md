# Reporte de despliegue y pruebas en staging

**Resultado: aprobado en los escenarios ejecutados.** El módulo quedó instalado
y disponible en [staging-portal.spinbike.mx](https://staging-portal.spinbike.mx/odoo/action-1546).
Las pruebas terminaron el 23 de noviembre de 2026, aproximadamente a las 10:27
de Ciudad de México. No se desplegó en producción.

## Versión desplegada

| Elemento | Resultado |
| --- | --- |
| Módulo | `witann_pos_cash_vendor_reconcile` |
| Versión instalada | `19.0.1.0.0`, estado `installed` |
| Rama | `staging` |
| Commit del código | `3f90e3fc017265b7f61b0fcb1de57270f4828c88` |
| Runtime | Odoo 19, Community `29cf86bd012cd3bf2a145a4ae3c6266f2b6f9034`, Python 3.13, addons Enterprise del servidor |
| Correspondencia de fuentes | Los 15 archivos del módulo desplegado coinciden por SHA-256 con el commit local |
| Base destino | Staging neutralizado; se conservó `database.is_neutralized=true` |
| Instalación | 26.89 segundos; reinicio exclusivo del servicio staging |

No se actualizaron Odoo core, Enterprise, Contabilidad, POS, suscripciones ni
Access API. La rama `main` permaneció en `7795fd7`. La actualización del
repositorio desde CloudPepper incorporó el nuevo módulo y documentación.

## Pruebas automatizadas con el runtime de staging

Se creó una base vacía y desechable `pos_cash_qa` en el servidor, con el mismo
intérprete y rutas de addons de staging. No se ejecutó `--test-enable` sobre la
base de staging que contiene los datos clonados.

| Prueba | Resultado |
| --- | --- |
| Suite ORM del módulo | **19 aprobadas, 0 fallas, 0 errores** |
| Mismo retiro contra dos facturas, en transacciones simultáneas | Una aplicación aceptada; la otra se reintenta y rechaza |
| Dos retiros contra una misma factura, en transacciones simultáneas | Una aplicación aceptada; la otra se reintenta y rechaza por saldo insuficiente |
| Limpieza de la base temporal | Eliminada; verificación final: no existe |

La suite cubre pago total y parcial, varias facturas, varias salidas para una
factura, vencimientos, reversión y reaplicación, reenvíos repetidos, duplicados,
importes inválidos, facturas ya pagadas, proveedor incorrecto, documentos en
borrador y de cliente, moneda incompatible, multiempresa, permisos de cajero y
contador, bloqueos fiscales, eliminación de salidas conciliadas, valores
automáticos del formulario y sesiones cerradas.

Las dos excepciones de serialización del log concurrente son esperadas y forman
parte de la prueba: acreditan la colisión real y la revalidación de saldos.

## Prueba funcional en navegador sobre staging

Se usó el proveedor **QA POS CASH 20261123 PROVEEDOR**, diarios exclusivos QA y
una sesión POS ficticia cerrada, ID `2259`, en Spinbike El Dorado, moneda MXN.
No se aplicaron salidas históricas a facturas reales.

| Escenario | Resultado observado |
| --- | --- |
| Acceso desde Contabilidad → Proveedores → Salidas de efectivo POS | Listado y filtro de pendientes disponibles; histórico visible |
| Reparto de salida A, $1,000 | $600 a factura A y $400 a factura B; A pagada y B con $400 pendientes |
| Intento de repartir $1,050 sobre salida de $1,000 | Rechazado con el mensaje de validación; sin aplicar el pago |
| Deshacer desde la interfaz | Salida pendiente; facturas A/B reabiertas a $600/$800 |
| Reaplicar la salida original | A pagada; B parcialmente pagada, sin crear otro retiro |
| Aplicar salida B, $400, desde la interfaz | Factura B liquidada |
| Aplicar salida C, $250, desde la interfaz | Factura C liquidada |
| Acceso desde la sesión POS cerrada | Botón Efectivo a proveedores disponible; muestra sus tres salidas conciliadas |

### Estado final conservado para revisión

| Factura QA | ID | Importe MXN | Saldo MXN | Estado nativo |
| --- | --- | ---: | ---: | --- |
| `QCP23/2026/11/0001` | 11642 | 600.00 | 0.00 | `paid` |
| `QCP23/2026/11/0002` | 11643 | 800.00 | 0.00 | `paid` |
| `QCP23/2026/11/0003` | 11644 | 250.00 | 0.00 | `paid` |

Salidas QA: `4706`, `4707`, `4708`; asientos originales: `11645`, `11646`,
`11647`. Los tres conservaron su identidad e importe. La sesión siguió cerrada
con saldo de **-$1,650.00**, sin un segundo descuento de caja ni nuevos
`account.payment` para estas aplicaciones.

## Integridad y salud final

- Los **10,071 movimientos contables previos** conservaron su conteo y suma
  después de instalar. Durante los puntos de control de pago, reversión y
  cierre también coincidieron las huellas completas de los registros ajenos
  a QA en `account_move`, `account_move_line` y `account_bank_statement_line`.
- Producción mantuvo el mismo PID y fecha de arranque antes y después. El
  módulo no figura instalado en la base productiva.
- Staging quedó activo. No aparecieron líneas `ERROR` nuevas en su log desde
  el cierre de instalación hasta la revisión final.
- Se observó una advertencia de esquema sobre `pos.preset.service_at`, ya
  presente antes del despliegue y ajena al módulo. No bloqueó las pruebas.

## Incidencias de preparación y alcance

El fixture QA se ajustó para usar las cuentas heredadas de la sucursal con el
dominio nativo de Odoo. Se retiraron dos movimientos ficticios redundantes de
preparación; solo quedaron las tres salidas documentadas. La comprobación de
reversión se ajustó al comportamiento nativo: Odoo recrea las partidas dentro
del mismo asiento, por lo que se verifican asiento, importe y saldos, en lugar
de exigir los IDs anteriores de las partidas después de deshacer. No fueron
necesarios cambios al código del módulo tras el despliegue.

La cobertura es específica de esta conciliación. No incluye timbrado ni
complementos CFDI, conversión de moneda, múltiples proveedores en una salida,
anticipos, diferencias contables ni una regresión completa de los demás
módulos. La interfaz exige distribuir el importe completo del retiro y usar
facturas de la misma empresa, proveedor y moneda de la empresa.

Se conservaron los documentos QA para revisión en staging. No se emitieron
pagos bancarios ni se modificaron documentos productivos.
