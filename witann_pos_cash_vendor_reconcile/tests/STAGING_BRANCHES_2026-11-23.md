# Conciliación entre empresas matrices y sucursales

**Resultado: aprobado y desplegado en staging, versión `19.0.1.1.0`.**
Código: `567d052c71ce8eb609fe821977ae7114554c2c4f`. Verificación final:
23 de noviembre de 2026, 12:35, hora de Ciudad de México.

## Regla general

Las salidas de efectivo pueden aplicarse a facturas de la misma empresa matriz
y de sus sucursales, según la jerarquía nativa de Odoo. No hay nombres ni IDs de
empresas fijos en el código. Las empresas matrices independientes siguen
separadas, aunque el usuario tenga acceso a ambas.

El asistente muestra la **Sucursal de la salida**, la **Empresa matriz** y la
**Empresa de factura**. La selección de facturas y proveedores reconoce la
jerarquía; la validación del servidor confirma que los documentos comparten
matriz y que la cuenta por pagar está disponible en la sucursal.

Se conservan moneda, proveedor, permisos y controles de saldo. Deben mantenerse
activas la matriz y las sucursales involucradas en el selector de empresas.
No se conceden permisos adicionales ni se cambia la empresa de los documentos.

## Pruebas

| Capa | Resultado |
| --- | --- |
| Gate local Odoo 19 | 24 pruebas funcionales, 0 fallas y 0 errores |
| Gate con runtime exacto del servidor | 24 pruebas funcionales, 0 fallas y 0 errores |
| Concurrencia, en ambos gates | 2 escenarios aprobados; no se reutiliza una salida ni se sobrepaga una factura |
| Base temporal del servidor | Eliminada después del gate |

Los cinco casos nuevos verifican: dos sucursales pagando una factura de matriz,
reversión y reaplicación; formulario con proveedor y factura propiedad de la
matriz; otra empresa independiente con su sucursal; rechazo de otra matriz;
y conservación de las restricciones de un contador que solo tiene acceso a
una sucursal. Las 19 regresiones anteriores también pasaron.

## Prueba de navegador en staging neutralizado

Se crearon exclusivamente documentos identificados como `QA CASH BRANCH 20261123`.

| Matriz de la factura | Factura QA | Salidas aplicadas | Saldo final |
| --- | --- | --- | ---: |
| Comercializadora Marlee | `QB1/2026/11/0001`, ID 11651, $1,000 MXN | SB Total Padel: $600, salida 4711; El Dorado: $400, salida 4712 | $0, `paid` |
| Grupo SB Fitness de Aguascalientes | `QB7/2026/11/0001`, ID 11656, $250 MXN | Santa Mónica: $250, salida 4713 | $0, `paid` |

Los tres pagos se ejecutaron desde el asistente del navegador. Después del
primero, la factura de Comercializadora mostró $400 pendientes; después del
segundo quedó pagada. Las salidas conservaron sus empresas de sucursal y las
facturas conservaron sus matrices. Las tres sesiones QA estaban cerradas.

## Integridad y despliegue

- Upgrade exclusivo del módulo: 16.68 segundos. Staging quedó activo y
  neutralizado. No se actualizaron core ni otros módulos.
- Las huellas SHA-256 de los archivos desplegados coinciden con el commit
  `567d052`. La instalación no alteró las huellas de las tres tablas contables
  verificadas.
- Después de las pruebas, las huellas completas de `account_move`,
  `account_move_line` y `account_bank_statement_line`, excluyendo únicamente
  los cinco asientos QA nuevos, siguieron coincidiendo con las iniciales.
- Se conservaron los asientos y las partidas de liquidez de las tres salidas,
  sus importes y los saldos de las sesiones. No se crearon `account.payment`.
- Sin líneas `ERROR` nuevas en el log del servicio desde el cierre del upgrade
  hasta la verificación final. Las excepciones de serialización del gate
  concurrente son esperadas y pertenecen a la base desechable.
- Producción conserva su PID y fecha de arranque, el módulo no está instalado
  allí y `main` permanece en `7795fd7`. Los documentos QA quedan en staging
  para revisión.

Se mantienen los límites de moneda de empresa, distribución completa del retiro,
facturas publicadas y un proveedor por salida. No se generaron documentos CFDI
ni se hicieron transferencias de dinero.
