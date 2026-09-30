# Suscripciones: diagnostico estructural y propuesta de estabilizacion

Fecha: 2026-09-28.
Estado: propuesta para revision; NO implementada ni desplegada.

Nota posterior: este documento conserva el diagnostico previo. La implementacion
local posterior, sus pruebas realizadas y las puertas pendientes de validacion
se documentan en `REFACTOR_SUSCRIPCIONES_STAGING.md`. No confundir propuesta con
despliegue ni pruebas aisladas con validacion completa en Enterprise.

## 1. Alcance y limites

- Checkout examinado: staging, commit `13b803b59220a859308f714c2a8b26be717e4cb0`.
- Main local: `292f4d94a871e1fcd0f584fa8b907e3cab872ce2`.
- Se examinaron tambien los cambios locales pendientes de calendario y renovacion.
- Se revisaron cotizacion, interfaz POS, serializacion, buffer, procesamiento del
  pago, alta, renovacion, reinscripcion, cambio de paquete, domiciliados,
  participantes, reembolsos, cobros pendientes, proyeccion de acceso, cron y reparacion.
- Esta revision NO hizo consultas ni escrituras en produccion. No demuestra por
  si sola cuantos registros productivos siguen afectados ni la causa individual
  de cada incidente historico.
- Las reproducciones se ejecutaron en memoria con funciones del codigo actual y
  colaboradores simulados. No se ejecuto Odoo Enterprise ni PostgreSQL.
- No se modifico codigo funcional. Los cambios locales anteriores siguen pendientes.
- El desarrollo de telemetria SpeedFace permanece suspendido y fuera de alcance.

## 2. Conclusion ejecutiva

No falta una condicion adicional para el caso dia -> mes. Falta un contrato
coherente entre lo cotizado, lo pagado, lo aplicado y lo posteriormente auditado.

Existe centralizacion parcial del pricing, pero no de la operacion comercial
completa. Fechas, producto/plan, efectos del pago, estados y acceso se resuelven
en distintos momentos con diferentes datos. Algunas reparaciones vuelven a usar
el flujo de venta contra el estado actual de un contrato historico.

Por eso es posible corregir la cabecera del plan y conservar una fecha anterior,
o corregir la fecha y volver a modificarla al reejecutar un pago. No recomiendo
liberar el diff local como una solucion integral.

## 3. Hallazgos

### H1. Alta: el estado actual del contrato se confunde con la aplicacion de un pago

`_wgs_sync_subscription_sales` omite una reinscripcion ya vinculada solamente si
la suscripcion sigue abierta. Si posteriormente se cierra, la misma linea puede
volver a entrar al procesador de reinscripcion.

El auditor, por su parte, marca flujos explicitos como `safe_to_repair=True`
cuando el origen esta cerrado, aunque la linea ya este vinculada correctamente.
Esa salida ocurre antes de comprobar pagos posteriores.

Reproducciones: una reinscripcion previamente vinculada despacho nuevamente al
procesador; una renovacion vinculada a su origen cerrado obtuvo
`explicit_flow_not_applied / safe_to_repair=True`.

No se afirma que toda llamada nativa del POS recorra esa ruta repetidamente;
el riesgo comprobado existe si se reejecuta la sincronizacion o reparacion.

Referencias:
`/Users/apreza/dev/marlee-modules/witann_group_subscriptions_pos/models/pos_order.py:2437`
`/Users/apreza/dev/marlee-modules/witann_group_subscriptions_pos/models/pos_order.py:2730`

### H2. Alta: un periodo incompatible puede sobrevivir al cambio de plan

`_wgs_normalize_subscription_period_for_pos` solo recalcula un fin ausente o
menor/igual al inicio. Un fin de dos dias pasa aunque el producto sea mensual.
Tampoco obliga a que fin y proxima fecha formen un periodo consistente.

Reproduccion: inicio 2026-09-09, fin 2026-09-10, siguiente fecha 2026-09-11 y plan
mensual conservaron exactamente esas fechas incorrectas.

En renovacion hay otro problema: se recalcula al aplicar usando la fecha actual
del servidor y las fechas actuales del origen, en lugar de aplicar una operacion
validada con fecha y periodo propios. Una reparacion tardia no debe extender
desde el dia de la reparacion.

El diff local mejora la eleccion del plan destino, pero no resuelve este contrato
temporal ni la validacion completa de periodos persistidos.

Referencias:
`/Users/apreza/dev/marlee-modules/witann_group_subscriptions_pos/models/pos_order.py:3120`
`/Users/apreza/dev/marlee-modules/witann_group_subscriptions_pos/models/pos_order.py:2910`
`/Users/apreza/dev/marlee-modules/witann_group_subscriptions_pos/models/pos_order_pricing.py:392`

### H3. Alta: respuestas de cotizacion pueden sobrescribir una seleccion posterior

Los formularios de venta no comprueban una secuencia de solicitud o identidad
de seleccion al aplicar la respuesta. El snapshot frontend tampoco conserva
producto/empresa/cliente como identidad completa de la cotizacion.

Reproduccion con las funciones JS reales: seleccionar A y luego B, responder B
antes que A, deja producto B seleccionado pero plan y precio de A en el snapshot.
El servidor puede rechazar algunos cruces de tarifa; no hay garantia completa de
que el importe mostrado y la operacion seleccionada correspondan siempre.

Ya existe proteccion de solicitudes en el directorio y detalle; debe reutilizarse
el patron para cotizaciones, no inventar otra arquitectura frontend.

Referencias:
`/Users/apreza/dev/marlee-modules/witann_group_subscriptions_pos/static/src/js/subscription_flow_controllers.js:624`
`/Users/apreza/dev/marlee-modules/witann_group_subscriptions_pos/static/src/js/subscription_pricing_snapshot.js:3`

### H4. Alta: la metadata del ticket se asocia por aproximacion

`_wgs_match_pos_line_for_ui_config` usa producto y cantidad, y finalmente toma
la primera candidata. Si no encuentra el producto solicitado, conserva el
conjunto original de candidatas. No exige una coincidencia unica por UUID de linea.

Dos lineas del mismo producto pueden representar periodos, personas u operaciones
distintas. Un buffer por UUID de orden no identifica cada una de esas operaciones.

Referencia:
`/Users/apreza/dev/marlee-modules/witann_group_subscriptions_pos/models/pos_order.py:2401`

### H5. Alta: se sincroniza acceso durante una transicion incompleta

Al cambiar producto, primero se pone en cero la linea anterior y despues se crea
la nueva. Hooks de `sale.order.line` sincronizan acceso durante ambos pasos.
Otros writes actualizan participantes, plan y fechas en etapas separadas.

Existe `wgs_defer_access_sync`, pero actualmente no cubre todos esos hooks y
el flujo POS no lo usa como frontera de la operacion completa.

La desactivacion de una persona libera su global_user_id y encola deletes. Aunque
todo pueda confirmar en una sola transaccion, pueden quedar efectos tecnicos de
estados intermedios, ademas de trabajo repetido. El impacto exacto en un dispositivo
requiere validar la secuencia real; no se presume que cada caso cambie su PIN.

Referencias:
`/Users/apreza/dev/marlee-modules/witann_group_subscriptions_pos/models/pos_order.py:3193`
`/Users/apreza/dev/marlee-modules/witann_group_subscriptions/models/sale_order.py:1420`
`/Users/apreza/dev/marlee-modules/access_control_api/models/access_person.py:286`

### H6. Media: navegador, calendario comercial y vista POS tienen calculos propios

El fallback JS suma meses con setUTCMonth, mientras Python usa relativedelta.
Reproduccion para 31-enero-2026 + un mes - un dia:

- Navegador: 02-marzo-2026.
- Backend: 27-febrero-2026.

El fallback no se usa siempre, pero existe en un camino de alta. Ademas, las
vistas del directorio y de detalle reconstruyen periodos si faltan fechas.
Un visor puede terminar mostrando una interpretacion, no el periodo efectivamente
comprado. El estado nativo y el derecho de acceso son conceptos distintos; tampoco
deben confundirse por el color de una etiqueta.

Referencias:
`/Users/apreza/dev/marlee-modules/witann_group_subscriptions_pos/static/src/js/subscription_status_button.js:274`
`/Users/apreza/dev/marlee-modules/witann_group_subscriptions_pos/models/pos_order_pricing.py:316`
`/Users/apreza/dev/marlee-modules/witann_group_subscriptions_pos/models/sale_order.py:2640`

### H7. Alta: domiciliados necesitan historial de ciclos, no reinicio destructivo

`wgs_create_for_subscription` elimina las mensualidades existentes antes de
reiniciar el contrato, perdiendo sus vinculos de pago como historial estructurado.

Ademas, una suscripcion legacy sin contrato domiciliado cuyo plan ahora tiene
la bandera domiciliado es rechazada por la cotizacion de renovacion normal.
La promesa de migracion en renovacion no esta representada como una operacion
explicita y probada en esa ruta.

Referencias:
`/Users/apreza/dev/marlee-modules/witann_group_subscriptions/models/domiciliation.py:159`
`/Users/apreza/dev/marlee-modules/witann_group_subscriptions_pos/models/pos_order_pricing.py:722`

### H8. Alta: hay reglas contrapuestas en reembolsos y prorrateo

Los reembolsos de renovacion/cobro pendiente salen sin cancelar el contrato ni
revertir el periodo/cuota en este metodo. Esto no coincide con la regla inicial
solicitada de cancelar al reembolsar un ticket de suscripcion.

El prorrateo del constructor normal se limita a `flow == new`; la prueba de
reinscripcion afirma que no debe prorratear. Debe contrastarse con la indicacion
posterior de permitir pasar desde otro paquete a uno con prorrateo.

No debemos resolver esas contradicciones cambiando reglas silenciosamente.
Reembolso parcial y momento efectivo de un paquete distinto al renovar requieren
una definicion expresa antes de implementar.

Referencias:
`/Users/apreza/dev/marlee-modules/witann_group_subscriptions_pos/models/pos_order.py:5078`
`/Users/apreza/dev/marlee-modules/witann_group_subscriptions_pos/models/pos_order_pricing.py:543`
`/Users/apreza/dev/marlee-modules/witann_group_subscriptions_pos/tests/test_pos_subscription_pricing.py:710`

### H9. Alta para liberar: el diff pendiente no tiene una regresion integral validada

El metodo de calendario de renovacion ahora exige `plan=`, pero una prueba
existente sigue llamandolo con `preferred_line=`. Esa llamada ya no coincide.
Hay tambien fixtures/compatibilidades que deben verificarse contra el Odoo 19
Enterprise instalado y pruebas criticas que pueden omitirse con skipTest.

Una prueba unitaria de calendario no demuestra el flujo real de un pago hasta
suscripcion, participantes, acceso y reintento.

Referencia:
`/Users/apreza/dev/marlee-modules/witann_group_subscriptions_pos/tests/test_pos_subscription_pricing.py:142`

## 4. Arquitectura propuesta: una operacion, no otra fuente de verdad

Cadena objetivo:

```text
Seleccion operativa
  -> cotizacion completa calculada por backend
  -> validacion antes del cobro
  -> ticket pagado + operacion aplicada una sola vez
  -> suscripcion/participantes/cartera consistentes
  -> perfil de acceso final
  -> cola existente de sincronizacion
```

### Responsabilidades y autoridad

| Dato | Autoridad |
| --- | --- |
| Paquete, plan y tarifa disponibles para vender hoy | Catalogo vigente de la empresa |
| Lo comprado en un pago determinado | Snapshot comercial validado y vinculado a su linea POS |
| Estado operativo actual | Suscripcion nativa; cartera del contrato para domiciliados |
| Si una operacion ya fue aplicada | Registro unico de aplicacion, no estado abierto/cerrado |
| Derecho de acceso | Resolver central existente, usando el estado comercial final |
| Evidencia fisica SpeedFace | Fuera de este cambio; no confundir con el derecho comercial |

El registro de aplicacion es un comprobante historico, no un segundo saldo ni
otro contrato mutable. Debe guardar operacion, origen, antes/despues y vinculo
exacto al ticket. No se propone reimplementar contabilidad ni Odoo Suscripciones.

### A. Cotizacion completa en backend

Una respuesta debe incluir empresa, socio/titular, producto, plan, tarifa,
operacion, origen, participantes/cupo, inicio solicitado, periodo resultante,
proxima fecha, importes, impuestos, descuento autorizado y cuotas seleccionadas.
Debe llevar identidad de cotizacion, version de reglas y version del origen.

No se permite completar silenciosamente un periodo mensual con fechas historicas
de otro plan ni completar una operacion ambigua con la primera linea disponible.
Para el cliente con un unico plan por producto, ese plan determina el plazo.
Si un producto tiene varias opciones, se exige una seleccion valida.

El POS muestra y transporta ese resultado. No suma meses ni escoge otro plan.
Cada formulario descarta respuestas que no correspondan a su ultima seleccion.

Precio base, impuestos, importe del ticket y total visible NO son tres motores
necesariamente: son representaciones legitimas del mismo calculo. Se conservan
las representaciones necesarias, generadas desde una sola cotizacion.
El descuento autorizado pertenece al evento, nunca a la tarifa permanente.

### B. Aplicacion unica y transaccional

Identificar la operacion por UUID estable de linea/operacion y relacion unica
con su linea POS. Un replay igual devuelve el resultado ya aplicado; el mismo
identificador con contenido diferente se rechaza para revision.

Validar/bloquear la suscripcion o contrato origen para evitar dos renovaciones
concurrentes sobre la misma version. Una segunda compra legitima obtiene otra
operacion y otra cotizacion; no se confunde con un retry.

Antes del cobro: resolver errores de paquete, tarifa, participante, cuota,
fecha y version. Despues del cobro: no recalcular usando hoy o el catalogo nuevo.
Una reconexion del POS o cambio de dia no puede alterar lo contratado.

La escritura comercial y su comprobante se confirman juntos. La propagacion
fisica no debe rechazar una venta comercialmente correcta. Si hubo un cobro
externo, un error Odoo no demuestra que el dinero se haya revertido: el flujo
de recuperacion debe conservar la identidad del intento y nunca pedir recobrar
automaticamente. Esto requiere pruebas del metodo de pago realmente utilizado.

### C. Acceso derivado una sola vez al finalizar

Completar linea, producto, plan, participantes, vigencia y estado antes de
proyectar acceso. Todos los hooks relevantes deben respetar el mismo diferimiento.
Despues recalcular titular, participantes previos y nuevos, y encolar solo el
resultado final mediante la cola existente.

Reutilizar el resolver central actual. No crear otro calculador de acceso en el
POS. Preservar bloqueos, origen manual, multisede, sede cobradora y horarios.
Los cron siguen atendiendo activaciones futuras y vencimientos con las mismas
fechas; no reparan precios ni reinterpretan pagos.

No se modifican en esta fase identidades/PINs ni el protocolo SpeedFace. El
objetivo es no generar transiciones artificiales que activen esos mecanismos.

### D. Historial y reparacion separados de vender

Reinscribir un domiciliado no elimina cuotas del contrato anterior: se conserva
el ciclo anterior y se abre uno nuevo con vinculos historicos.
Un reembolso se vincula a su operacion origen y aplica la politica aprobada,
sin borrar evidencia. Un cobro pendiente concilia la deuda concreta; no agrega
por si mismo otro periodo de membresia.

Reparar NO llama ciegamente a vender otra vez. Reconstruye cronologicamente los
pagos, reversos y cambios autorizados usando evidencia historica. Si falta una
fecha/plan fiable, el caso se marca como ambiguo para decision humana.

## 5. Contrato funcional que debe fijarse en pruebas

| Flujo | Resultado exigido |
| --- | --- |
| Nueva | Solo elegibles sin historial segun la regla vigente; fecha elegida retroactiva/futura; plazo del paquete vendido |
| Renovar mismo paquete | Conservar lo ya pagado y agregar el periodo correspondiente, sin heredar descuento del pago anterior |
| Renovar otro paquete | Conservar la referencia de vigencia pagada; usar el plazo/precio destino, nunca el plan origen |
| Reinscribir | Origen cerrado/cancelado; permitir otro paquete; inicio elegido; participantes del nuevo cupo |
| Cambiar paquete | Conservar la regla actual de diferencia/credito y calendario; cerrar/reemplazar origen solo al completar destino |
| Dia / WellHub / TotalPass | Un dia completo no significa prueba gratis; aplicar elegibilidad y flujo correcto |
| Prueba gratis | Su regla de uso unico es independiente de que el plan dure un dia |
| Alineado | Alinear y prorratear segun configuracion y flujo aprobado; no crear por eso un contrato domiciliado |
| Domiciliado nuevo | Plazo contractual y cuotas mensuales separados; seleccion inicial permitida y primer mes proporcional |
| Domiciliado renovar | Cuotas consecutivas desde la primera pendiente; admite adelantos y mes final previamente pagado; acceso solo al corriente |
| Legacy domiciliado | Transicion explicita aprobada, sin inferir cuotas historicas pagadas ni duplicar contratos/cobros |
| Cobro pendiente | Liquidar la deuda concreta; reintento sin duplicar conciliacion ni beneficio |
| Reembolso/cancelacion | Efecto comercial, cartera y acceso coherentes con la politica expresamente aprobada |

Vigencia normal: fechas comerciales inclusivas. Acceso desde 00:00 del inicio
hasta antes de 00:00 del dia posterior al fin en America/Mexico_City. Eso incluye
23:59:59 completo; no se almacena el fin como 23:59:00 ni como medianoche inicial.
Mantener campos Date donde corresponde y convertir timestamps de pago a fecha
comercial una sola vez.

Fecha de pago + plazo es la referencia de una alta inmediata, no una formula
universal: inicio futuro/retroactivo, renovacion anticipada, alineacion y
domiciliados tienen anclas explicitas. En una reparacion nunca se usa la fecha
actual como sustituto de una compra historica.

Puntos a cerrar antes de implementar: devoluciones parciales frente a cancelacion
total; momento de entrada de beneficios/participantes al renovar hacia otro paquete;
y prorrateo de reinscripcion al mismo paquete frente a cambio a otro alineado.
No se cambian las reglas operativas silenciosamente para facilitar el refactor.

## 6. Ruta de implementacion y puertas de salida

### Etapa 0: base reproducible

Congelar matriz de reglas y casos sinteticos que reproduzcan los incidentes.
Revisar/reutilizar lo valido del diff pendiente; no publicarlo como conjunto.
Documentar diferencias main/staging y entorno Odoo Enterprise usado para pruebas.

### Etapa 1: cotizacion y calendario

Extraer un servicio backend de calculo sin efectos laterales y un adaptador
explicito a campos de Odoo 19. Reducir fallbacks y eliminar calculo de fechas JS.
Unificar snapshot y proteger respuestas asincronas. Probar alta, renovacion,
reinscripcion y cambio de paquete contra la misma matriz.

Salida: cotizacion completa, modal=ticket, fechas congruentes en todos los flujos.

### Etapa 2: aplicacion e idempotencia

Identidad estable por operacion/linea, control de version/concurrencia, registro
de aplicacion, actualizacion comercial atomica y acceso al estado final.
Adaptar entrada POS y operaciones backend WGS al mismo servicio, sin afectar
ordenes no WGS. Conservar endpoints existentes como adaptadores temporales.

Salida: retries no extienden dos veces; cierre posterior no convierte un pago
historico en pendiente; fallo fisico no cambia el resultado comercial.

### Etapa 3: consecuencias y recuperacion

Historial de domiciliados, casos legacy, reembolsos y cobros pendientes; auditor
de solo lectura con clasificacion basada en evidencia y reparacion dirigida.
Esta etapa no autoriza importadores, nuevas reglas comerciales ni resincronizacion masiva.

Salida: simulacion antes/despues por ID, motivos, impactos por socio/sede y
segunda ejecucion sin nuevos cambios. Bloqueos y accesos manuales preservados.

### Etapa 4: validacion completa en staging

No ir liberando a main cada parche individual. El corte inicial a produccion
requiere que todas las rutas activas usen el mismo contrato y que ninguna quede
dependiendo de un fallback incompatible. Dividir commits para revision, no la
consistencia funcional del despliegue.

Probar con copia aislada representativa y salida fisica de pruebas deshabilitada
o apuntada a infraestructura de staging. Nunca una copia que envie deletes o
upserts a los SpeedFace de produccion.

## 7. Matriz minima de regresion

- Dia -> mes, mes -> dia, semestre/anual -> mes, mes -> semestre/anual.
- Alta, renovacion y reinscripcion con el mismo producto y con otro producto.
- Compra ordinaria, anticipada, vencida aun renovable, cerrada y cancelada.
- Fechas retroactivas/futuras; 28/29-febrero; 30/31; fin de mes/anio.
- 17:59/18:01 y 23:59/00:00 hora Mexico; inicio y fin incluidos completos.
- Renovacion anticipada preserva periodo pagado, reparacion tardia no agrega tiempo.
- Pareja/trio -> individual y viceversa; operar desde titular o participante.
- Producto de SM/ED, multisede, acceso manual y bloqueo de todos los participantes.
- IVA incluido/excluido; descuento autorizado/100%; proxima venta a tarifa normal.
- Respuestas A/B fuera de orden, cambio rapido de fecha/plan, cierre de formulario.
- Dos lineas iguales con configuraciones distintas; payload/buffer sin coincidencia exacta.
- Reenvio de ticket, reconexion, dos cajeros simultaneos y cron concurrente.
- Cierre posterior de una suscripcion con pagos ya aplicados; replay sin reactivacion.
- Domiciliado 1, 1+12, consecutivos; parcial de adeudo, al corriente, adelantos,
  mes 12 prepagado, plazo terminado, nuevo ciclo y legacy sin contrato.
- Reembolso/cancelacion conforme a matriz aprobada; conciliacion de cobro pendiente.
- Error al sincronizar acceso: trazabilidad y recuperacion sin otro cobro.
- Backend y POS muestran el mismo producto, plan, periodo y motivo de acceso.
- Funciones preservadas: renovar/reinscribir/nueva, participantes, bloqueo,
  desbloqueo, WellHub, TotalPass, abrir puerta, resincronizar, bitacora y ventas POS.

Pruebas criticas Odoo 19: cero omisiones por fixtures incompatibles. Las unitarias
aisladas no sustituyen transaccion, ORM, impuestos, payload POS, cola y cron reales.

## 8. Datos historicos y despliegue

Primero estabilizar ventas futuras. Despues emitir un nuevo reporte de casos
historicos, sin escritura: pagos en orden, producto/plazo adquirido, inicio
elegido si existe, beneficio aplicado, devoluciones y periodo esperado.

Cada reparacion requiere IDs aprobados y precondiciones antes/despues para evitar
pisar una venta nueva. Una compra de agosto no pasa a octubre solo porque se
reparo en septiembre. Un pago posterior real si puede justificar otra vigencia.

No cambiar todos los contratos a la tarifa/plan actual del producto. No abrir
suscripciones vencidas por el solo hecho de encontrar pagos antiguos.
Backup, validacion de restauracion y reporte de impactos antes de produccion.
Si hay un rollback tras ventas nuevas, conservar el comprobante de operaciones
y tratar datos compatibles; revertir solo el codigo no deshace ventas ni cuotas.

## 9. Resultado de esta revision

Se comprobaron en ejecuciones aisladas: normalizacion permisiva de periodo,
reaplicacion de reinscripcion, falso positivo de reparacion, carrera entre
cotizaciones y diferencia calendario JS/Python. No se ejecutaron reparaciones,
pruebas integrales Odoo, commit, push, merge ni despliegue.
