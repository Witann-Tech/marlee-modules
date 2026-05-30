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
