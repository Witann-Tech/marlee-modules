# -*- coding: utf-8 -*-
import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)
_TIME_RE = re.compile(r"^\d{2}:\d{2}$")


class AccessControlTimezone(models.Model):
    _name = "access_control.timezone"
    _description = "Horario Global de Acceso"
    _order = "timezone_id asc, id asc"

    active = fields.Boolean(default=True, index=True)
    name = fields.Char(required=True)
    timezone_id = fields.Integer(string="Timezone ID", required=True, index=True, readonly=True)
    description = fields.Text()
    interval_ids = fields.One2many(
        "access_control.timezone.interval",
        "access_timezone_id",
        string="Ventanas",
        copy=True,
    )
    last_sync_at = fields.Datetime(string="Última sincronización", readonly=True)
    sync_state = fields.Selection(
        [("pending", "Pendiente"), ("synced", "Sincronizado")],
        string="Estado de sincronización",
        default="pending",
        readonly=True,
        index=True,
    )
    is_general = fields.Boolean(string="Acceso general", compute="_compute_is_general", store=True)
    interval_summary = fields.Char(string="Ventanas por día", compute="_compute_interval_summary")

    _timezone_id_uniq = models.Constraint(
        "unique(timezone_id)",
        "El timezone_id debe ser único.",
    )
    _timezone_id_positive = models.Constraint(
        "CHECK(timezone_id >= 1)",
        "El timezone_id debe ser mayor o igual a 1.",
    )

    @api.depends("timezone_id")
    def _compute_is_general(self):
        for rec in self:
            rec.is_general = rec.timezone_id == 1

    @api.depends("interval_ids.day", "interval_ids.start_time", "interval_ids.end_time", "interval_ids.sequence")
    def _compute_interval_summary(self):
        day_labels = dict(self.env["access_control.timezone.interval"]._fields["day"].selection)
        for rec in self:
            by_day = {}
            for line in rec.interval_ids.sorted(key=lambda item: (item.day or "", item.sequence or 0, item.id or 0)):
                by_day.setdefault(line.day, []).append("%s-%s" % (line.start_time, line.end_time))
            rec.interval_summary = "; ".join(
                "%s %s" % (day_labels.get(day, day), ", ".join(values))
                for day, values in by_day.items()
            )

    @api.model
    def _next_timezone_id(self):
        last = self.with_context(active_test=False).search([], order="timezone_id desc", limit=1)
        return max(2, int(last.timezone_id or 1) + 1)

    @api.onchange("name", "description", "interval_ids", "active")
    def _onchange_warn_assigned_active_people(self):
        for rec in self:
            if not rec.id or rec.timezone_id <= 1:
                continue
            assigned_count = self.env["access_control.person"].sudo().search_count(
                [
                    ("active", "=", True),
                    ("access_timezone_id", "=", rec.id),
                ]
            )
            if assigned_count:
                return {
                    "warning": {
                        "title": _("Horario asignado"),
                        "message": _(
                            "Este horario está asignado a %s persona(s) activa(s). "
                            "Cualquier cambio impactará todos los SpeedFace sincronizados."
                        )
                        % assigned_count,
                    }
                }
        return {}

    @api.model_create_multi
    def create(self, vals_list):
        prepared = []
        for vals in vals_list:
            data = dict(vals or {})
            if not data.get("timezone_id"):
                data["timezone_id"] = self._next_timezone_id()
            elif int(data["timezone_id"]) == 1 and not self.env.context.get("allow_general_access_timezone"):
                existing_general = self.with_context(active_test=False).search([("timezone_id", "=", 1)], limit=1)
                if existing_general:
                    raise ValidationError(_("El timezone_id=1 está reservado para Acceso general."))
            elif int(data["timezone_id"]) < 1:
                raise ValidationError(_("El timezone_id debe ser mayor o igual a 1."))
            prepared.append(data)
        records = super().create(prepared)
        records.filtered(lambda rec: rec.timezone_id > 1 and rec.active)._queue_timezone_upserts(reason="timezone_create")
        return records

    def write(self, vals):
        protected = self.filtered(lambda rec: rec.timezone_id == 1)
        if protected and any(field in vals for field in ("timezone_id", "active", "name", "description", "interval_ids")):
            raise ValidationError(_("El horario timezone_id=1 Acceso general no se puede editar desde la UI."))
        watched_fields = {"name", "description", "interval_ids", "active"}
        res = super().write(vals)
        if watched_fields.intersection(vals):
            to_sync = self.filtered(lambda rec: rec.timezone_id > 1 and rec.active)
            if to_sync:
                to_sync.write({"sync_state": "pending"})
                to_sync._queue_timezone_upserts(reason="timezone_write")
        return res

    def unlink(self):
        if any(rec.timezone_id == 1 for rec in self):
            raise ValidationError(_("El horario timezone_id=1 Acceso general no se puede borrar."))
        self.write({"active": False, "sync_state": "pending"})
        return True

    def _interval_payload(self):
        self.ensure_one()
        return [
            {
                "day": line.day,
                "start": line.start_time,
                "end": line.end_time,
            }
            for line in self.interval_ids.sorted(key=lambda item: (item.day or "", item.sequence or 0, item.id or 0))
        ]

    def _command_payload(self):
        self.ensure_one()
        return {
            "timezoneId": int(self.timezone_id),
            "name": self.name or "",
            "description": self.description or "",
            "priority": True,
            "intervals": self._interval_payload(),
        }

    def _queue_timezone_upserts(self, site_ids=None, reason="timezone_update"):
        Change = self.env["access_control.sync_change"].sudo()
        return Change.queue_timezone_upsert(self, site_ids=site_ids, reason=reason)

    @api.model
    def queue_active_timezones_for_sites(self, site_ids=None, reason="timezone_resync"):
        timezones = self.search([("active", "=", True), ("timezone_id", ">", 1)], order="timezone_id asc")
        return timezones._queue_timezone_upserts(site_ids=site_ids, reason=reason) if timezones else False

    def mark_synced(self, synced_at=None):
        synced_at = synced_at or fields.Datetime.now()
        self.filtered(lambda rec: rec.timezone_id > 1).sudo().write(
            {
                "last_sync_at": synced_at,
                "sync_state": "synced",
            }
        )


class AccessControlTimezoneInterval(models.Model):
    _name = "access_control.timezone.interval"
    _description = "Ventana de Horario de Acceso"
    _order = "day asc, sequence asc, id asc"

    access_timezone_id = fields.Many2one(
        "access_control.timezone",
        string="Horario",
        required=True,
        index=True,
        ondelete="cascade",
    )
    day = fields.Selection(
        [
            ("mon", "Lun"),
            ("tue", "Mar"),
            ("wed", "Mié"),
            ("thu", "Jue"),
            ("fri", "Vie"),
            ("sat", "Sáb"),
            ("sun", "Dom"),
        ],
        required=True,
        index=True,
    )
    sequence = fields.Integer(default=10)
    start_time = fields.Char(string="Inicio", required=True, default="06:00")
    end_time = fields.Char(string="Fin", required=True, default="14:00")

    @api.constrains("day", "start_time", "end_time", "access_timezone_id")
    def _check_interval_values(self):
        for rec in self:
            start_minutes = rec._time_to_minutes(rec.start_time)
            end_minutes = rec._time_to_minutes(rec.end_time)
            if start_minutes is False or end_minutes is False:
                raise ValidationError(_("Las ventanas deben usar formato HH:MM."))
            if start_minutes > end_minutes:
                raise ValidationError(_("La hora de inicio debe ser menor o igual a la hora de fin."))
            if rec.access_timezone_id:
                count = self.search_count(
                    [
                        ("access_timezone_id", "=", rec.access_timezone_id.id),
                        ("day", "=", rec.day),
                        ("id", "!=", rec.id),
                    ]
                )
                if count >= 3:
                    raise ValidationError(_("Cada día permite máximo 3 ventanas de acceso."))

    @api.model
    def _time_to_minutes(self, value):
        value = (value or "").strip()
        if not _TIME_RE.match(value):
            return False
        hour, minute = value.split(":", 1)
        hour = int(hour)
        minute = int(minute)
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            return False
        return hour * 60 + minute
