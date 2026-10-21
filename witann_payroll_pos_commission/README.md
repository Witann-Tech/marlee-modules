# Comisión POS en nómina mexicana

Addon para Odoo 19 y **Nómina mexicana nativa con CFDI**. Depende de
`pos_hr` y `l10n_mx_hr_payroll_account_edi`; no depende de los módulos de
suscripciones ni de `witann_mx_payroll`.

## Uso

1. Instalar **Witann: comisión POS en nómina**.
2. El empleado debe tener acceso como cajero en un POS activo de su compañía,
   con **Iniciar sesión como empleado** habilitado; se respetan las listas
   nativas de permisos mínimos, básicos y avanzados, incluido el modo de acceso
   para todos los empleados. También es elegible con un usuario interno activo
   vinculado, permisos de Punto de Venta y acceso a su compañía.
   No necesita un usuario de Odoo propio si accede como cajero.
3. Un responsable de Nómina configura **Comisión POS → Comisión mensual POS (%)**.
   La pestaña permite configurar el origen; el porcentaje se habilita con acceso
   POS propio o con un origen válido. El valor inicial es **0**:
   no se habilitan comisiones para toda la plantilla durante la instalación.
4. Calcular la nómina ordinaria mexicana con frecuencia **quincenal** y periodos
   del 1 al 15 o del 16 al último día del mes. Aparece la percepción
   **Comisión por venta** y una pestaña con el detalle del cálculo.

Ejemplo: ventas de septiembre de $116,000 con $16,000 de IVA; porcentaje mensual
del empleado de 1%. La base es $100,000 y se pagan $500 en cada quincena de octubre.
Con 2% mensual, serían $1,000 por quincena. Con 0%, no se genera entrada ni ingreso.

## Nómina en otra compañía: POS y cajera de origen

En la ficha de la empleada de **Comercializadora Marlee**, configurar:

- **POS de origen:** SB Total Padel.
- **Cajera o cajero de origen:** su ficha operativa de Padel.
- **Comisión mensual POS (%):** 1 para pagar 0.5% por quincena.

La ficha de nómina puede no tener usuario ni acceso propio a POS. Se mantiene
separada de la ficha operativa; los contratos, recibos, contabilidad y CFDI siguen
el flujo nativo de su compañía. No se crean, trasladan ni sincronizan empleados
automáticamente, ni se modifican los permisos o el funcionamiento del POS.

Solo un responsable de Nómina puede guardar o cambiar el vínculo, con los permisos
nativos de lectura sobre el POS y la cajera. Los dos selectores consultan las
compañías autorizadas del usuario, incluidas sucursales no activas en la sesión;
no es necesario cambiar el selector general de compañías. Después, un usuario de Nómina puede calcular con solo la compañía
empleadora seleccionada y sin permisos de POS: se lee exclusivamente el origen
guardado. No se amplían ACL ni reglas multiempresa de Odoo.

Ambos campos de origen se completan juntos. La cajera debe pertenecer a la compañía
del POS, estar activa y tener acceso nativo a ese POS activo. Las dos compañías
deben utilizar la misma moneda. Se consideran únicamente tickets con esa cajera
en ese POS: no se toma el usuario que abrió la sesión ni se buscan coincidencias
por nombre. Los tickets sin cajera quedan excluidos del origen explícito.

Dejar ambos campos vacíos conserva el cálculo anterior por empleado/usuario propio.
El porcentaje cero o la pérdida del acceso al origen detienen nuevas comisiones.
Una quincena validada conserva también el origen para la otra quincena del mes;
un cambio de origen con porcentaje positivo se aplica al siguiente mes no cerrado.

## Criterios del cálculo

- Sin origen explícito: el cajero de `pos.order.employee_id` tiene prioridad. Solo en tickets
  sin cajero se utiliza `pos.order.user_id`, relacionado con `hr.employee.user_id`.
  Así, varias cajeras pueden compartir sesión sin que sus ventas se atribuyan
  al usuario que la abrió. Los tickets históricos sin cajero no se asignan
  automáticamente a empleados sin usuario: no contienen esa identificación.
- Mes calendario anterior al periodo del recibo; nunca relativo al día en que
  se pulsa Calcular. Se respeta la zona horaria del calendario de la compañía
  (respaldo `America/Mexico_City`), con inicio incluido y fin excluido.
- Pedidos pagados/contabilizados de la compañía de origen (o de nómina cuando no
  se configuró otro origen). Se incluyen los facturados
  sin contar por separado sus facturas; se excluyen borradores y cancelados.
- Base: total menos impuestos de cada pedido, que ya incorpora descuentos y el
  signo de las devoluciones. Las devoluciones se restan en el mes de su registro
  y al cajero o usuario POS que las registra. Una base negativa no produce una deducción
  salarial ni se arrastra a otro mes.
- Si la moneda del ticket difiere de la compañía, se utiliza el tipo de cambio
  histórico almacenado en el pedido. Se guarda evidencia del importe y cambio.
- El porcentaje es mensual. Se redondea el derecho mensual a la moneda del recibo
  y se divide entre dos; el ajuste de un centavo, si existe, se hace en la segunda
  quincena para que ambas sumen exactamente el derecho mensual.
- Los borradores se actualizan al recalcular. Al validar una quincena, su base,
  tasa y tickets se conservan también para la otra quincena de ese mes. Cambiar
  una tasa positiva después afecta al siguiente mes no cerrado. Poner 0 o quitar
  el acceso POS desactiva las siguientes comisiones, sin modificar pagos anteriores.
- La validación vuelve a calcular las comisiones de borradores. Si se mantiene
  un borrador de la segunda quincena mientras se valida la primera, la segunda
  adoptará la base cerrada al recalcular o validar.

## Nómina y CFDI

Se utiliza la entrada y regla salarial nativas `COMMISSIONS`, con su categoría,
cuentas contables, integración salarial y concepto CFDI `028`. Se conserva el
cálculo nativo de impuestos, cuotas, bruto y neto. El importe de la comisión es
una percepción antes de las deducciones que determine Nómina.

La entrada y la línea del recibo se llaman **Comisión por venta**. Para este ingreso,
el módulo adapta también la descripción en los valores del CFDI; no cambia las
claves ni genera o timbra documentos por su cuenta.

Si hay entradas manuales `COMMISSIONS` en un recibo que recibirá comisión POS,
se pide conciliarlas antes de continuar, sin borrarlas ni sumarlas silenciosamente.
El generador CFDI nativo de la revisión usada agrupa por regla salarial y puede
omitir importes si hay varias líneas con la misma regla; por eso esta combinación
no se admite. Con porcentaje cero, las comisiones manuales siguen funcionando.

## Controles

- Un índice único en PostgreSQL impide dos comisiones automáticas activas del
  mismo empleado, compañía y quincena, incluyendo cálculos concurrentes.
- Una reserva interna con unicidad SQL por POS, vendedor y quincena impide
  comisionar el mismo origen desde fichas de nómina distintas, incluso si una
  usa el cálculo propio y otra un vínculo explícito. Se libera al cancelar el
  recibo o recalcular su comisión a cero. El modelo interno no tiene ACL de usuario.
- Al actualizar desde versiones anteriores, la migración registra esas reservas
  para recibos con comisión activos, sin modificar sus importes ni evidencia.
  Si existen orígenes ya duplicados o tickets históricos que no permiten localizar
  el POS, la actualización se detiene para conciliarlos; no se descartan pagos.
- Las entradas automáticas y la evidencia no pueden editarse mediante formulario
  ni RPC. Se regeneran desde el cálculo privado del módulo.
- Los recibos confirmados conservan sus datos. Para corregirlos se utiliza el
  flujo nativo; un CFDI firmado debe cancelarse antes de regresar a borrador.
- Una sustitución requiere cancelar el recibo anterior para liberar la quincena.
  Las devoluciones nativas conservan sus líneas invertidas y no generan otra
  comisión. No se permite recalcular una devolución de un recibo con comisión POS.
- Solo se calculan comisiones para la estructura ordinaria mexicana nativa.
  Aguinaldo, extraordinarios, finiquitos, estructuras copiadas y periodos parciales
  no incorporan automáticamente esta percepción.
- Nómina puede calcular sin permisos de POS: la lectura elevada de tickets está
  limitada al vendedor, compañía autorizada y mes. No se otorga acceso general al POS.

## Validación

Pruebas aritméticas sin Odoo, desde la raíz del repositorio:

```sh
python3 -m unittest discover -s tests/standalone -p test_pos_payroll_commission.py -v
```

Pruebas integradas, en una base **desechable** con las fuentes de Odoo 19 Community
y Enterprise autorizadas y los addons de este repositorio:

```sh
odoo-bin -d BASE_DESECHABLE -i witann_payroll_pos_commission \
  --test-enable --test-tags /witann_payroll_pos_commission --stop-after-init
```

La configuración fiscal, cuentas y timbrado siguen a cargo de la localización
nativa. La instalación y la validación en Marlee se realizan separadamente de las
pruebas locales; este desarrollo no despliega ni modifica su base de datos.

### Resultado local — 19 de octubre de 2026

- **8 pruebas independientes y 19 pruebas integradas aprobadas**, sin fallos.
- Instalación inicial y actualización del addon verificadas en Odoo 19 local,
  PostgreSQL 16 y localización mexicana Enterprise, sobre datos ficticios.
- Se comprobó el XML CFDI renderizado por la plantilla nativa: percepción `028`,
  descripción «Comisión por venta» e importe gravado de $500 en ambas quincenas.
  Se usaron certificados de prueba nativos; **no se envió al PAC ni al SAT**.
- Se verificaron bruto/neto, usuario POS, exclusión de otras compañías, devoluciones,
  periodos, permisos, desactivación, recálculo, conservación del mes validado,
  entradas manuales, reversión nativa e índice SQL contra duplicados (incluidos
  recibos cuyo campo `credit_note` es NULL).
- Sintaxis Python, vistas XML y archivos declarados en el manifiesto correctos.
- Pendiente de instalar y validar en el staging de Marlee con su revisión de Odoo,
  configuración fiscal, cuentas y flujo de timbrado. No se ha desplegado.

### Corrección de cajeros — 20 de octubre de 2026

- Versión `19.0.1.1.0`: reconoce acceso nativo como empleado sin exigir un usuario
  de Odoo vinculado. La configuración de POS invalida la elegibilidad al cambiar.
- Los tickets con cajero se atribuyen exclusivamente a ese empleado; los tickets
  sin cajero conservan la atribución por usuario.
- **8 pruebas independientes y 24 pruebas integradas aprobadas**, sin fallos,
  incluida actualización del módulo y regresión del XML CFDI nativo.
- Casos añadidos: dos cajeras sin usuario compartiendo sesión, prioridad del
  cajero sobre el usuario, los tres niveles de permisos, revocación de acceso,
  POS deshabilitado/archivado y aislamiento por compañía.

### Origen configurable — 21 de octubre de 2026

- Versión `19.0.1.2.0`: POS y cajera de origen opcionales en la ficha de nómina.
- **8 pruebas independientes y 32 pruebas integradas aprobadas**, sin fallos,
  con instalación/actualización local del addon y vistas validadas por Odoo.
- Se verificaron nómina y XML CFDI nativos en la compañía empleadora tomando
  ventas de otra compañía, filtrado por POS y cajera, permisos de configuración
  y cálculo, conservación del origen validado, duplicados entre fichas, reserva
  SQL y migración idempotente de evidencia histórica. Sin envío al PAC ni al SAT.
- Esta entrega es código para actualizar el módulo; no crea fichas reales ni
  configura los vínculos o porcentajes de empleados en staging.

### Selectores de sucursales — 21 de octubre de 2026

- Versión `19.0.1.2.1`: los selectores de POS y cajera usan las compañías
  autorizadas del usuario aunque solo esté activa la compañía de nómina.
- El guardado verifica ese mismo alcance en el servidor, con las ACL y reglas
  nativas. El contexto general de la ficha y los demás selectores no cambian.
- **8 pruebas independientes y 34 integradas aprobadas**. La regresión utiliza
  el contexto de los campos de la vista real para buscar POS/cajera y guardar
  el vínculo, y comprueba que compañías no autorizadas permanezcan excluidas.
