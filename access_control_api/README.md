# Witann - Access Control API

## Autenticación ADMS

ADMS debe enviar los requests a Odoo con:

```http
Authorization: Bearer <token>
```

El token esperado se configura en Odoo únicamente con el parámetro:

```text
access_control.api_token
```

Ejemplo de configuración:

```text
ADMS ODOO_TOKEN=<token>
Odoo ir.config_parameter access_control.api_token=<mismo token>
```

No se usan nombres alternos ni fallbacks para tokens internos. Si existe un parámetro legacy como `access_control_api.api_token`, se ignora.

## Re-sincronización limpia de un SpeedFace

En `Control de Acceso > Inventario > Dispositivos`, el botón `Re-sincronizar SF` encola cambios nuevos y prioritarios para reconstruir un equipo sin pedirle a ADMS que reinicie desde cursor/token `0`.

La acción encola, para el sitio del dispositivo:

- `timezone_upsert` activos.
- `upsert` prioritario de cada persona activa esperada, incluyendo biophoto cuando exista.

ADMS debe consumir esos cambios con su cursor actual mediante `/api/access/sync/delta`.

## Administradores locales por SpeedFace

Un administrador de Odoo (Ajustes) puede seleccionar varios contactos existentes en
`Control de Acceso > Inventario > Dispositivos > Administradores locales`.
Cada contacto debe estar activo y tener una imagen de rostro válida, en el contacto
o en su persona de acceso. Odoo no verifica que la imagen contenga una cara: la
aceptación biométrica depende del equipo.

Al guardar se encolan upserts prioritarios, con rostro, exclusivamente para ese
dispositivo. El payload incluye `privilege: 14` para sus administradores y
`privilege: 0` para el resto. La asignación concede acceso general (horario 1,
grupo 1) en ese equipo, independientemente de la vigencia de una suscripción.
No concede administración ni acceso adicional en otros equipos del mismo sitio.
Los snapshots, las resincronizaciones y la auditoría incluyen estas identidades.

Al retirar un administrador se encola una actualización a usuario normal si aún
tiene acceso al sitio, o un delete si ya no lo tiene. La revocación se hace efectiva
cuando ADMS entregue el cambio al equipo. No se libera su PIN mientras siga
asignado a otro dispositivo. Se impide quitar su rostro, cambiar su identidad o
archivar el contacto mientras existan asignaciones.

ADMS debe enviar `deviceSerial` en cada petición de sync y preservar `privilege`
al decodificar el JSON, crear el comando `DATA UPDATE user` y reintentar la entrega.
La ausencia del atributo equivale a 0. La versión local revisada de ADMS fija ese
valor en 0 y requiere el cambio correspondiente antes de activar esta función.
El último sync de Odoo indica entrega del payload a ADMS, no confirmación biométrica
ni aceptación del privilegio por el dispositivo.

Despliegue: detener los workers, actualizar `access_control_api` con `-u` usando la
configuración y base del ambiente y `--stop-after-init`, verificar que finalice sin
errores y volver a iniciar Odoo. Subir código o reiniciar por sí solo no crea las
dos tablas relacionales ni actualiza la vista. No hay columnas nuevas en contactos.
