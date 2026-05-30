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
