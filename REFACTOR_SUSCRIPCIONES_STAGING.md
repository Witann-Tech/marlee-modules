# Refactor comercial de suscripciones: validacion en staging

Registro inicial: 2026-09-28. Rama de trabajo: `staging`.

## Preparacion de entrega y build: 2026-10-19

Solicitados commit y push de la recuperacion automatica a `staging`. Se
repitieron 67 tests Python y 22 JavaScript, todos aprobados. El usuario aplicara
el build y los upgrades y confirmara antes de iniciar pruebas por navegador.
Versiones objetivo: base `19.0.1.1.58` y POS `19.0.1.6.4`. No se ha ejecutado la
suite ORM ni validacion de caja sobre este despliegue. Las menciones de codigo
local mas abajo describen el estado previo a esta entrega.

## Recuperacion automatica de activaciones: 2026-10-19

Implementado localmente en `staging`, POS `19.0.1.6.4`; mantiene la dependencia
base `19.0.1.1.58`. Sin commit/push ni despliegue desde esta iteracion. Las
secciones siguientes son historicas: esta seccion sustituye su cuarentena de
operaciones en `review`. No se modifica el importador bancario.

### Comportamiento

- Se elimina la escritura de nuevas operaciones en `review`. El valor se
  conserva solo por compatibilidad con registros anteriores, que vuelven a
  entrar automaticamente en la cola de activacion. No hay paso de aprobacion
  manual para una compra comercialmente valida.
- Si la huella coincide, se aplica directamente. Si solo difiere el estado por
  un cierre en el ultimo dia inclusivo, se exige que coincida exactamente la
  huella normalizada y evidencia de OdooBot, motivo de cierre nativo, fechas de
  cierre/cobro y seguimiento del estado. Solo entonces se restaura el estado
  anterior y se aplica el paquete firmado dentro del mismo savepoint.
- No se ignoran diferencias de titular, empresa, paquete, plan, precio,
  participantes o fechas. Una cancelacion manual no se reabre. Una operacion
  cancelada/reembolsada o un ticket sin pagar no se activan.
- Los fallos tecnicos revierten la aplicacion parcial y conservan la compra en
  `scheduled`, con diagnostico, contador y proximo intento (15 minutos minimo,
  ejecutado por los crons existentes). No se repite un intento dentro del mismo
  lote; los contratos sin fallos tienen prioridad sobre reintentos. Una cola
  ajena no queda bloqueada por otro cliente. Se mantienen lotes de 100.
- La lectura explicita de la ficha POS intenta recuperar solo las compras
  pagadas ya exigibles de ese cliente/empresa antes de elegir Renovar/Reinscribir.
  No ejecuta una activacion global ni adelanta beneficios futuros. La cotizacion
  tambien termina periodos exigibles antes de calcular la proxima compra.
- Antes de cobrar se comprueba que siga existiendo el plan firmado. Si un pago
  exigible no puede aplicarse, se impide cobrar otra vez sobre la misma fuente;
  no se considera resuelto ignorando el error o concediendo un periodo inventado.
- La tarjeta ya no solicita una revision inexistente. Un error tecnico muestra
  activacion automatica pendiente, no una tarea para el cajero. Los errores de
  concurrencia SQL siguen el reintento transaccional nativo de Odoo.
- Se conservan hashes, comprobantes, importes y fechas originales. La proteccion
  de los tres crons nativos sigue siendo la prevencion principal del cierre
  anticipado; la recuperacion cubre compras heredadas del defecto anterior.

### Validacion

67 tests aislados Python y 22 JavaScript aprobados. Incluyen recuperacion por
estado, rechazo de cambios comerciales reales/cancelacion manual, recuperacion
de compras heredadas, reintento tras fallo tecnico, no duplicacion, equidad de
colas y rechazo de plan inexistente antes del pago. SQL ejercitado en SQLite con
traduccion explicita de exclusion de arrays; NO prueba PostgreSQL.

40 tests ORM de operaciones preparados, NO ejecutados localmente. Sigue siendo
obligatorio correr la suite en la copia desechable con el build exacto de Odoo
19 Enterprise, incluyendo locks/savepoints y dos workers.

Pruebas nuevas prioritarias en esa copia:

1. Reproducir un cierre nativo por OdooBot en el ultimo dia, con cambio pagado
   para el siguiente: primera activacion recupera y aplica exactamente la compra.
2. Una compra heredada en `review` se aplica sin nuevo pago ni accion manual.
3. Omitir el plan en el handler de prueba: rollback sin cambio comercial ni
   cuarentena; retirar el fallo y comprobar la aplicacion al reintentar.
4. Abrir la ficha antes del cron: aplica solo pagos exigibles de ese cliente,
   refresca el paquete/boton, no activa otros socios ni periodos futuros.
5. Cierre manual, reembolso, cambio real de precio/participantes y dos compras
   futuras: no reapertura indebida, no recobro y orden de aplicacion conservado.
6. Muchas colas fallidas junto a clientes nuevos: los nuevos progresan y cada
   intento queda acotado. Ejecutar de nuevo los tres crons nativos: no cierran WGS.

No se garantiza exito frente a datos corruptos, cancelaciones expresas o caidas
de infraestructura: esas condiciones no justifican omitir controles. El criterio
de salida es que las ventas validas se apliquen sin cuarentenas ni recobros, y
los fallos transitorios se recuperen automaticamente. No promover sin la prueba
ORM y operativa.

### Reparacion puntual de produccion autorizada

Solo `S01905`, compra POS `14488` / linea `25882`, ticket `2648-8-000088`.
Cobro de $250 del 15/octubre conservado. Aplicada SEMANA SM del 16 al 22/octubre,
siguiente cobro 23/octubre; sin extender desde la fecha de reparacion. Restaurado
acceso en Santa Monica con el horario general correspondiente al paquete.
Dry-run, reparacion atomica y verificacion independiente correctos; se retiro la
accion temporal. Personas existentes conservadas, sin crear/eliminar/consolidar.
Upsert `34882` encolado; entrega fisica a SpeedFace no verificada. No se cambiaron
configuraciones globales de crons ni otros contratos en produccion.

## Entrega para pruebas: 2026-10-15

Commit y push a `staging` solicitados. Se repitieron satisfactoriamente 53 tests
Python y 20 JavaScript; sigue pendiente la suite ORM sobre el build exacto.
Actualizar ambos addons: base `19.0.1.1.58`, POS `19.0.1.6.3`. Sin merge a main
ni nuevos cambios de datos en produccion. Los estados locales mencionados mas
abajo describen la preparacion del 14/octubre, anterior a esta entrega.

Para las pruebas manuales usar clientes de prueba y comprobar siempre modal,
ticket, ficha de suscripcion y control de acceso. No basta con el estado visual
del directorio. Crear cotizaciones nuevas tras upgrade/recarga; las ya firmadas
conservan sus condiciones. No borrar almacenamiento si quedan tickets pendientes.
No conectar la copia de pruebas a dispositivos o gateways de produccion.

El conflicto de crons requiere dos momentos: ultimo dia pagado y dia siguiente.
No basta ejecutar el cron hoy sobre un contrato que vence dentro de un mes. En
la suite ORM se congelan fechas sin cambiar el reloj del servidor. En pruebas
operativas puede usarse un contrato corto de prueba que venza hoy y un cambio
pagado para manana. Verificar hoy que los jobs nativos no lo cierren ni cambien
su paquete; manana activar WGS y verificar el destino comprado. No modificar
las fechas de una fuente despues de cotizar/pagar: eso invalida su revision.

## Frontera de aplicacion WGS POS: 2026-10-14

Version base `19.0.1.1.58`, POS `19.0.1.6.3`. Implementacion local en `staging`,
sin commit/push ni despliegue de codigo en produccion. Alcance WGS/POS; no
incluye importador bancario, loyalty ni cambios al protocolo/identidades SpeedFace.
Los estados y resultados anteriores de este documento son registros historicos.
Separadamente se repararon, con autorizacion puntual, los dos contratos del
incidente del 12/octubre; ver el registro al final de esta seccion.

### Cambios e invariantes

- Cotizacion firmada como autoridad del plan/precio/periodo comprado. La lectura
  de una operacion firmada no sustituye el plan por metadata duplicada ni por
  el catalogo actual. Sin plan existente no se admite una nueva cotizacion.
- Una frontera de aplicacion para cobro inmediato y activacion futura. Antes de
  registrar la aplicacion se verifican titular/empresa, paquete/plan, cantidad,
  precio recurrente sin descuento heredado, participantes y periodo persistido.
- Un cambio programado no altera el periodo ni beneficios actuales. Cambiar
  solo el plan del mismo producto tambien espera al siguiente periodo.
- Domiciliacion valida contrato y cuotas seleccionadas contra el pago, sin
  confundir su cartera con la vigencia ordinaria. El reembolso total valida
  cancelacion de la membresia, contrato domiciliado y cambios futuros.
- Adaptador nativo Odoo 19 separado: plan exclusivamente en `sale.order.plan_id`;
  nunca se escribe su campo relacionado de la linea. Alta, upsale, renovacion y
  reinscripcion construyen sus lineas con el mismo adaptador.
- Eliminada la cadena privada sin llamadas de creacion alternativa de upsell.
  El flujo vigente de Cambiar paquete y su credito se conservan.
- Activacion verifica la huella original del pago, conserva locks/savepoints y
  pasa por las mismas comprobaciones que checkout. Si falla, revierte solo la
  activacion y deja la operacion en revision; no marca un resultado incorrecto
  como aplicado ni vuelve a cobrar.
- Cola seleccionada por cabecera de suscripcion antes de limitar el lote. Una
  revision bloquea su cola, no otras. Se procesan cambios consecutivos ya
  exigibles dentro del mismo presupuesto, nunca mas de 100 por ejecucion.
- Cierre excluye cambios pagados exigibles pendientes de activacion y contratos
  domiciliados dentro del plazo, evitando ocupar repetidamente el lote con
  contratos que todavia no deben cerrarse. Sin cambios de frecuencia ni commits
  manuales; se usa exclusivamente el cursor/transaccion de Odoo.
- Una sola regla de propiedad del ciclo de vida: sitios de acceso persistidos,
  contrato domiciliado o evidencia de una operacion comercial POS pagada y
  positiva (incluye ventas autorizadas al 100%). Cobrar una factura nativa
  mediante `pending_charge` no transfiere por si solo esa responsabilidad a WGS.
- Los tres crons nativos (facturacion, expiracion y recordatorios) excluyen esos
  contratos de sus selecciones ORM y de los resultados SQL de expiracion. Se
  filtra antes del limite ORM y tambien antes de cerrar lotes explicitos. Un
  lote explicito totalmente WGS termina vacio, sin convertirse en busqueda global.
- El cron WGS solo cierra contratos de su responsabilidad. El cierre manual
  nativo se conserva. No se cambian flags/frecuencias de crons en la base ni se
  agregan cursores, transacciones, threads o conexiones externas. Se retira del
  XML la desactivacion global del cron nativo; esto NO reactiva crons ya apagados.
- Una sola extension PaymentScreen para preflight y politica de solo tickets.
  Se conservan bloqueo de Facturar/Informacion, reembolsos, apertura de puerta,
  bloqueo/desbloqueo, manuales, WellHub, TotalPass, multisede y bitacoras.
- El upgrade no recalcula ventas aplicadas ni migra fechas, pagos o personas. Los
  snapshots previos conservan sus reglas y fechas contratadas.

### Puerta de validacion

Las pruebas comerciales ahora usan `product.pricelist.item` con `plan_id`, el
esquema nativo de esta instalacion Odoo 19. El helper de compra pasa por
`pos.order._process_order` con payload de linea y pago nativo; ya no simula un
cobro escribiendo solamente `state=paid`.

Se inspecciono un checkout local de Odoo 19 Enterprise, pero no hay un runtime
Odoo ejecutable con sus dependencias y base PostgreSQL. La suite ORM y sus locks/savepoints,
restricciones y hooks no se han ejecutado aqui. No promover a main hasta pasar
esa suite y las pruebas operativas. Los tests aislados no sustituyen este paso.
El checkout Enterprise inspeccionado no coincide con la revision reportada por
produccion: el gate debe utilizar el build exacto de staging.

Resultado local de esta iteracion: 53 pruebas Python y 20 JavaScript aprobadas,
mas sintaxis de todos los modulos JS del addon, referencias de assets y
`git diff --check`. La seleccion SQL se ejecuta localmente sobre SQLite para
comprobar orden/filtros/limites; esto NO valida PostgreSQL ni la concurrencia ORM.

Ejecutar la suite en una copia desechable de staging, desconectada de gateways,
cajeros y dispositivos; nunca sobre la base operativa. Con la configuracion y
addons de staging, indicando el nombre real de esa copia:

```sh
venv/bin/python3 src/odoo-bin -c odoo.conf -d WGS_POS_VALIDATION_DB \
  -u witann_group_subscriptions,witann_group_subscriptions_pos --test-enable \
  --test-tags /witann_group_subscriptions,/witann_group_subscriptions_pos --stop-after-init \
  --max-cron-threads=0 --no-http
```

Los 35 casos ORM de operaciones POS incluyen regresiones del conflicto nativo;
tambien se actualizan los fixtures base a `type`, `product_uom_id` y plan en la
cabecera. Esto no constituye un resultado de ejecucion ORM.

En staging operativo: build, actualizar WGS base a `.1.1.58` y POS a `.1.6.3`; recargar las cajas
cuando sus tickets esten sincronizados. No borrar almacenamiento local.

| Prueba | Resultado esperado |
| --- | --- |
| Nueva mensual y diaria | Plan, precio y fechas de la cotizacion; diario sin siguiente factura |
| Reinscribir diario -> mensual, mensual -> trimestre/semestre/anual y a la inversa | Plan destino y plazo comprado, sin heredar el anterior |
| Reinscribir pareja/trio -> personal y personal -> pareja/trio | Titular/participantes/cupo correctos, sin participantes anteriores colgados |
| Renovar mensual -> anual y semestre -> mensual | Periodo previo intacto; paquete, plan y participantes nuevos al terminarlo |
| Cambiar plan del mismo producto al renovar | Tambien programado; no cambia beneficios de inmediato |
| Dos renovaciones futuras; cron atrasado | Orden de compra conservado, aplicacion una sola vez y sin recobro |
| Cola en revision junto a otro cliente elegible | La segunda suscripcion sigue avanzando |
| Mas cambios exigibles que el limite del cron | Fuentes pendientes pagadas no se cierran por adelantado |
| Facturacion, expiracion y recordatorios nativos activos: ultimo dia inclusivo con cambio pagado | Ninguno cierra, factura ni recuerda deuda de WGS; acceso previo vigente |
| Dia siguiente: crons nativos antes/despues de activacion WGS | Cambio pagado aplicado una vez; paquete/plan/horario destino y fechas firmadas |
| Membresia WGS de backend y contrato domiciliado, sin venta POS | Tampoco son procesados por automatizaciones nativas |
| Suscripcion ajena a WGS y cobro POS de factura nativa | Sigue bajo facturacion/cierre nativos; WGS no la cierra |
| Cierre manual de membresia WGS | Accion explicita conservada; no confundir con cierre automatico |
| Catalogo cambia despues de pagar una renovacion futura | Al activarse conserva precio, plan y fechas comprados |
| Reinscribir trimestral con 100% autorizado y luego renovar | Primer ticket cero; siguiente cobro normal y plan trimestral |
| Domiciliado retroactivo, abono parcial de meses, ponerse al corriente y adelantar | Cartera exacta; acceso solo al corriente; conserva ciclos anteriores |
| Reembolso total con cambios futuros; intento parcial/repetido | Cancela todo lo correspondiente; rechaza parcial y duplicado |
| Respuesta de cobro perdida/reintento/fallo de acceso | Una aplicacion comercial; reintenta solo proyeccion de acceso |
| Inicio/fin inclusivos, corte 29/30/31, alineados y multisede | Calendarios, sitios, horarios y bloqueos conservados |
| Facturar, Recibo/Factura e Informacion en distintas vistas | Restricciones vigentes, con impresion de ticket funcionando |

La concurrencia con dos workers y entrega real de acceso a dispositivo de prueba
siguen siendo validaciones operativas obligatorias. No se cambio la asignacion
de IDs ni el protocolo SpeedFace. La sustitucion del guard DOM restante y de los
setters dinamicos del ticket no se incluye sin una suite de carga/UI contra el
build exacto de Odoo; esos riesgos no se dan por resueltos en esta iteracion.
En la copia desechable, probar expresamente los tres jobs nativos con sus flags
activos; ejecutar sus metodos de forma controlada y con fechas congeladas. No
habilitar automatizaciones ni conexiones a dispositivos de produccion en esa copia.

Estado: implementacion local y pruebas aisladas ejecutadas. NO desplegado desde
esta tarea; NO validado todavia contra Odoo 19 Enterprise. NO autoriza promover a
main ni ejecutar reparaciones historicas. La auditoria original conserva el
diagnostico del checkout previo en `AUDITORIA_FLUJOS_SUSCRIPCIONES_2026-09-28.md`.

### Incidente y reparacion puntual autorizada: 2026-10-14

- Tickets `2648-8-000039` y `2648-8-000040`, fuentes `S02753` y `S01402`.
  Cambio pagado de Estudiante a Horario Especial, con periodo firmado
  14/octubre-13/noviembre y siguiente cobro 14/noviembre.
- OdooBot cerro ambas fuentes durante el ultimo dia inclusivo, 13/octubre. La
  activacion encontro la revision modificada y dejo las compras en revision.
  La huella coincide con la cotizada al restaurar solamente el estado activo.
- En produccion estaban activos los tres jobs nativos. El core inspeccionado
  incluye `end_date <= hoy` en facturacion/cierre automatico. Es una ruta que
  reproduce el defecto; el historial no identifica por si solo cual cron cerro
  cada registro. No se atribuye un job concreto sin esa evidencia.
- Reparacion atomica solo de esas dos compras, con dry_run, locks, comprobacion
  de revision/cotizacion y verificacion posterior por otra conexion. Aplicacion
  mediante el handler existente y resincronizacion normal del acceso. Se
  conservaron fechas firmadas, cobros, hashes y personas existentes; sin fusionar
  personas ni intervenir contratos adicionales. Se retiro la accion temporal.
- Resultado confirmado: ambos en progreso, mensualidad SM, Horario Especial,
  acceso habilitado en Odoo. Upserts `33994`/`33995` encolados; entrega fisica a
  SpeedFace NO verificada. No se modificaron configuraciones globales de crons
  ni se desplego este refactor en produccion.

## Reglas confirmadas

- Nueva: solo sin historial; inicio elegido explicitamente, incluso retroactivo.
- Renovar: conserva el periodo pagado y agrega el plazo del paquete comprado.
  Si cambia el paquete, beneficios y participantes entran al terminar el periodo
  actual. La ficha muestra el paquete actual y el cambio futuro por separado.
- Reinscribir: origen cerrado/cancelado; nuevo paquete, plan, participantes e
  inicio explicitos. En planes alineados se prorratea tanto al repetir paquete
  como al cambiarlo.
- Cambiar paquete inmediato: conserva el flujo de upsale, distinto de renovar
  cambiando paquete al siguiente periodo.
- Domiciliado: conserva seleccion de mensualidades, meses vencidos, anticipos y
  acceso condicionado a estar al corriente. Un nuevo ciclo no borra el anterior.
- Reembolso de membresia: solo total de la linea original (cantidad, precio y
  descuento). Cancela la membresia y sus cambios futuros pendientes; no acepta
  un segundo reembolso del mismo pago. No cambia las reglas de productos normales.
- El descuento autorizado pertenece a un pago, no al precio de futuras compras.
- Las fechas comerciales son locales e inclusivas: inicio a las 00:00 y acceso
  durante todo el ultimo dia. El siguiente cobro es un limite exclusivo. Los
  pases diarios no generan facturas recurrentes nativas.

## Ajuste de corte mensual: 2026-10-14

Implementado localmente en `staging`, version POS `19.0.1.6.1`. Requiere upgrade
del addon antes de abrir POS: agrega `sale.order.wgs_monthly_cutoff_day`.
No modifica main ni las vigencias existentes durante el upgrade.

- Solo planes de exactamente un mes, no alineados ni domiciliados.
- Alta/reinscripcion 20/abril -> 20/mayo inclusive. Corte persistido: dia 20.
- Renovacion continua 21/mayo -> 20/junio, siguiente cobro 21/junio.
- Corte 31: 31/enero -> 28/febrero (29 en bisiesto), luego 1/marzo -> 31/marzo,
  luego 1/abril -> 30/abril. El corte original no se pierde.
- Si se renueva con atraso, el inicio sigue siendo el dia de la operacion;
  el fin usa el corte guardado en el mes siguiente. Reinscribir establece
  un corte nuevo desde la fecha de inicio elegida.
- Las suscripciones sin corte persistido conservan su periodo pagado. Su primera
  nueva compra mensual fija el corte desde el inicio de ese nuevo periodo.
- Los cambios de paquete futuros toman el corte del ultimo periodo pagado en
  cola; no cambian el corte actual hasta aplicarse. Pasar a diario, semestre,
  anual, alineado o domiciliado no propaga un corte mensual residual.
- El corte viaja en el snapshot firmado y se aplica junto con las fechas. Los
  snapshots anteriores conservan sus fechas, con corte cero. Las huellas de
  origen antiguas no cambian por agregar un campo vacio.
- No se modificaron precios, IVA, descuentos, horas de acceso, crons, cuotas
  domiciliadas ni el calendario de reconstruccion de reparaciones historicas.

Pruebas locales: 86 tests Python y 14 tests Node aprobados. Incluyen 1,096 dias
de inicio de 2026-2028 con doce renovaciones por fecha, contratos nuevos,
reinscripciones, adelantos, cola futura, legado y excepciones. Los tests ORM
fueron ampliados/ajustados, pero no ejecutados aqui por falta de Odoo Enterprise.

Pruebas operativas tras upgrade y recarga del POS en staging:

| Caso | Esperado |
| --- | --- |
| Alta mensual con inicio 20/octubre | Fin 20/noviembre, mismo importe |
| Dos renovaciones anticipadas de ese contrato | Fines 20/diciembre y 20/enero, sin desplazamiento |
| Reinscribir diario/semestral en mensual con inicio 20/octubre | Plan mensual y fin 20/noviembre |
| Inicio 31/octubre, renovar anticipadamente | Fin inicial 30/noviembre; siguiente fin 31/diciembre |
| Inicio 31/enero 2027, renovar anticipadamente | Fin inicial 28/febrero; siguiente fin 31/marzo |
| Renovar cambiando paquete mensual | Conserva corte; beneficios/participantes nuevos solo al finalizar periodo previo |
| Semestre -> mensual | Plazo mensual del destino; semestre pagado intacto |
| Mensual -> semestre -> mensual con cambios futuros | Solo la etapa mensual usa corte; no hereda una regla incorrecta de la cola |
| Alineados, domiciliados, diarios, quincenas, semestres y anualidades | Misma regla e importes anteriores |
| Suscripcion y cambio futuro pagados antes del upgrade | Fechas originales intactas, sin recalculo ni doble aplicacion |

No borrar almacenamiento del POS si hay tickets pendientes. Para comprobar la
regla nueva usar una cotizacion nueva: una cotizacion anterior firmada mantiene
su calendario original. No promover a main hasta validar la matriz en staging.

## Responsabilidades

1. `subscription_contract.py`: calendario puro, serializacion canonica y huella.
2. `pos_order_pricing.py`: catalogo y cotizacion con el plan destino explicito.
3. `subscription_operation.py`: firma de cotizacion, validacion, aplicacion
   idempotente, programacion y reintento de la proyeccion de acceso.
4. `pos_order.py`: adaptador nativo Odoo 19 y manejadores comerciales existentes.
   Se retiraron la asociacion por producto aproximado, la inferencia del titular
   por posicion del participante y los helpers de reparacion comercial obsoletos.
5. `sale_order.py` del modulo base: lectura unica del periodo persistido y
   proyeccion central de acceso. No reconstruye vigencias desde el plan actual.
6. `domiciliation.py`: ciclos historicos conservados; solo uno activo por suscripcion.
7. `subscription_period_repair.py`: propuesta historica explicita y aprobada,
   separada de volver a aplicar una venta.
8. Frontend: cotizacion vigente por formulario, metadata serializada en la linea
   nativa por UUID, control de respuestas tardias y de doble envio al ticket.

## Cadena del pago

`Cotizacion backend -> snapshot firmado -> linea UUID -> validacion previa al
pago -> procesamiento nativo Odoo -> aplicacion comercial -> comprobante de
aplicacion -> proyeccion de acceso`.

- La firma incluye empresa, cliente, flujo, producto, plan, fechas e importes.
  La revision del origen detecta cambios entre cotizar y pagar. Se normalizan
  numeros enteros decimales para sobrevivir a la serializacion Python/JavaScript.
- No se sustituye el titular del ticket por un participante. Cambiar de persona,
  producto o empresa requiere una cotizacion que corresponda a esos datos.
- Las lineas se enlazan por UUID, producto y cantidad, no por el primer producto
  coincidente. El JSON es un campo nativo que sobrevive al guardado de borradores.
- El comprobante por linea registra huella, revision y periodo. Reintentar el
  mismo pago no extiende ni reactiva otra vez la suscripcion, aun si ya cerro.
- Una linea historica vinculada no se reproduce automaticamente por encontrar
  hoy su suscripcion cerrada. Un vinculo por si solo tampoco prueba que las fechas
  historicas sean correctas: eso requiere auditoria.
- La cotizacion se valida antes del procesamiento nativo; la aplicacion se
  verifica nuevamente dentro de la transaccion. Una revision obsoleta falla en
  lugar de inventar otra vigencia o aplicar el pago a otra persona.
- Se usa el cursor/entorno de Odoo, bloqueos de filas en orden estable y
  savepoints. No se agregan commits manuales, hilos ni llamadas a dispositivos.
  Los errores de serializacion/deadlock se devuelven al reintento nativo de Odoo.
- En nuevas inscripciones, ademas del bloqueo del titular se genera una version
  MVCC de su fila sin cambiar valores (`write_date = write_date`). Odoo usa
  Repeatable Read: un simple bloqueo no actualiza la foto de otra transaccion
  que ya consulto el historial. Esta escritura hace que una venta concurrente
  del mismo titular reintente con una foto fresca antes de aceptar otra alta.
- Durante el cambio comercial se difiere la proyeccion central. Al final se
  proyecta el resultado. Si esa etapa falla, se conserva el resultado comercial
  y queda un pendiente persistente: no se pide cobrar de nuevo.

La confirmacion bancaria externa y el pago Odoo no son una transaccion distribuida.
Ante respuesta perdida o rechazo posterior del servidor, verificar el ticket y
el terminal antes de intentar otro cargo. No interpretar un error de red como
prueba de que no se cobro.

## Cambios futuros y acceso

- Los cambios futuros guardan la cotizacion y participantes de ese periodo sin
  alterar el paquete actual. La siguiente renovacion toma por defecto el ultimo
  paquete programado y comienza despues del ultimo periodo ya comprado.
- Los cron existentes de acceso/cierre aplican primero los cambios vencidos;
  no se agrega otro cron. El lote inicial tiene un limite de 100 lineas.
- Cada activacion verifica la revision esperada. Si hay conflicto queda en
  `review` con mensaje en la suscripcion, no se aplica a ciegas. Los periodos
  siguientes no saltan sobre una operacion anterior pendiente de revision.
- La ficha informa pagos programados y proyeccion pendiente. Una revision exige
  intervencion administrativa antes de otro cobro, no otra venta para compensar.
- Limite explicito: una conversion legacy a domiciliado pagada pero aun futura
  bloquea otro cobro de esa suscripcion hasta activar el ciclo. No se crea un
  segundo contrato inicial para simular un abono. Los anticipos se pueden elegir
  en la contratacion original. Validar este comportamiento con operacion antes
  de liberar; la cobranza adicional sobre ciclos aun no activados no se implementa.
- El reintento automatico de acceso procesa hasta 100 ordenes y espera al menos
  una hora entre intentos de la misma orden. No vuelve a ejecutar la venta.
- El inicio efectivo de beneficios depende de la ejecucion del cron existente.
  Este cambio no garantiza entrega fisica a las 00:00 exactas. Medir esa latencia
  en staging con la frecuencia real; no modificar frecuencias sin revisarlas.
- No se modifican protocolos SpeedFace, PINs, horarios ni comandos de dispositivos.
  Una proyeccion correcta en Odoo no prueba que el dispositivo haya recibido y
  confirmado los comandos: esa entrega es una comprobacion separada.

## Cobertura de hallazgos

| Hallazgo original | Cambio | Estado de validacion |
| --- | --- | --- |
| H1: reproducir pagos al encontrar origen cerrado | Recibo idempotente y no replay de vinculados legacy | Aislado; ORM pendiente |
| H2: dia residual / fechas de reparacion | Plan destino explicito, periodo persistido y reparacion aprobada | Calendario aislado; ORM pendiente |
| H3: respuestas A/B y cambio de formulario | Tokens de cotizacion y guardas al enviar ticket | JavaScript aislado |
| H4: asociacion aproximada de lineas | UUID exacto y campo JSON nativo | Aislado; POS real pendiente |
| H5: acceso intermedio | Diferimiento central y pendiente de proyeccion durable | Aislado; ORM/dispositivo pendiente |
| H6: fechas recalculadas en vista/navegador | Lectura central del periodo y snapshot backend | Aislado; UI real pendiente |
| H7: borrar cuotas historicas | Ciclos separados, propietario/moneda congelados | Upgrade/ORM pendiente |
| H8: reglas contradictorias | Prorrateo en ambas reinscripciones y reembolso total | Aislado; POS real pendiente |
| H9: falta de regresion integral | Suite standalone y fixtures de integracion preparadas | NO cerrado hasta ejecutarlas en Enterprise |

## Pruebas locales

Ejecutadas: 18 pruebas Python y 13 JavaScript, sin fallos. La prueba de calendario
recorre 720 combinaciones; se revisa sintaxis y referencias globales Python de los
addons. Tambien se comprueba sintaxis JavaScript y `git diff --check`.

```sh
python3 -m unittest discover -s tests/standalone -v
node --test tests/standalone/subscription_quotes.test.mjs
for f in witann_group_subscriptions_pos/static/src/js/*.js; do node --check "$f" || exit; done
git diff --check
```

Python necesita `python-dateutil`. Algunas pruebas ejecutan cuerpos reales de
metodos con colaboradores simulados: NO son pruebas del ORM ni del POS completo.
Se verifico en una imagen Community Odoo 19 la firma `_process_order(order,
existing_order)`, el fixture POS y la disponibilidad de `models.UniqueIndex`.
No se modificaron contenedores o bases existentes para esa inspeccion.

Hay 14 pruebas comerciales de integracion preparadas en
`witann_group_subscriptions_pos/tests/test_subscription_operations.py`, ademas
de las de calendario/precio. Incluyen reintentos, respuesta perdida, historial
cerrado, titular independiente del orden de participantes, dia -> mes, dos
periodos futuros, reembolsos, fallo de proyeccion y ciclos domiciliados.
Los fixtures comerciales crean ordenes y marcan su estado pagado: NO sustituyen
la prueba del terminal, del payload completo `sync_from_ui` ni de concurrencia.
No se ejecutaron porque falta `sale_subscription` Enterprise en este entorno.

## Actualizacion segura de staging

1. Usar una copia desechable de staging para tests automatizados, con el mismo
   Odoo 19 Enterprise y dependencias de produccion. Deshabilitar salida a los
   dispositivos reales y servicios externos en esa copia, sin cambiar PINs.
2. Conservar backup conjunto de base, filestore y commit previo. No mezclar ventas
   reales con la bateria de pruebas. Terminar/revisar tickets pendientes antes
   del upgrade; nunca borrar almacenamiento local con pagos sin sincronizar.
3. Actualizar juntos `witann_group_subscriptions` a `19.0.1.1.57` y
   `witann_group_subscriptions_pos` a `19.0.1.6.0`, reiniciar workers y recargar
   los POS despues de confirmar que las columnas/modelos quedaron disponibles.
4. En la copia desechable, ejecutar upgrade con `--test-enable`,
   `--test-tags /witann_group_subscriptions,/witann_group_subscriptions_pos` y
   `--stop-after-init`. No correr esos tests contra main ni una caja operativa.
5. Confirmar que los contratos domiciliados existentes conservan cuotas,
   propietarios, moneda y saldos; el nuevo indice admite un solo ciclo activo.
   No se hace migracion automatica de pagos o fechas historicas.
6. Los tickets abiertos con cotizacion vieja/no firmada necesitan recotizacion
   si aun no se cobraron. Los ya cobrados se revisan por su UUID, no se revenden.
7. Mantener la version en staging hasta completar la matriz y revisar logs.

## Matriz operativa obligatoria

Registrar por caso: empresa/POS, cliente, UUID de orden/linea, recibo, importes con
IVA, plan, inicio/fin, participantes, estado de aplicacion y acceso esperado/real.
Repetir los casos principales en Santa Monica y El Dorado.

| Caso | Resultado esperado |
| --- | --- |
| Nueva mensual hoy, pasada y futura | Periodo desde fecha elegida, precio normal, acceso solo dentro de vigencia |
| Nueva para persona con historial | Sin opcion de nueva; validacion backend tambien rechaza |
| Diario / quincenal / mes / semestre / anual | Plazo destino exacto, sin heredar DIA ni SEMESTRE anterior |
| Dia -> mes; semestre -> mes | Plan, paquete, fechas y precio del destino coherentes |
| Renovar vigente y por renovar | Conserva lo pagado; no usa descuento del pago anterior |
| Renovar solo -> pareja antes de vencer | Solo conserva beneficios actuales; pareja/participante entra despues |
| Dos renovaciones futuras consecutivas | Sin solapamiento; cada periodo conserva sus participantes y plan |
| Modificar manualmente origen antes de activacion | Revision visible; no reemplazo silencioso ni salto al periodo siguiente |
| Reinscribir pareja/trio -> individual | Solo titular elegido, sin participantes anteriores |
| Reinscribir individual -> pareja/trio | Selector disponible, capacidad validada y participantes correctos |
| Reinscribir participante como titular | Ticket y nueva etapa pertenecen a esa persona, no al titular anterior |
| Reinscribir alineado mismo/diferente paquete a mitad de mes | Ambos proporcionales; inicio real y fin del mes |
| Cambio inmediato de paquete (upsale) | Conserva su regla propia, separado del cambio futuro de renovacion |
| Descuento supervisor 0%, parcial y 100% | Afecta solo ese pago; siguiente cotizacion vuelve al precio normal |
| IVA y posicion fiscal | Importe modal = ticket = pago; revisar incluidos/excluidos |
| Domiciliado alta primer mes y ultimo / consecutivos | Solo cuotas seleccionadas, proporcional e IVA correctos |
| Domiciliado retroactivo, abono parcial y liquidacion | Sin acceso con adeudo; vuelve al corriente sin duplicar cuotas |
| Domiciliado anticipos y nuevo ciclo | Permite adelantar; ciclo anterior conserva cuotas y pagos |
| Legacy domiciliado que renueva | Nuevo ciclo explicito, no deuda historica inventada; no segundo ciclo mientras espera activacion |
| Reembolso parcial de membresia | Rechazado antes de pago; backend tambien lo rechaza |
| Reembolso total y segundo intento | Cancela una vez; segundo reembolso rechazado |
| Reembolso de compra con cambio futuro | No activa despues el cambio cancelado |
| Producto ordinario y devolucion ordinaria | Sin cotizacion de membresia ni bloqueo indebido |
| Cotizacion A lenta despues de B, cerrar/cambiar cliente | No sobrescribe seleccion ni revive formulario |
| Borrador, recargar POS y pagar | UUID/metadata conservados, una aplicacion |
| Doble click, respuesta perdida y reenvio | Una venta aplicada, sin doble plazo ni segundo cobro |
| Dos cajas/workers renuevan simultaneamente | Uno aplica; otro recotiza/revisa, no dos aplicaciones de la misma revision |
| Dos cajas inscriben al mismo cliente nuevo | Una sola alta; la segunda ve historial despues del reintento transaccional |
| Fallo de proyeccion de acceso | Pago/periodo conservados; pendiente visible; retry no extiende fechas |
| Ultimo dia, despues de 18:00, medianoche y primer dia futuro | Limites locales correctos sin desplazar vigencias por UTC |
| Multisede, horario, bloqueo, manual y participantes | Conserva origen/empresa y restricciones; no confundir acceso manual |
| Abrir puerta, resincronizar, WellHub, TotalPass | Botones conservados y bitacora correcta |
| Facturacion e informacion de producto | Restricciones POS existentes conservadas |
| Auditoria historica y dry_run dirigido | Sin escrituras; fecha/plazo propuestos revisables antes de aprobar |

## Criterio de salida y recuperacion

No promover a main hasta: upgrade limpio, tests Enterprise aprobados, matriz
manual con evidencia, concurrencia de dos workers y recuperacion de respuesta
perdida verificadas. Confirmar entrega a un dispositivo de prueba, no asumirla
por el indicador verde de Odoo. Vigilar pendientes/revisiones y duracion del cron.

El rollback de staging es restaurar base+filestore+codigo previos de esa copia,
no desinstalar addons ni bajar solo el codigo despues de generar operaciones
programadas. No borrar recibos de aplicacion ni cuotas para "volver a intentar".
Un eventual rollback productivo requiere revisar las ventas posteriores al
despliegue; no restaurar una base antigua perdiendo cobros reales.

La reparacion masiva por inferencia queda deshabilitada. La API dirigida requiere
plan, inicio historico y digest de la propuesta; una aprobacion queda invalidada
si cambia la suscripcion o el pago. No se ejecuto ninguna reparacion de datos.
