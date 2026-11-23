# Despliegue y validación en producción

**Resultado: módulo instalado y validación técnica aprobada en producción.**
Versión `19.0.1.1.0`, código desplegado `5a87092fde4ca30951ca5aecc3f72ff422b021dd`.
Fecha: 23 de noviembre de 2026. Instalación completada aproximadamente a las
13:23 y revisión de salud final a las 13:29, hora de Ciudad de México.

Acceso: [Salidas de efectivo a proveedores](https://portal.spinbike.mx/odoo/action-1571).

## Despliegue

| Control | Resultado |
| --- | --- |
| Destino | `portal.spinbike.mx`, base productiva sin neutralizar |
| Promoción Git | Fast-forward de `main`, desde `7795fd7` a `5a87092` |
| Repositorio productivo | Actualizado desde CloudPepper, rama `main` |
| Módulo | `witann_pos_cash_vendor_reconcile`, estado `installed` |
| Versión instalada / disponible | `19.0.1.1.0` / `19.0.1.1.0` |
| Instalación CLI | 24.54 segundos |
| Ventana controlada de respaldo, instalación y arranque | 71.21 segundos |
| Servicio y HTTP al cierre | Activo; `/web/login` responde 200 |
| Otros módulos | Versiones instaladas conservadas; único módulo nuevo: este módulo |

El alcance del código promovido se limita al módulo, sus pruebas y
documentación. La diferencia contra el código productivo anterior también
incluye una bitácora de liberación ya existente. No se actualizaron Odoo core,
Enterprise, suscripciones, Access API ni otros módulos durante esta liberación.

## Gate previo con el runtime productivo

Se detectó que producción usa una revisión de Contabilidad distinta a staging:
`account 19.0.1.5`. Por ello se repitió el gate con el intérprete, core y rutas
de addons de producción, usando una base nueva y desechable `pos_cash_qa`.
Core observado en CloudPepper: `b2319924a35b575981ecc885acc1a44641470b41`.

| Prueba | Resultado |
| --- | --- |
| Suite ORM completa del módulo | **24 aprobadas; 0 fallas y 0 errores** |
| Mismo retiro contra dos facturas simultáneas | Una operación aceptada; la otra reintentada y rechazada |
| Dos retiros contra una misma factura simultánea | Una operación aceptada; la otra reintentada y rechazada |
| Correspondencia de código | SHA-256 de código, XML y seguridad coincidentes con el candidato probado |
| Limpieza | Base temporal eliminada y ausencia comprobada al cierre |

La cobertura incluye pagos totales/parciales, matrices y sucursales de dos
empresas independientes, rechazo de otras matrices, permisos, reversión,
reaplicación, duplicados, sobrepagos, vencimientos y bloqueos fiscales. Las
excepciones de serialización del log concurrente son el resultado esperado de
la prueba de colisión; pertenecen a la base desechable.

No se ejecutó `--test-enable` sobre la base productiva.

## Integridad de los datos productivos

Con el servicio detenido se registraron conteos y huellas de los campos
existentes; se repitió la comparación después de instalar y antes de reabrir
el servicio.

| Tabla | Registros | Resultado |
| --- | ---: | --- |
| Asientos y documentos contables | 12,013 | Conteo y huella completos idénticos |
| Apuntes contables | 33,117 | Conteo y huella completos idénticos |
| Pagos contables | 3,205 | Conteo y huella completos idénticos |
| Conciliaciones parciales | 4,866 | Conteo y huella completos idénticos |
| Conciliaciones completas | 4,856 | Conteo y huella completos idénticos |
| Sesiones POS | 1,503 | Conteo y huella completos idénticos |
| Pagos POS | 18,310 | Conteo y huella completos idénticos |
| Movimientos de banco/caja | 4,851 | Conteo y campos financieros conservados; cambios de auditoría descritos abajo |

**Observación de auditoría:** la primera comprobación detectó una huella distinta
en `account_bank_statement_line`. Se comparó campo por campo contra el respaldo
previo, dentro del servidor y mediante una tabla temporal. Los únicos campos
existentes que cambiaron fueron `write_date` en 4,851 registros y `write_uid`
en 2,364, al guardar el nuevo estado calculado del módulo.

Importes, fechas del movimiento, diarios, contactos, sesiones, empresas,
asientos relacionados y campos de creación conservaron sus valores. No hubo
cambios en saldos, estados de pago ni relaciones contables existentes. La
huella integral de las otras siete tablas coincidió exactamente.

## Validación sobre producción

- Menús de Contabilidad y POS, acción del listado y ambas vistas verificados.
- Asistentes sin guardar comprobados por ORM para Padel, El Dorado y Santa
  Mónica: cada sucursal resolvió correctamente su matriz.
- Navegador: módulo instalado visible y asistente de una salida de Padel
  abierto correctamente con Comercializadora Marlee como matriz; se canceló
  sin seleccionar facturas ni aplicar un pago.
- En las matrices muestreadas no había facturas publicadas con saldo en la
  moneda requerida al realizar la inspección. La validación financiera completa
  de pagos se efectuó en QA; las comprobaciones sobre producción fueron de
  lectura y no crearon documentos ni aplicaron conciliaciones reales.
- Revisión final: producción y staging activos, HTTP 200, core coincidente con
  el runtime probado y cero líneas `ERROR` nuevas después del reinicio hasta
  la comprobación final.

## Respaldo y uso

Se conservó un respaldo PostgreSQL previo, de 294,100,361 bytes, en el mismo
servidor: `/tmp/pos-cash-production-20261123/backup/before-install.dump`.
Archivo con modo `0600` y catálogo del archivo validado por `pg_restore --list`.
No se descargó la base ni su respaldo a la estación de trabajo.

Para utilizar el módulo, recargar Odoo y activar la empresa matriz y las
sucursales involucradas en el selector de empresas. Después seguir
**Contabilidad → Proveedores → Salidas de efectivo POS**, o el botón
**Efectivo a proveedores** de la sesión POS. Se mantienen los límites y permisos
de la versión validada en staging.
