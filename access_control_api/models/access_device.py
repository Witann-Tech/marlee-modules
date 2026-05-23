# -*- coding: utf-8 -*-
import logging

import requests

from odoo import _, models, fields
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)


class AccessControlDevice(models.Model):
    _name = "access_control.device"
    _description = "Dispositivo de Control de Acceso (SpeedFace)"
    _rec_name = "name"

    active = fields.Boolean(default=True)

    name = fields.Char(required=True)
    device_serial = fields.Char(required=True, index=True)

    site_id = fields.Many2one("access_control.site", required=True, ondelete="cascade")

    user_capacity = fields.Integer(string="Capacidad de usuarios", default=10000)

    # Telemetría (actualizada por middleware/ADMS)
    last_heartbeat_at = fields.Datetime(string="Último heartbeat", readonly=True)
    last_sync_at = fields.Datetime(string="Última sincronización", readonly=True)
    last_error = fields.Text(string="Último error", readonly=True)

    _device_serial_uniq = models.Constraint(
        "unique(device_serial)",
        "El serial del dispositivo debe ser único.",
    )
    _user_capacity_positive = models.Constraint(
        "CHECK(user_capacity IS NULL OR user_capacity > 0)",
        "La capacidad de usuarios debe ser mayor a cero.",
    )

    def _get_adms_config(self):
        ICP = self.env["ir.config_parameter"].sudo()
        base_url = (
            ICP.get_param("adms.base_url")
            or ICP.get_param("ADMS_BASE_URL")
            or ICP.get_param("access_control.adms_base_url")
        )
        token = (
            ICP.get_param("adms.internal_api_token")
            or ICP.get_param("INTERNAL_API_TOKEN")
            or ICP.get_param("access_control.internal_api_token")
        )
        return (base_url or "").strip().rstrip("/"), (token or "").strip()

    def open_door_via_adms(self, door_id=1, open_time_seconds=5, reason="manual_open_door", operator_user=None):
        self.ensure_one()
        if not self.active:
            raise UserError(_("El dispositivo seleccionado está inactivo."))
        if not self.device_serial:
            raise UserError(_("El dispositivo no tiene serial configurado."))

        base_url, token = self._get_adms_config()
        if not base_url or not token:
            raise UserError(_("Configura ADMS_BASE_URL e INTERNAL_API_TOKEN antes de abrir puertas."))

        try:
            door_id = int(door_id or 1)
        except (TypeError, ValueError):
            door_id = 1
        try:
            open_time_seconds = int(open_time_seconds or 5)
        except (TypeError, ValueError):
            open_time_seconds = 5
        door_id = max(1, door_id)
        open_time_seconds = min(max(1, open_time_seconds), 60)
        operator_user = operator_user or self.env.user

        payload = {
            "deviceSerial": self.device_serial,
            "doorId": door_id,
            "openTimeSeconds": open_time_seconds,
            "operatorUserId": operator_user.id,
            "reason": str(reason or "manual_open_door").strip(),
        }
        url = "%s/admin/devices/open-door" % base_url
        try:
            response = requests.post(
                url,
                json=payload,
                headers={
                    "Authorization": "Bearer %s" % token,
                    "Content-Type": "application/json",
                },
                timeout=8,
            )
            response.raise_for_status()
            response_data = response.json() if response.content else {}
            if isinstance(response_data, dict) and response_data.get("ok") is False:
                raise UserError(response_data.get("reason") or _("ADMS rechazó el comando de apertura."))
        except UserError:
            raise
        except requests.RequestException as error:
            status_code = getattr(getattr(error, "response", None), "status_code", None)
            body = ""
            if getattr(error, "response", None) is not None:
                body = (error.response.text or "")[:500]
            _logger.warning(
                "access_device open_door failed device_id=%s serial=%s status=%s error=%s body=%s",
                self.id,
                self.device_serial,
                status_code,
                error,
                body,
            )
            raise UserError(_("No se pudo abrir la puerta desde ADMS. Revisa conexión y permisos.")) from error
        except ValueError as error:
            _logger.warning(
                "access_device open_door invalid_json device_id=%s serial=%s error=%s",
                self.id,
                self.device_serial,
                error,
            )
            response_data = {}

        _logger.info(
            "access_device open_door requested device_id=%s serial=%s user_id=%s door_id=%s open_time=%s",
            self.id,
            self.device_serial,
            operator_user.id,
            door_id,
            open_time_seconds,
        )
        return {
            "ok": True,
            "device_id": self.id,
            "device_name": self.display_name,
            "device_serial": self.device_serial,
            "door_id": door_id,
            "open_time_seconds": open_time_seconds,
            "adms_response": response_data if isinstance(response_data, dict) else {},
        }
