# Refactor comercial de suscripciones: validacion en staging

Registro inicial: 2026-09-28. Rama de trabajo: `staging`.

## H3: historial despues de reembolso, 2026-10-21

**H3 corregido y validado por navegador en staging POS `19.0.1.6.7`.**
Codigo desplegado: `60afffa`. Base sin cambios (`19.0.1.1.59`).
No se ha autorizado ni realizado merge a main.

El QA del 20/oct sobre `5d322fc` verifico H1 (primera prueba gratis ED/SM,
bloqueo de CURP repetida incluso entre sedes) y H2 (contratos independientes
de titular/participante, renovacion y reembolso aislados). Fueron ocho
operaciones ficticias: siete ventas y una devolucion. El nuevo hallazgo H3:
S03632 seguia cancelada y con pagos nativos, pero el directorio la omitia y
permitia cotizar una alta nueva. No se confirmo esa alta.

### Correccion y limites

- Odoo limpia `is_subscription/subscription_state` al cancelar. Una sola
  regla de identidad reconoce ademas el contrato cancelado con lineas
  recurrentes y compras positivas POS pagadas aplicadas a ese contrato.
- Relacion inversa `wgs_pos_application_line_ids` sobre el destino real
  `wgs_sale_order_id`, no sobre el origen del participante. Aprovecha los
  enlaces existentes; no necesita reescribir historicos ni hacer backfill.
- Directorio, detalle y validaciones comerciales incluyen las canceladas
  mediante un dominio compartido `any`/EXISTS de pagos positivos. No se
  cargan todas las cotizaciones canceladas para buscar esa evidencia.
- La cancelacion de venta prevalece sobre etiquetas, fechas futuras o un
  contrato domiciliado desactualizado: sin acceso, Renovar ni Cambiar plan;
  se permite Reinscribir, nunca Nueva suscripcion por perdida de historial.
- Reinscribir una venta nativa cancelada crea un contrato confirmado nuevo,
  incluso para el mismo titular. Se conserva procedencia y se verifica que
  el origen no cambio. No se reactiva una venta reembolsada ni se mezclan
  pagos. Otro contrato vigente/futuro impide repetir esa reinscripcion.
- El titular de una venta confirmada cerrada por vencimiento conserva el
  flujo existente. Los participantes siguen comprando contratos propios.
- No se modifican main, produccion, importador bancario, Payroll POS,
  calendario, crons ni protocolo SpeedFace. Los commits Payroll existentes
  en staging se conservan sin editar.

### Verificacion local

106 tests Python y 26 JavaScript aprobados; siete nuevos tests aislados de
H3 ejecutan cuerpos de metodos de produccion. Dos nuevos tests ORM cubren
directorio individual/lote, bloqueo de alta, reinscripcion, conservacion de
pagos y rechazo de cotizaciones canceladas sin compra. Total: 52 tests ORM
preparados, no ejecutados por falta de runner/base desechable. No sustituir
ese requisito con ejecuciones sobre la base operativa de staging.

Logs: `/tmp/wgs-qa-20261021-h3/{python,source-calendar,javascript}.log`.
El Python del sistema no tenia `dateutil`; las ejecuciones aprobadas usan
el runtime Python incluido en Codex. `git diff --check` sin errores.

### Resultado por navegador: 2026-10-21

CloudPepper mostro `60afffa451cbfeb7699321e8a4467c189d5899af` como commit
instalado del repositorio staging. Se actualizo la lista de aplicaciones y
exclusivamente WGS POS; Aplicaciones confirmo instalada/disponible `19.0.1.6.7`.
No se actualizo Enterprise, Payroll, importador bancario ni produccion.
No se ejecuto la funcion CloudPepper Refresh Staging from Production; su
dialogo se cancelo sin copiar/restaurar la base de produccion.

Se probo sobre el contacto ficticio existente `QA WGS 20261020 R6 Miembro`
en El Dorado, sin reescribir el fixture que habia fallado:

| Caso | Resultado observado |
| --- | --- |
| Recuperar S03632 reembolsada antes del upgrade | Cancelada visible, sin acceso, con Reinscribir; no Nueva suscripcion ni Renovar. No backfill/manual write. |
| Reinscripcion desde S03632 | Recibo `263-3-000129`, $799; contrato nuevo S03635 confirmado, MENSUALIDAD ED, 21/oct-21/nov/2026; una persona activa. |
| Preservar origen S03632 | Cancelado, mismo titular, plan y fin 20/dic; pagos positivos `000124` y `000126` por $799 cada uno siguen ligados solo al origen. |
| Reembolso total de compra nueva | Recibo `263-3-000130`, -$799; S03635 cancelada y acceso retirado. |
| Recarga normal despues de devolver | S03635 sigue visible como Cancelada, no Sin suscripcion; Reinscribir disponible y alta nueva ausente. |
| Segunda reinscripcion desde S03635 | Recibo `263-3-000131`, $799; S03636 nuevo confirmado y con acceso, 21/oct-21/nov/2026. Origen nativo `Reinscripcion desde S03635`. |
| Aislamiento del contrato devuelto | S03635 sigue cancelado, origen `Reinscripcion desde S03632`, periodo conservado y unico pago positivo `000129`; no recibe el `000131`. |
| Control de titular original | S03631 sigue en progreso, acceso activo, 20/oct-20/nov/2026, titular/participante propio y pagos `000123` ($1,398.99) y `000125` ($799). |
| Control de renovacion posterior | Solo cotizacion de S03636: $799, 22/nov-21/dic/2026. Cancelada sin agregar/cobrar, conserva corte 21. |

**Tres operaciones confirmadas: dos ventas ficticias y una devolucion.**
No se duplicaron cobros, no se publicaron/timbraron facturas, no se aplicaron
accesos manuales ni se borraron contactos/tickets/cache. Pendientes previos
3058, 3065 y 3119 intactos; se termino con 3132 vacio. El aviso de impresora
no disponible es del entorno: continuar sin imprimir, nunca repetir la venta.

El detalle mantiene su regla previa de mostrar el contrato comercial de
mayor prioridad/mas reciente, no todas las tarjetas antiguas a la vez. La
cancelada vuelve a ser operable cuando no hay otra activa; los contratos y
pagos completos se verificaron en las vistas nativas de Ventas/POS.

**Sin nuevos fallos comerciales observados en este alcance.** No es una
reejecucion de toda la matriz del refactor: H1/H2 de 20/oct y sus pruebas
previas se conservan como evidencia separada. Los 52 tests ORM, concurrencia
real, rollback PostgreSQL y entrega fisica SpeedFace siguen sin ejecutarse.

Capturas y estado estructurado:
`/Users/apreza/.codex/visualizations/2026/02/18/019c72fb-fa85-7b22-a4fa-20aa1262c18f/wgs-staging-qa-60afffa/`.
Main y origin/main permanecen en `df4e525`.

## Correccion de H1 y H2: 2026-10-20

**Candidato en staging, pendiente build/upgrade y repeticion por navegador.**
No aprobado para main. POS sube a `19.0.1.6.6`; base se conserva en
`19.0.1.1.59`. El QA de `34db870` documentado abajo es evidencia del build
anterior, no una aprobacion de estas correcciones.

### Limites transaccionales y de identidad

- H1: la elegibilidad publica y la aplicacion comparten la misma regla. Solo
  el metodo privado de checkout recibe el registro servidor de la linea
  pagada que se aplica; verifica orden, cliente, producto, cantidad positiva
  y estado pagado. Excluye exclusivamente esa linea, nunca todo el ticket.
  No se expone una excepcion mediante RPC, payload del navegador o contexto.
- Una CURP de prueba usada se captura en `pos.order.line.wgs_free_trial_curp`,
  con `UNIQUE` PostgreSQL, en la misma transaccion del pago y la membresia.
  La restriccion arbitra usos concurrentes incluso con contactos diferentes.
  Un fallo comercial revierte la captura; reembolso, cambios posteriores de
  CURP o catalogo y replay no liberan el uso. Se mantienen las consultas de
  evidencia legacy, con `search(limit=1)` en lugar de contar todos los usos.
  Antes de cobrar se rechazan dos lineas/unidades de prueba en un ticket;
  el backend repite la validacion al aplicar.
- H2: si compra el titular, se conserva la ruta de reinscripcion existente.
  Si compra un participante del origen cerrado, se crea una suscripcion
  nativa independiente por la ruta compartida de creacion, usando la misma
  cotizacion firmada, plan, precio recurrente y vigencia contratada. Se crea
  un contrato domiciliado propio si corresponde, sin reciclar cuotas ajenas.
- `sale.order.wgs_reenrollment_source_id` y el origen del recibo conservan la
  procedencia del participante. No son una sustitucion por upsale. El origen
  mantiene titular, participantes, producto, plan, fechas, estado y pagos.
  Una postcondicion compara su revision tomada ANTES de aplicar: una
  reasignacion accidental no puede desactivar la comprobacion cambiando el
  propio titular que se usa para decidirla.
- El destinatario aplicado (`wgs_sale_order_id`) manda al consultar pagos y
  devoluciones; `wgs_subscription_source_id` solo representa procedencia.
  Una nueva compra del participante no se agrega a los cobros reembolsables
  del anterior titular ni un reembolso suyo cancela el contrato anterior.
- Se rechaza un comprador ajeno al origen y una nueva reinscripcion desde
  ese mismo origen si el participante ya compro otra membresia vigente o
  futura. La version de fila del comprador, ya utilizada para altas, se usa
  tambien para reinscripciones para forzar retry con snapshot fresco frente
  a dos workers. Los reintentos aplicados conservan su recibo y no crean otro
  contrato. No hay nuevos cursores, commits, threads ni colas externas.

No se reparan ni reescriben automaticamente contratos historicos o fixtures
del QA anterior. Se conservan sus evidencias. Sin cambios a main, importador
bancario, reglas de calendario ni protocolo SpeedFace.

### Verificacion local

- **99 tests Python y 26 JavaScript aprobados**, incluidos 19 nuevos tests
  aislados que ejecutan los metodos de produccion. No sustituyen el ORM.
- **50 tests ORM comerciales preparados, no ejecutados**: cinco nuevos
  escenarios integrados cubren primera prueba/replay/reembolso, unicidad y
  rollback de captura, participante con renovacion y reembolso aislados,
  domiciliacion propia y comprador ajeno. El caso CURP requiere el campo
  configurado en produccion; se omite expresamente si no esta instalado en
  la base desechable. Sigue faltando runner Enterprise/PostgreSQL desechable.
- Logs: `/tmp/wgs-qa-20261020-h1-h2/python.log` y
  `/tmp/wgs-qa-20261020-h1-h2/javascript.log`. `git diff --check` sin errores.

### Repeticion por navegador pendiente de despliegue

El usuario realiza el build y los upgrades. Se requiere actualizar
`witann_group_subscriptions_pos` a `19.0.1.6.6` y recargar el POS conservando
almacenamiento y pendientes. No repetir las ventas fallidas anteriores ni
declarar aprobada la correccion probando sobre `19.0.1.6.5`.

1. ED y SM: contacto QA nuevo con CURP ficticia unica, primera prueba gratis
   pagada por cero, un solo dia y acceso; verificar recibo y suscripcion.
2. Bloquear otro uso de la misma CURP, incluido despues de reembolso/cambio
   del dato en contactos QA. Control: WELLHUB/TOTALPASS siguen renovables.
3. Pareja QA vencida, reinscribir al participante en individual: cliente,
   precio normal, plan, vigencia y acceso propios; suscripcion distinta.
   Titular anterior conserva contrato, participantes y recibos historicos,
   sin opcion de Nueva suscripcion. No modifica su vigencia.
4. Recarga antes de cobrar, renovacion del nuevo titular y reembolso total:
   sin traspaso del origen ni cobro repetido. Control de reinscripcion del
   titular original por la ruta existente.
5. No sustituir por UI las pruebas pendientes de dos transacciones realmente
   concurrentes, rollback PostgreSQL o entrega fisica al SpeedFace aislado.

## Repeticion por navegador del build 34db870: 2026-10-20

**NO APROBADO para main.** Build y upgrades confirmados por el usuario y
versiones verificadas en Aplicaciones: base `19.0.1.1.59`, POS `19.0.1.6.5`.
Se recargo el POS conservando almacenamiento y tickets pendientes. Se probaron
El Dorado (configuracion 3) y Santa Monica (configuracion 8), exclusivamente en
`staging-portal.spinbike.mx`, con contactos sinteticos QA. No se modifico codigo
funcional, catalogos, produccion, importador bancario ni protocolo SpeedFace.
Se continuaron las pruebas independientes despues de encontrar fallos.

### Resultado ejecutivo

- **34 operaciones confirmadas: 32 ventas y dos devoluciones**. Las ventas
  incluyen importes cero, descuentos autorizados y anticipos. No se cuentan
  como exitosos los intentos gratuitos fallidos ni los borradores sin validar.
- **Dos hallazgos de severidad alta**: primer uso de prueba gratis rechazado
  en ambas sucursales; transferencia del contrato historico al reinscribir a
  un participante como titular, dejando al titular anterior sin historial
  visible y con opcion de Nueva suscripcion.
- Los fallos del build anterior de diario, cotizacion S03615, recarga del
  cliente, upsale mismo dia, centavo de IVA y cierre domiciliado explicito no
  reaparecieron en los escenarios efectivamente ejecutados abajo.
- **80 tests Python y 26 JavaScript repetidos: todos aprobados.** Estos tests
  aislados NO detectaron los dos hallazgos de integracion observados. Logs:
  `/tmp/wgs-qa-20261020/python-retest.log` y
  `/tmp/wgs-qa-20261020/javascript-retest.log`.
- **45 tests ORM NO ejecutados**, por falta de runner y base desechable,
  confirmada previamente por el usuario. No se ejecutaron contra la base
  operativa para sustituir ese requisito.
- Anualidad nueva: tras autorizacion explicita del usuario se confirmo el
  pago ficticio de $7,200 en staging. Recibo `263-3-000121`, S03629,
  ANUALIDAD ED, 20/oct/2026-19/oct/2027 y acceso activo. Captura60.

### Hallazgos altos

**H1. La primera prueba gratuita se considera uso previo de si misma.**

Reproducido con dos contactos nuevos e identificadores ficticios distintos:
`QA WGS 20261020 SM Flujo` (inicio 20/sep) y
`QA WGS 20261020 PruebaHoy` (inicio 20/oct). Alta y cotizacion admitidas,
pero al validar aparece: "La CURP ... ya utilizo previamente el dia de prueba
gratis. Solo se permite una vez en la vida." El segundo caso descarta que el
fallo dependa de la retroactividad o de Santa Monica. WELLHUB/TOTALPASS de
precio cero si se vendieron y renovaron correctamente.

Cadena de codigo que explica la reproduccion:

- `witann_group_subscriptions_pos/models/pos_order.py:1965`: el procesamiento
  nativo precede a la aplicacion WGS en la misma transaccion.
- `witann_group_subscriptions_pos/models/pos_order.py:1972` llama
  `_wgs_sync_subscription_sales`.
- `witann_group_subscriptions_pos/models/subscription_operation.py:393`
  procesa ordenes ya `paid/done/invoiced`; en la linea 430 repite elegibilidad.
- `witann_group_subscriptions_pos/models/pos_order.py:682` consulta el uso de
  prueba gratis. La busqueda de POS en la linea 865 incluye los pedidos no
  draft/cancel y no excluye la orden/linea que se esta aplicando. La propia
  primera venta ya cumple ese dominio. La lectura anterior al cobro en
  `subscription_operation.py:244` no presenta esa misma situacion.

No se observo contrato aplicado para el primer contacto en el listado nativo
filtrado por **Cliente** ni en su directorio POS tras el error. No se interpreta
el cambio automatico a ticket vacio como pago exitoso. Se conservaron los
intentos locales 7050 / `267-8-000050` y 3119 / `263-3-000119`, sin reintentar
ni borrar cache. Capturas 43, 55 y 56. No se verifico por SQL la totalidad de
los efectos de rollback.

Correccion propuesta, **no aplicada**: separar elegibilidad previa y aplicacion
del primer uso dentro de la misma frontera transaccional; excluir solamente
el propio evento identificado de la consulta de usos anteriores, sin permitir
otro uso real, duplicados en el mismo ticket ni carreras entre dos ventas.
Agregar integracion de primera venta, repeticion, replay y concurrencia.

**H2. Reinscribir un participante cambia el propietario del contrato historico.**

Se preparo una pareja cerrada en S03611: titular
`QA WGS 20261019 Descuento`, participante `QA WGS 20261019 Pareja`.
Desde la ficha del participante se reinscribio TODO INCLUIDO individual por
$799. Ticket, recarga, pago y acceso individual quedaron a nombre del
participante, pero el recibo 000118 reutiliza **S03611**, no un contrato
independiente. Backend confirma que S03611 ahora pertenece a Pareja.
El antiguo titular aparece **Sin suscripcion**, sin suscripciones relacionadas
y con **Nueva suscripcion**, pese a sus pagos anteriores. Capturas 51-54.

La causa es explicita en
`witann_group_subscriptions_pos/models/pos_order.py:2739`: se escribe el
`partner_id` del origen cuando es diferente al comprador, y se reutiliza ese
origen. La busqueda de historial en la linea 3729 solo resuelve por titular y
participantes actuales; despues de sustituir ambos deja de encontrar al
titular anterior. No se borraron sus tickets anteriores: el fallo demostrado
es el traspaso de identidad del contrato y la perdida del historial visible,
no una desaparicion de los pagos POS.

Correccion propuesta, **no aplicada**: mantener identidad/titularidad del
contrato historico cuando cambia el comprador. Crear una etapa/contrato
independiente vinculada al origen para el antiguo participante, manteniendo
pagos y referencias historicas. Directorio, bloqueo de alta nueva y consultas
deben consultar participacion historica, no solo relaciones actuales. Probar
tambien que renovar/reembolsar la nueva membresia no modifique al otro socio.

### Matriz efectivamente repetida

| Grupo | Resultado observado en este build | Limite |
| --- | --- | --- |
| S03615 vencida antes del cron | Reinscripcion cotiza $799, paga y queda 20/oct-20/nov con acceso | Sin factura ni cierre manual para desbloquear |
| Diario hoy y pasado | DAY PASS pagado, fechas de un dia, acceso hoy/no acceso historico | Siguiente factura vacia comprobada en listado nativo S03619 |
| Renovacion diaria | $99.99, dia siguiente correcto, sin error de fecha ausente | No se espero al cambio real de dia |
| Diario -> mensual | ED y SM: $799, MENSUALIDAD de la empresa, hasta 20/nov, acceso activo | Inicio historico del contrato se conserva en renovacion; periodo cobrado desde 20/oct |
| Diario vigente -> mensual futuro | Cobro confirmado y programacion 22/oct-22/nov; conserva diario actual | Activacion futura no ejecutada |
| Semestre -> mensual | $799, 20/abr-20/may/2027 programado; semestre hasta 19/abr intacto | No se simulo abril cambiando fechas o reloj |
| Corte mensual 29/30/31 | Tres cotizaciones enero -> 28/feb; corte31 futuro comprado sin acceso | Recuperacion del corte en marzo pendiente ORM/avance temporal |
| Upsale mismo dia | Modal y ticket $600; dos integrantes activos; origen nativo terminal hasta 20/nov, sin fecha invertida | Upsale de un ciclo con dias ya transcurridos no repetido |
| Renovaciones futuras encadenadas | Dos periodos consecutivos de S03621, 21/nov-20/dic y 21/dic-20/ene | No se ejecutaron sus activaciones; posteriormente cancelados por refund |
| Solo -> pareja futura SM | $1,398.99; 21/nov-20/dic; titular actual conserva un acceso | Participante sigue sin acceso antes del inicio |
| Reinscribir -> TRIO | Selector, tres personas activas y precio $1,899 correctos | Fixture cerrada explicitamente con factura QA anterior |
| TRIO cerrado -> individual | $799, solo titular y una persona activa | No conserva integrantes antiguos |
| Participante -> titular | Pago/cliente/acceso propio funcionan tras recarga | **Falla aislamiento historico, H2** |
| Cierre domiciliado explicito | Sin acceso y Reinscribir disponible | Se reutilizo el unico borrador contable autorizado de S03611; no se crearon mas |
| Nuevo ciclo DOM tras cierre | Desde 20/oct, primer proporcional $239.62, meses1+12 $858.63; posterior anticipo nov-dic $1,238.02 | Anterior ciclo no se convierte en nuevas cuotas; conservacion completa de cuotas historicas pendiente inspeccion ORM |
| DOM febrero, primer mes solamente | 15-28/feb $309.50; plazo hasta 31/ene/2027; sin acceso con adeudos | Resumen proporcional ya no muestra el fin anual |
| Seleccion DOM | 1; 1+12; marcar3 incluye2; quitar2 retira3; fechas reales e IVA | Seleccion inicial1-3 comprobada en cotizacion, no otro pago distinto |
| DOM abono/regularizacion | Mar-abr pagados sin reactivar; may-oct pagados reactivan acceso | No duplica meses previos |
| DOM anticipos/liquidacion | Nov-ene $1,857.03; Renovar deshabilitado al pagar las doce cuotas | No simula terminacion real del plazo |
| Descuentos | 50% en semestre,100% en renovacion; siguiente cotizacion vuelve a normal y se cobra $799 | No se modificaron posiciones fiscales para fabricar otra combinacion de IVA |
| Recarga de borradores | Alta diaria nueva, reinscripcion, renovacion ED y pareja futura SM pagan sin recuperar manualmente cliente | UUID de todas las lineas no exportado; no equivale a prueba de replay |
| Cliente distinto | Preflight rechaza antes de aplicar; restaurado correcto y cobrado una sola vez en000098 | El usuario ayudo a cerrar la alerta nativa; no es fallo comercial |
| WELLHUB/TOTALPASS | Altas y renovaciones de monto cero confirmadas | TOTALPASS vencido renueva hoy y no se considera prueba gratis |
| Prueba gratis | **Primera venta falla en ED y SM, H1** | No se declara probada venta ni regla de segundo uso exitoso |
| Refund parcial | Rechazo antes de registrar devolucion por cantidad0.5 | No se ha ejecutado ataque directo a API ni suite ORM |
| Refund total | -$600, destino Cancelado nativo, titular/participante sin acceso, origen sigue cerrado | UI ya no muestra cambios futuros; falta comprobar cola durable y no activacion por cron |
| Segundo refund | Cantidad reembolsada1.00; no permite seleccionar/devolver de nuevo | Comprobacion UI, no carrera concurrente |
| Producto ordinario | Agua $17 y devolucion -$17 confirmadas sin flujo de membresia | Exclusivamente productos QA en staging |
| Quincena | QUINCENA ED de2semanas,20/oct-2/nov,$450,un acceso | No se redefine como quince dias ni mensual |
| Anualidad nueva | $7,200 pagados ficticiamente; S03629, ANUALIDAD ED,20/oct/2026-19/oct/2027,una persona activa en ED y SM | Sin entrega fisica SpeedFace; venta autorizada expresamente por el usuario |
| Resincronizar | Exito, una persona activa antes/despues, cooldown visible | No prueba cron por lotes, RSS ni dispositivo fisico |
| Restricciones | Factura deshabilitada en Pago y Ordenes; Informacion deshabilitada en Acciones | No se intentaron permisos administrativos fuera del POS |
| Empresas | Catalogo/plan/acceso ED y SM correspondientes; pareja futura SM preserva beneficios actuales | No se repitio cada combinacion de toda la matriz en ambas empresas |

La tarjeta seleccionada pendiente DOM se vio blanca con borde, mientras la
pagada se vio sombreada y etiquetada Pagada. No se confundio un checkbox
obligatorio con un pago ya realizado. Captura21 inspeccionada visualmente.

### Operaciones confirmadas de esta sesion

Todas son del **20/octubre/2026**. ED usa prefijo `263-3-`, SM `267-8-`.
Hay referencias historicas repetidas en esta copia: identificar siempre por
fecha, cliente, monto y empresa, no solo por el contador visible del ticket.

| Sede / contador | Contrato | Operacion | Total con IVA |
| --- | --- | --- | ---: |
| ED000090 | S03615 | Reinscribir mensual | 799.00 |
| ED000091 | S03619 | DAY PASS hoy | 99.99 |
| ED000092 | S03619 | Renovar diario | 99.99 |
| ED000093 | S03619 | Mensual futuro despues del diario | 799.00 |
| ED000094 | S03620 | DAY PASS historico | 99.99 |
| ED000095 | S03620 | Renovar diario vencido a mensual | 799.00 |
| ED000096 | S03621 | Upsale mismo dia a pareja | 600.00 |
| ED000097 | S03621 | Individual futuro, descuento100% | 0.00 |
| ED000098 | S03621 | Siguiente mensual sin descuento heredado | 799.00 |
| ED000099 | S03611 | Nuevo ciclo DOM, meses1+12 | 858.63 |
| ED000100 | S03611 | DOM anticipar nov-dic | 1238.02 |
| ED000101 | S03622 | DOM desde15/feb, solo proporcional | 309.50 |
| ED000102 | S03622 | DOM abonar mar-abr | 1238.02 |
| ED000103 | S03622 | DOM liquidar may-oct | 3714.06 |
| ED000104 | S03622 | DOM adelantar nov-ene | 1857.03 |
| ED000105 | S03623 | Alta semestre, descuento50% | 2049.50 |
| ED000106 | S03623 | Renovar semestre a mensual futuro | 799.00 |
| ED000107 | S03624 | Alta futura31/ene-28/feb | 799.00 |
| ED000108 | S03625 | Alta WELLHUB | 0.00 |
| ED000109 | S03625 | Renovar WELLHUB | 0.00 |
| ED000110 | S03626 | Alta TOTALPASS retroactivo | 0.00 |
| ED000111 | S03626 | Renovar TOTALPASS para hoy | 0.00 |
| ED000112 | S03621 | Refund total de000096 | -600.00 |
| ED000113 | Sin suscripcion | Agua | 17.00 |
| ED000114 | Sin suscripcion | Refund de agua000113 | -17.00 |
| SM000051 | S03627 | DAY PASS historico | 99.99 |
| SM000052 | S03627 | Renovar diario a mensual | 799.00 |
| SM000053 | S03627 | Pareja futura, borrador recargado | 1398.99 |
| ED000115 | S03611 | Reinscribir TRIO | 1899.00 |
| ED000116 | S03611 | Reinscribir TRIO a individual | 799.00 |
| ED000117 | S03611 | Reinscribir pareja de control | 1398.99 |
| ED000118 | S03611 | Participante a titular: reproduce H2 | 799.00 |
| ED000120 | S03628 | Alta quincenal | 450.00 |
| ED000121 | S03629 | Alta anual, pago ficticio autorizado | 7200.00 |

### Pendientes y limites no sustituidos por pruebas aisladas

- Corregir H1/H2 de manera integrada y repetir sus escenarios, incluidos
  titular anterior, participante, pagos historicos, reembolso y nueva alta.
- Ejecutar45 tests ORM Enterprise/PostgreSQL en base desechable. Sin SSH/runner
  disponible no se aprobaron crons, locks ni concurrencia con dos workers.
- Activacion futura real y retrasada, recuperacion de estados heredados,
  excepcion transitoria de acceso/reintento, reenvio por perdida de respuesta,
  dos altas simultaneas y dos renovaciones sobre la misma revision.
- Ultimo segundo del dia, primer segundo del dia y conversiones reales a las
  18:00/medianoche; no se cambio el reloj del servidor. Acceso vigente hoy o
  programado no prueba por si solo esas fronteras temporales.
- Nuevo ciclo de domiciliado legacy sintetico y proporcional de alineados
  no domiciliados: no se fabricaron cambios de catalogo ni se utilizaron
  clientes reales para suplir fixtures. Upsale con dias transcurridos, otra
  posicion fiscal y todas las combinaciones de plazos no se repitieron.
- No se ejecutaron crons globales sobre clientes copiados. Auditoria historica
  masiva/dry_run y alteracion intencional de origen antes de activar no se
  ejercitaron. La ausencia de review en ventas nuevas observadas no prueba
  que cualquier review historico se recupere correctamente.
- No se probo entrega al SpeedFace: el aislamiento de staging fue confirmado
  por el usuario. Indicador verde solo demuestra proyeccion en Odoo.

### Residuos QA, seguridad y evidencias

Los tickets previos **3058/000058** y **3065/000065** siguen intactos.
Se conservaron los dos intentos gratuitos fallidos. El borrador QA de reembolso
parcial fue descartado despues del rechazo, sin registrar pago, para realizar
el reembolso total; no se eliminaron ventas, cuotas ni recibos de aplicacion.
No se borraron datos locales para ocultar fallos. El usuario cerro una alerta
nativa de cliente incorrecto que bloqueaba el control de esa pestaña; las
comprobaciones independientes de backend continuaron mientras tanto.

Se abrio una sesion QA en Santa Monica con saldo ficticio0 y nota explicita
de pruebas sin efectivo real. No se cerro ni publico su contabilidad. El unico
borrador contable QA de $1 autorizado anteriormente para S03611 no se publico,
timbro, envio ni pago; se reutilizo para cierres controlados. S03611 queda
traspasado al participante, evidencia de H2, no reparado silenciosamente.

La impresion automatica sin impresora produjo avisos tardios en ambas cajas.
Se eligio Continuar sin reintentar cobros ni alterar configuracion global.
El recibo anterior permanece en el DOM de impresion aunque la pantalla actual
sea otro ticket: el cobro anual se detuvo inicialmente tras un bloqueo de
seguridad por esa interpretacion; producto/cliente/monto actuales fueron
verificados tambien visualmente. Tras autorizacion explicita del usuario se
confirmo una sola vez el ticket3121, por $7,200 ficticios, para
`QA WGS 20261020 Anual`, exclusivamente en staging. El recibo000121 y el
directorio confirmaron S03629 y acceso activo. No se evadio ese bloqueo.

60 capturas, estados finales QA y `estado-pruebas.json`, separados del QA del build anterior:
`/Users/apreza/.codex/visualizations/2026/02/18/019c72fb-fa85-7b22-a4fa-20aa1262c18f/wgs-staging-qa-20261020/`.
Sin PIN ni claves guardados intencionalmente. Sugeridas para inspeccion: 04
(reinscripcion),14(cierre upsale),23(proporcional),27(reactivacion),43/56(H1),
45(SM mensual),48/50(TRIO e individual),52-54(H2),60(anualidad aplicada).

No hubo commit/push/merge ni modificaciones a main durante esta validacion.
El codigo evaluado sigue en `34db870`; main conserva `df4e525`.

## Correccion integral de hallazgos QA: 2026-10-20

Estado al entregar el commit, antes del QA registrado arriba: **candidato de staging; pendiente build/upgrades y repeticion por
navegador**. No aprobado para main. El usuario confirmo que aplicara el build y
ambos upgrades; no se sustituye esa comprobacion con ventas sobre el build viejo.
Versiones nuevas: base `19.0.1.1.59`, POS `19.0.1.6.5`.
Solo WGS/POS, sus pruebas y esta bitacora; sin cambios a produccion, importador
bancario ni reglas/protocolo de SpeedFace. No hay reparacion automatica masiva
de los datos historicos ni de las fixtures QA anteriores.

### Fronteras compartidas

- `_wgs_subscription_operation_policy_for_pos` decide Renovar/Reinscribir/
  Cambiar Plan para directorio, ficha, cotizacion y manejadores de pago.
  Superar la gracia permite reinscribir aunque el cron no haya cambiado aun el
  estado nativo. Un contrato futuro, sustituido o cerrado manualmente conserva
  sus restricciones. Directorio resuelve sustituciones por lote, sin agregar
  busquedas por cada fila ni guardar decisiones en caches globales/contexto de
  cobro. No hay escrituras desde esta politica de lectura.
- La activacion de un cambio **ya pagado** es distinta de una nueva compra:
  conserva firma, hash, revision, participantes y periodo original. Un retraso
  mas alla de la gracia no la rechaza por la elegibilidad de una nueva venta.
  Cierres manuales siguen sin reabrirse automaticamente.
- `_wgs_close_subscription_commercially` usa `set_close`, la API mutante nativa,
  y verifica el estado terminal. No ejecuta un wizard ni silencia errores para
  escribir directamente un estado. Conserva el fin del periodo historico del
  origen; no lo mueve a un dia anterior al inicio. El upsale exige tambien
  como postcondicion que el origen distinto del destino haya quedado cerrado.
- En las postcondiciones, ambas fechas se convierten con la misma API Date.
  Ausencias `False`/`None` no producen un falso desacuerdo de vigencia; fechas
  realmente distintas siguen rechazandose. La doble de Date usada en tests
  ahora reproduce el `None` real de Odoo al convertir un valor ausente.
- Modal y ticket proyectan el mismo precio unitario fiscal del upsale. Se
  elimina la resta paralela de dos totales con IVA redondeados por separado.
  En el ejemplo QA previo el cargo real de $600 tambien se mostraria como $600,
  no $599.99; no se alteraron precios de catalogo ni descuentos.
- La carga de clientes usa registros nativos `pos.data.read`, no un objeto RPC
  temporal que pierde su relacion al serializar. El preflight puede resolver el
  titular de la cotizacion persistida si la relacion no esta cargada; nunca
  sustituye a otro cliente seleccionado ni infiere al titular de participantes.
  El backend sigue verificando la firma/identidad. Si falla la carga, no se
  inicia el pago nativo; tampoco si el cajero cambia de ticket durante el await.
- Un cierre nativo **explicito** cancela el ciclo domiciliado activo y conserva
  cuotas/pagos para trazabilidad. No ocurre al abrir el wizard ni con los crons
  nativos, cierre automatico WGS o generacion de renovacion nativa. El historial
  no se borra. Los domiciliados antiguos cerrados por contabilidad NO se migran
  ni cancelan en bloque por su estado nativo: no debe bloquearse su cobranza.
- El proporcional inicial tiene su propio `first_period_end_date`. La primera
  cuota y el resumen muestran fin del mes, separado del fin del plazo forzoso.

Referencia del adaptador POS comprobada contra el codigo oficial de
[Odoo 19: carga nativa de res.partner](https://github.com/odoo/odoo/blob/19.0/addons/point_of_sale/static/src/app/services/pos_store.js).
No se consultaron ni cambiaron datos de produccion para implementar el arreglo.

### Pruebas locales de esta entrega

**80 Python y 26 JavaScript aprobadas**. Python incluye el gate de sintaxis y
nombres globales, calendario, aplicacion, activacion y lifecycle, mas 13 casos
nuevos de politica/fronteras. JavaScript ejecuta carga/restauracion del titular,
rechazo de otro cliente, fallo de carga/propietarios mezclados y separacion del
fin proporcional. Se mantienen las regresiones previas de descuentos, firma,
UUID, reembolso total, cuotas, cola y tres crons nativos.

**45 tests ORM de operaciones preparados, NO ejecutados**: se agregan al gate
anterior diario sin siguiente factura, reinscripcion antes del cron, upsale el
mismo dia, cierre comercial domiciliado y activacion mas alla de la gracia.
El usuario no dispone de runner/SSH/base desechable; esto sigue siendo una
limitacion de integracion, no una aprobacion implicita de PostgreSQL/Enterprise.

### Repeticion por navegador tras el build

1. Verificar versiones instaladas y recargar POS sin borrar almacenamiento.
   Conservar el ticket fallido 000065 y no intervenir la orden ajena 000058.
2. DAY PASS hoy y retroactivo, renovacion diaria, gratis/WellHub/TotalPass segun
   catalogo, y diario -> mensual: mismo periodo modal/ticket/contrato, sin
   siguiente factura diaria y sin volver a traer el plan DIA.
3. S03615: cotizar y reinscribir sin fabricar factura/cierre nativo para
   desbloquearlo. Comparar tambien una reinscripcion realmente cerrada.
4. Upsale nuevo el mismo dia y otro posterior: IVA y precio modal/ticket iguales;
   origen cerrado con periodo historico intacto; destino/participantes/acceso
   correctos. Refund total no debe resucitar el origen ni futuros cambios.
5. Cliente QA recien creado: alta/renovacion/reinscripcion con borrador, recargar
   y pagar sin buscar otra vez al cliente. Repetir con otro cliente seleccionado:
   rechazo antes de pago, sin reemplazo silencioso ni segundo cobro.
6. Domiciliado nuevo/retroactivo: primer periodo mostrado correctamente, cuotas
   1, 1+12, consecutivos, abonos, liquidacion y anticipos. Cierre comercial
   explicito: sin acceso y reinscribible, cuotas anteriores conservadas; nuevo
   ciclo independiente. No usar cierre contable viejo como migracion masiva.
7. Repetir mensual/cortes 29-31, semestral -> mensual, cambios futuros, pareja/
   trio/individual, descuentos, restricciones POS y devolucion ordinaria.
8. Separar resultados observados por navegador de concurrencia, cambio de dia,
   reintentos tecnicos y entrega fisica al SpeedFace, que no quedan demostrados
   por los tests aislados. No promover a main sin autorizacion posterior.

## Cierre de la continuacion de QA: 2026-10-19

**NO APROBADO para main.** Se continuaron los escenarios independientes a pesar
del fallo diario, exclusivamente en staging, commit `e6087fa`, base
`19.0.1.1.58` y POS `19.0.1.6.4`. No se corrigio codigo funcional durante QA.
La seccion siguiente conserva el primer corte de resultados como historico;
esta seccion lo complementa y sustituye su listado de pendientes.

### Balance acumulado

- 25 ventas simuladas confirmadas, incluidas una venta ordinaria y una
  renovacion con descuento autorizado del 100%.
- Tres devoluciones confirmadas: dos totales de membresia y una ordinaria.
- Un checkout diario fallido, un parcial rechazado, un segundo intento de
  reembolso bloqueado en la interfaz y un preflight rechazado tras recarga.
- Doce contactos QA sinteticos; contratos S03607, S03609-S03618. No se
  intervinieron clientes reales, produccion ni importador bancario.
- 66 tests Python WGS y 22 JavaScript repetidos en esta continuacion: todos
  aprobados. No se repitio el gate sintactico global de otros addons; los 67
  Python del corte anterior incluyen ese gate adicional.
- **40 tests ORM NO ejecutados.** El usuario confirmo que no dispone de
  SSH/runner y base desechable. No se ejecutaron sobre la base operativa.

### Ventas adicionales y resultado

Recibos con prefijo `263-3-`, todos del 19/octubre/2026, caja El Dorado.
En la copia hay referencias de recibo repetidas con ventas historicas: para
identificar QA se deben usar tambien fecha, cliente y monto, no solo el texto
del recibo. No se tocaron las ventas historicas coincidentes.

| Recibo | Contrato | Operacion | Resultado |
| --- | --- | --- | --- |
| 000074 | Sin suscripcion | Agua, $17 | Venta ordinaria confirmada sin flujo de membresia |
| 000075 | S03612 | Mensual, $799 | 19/oct-19/nov, titular con acceso |
| 000076 | S03613 | Upsale inmediato a pareja, $600 | Destino correcto, dos participantes con acceso; origen y centavo de cotizacion fallan, ver hallazgos |
| 000077 | S03613 | Renovacion pareja -> individual, $799 | 20/nov-19/dic programado; pareja y dos accesos actuales conservados; persiste al recargar |
| 000078 | S03613 | Devolver totalmente 000076, -$600 | Destino cancelado, sin acceso; origen S03612 reaparece inconsistente |
| 000079 | S03611 | Reinscribir cerrado -> trio, $1,899 | Selector disponible, tres participantes QA y tres accesos, MENSUALIDAD ED, fin 19/nov |
| 000080 | S03611 | Reinscribir trio cerrado -> individual, $799 | Solo titular, sin participantes anteriores, un acceso, fin 19/nov |
| 000081 | S03611 | Reinscribir mensual cerrado -> domiciliado, $259.58 | Solo proporcional 19-31/oct; contrato hasta 30/sep/2027, acceso activo |
| 000082 | S03614 | Mensual futuro, $799 | 31/ene/2027-28/feb/2027, sin acceso antes del inicio |
| 000083 | S03615 | Mensual historico, $799 | 31/ago-30/sep; sin acceso, mostrado Cerrada. Reinscripcion posterior no cotiza |
| 000084 | S03616 | Semestre vigente, $4,099 | 19/oct/2026-18/abr/2027, un titular con acceso |
| 000085 | S03616 | Semestre -> mensual, $799 | Programa 19/abr-19/may/2027; conserva semestre actual, no cobra ni asigna seis meses al destino |
| 000086 | S03616 | Renovar individual -> pareja futura, $1,398.99 | Programa 20/may-19/jun/2027; titular actual intacto, nuevo participante sin acceso anticipado. Borrador necesitaba recuperar cliente tras recarga |
| 000087 | Sin suscripcion | Devolver agua de 000074, -$17 | Devolucion ordinaria confirmada, sin bloqueo de membresia |
| 000088 | S03617 | Nueva quincena, $450 | QUINCENA ED de dos semanas, 19/oct-1/nov; titular y acceso correctos |
| 000089 | S03618 | Nueva anualidad, $7,200 | ANUALIDAD ED de un anio, 19/oct/2026-18/oct/2027; acceso activo en ambas sedes |

Para S03611 el usuario autorizo especificamente una factura QA **solo borrador**.
Se creo un unico anticipo fijo de $1 para permitir el cierre nativo y preparar
reinscripciones reales, con motivo Fin del contrato. No se publico, timbro,
envio ni pago. Ese documento y los cierres QA permanecen como evidencia; no se
crearon otras facturas ni se cambiaron fechas de contratos pagados para forzar
activaciones futuras. La captura 33 documenta el borrador.

### Hallazgos pendientes

1. **Alta: checkout DAY PASS rechazado.** Sigue abierto el defecto documentado
   abajo: misma vigencia diaria pero fecha opcional esperada `None` frente a
   `False` ORM. Recibo 000065 permanece en Pago, sin membresia aplicada. Impide
   aprobar diarios y la transicion diario -> mensual de extremo a extremo.
   Referencias: `pos_order.py:3239`, `subscription_application.py:66`.

2. **Alta: upsale no deja cerrado coherentemente el origen.** S03612 inicia el
   19/oct; al hacer upsale el mismo dia termina el 18/oct, pero sigue En progreso.
   El destino S03613 si tiene pareja y vigencia correctas. El directorio muestra
   el vencimiento del origen; tras devolver el destino queda el origen visible,
   sin acceso y sin Renovar/Cambiar Plan disponibles. No desaparece recargando.
   `_wgs_close_source_subscription_after_upgrade`, `pos_order.py:4071`, escribe
   inicio del destino menos un dia y da por bueno cualquier retorno del primer
   metodo de cierre. No comprueba estado final ni procesa un posible wizard.
   La implementacion Enterprise de ese retorno no se inspecciono con ORM:
   retorno de wizard es hipotesis, estado inconsistente es evidencia observada.
   Capturas 29-31 y estado despues de 000078.

3. **Alta: una fuente vencida aparece reinscribible pero no logra cotizar.**
   S03615 se creo con 31/ago-30/sep; hoy aparece Cerrada y ofrece Reinscribir.
   Al abrir, muestra "No se pudo consultar el cobro de reinscripcion"; tampoco
   cotiza al elegir PREMIUM 619. Consola muestra RPC_ERROR, sin traceback Python.
   La UI clasifica como cerrado al superar su limite, mientras el guard de
   `pos_order.py:3893` exige tokens terminales del estado nativo; el builder de
   cotizacion aplica ese guard en `pos_order.py:1345`. Esta diferencia es una
   causa probable, no una causa runtime confirmada sin traceback/ORM. Captura 45.
   Contrasta con S03611 realmente cerrado por el wizard: sus reinscripciones
   trio, individual y domiciliado si se pagaron y aplicaron.

4. **Alta: recargar borrador pierde la resolucion del cliente.** Borrador 000086
   conserva producto PAREJA y $1,398.99, pero muestra Cliente en lugar del titular.
   Validar rechaza "La cotizacion no corresponde al cliente, empresa, paquete u
   operacion del ticket". La guarda impidio aplicar una identidad incorrecta.
   Buscando al titular original en el selector nativo y pulsando Enter se cargo
   desde servidor; seleccionandolo de nuevo se pudo pagar la misma venta una
   sola vez y se conservaron sus dos periodos futuros. No es evidencia de que
   el ID se borre de la base: indica al menos una relacion no resuelta al
   recargar. Revisar carga de partners y `subscription_payment_guard.js:43`
   junto con `subscription_ticket.js:101`. Capturas 48-51. **Recarga automatica
   no aprobada**, aunque la recuperacion manual funciono.

5. **Media, operacion por definir: cerrar nativo no termina domiciliado.**
   Tras cerrar S03611 con motivo Fin del contrato, backend permanece Cancelado,
   ofrece Volver a abrir y fin 19/oct; POS sigue En progreso, fin 30/sep/2027 y
   acceso activo. No es cache ni reapertura de la fila nativa. El codigo lo
   hace deliberadamente: `sale_order.py:2582` del POS y `sale_order.py:710` base
   toman el contrato domiciliado como autoridad, ignorando cierre nativo para
   no bloquear adeudos por cierres contables. Falta aclarar/proveer un cierre
   comercial explicito que no se confunda con el cierre contable; no debe
   arreglarse reactivando el problema de adeudos. Capturas 39 y 41. Este escenario
   no demuestra por si solo una regresion del refactor y no se declara pasada
   la reinscripcion al mismo domiciliado usando el cierre nativo.

6. **Baja: modal de upsale difiere un centavo del ticket.** Credito $799 sobre
   pareja $1,398.99 cotiza $599.99; ticket, pago y recibo 000076 cobran $600.
   Validar calculo central antes/despues de IVA y redondeo; no ocultar cambiando
   solo el texto. Captura 29 y recibo 000076.

7. **Baja: texto domiciliado llama proporcional al plazo completo.** La primera
   tarjeta dice correctamente 19-31/oct y $259.58, pero el resumen dice
   "Primer periodo proporcional: 19 oct 2026 - 30 sep 2027". Capturas 37, 46-47.

### Cobertura aprobada y sus limites

| Grupo | Evidencia aprobada | Limite de lo comprobado |
| --- | --- | --- |
| Mensual | Alta hoy, pasada y futura; renovar mismo paquete; corte conservado | Recuperar corte 31 despues de febrero requiere periodo posterior |
| Fechas 29/30/31 | Cotizaciones enero -> 28/feb; alta 31/ene pagada; 31/ago -> 30/sep pagado | No se cambio reloj ni se forzo renovar un inicio futuro |
| Semestre/mensual | Mensual -> semestre -> mensual y semestre vigente -> mensual, todos pagados | Programacion observada; activacion futura no ejecutada |
| Otros plazos | Altas quincenal y anual pagadas; planes y fechas exactos del catalogo, sin heredar mensual | No prueba todas las combinaciones de cambio entre esos plazos |
| Participantes | Alta pareja; reinscribir trio; trio -> individual; pareja -> individual futura; individual -> pareja futura | No prueba participante historico que pasa a titular ni entrega fisica |
| Domiciliados | Alta retroactiva febrero, cuotas 1+12, abono, liquidacion, sin acceso con adeudos y reactivacion al quedar al corriente; anticipos | Cuotas/pagos del nuevo ciclo legacy no ejercitados |
| Seleccion domiciliada | Solo 1; 1+12; marcar 3 incluye 2; desmarcar 2 retira 3; IVA y fecha inicial correctos | Consecutivos iniciales 1-3 comprobados en cotizacion, sin un nuevo pago para esa combinacion |
| Prorrateo | Reinscribir mensual -> domiciliado el 19/oct cobra $259.58, sin ultimo mes obligatorio | Mismo domiciliado y alineado no domiciliado no aprobados |
| Descuentos | Autorizacion 50% y 100%; siguiente renovacion cotiza normal, sin heredar descuento | No se cambiaron listas fiscales ni otras posiciones fiscales |
| Devoluciones | Parcial de membresia rechazado; total confirmado; repetido no seleccionable; venta/devolucion ordinaria confirmadas | Cancelacion durable de toda la cola tras refund pendiente ORM |
| Acceso | Activo/no activo congruente en casos aprobados; multisede domiciliado; resincronizacion sin duplicar persona visible | No pruebas de hardware, zona horaria del equipo ni entrega al gateway |
| Restricciones POS | Facturar deshabilitado Pago/Ordenes; Informacion ausente; teclado precio/descuento bloqueado para membresias | No auditoria de permisos de backend fuera del POS |
| Recarga | Cambios ya pagados persisten; borrador recuperable manualmente | Resolucion automatica del cliente fallo; replay/red perdida no ejercitados |

### Pendientes sin simular como aprobados

- Resolver y repetir los hallazgos altos; conservar el rechazo de incoherencias,
  la atomicidad y la firma, no quitar guardas para hacer verde la prueba.
- Suite ORM Enterprise/PostgreSQL de 40 tests, locks y dos workers. Sin acceso
  a runner/base desechable, queda bloqueada por infraestructura, confirmado por
  el usuario. No convertir esta carencia en permiso para usar produccion.
- Activacion futura real, recuperacion heredada de review, fallo transitorio y
  reintento, tres crons nativos, ultimo dia 23:59:59/inicio 00:00 y medianoche
  local. Ventas hechas despues de las 18:00 conservaron fechas, pero no prueban
  por si mismas esos bordes temporales.
- Doble click/respuesta perdida/reenvio concurrente, dos altas simultaneas y
  dos renovaciones sobre la misma revision. Una recarga no sustituye estos tests.
- Cadena de cambios futuros cancelada por refund: cancelar sin activar es solo
  comprobacion visual; falta verificar recibos/cola a nivel ORM y su no activacion.
- Reinscripcion diaria, mismo domiciliado tras terminar plazo y nuevo ciclo
  legacy; participante anterior como nuevo titular; alineado no domiciliado;
  cambios entre todos los plazos, IVA excluido/otra posicion fiscal.
  No se reutilizaron clientes reales ni se alteraron catalogos para fabricar casos.
- Repetir matriz de caja en Santa Monica: esta evidencia operativa se obtuvo
  en El Dorado, no se presenta como prueba de ambas cajas.

### Residuos QA y evidencias

Se conservaron las ventas y devoluciones sinteticas para trazabilidad. El ticket
000065 sigue en Pago; la orden ajena 000058 no se modifico. No limpiar cache,
almacenamiento ni borrar pedidos para dar por resuelto un checkout fallido.
El unico borrador contable autorizado de S03611 sigue sin publicar. S03611
queda cerrado nativamente pero su contrato domiciliado sigue activo, conforme
al hallazgo 5; S03612 queda como evidencia del upsale inconsistente.

Capturas 01-54 y `estado-pruebas.json` en
`/Users/apreza/.codex/visualizations/2026/02/18/019c72fb-fa85-7b22-a4fa-20aa1262c18f/wgs-staging-qa-20261019/`.
No contienen claves de acceso ni PIN guardados intencionalmente. Las capturas
son evidencia de interfaz, no sustituyen una lectura ORM transaccional.
Solo este documento cambia en el repo; sin commit, push ni merge en esta QA.

## Primer corte de pruebas por navegador: 2026-10-19

Resultado parcial: **NO APROBADO para promover a main**. Build probado en
`staging-portal.spinbike.mx`, commit `e6087fa`; versiones instaladas verificadas
en Aplicaciones: base `19.0.1.1.58`, POS `19.0.1.6.4`. El usuario confirmo el
aislamiento del gateway SpeedFace de produccion antes de las ventas simuladas.
Solo se operaron clientes sinteticos `QA WGS 20261019`; no se intervino
produccion, importador bancario ni clientes reales de la copia.

### Evidencia operativa

11 ventas simuladas confirmadas, un reembolso total confirmado y un intento de
venta diaria rechazado. Tambien se comprobo el rechazo de reembolso parcial.
Caja El Dorado, recibos con prefijo `263-3-`; importes incluyen IVA.

| Recibo | Contrato | Operacion | Resultado observado |
| --- | --- | --- | --- |
| 000061 | S03607 | Nueva TODO INCLUIDO, $799 | MENSUALIDAD ED, 19/oct-19/nov; una persona activa en El Dorado |
| 000062 | S03607 | Renovacion igual paquete, $799 | Fin 19/dic, siguiente periodo 20/nov-19/dic; acceso conservado |
| 000063 | S03607 | Renovar a SEMESTRE, $4,099 | Cambio pagado 20/dic/2026-19/jun/2027; mensual vigente intacto |
| 000064 | S03607 | Volver a mensual tras semestre futuro, $799 | Segundo cambio 20/jun-20/jul/2027, no seis meses; ambos cambios visibles |
| 000065 | Sin contrato aplicado | DAY PASS de ayer, $99.99 | Rechazo de vigencia al validar; permanece en Pago en el POS |
| 000066 | S03609 | Domiciliado desde 15/feb, meses 1 y 12, $928.51 | Proporcional $309.50 mas ultimo mes $619.01; sin acceso con adeudos |
| 000067 | S03609 | Abono de marzo y abril, $1,238.02 | Cuotas pagadas bloqueadas; conserva adeudos y no activa acceso |
| 000068 | S03609 | Liquidar mayo-octubre, $3,714.06 | Acceso activo; una persona, sitios El Dorado y Santa Monica |
| 000069 | S03609 | Adelantar noviembre-diciembre, $1,238.02 | Se permite estando al corriente; al pagar todo el plazo ya no permite otro cobro |
| 000070 | S03610 | Pareja historica, $1,398.99 | Dos participantes QA persistidos; MENSUALIDAD ED, 18/sep-18/oct |
| 000071 | S03607 | Reembolso total de 000064, -$799 | Confirmado; ficha deja de mostrar membresia activa y acceso |
| 000072 | S03611 | Mensual con autorizacion de 50%, $399.50 | Acceso activo; siguiente renovacion cotiza $799 sin descuento heredado |
| 000073 | S03611 | Renovacion con autorizacion de 100%, $0 | Fin 19/dic; siguiente renovacion vuelve a $799 y conserva corte 19 |

El intento parcial de 0.5 unidades de 000064 se rechazo antes de sincronizar:
"Las membresias solo permiten reembolso total, sin cambiar cantidad, precio ni
descuento." Se descarto solo ese borrador QA y se repitio con una unidad completa.
No hubo devolucion parcial confirmada. La cancelacion de otras compras futuras
del mismo contrato tras el reembolso no se inspecciono a nivel ORM.

En S03610 se intento preparar un cierre por backend para probar reinscripcion.
El cierre nativo fue rechazado porque no tenia facturas; posteriormente se
cancelo solo ese contrato QA. Esa cancelacion elimina su estado de suscripcion
y el directorio lo muestra sin historial visible, por lo que **no constituye
una prueba de reinscripcion de una suscripcion cerrada**. No se alteraron fechas
despues de cotizar ni se crearon facturas para forzar el escenario.

Otras comprobaciones aprobadas: Factura deshabilitada en Pago y Ordenes; menu
Acciones sin Informacion; precio/descuento del teclado bloqueados en membresias;
no ofrece Nueva suscripcion en contratos activos; selector de pareja permite
buscar y seleccionar otro QA; resincronizar S03611 conserva una persona activa,
fechas y paquete, con enfriamiento visible. Las cuotas iniciales y de renovacion
domiciliadas muestran IVA y fecha real de arranque del proporcional. El primer
mes futuro seleccionado tiene tarjeta blanca, distinta de las cuotas pagadas.

### Hallazgo bloqueante: fechas vacias en pases diarios

Se reprodujo en caja el error "La vigencia aplicada no coincide con la vigencia
contratada" al validar DAY PASS del 18/oct. No quedo contrato aplicado ni persona
para el cliente QA Diario; el ticket 000065 sigue pendiente localmente. **No
borrar almacenamiento ni reintentar cobros en bloque para ocultar este error.**

La inspeccion acota una causa probable a la representacion de fecha vacia:
`pos_order.py:3239` convierte `next_billing_date=False` con `fields.Date.to_date`,
mientras `subscription_application.py:66` compara directamente con la fecha
ORM. El sellado ya elimina correctamente la siguiente factura para un dia
(`subscription_operation.py:135`); no debe reintroducirse una factura recurrente
para eludir el rechazo.

Se ejecuto el metodo real de postcondiciones con la fixture aislada existente,
sin editar fuentes: fechas de inicio/fin iguales y correctas, corte 0, siguiente
factura ORM `False` y esperada `None` producen exactamente el rechazo. Cambiar
solo la representacion esperada a `False` lo acepta. Esto demuestra el defecto
de comparacion, pero no sustituye la inspeccion ORM de los valores reales ni la
prueba de checkout diario sobre el build corregido. Severidad **alta**: impide
ventas validas de un dia y bloquea probar diario -> mensual de extremo a extremo.

Correccion requerida: una convencion consistente para fechas opcionales en la
frontera cotizacion/adaptador/postcondiciones, conservando el rechazo de fechas
realmente distintas. Agregar regresion de `None`/`False`, diario hoy/retroactivo,
renovacion diaria, reinscripcion diario -> mensual y cambio mensual -> diario.
No quitar postcondiciones, firmas ni atomicidad. No se aplico codigo durante
esta sesion de pruebas, ni se hizo commit/push/merge.

### Observaciones no bloqueantes

- En alta domiciliada, el texto "Primer periodo proporcional" usa el fin del
  contrato completo, aunque la tarjeta del primer mes y el importe son correctos.
  Severidad baja; debe mostrar el fin de esa cuota, no el del plazo forzoso.
- No hay impresora fisica disponible en staging: aparece un aviso despues de
  ventas y puede interceptar la siguiente accion. Se continuo sin imprimir; no
  se reintento el cobro ni se cambiaron ajustes globales de impresion.
- El selector de participantes llega a renderizar unos 3,002 elementos antes
  del filtro. Observacion de rendimiento, no fallo comercial demostrado.

### Cobertura pendiente y condicion de salida

No se declara completada toda la matriz. Faltan reinscripcion real desde estado
cerrado, diario -> mensual, participantes en reinscripcion y retiro de antiguos
participantes al pasar a individual, prorrateo de reinscripcion alineada,
upsale inmediato, venta ordinaria no recurrente, devolucion repetida,
reconexion/reenvio del mismo ticket y bordes de corte 29/30/31 en el despliegue.
La cadena mensual -> semestre -> mensual fue pagada y programada, pero **no se
adelanto el reloj ni se verifico su activacion futura**.

Siguen pendientes los 40 tests ORM sobre Odoo 19 Enterprise/PostgreSQL con dos
workers, incluido ultimo dia inclusivo, conflicto de crons, recuperacion de
`review`, fallos tecnicos y concurrencia. No se ejecutan desde esta validacion
de navegador; requieren una copia desechable con acceso al runner Odoo. Las
67 pruebas Python y 22 JS historicas no equivalen a este gate de integracion.
Acceso activo en Odoo no demuestra entrega fisica a SpeedFace.

Capturas 01-24 y estado estructurado guardados fuera del repo en
`/Users/apreza/.codex/visualizations/2026/02/18/019c72fb-fa85-7b22-a4fa-20aa1262c18f/wgs-staging-qa-20261019/`.

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
