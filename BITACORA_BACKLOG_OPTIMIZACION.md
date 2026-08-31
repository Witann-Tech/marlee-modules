# Bitacora de Backlog Tecnico

Fecha de auditoria: 2026-08-29  
Base revisada: `bcd55e2` (`main` y `staging` alineados)

Este backlog registra mejoras de confiabilidad, rendimiento, seguridad y
mantenibilidad detectadas en los addons actuales. No autoriza retirar ni
modificar reglas operativas sin una historia funcional aprobada.

## Sprint 1 - Integridad y Seguridad Operativa

Objetivo: evitar que una venta, una identidad de acceso o una operacion
administrativa quede en estado inconsistente.

- [ ] **Separar el cierre de venta POS de la sincronizacion fisica de acceso.**
  La suscripcion y el pago deben confirmarse con su metadata WGS; la
  propagacion a SpeedFace debe ejecutarse mediante una cola transaccional
  durable y reintentable. Un fallo de acceso no debe rechazar ni dejar a medias
  un cobro POS.
  Archivos de partida: `witann_group_subscriptions_pos/models/pos_order.py`.
  Criterio de salida: una simulacion de error de acceso conserva una venta y
  suscripcion validas, genera trabajo pendiente y permite reintento idempotente.

- [ ] **Hacer concurrente y segura la asignacion de `global_user_id`.**
  Sustituir el escaneo completo y seleccion en memoria por un mecanismo con
  bloqueo transaccional o una tabla/secuencia de asignacion. Mantener el rango
  permitido y la unicidad de PostgreSQL.
  Archivos de partida: `access_control_api/models/access_person.py`.
  Criterio de salida: dos transacciones simultaneas no pueden seleccionar el
  mismo ID ni hacer fallar una venta por colision evitable.

- [ ] **Garantizar en base de datos una sola persona activa por contacto.**
  Mantener historial inactivo permitido, pero agregar una restriccion parcial
  de PostgreSQL para impedir dos identidades activas aun bajo concurrencia.
  Criterio de salida: la base rechaza el segundo registro activo para el mismo
  contacto; los registros inactivos historicos siguen siendo validos.

- [ ] **Restringir operaciones tecnicas de reparacion POS.**
  Exigir grupo de administrador para auditar o reparar lineas POS pagadas y
  eliminar elevacion `sudo()` accesible desde llamadas no administrativas.
  Archivos de partida: `witann_group_subscriptions_pos/models/subscription_pos_sync_service.py`.
  Criterio de salida: un usuario POS no puede ejecutar auditorias o reparaciones;
  un administrador conserva el flujo dirigido con trazabilidad.

- [ ] **Separar permisos de control fisico de `base.group_user`.**
  Crear grupos especificos para administrar sitios, dispositivos, horarios,
  inventario SF, borrado en ADMS y apertura de puerta. Agregar record rules o
  controles de metodo coherentes.
  Archivos de partida: `access_control_api/security/ir.model.access.csv`.
  Criterio de salida: un usuario interno ordinario no puede editar topologia,
  abrir puertas ni borrar personas de ADMS.

## Sprint 2 - Rendimiento y Retencion de Datos

Objetivo: mantener tiempos de respuesta estables y evitar crecimiento
indefinido de tablas operativas.

- [ ] **Definir acuse y retencion segura para `access_control.sync_change`.**
  Persistir el cursor confirmado por dispositivo, conservar cambios mientras
  algun dispositivo del sitio los necesite y purgar solo cambios ya consumidos
  conforme a una politica configurable.
  Archivos de partida: `access_control_api/models/access_sync_change.py` y
  `access_control_api/controllers/main.py`.
  Criterio de salida: la cola no crece indefinidamente, un SF atrasado puede
  reconstruirse y no se pierde ningun `delete`, `upsert` o comando requerido.

- [ ] **Reemplazar conteos completos del directorio POS por agregados.**
  Los pills del encabezado no deben recorrer todos los socios ni construir su
  ficha de suscripcion en cada carga. Resolver conteos con dominios/agregados
  indexables o una proyeccion de estado mantenida transaccionalmente.
  Archivos de partida: `witann_group_subscriptions_pos/models/sale_order.py`.
  Criterio de salida: abrir el directorio solo consulta la pagina visible y los
  conteos no hacen un recorrido completo del padrón.

- [ ] **Procesar eventos de acceso por lote.**
  Limitar el tamano de request, precargar eventos, sitios, dispositivos y
  personas por lotes; usar `create` masivo y conservar idempotencia por
  `event_id`.
  Archivos de partida: `access_control_api/controllers/main.py`.
  Criterio de salida: un lote grande no genera queries N+1, tiene limite claro
  y devuelve un resultado parcial trazable cuando existan eventos invalidos.

- [ ] **Acotar bootstraps de SpeedFace.**
  Sustituir paginacion por `offset` por cursor de clave, reducir el maximo de
  personas con biophoto por respuesta y mantener la carga de fotos en un flujo
  paginado separado.
  Archivos de partida: `access_control_api/controllers/main.py`.
  Criterio de salida: ningun bootstrap puede construir una respuesta excesiva
  en RAM y el tiempo por pagina se mantiene estable conforme crece el padron.

- [ ] **Optimizar rotacion de PIN WGS.**
  Reemplazar `search([]).filtered(...)` por un dominio de vencimiento con
  campos indexados, y procesar los resultados en lotes.
  Archivos de partida: `witann_group_subscriptions_pos/models/hr_employee.py`.
  Criterio de salida: el cron no carga todas las credenciales para encontrar
  las que vencieron.

- [ ] **Acotar las consultas auxiliares de reportes POS.**
  No cargar hasta 5,000 ordenes para construir filtros de vendedor/sesion; usar
  agregados o endpoints de opciones con paginacion. Limitar tambien snapshots
  de auditoria SF y establecer retencion.
  Archivos de partida: `witann_group_subscriptions_pos/models/pos_order.py` y
  `access_control_api/models/access_device_audit.py`.
  Criterio de salida: filtros y auditorias tienen limites de datos, tiempos de
  espera y retencion configurables.

## Sprint 3 - Modelo de Datos y Observabilidad

Objetivo: eliminar almacenamiento tecnico impropio y hacer recuperables los
fallos sin reparaciones manuales ambiguas.

- [ ] **Migrar bloqueos manuales de `ir.config_parameter` a un modelo propio.**
  Guardar contacto, motivo, usuario, fechas, estado y auditoria en campos
  relacionales e indexables. Preservar el comportamiento actual de bloquear a
  todos los participantes del paquete.
  Archivos de partida: `witann_group_subscriptions/models/res_partner.py`.
  Criterio de salida: los bloqueos son buscables, auditables, exportables y no
  generan multiples lecturas de parametros por socio.

- [ ] **Agregar observabilidad de la cadena POS -> suscripcion -> acceso.**
  Registrar un identificador de correlacion por linea POS, resultado de cada
  etapa, error recuperable y reintentos. Exponer una vista administrativa de
  trabajos pendientes y fallidos.
  Criterio de salida: cada cobro recurrente permite rastrear sin SQL si se
  aplico a la suscripcion y si el acceso quedo pendiente o confirmado.

- [ ] **Centralizar configuracion y compatibilidad.**
  Eliminar aliases heredados de parametros ADMS y horario una vez migrados;
  documentar una sola clave por configuracion y validar al iniciar/actualizar.
  Criterio de salida: no existen fuentes alternativas silenciosas para tokens,
  URLs u horarios.

- [ ] **Revisar el workaround de POS Loyalty antes de cada upgrade de Odoo.**
  El addon modifica un inverso de un campo en `_register_hook`; mantener prueba
  de instalacion/upgrade contra la version objetivo de Odoo.
  Archivos de partida: `witann_pos_loyalty_install_fix/models/loyalty_program.py`.
  Criterio de salida: la compatibilidad se valida antes de subir Odoo y el
  workaround se retira si el core ya corrige el defecto.

## Sprint 4 - Modularizacion y Pruebas de Regresion

Objetivo: reducir el radio de impacto de cada cambio funcional.

- [ ] **Extraer servicios del flujo POS de suscripciones.**
  Dividir configuracion serializada, pricing, alta/renovacion/reinscripcion,
  domiciliados, reparacion dirigida y sincronizacion de acceso. Mantener APIs
  publicas compatibles durante la migracion.
  Archivos de partida: `witann_group_subscriptions_pos/models/pos_order.py`.
  Criterio de salida: cada servicio tiene responsabilidad unica, pruebas propias
  y no requiere modificar un archivo monolitico para un cambio aislado.

- [ ] **Consolidar extensiones frontend del POS.**
  Unificar los parches de `PaymentScreen` y reemplazar alteraciones dinamicas
  de prototipos de lineas por extensiones Odoo soportadas cuando sea posible.
  Archivos de partida: `witann_group_subscriptions_pos/static/src/js/`.
  Criterio de salida: orden de assets documentado, una sola extension por
  componente base y pruebas de carga POS despues de upgrade.

- [ ] **Construir pruebas de integracion para los flujos criticos.**
  Cubrir payload POS real, pago, metadata WGS, renovacion, reinscripcion,
  reembolso, domiciliacion, error de acceso, reintento y concurrencia de
  identidades.
  Criterio de salida: una regresion como pago POS sin vigencia o acceso no
  vuelve a llegar a produccion sin una prueba que falle previamente.

## Criterios Generales

- Todo cambio de este backlog debe conservar las funcionalidades actuales:
  resincronizar, abrir puerta, bloqueo/desbloqueo, WellHub, TotalPass,
  bitacora, ventas y flujos de suscripcion.
- Los cambios de datos deben incluir migracion, rollback operativo y prueba en
  staging con datos representativos antes de merge a `main`.
- Ninguna reparacion masiva se ejecuta en produccion sin modo `dry_run`, reporte
  revisable e identificadores concretos de los registros afectados.
