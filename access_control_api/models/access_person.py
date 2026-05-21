# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class AccessPerson(models.Model):
    _name = "access_control.person"
    _description = "Persona de Control de Acceso (sincronización a dispositivos)"
    _rec_name = "partner_id"

    active = fields.Boolean(default=False, index=True)
    access_state = fields.Selection(
        [("enabled", "Habilitado"), ("suspended", "Suspendido")],
        default="enabled",
        required=True,
        index=True,
        string="Estado de acceso",
    )
    managed_by_subscription = fields.Boolean(string="Gestionado por suscripción", default=False, index=True)
    access_origin = fields.Selection(
        [("manual", "Manual"), ("subscription", "Suscripción")],
        string="Origen",
        compute="_compute_access_origin",
        store=False,
    )

    name = fields.Char(related="partner_id.name", store=True, readonly=True, index=True)

    site_ids = fields.Many2many(
        "access_control.site",
        "access_control_person_site_rel",
        "person_id",
        "site_id",
        string="Sitios",
    )

    # Id global secuencial utilizado por SpeedFace (1..10000)
    global_user_id = fields.Integer(string="ID global", index=True)
    # Compatibility alias for existing saved filters/list layouts in database.
    f18_user_id = fields.Integer(related="global_user_id", readonly=False)

    partner_id = fields.Many2one("res.partner", string="Partner", required=True, index=True)
    partner_face_image = fields.Binary(related="partner_id.image_1920", string="Foto de rostro", readonly=True)
    face_image = fields.Binary(string="Foto de rostro", attachment=True)
    face_pic_b64 = fields.Text(string="Foto de rostro (Base64)")
    has_face_pic = fields.Boolean(string="Tiene foto de rostro", compute="_compute_has_face_pic", store=False)
    last_access_at = fields.Datetime(string="Último acceso", readonly=True, index=True)
    last_access_result = fields.Selection(
        [("allowed", "Permitido"), ("denied", "Denegado"), ("error", "Error")],
        string="Resultado último acceso",
        readonly=True,
    )
    last_access_site_id = fields.Many2one("access_control.site", string="Sitio último acceso", readonly=True)
    last_access_device_id = fields.Many2one("access_control.device", string="Dispositivo último acceso", readonly=True)

    @api.depends("face_image", "face_pic_b64", "partner_face_image")
    def _compute_has_face_pic(self):
        for rec in self:
            rec.has_face_pic = bool(
                (rec.face_pic_b64 and str(rec.face_pic_b64).strip())
                or rec.face_image
                or rec.partner_face_image
            )

    @api.depends("managed_by_subscription")
    def _compute_access_origin(self):
        for rec in self:
            rec.access_origin = "subscription" if rec.managed_by_subscription else "manual"

    @api.model
    def _used_global_user_ids(self):
        self.env.cr.execute(
            """
            SELECT global_user_id
              FROM access_control_person
             WHERE global_user_id IS NOT NULL
            """
        )
        return {row[0] for row in self.env.cr.fetchall() if row and row[0]}

    @api.model
    def _next_available_global_user_id(self, used):
        for i in range(1, 10001):
            if i not in used:
                return i
        return False

    @api.model
    def _normalize_face_vals(self, vals):
        data = dict(vals or {})
        partner_model = self.env["res.partner"]

        def _clean(value):
            return partner_model._normalize_image_b64(value)

        if "face_image" in data:
            cleaned = _clean(data.get("face_image"))
            data["face_image"] = cleaned
            data["face_pic_b64"] = cleaned
        elif "face_pic_b64" in data:
            cleaned = _clean(data.get("face_pic_b64"))
            data["face_pic_b64"] = cleaned
            data["face_image"] = cleaned
        return data

    @api.model
    def _fill_face_from_partner(self, vals):
        data = dict(vals or {})
        if data.get("face_image") or data.get("face_pic_b64"):
            return data
        partner_id = data.get("partner_id")
        if not partner_id:
            return data
        partner = self.env["res.partner"].sudo().browse(partner_id)
        if partner.exists() and partner.image_1920:
            img = self.env["res.partner"]._prepare_biometric_face_b64(
                partner.image_1920,
                log_context=f"person_fill_partner:{partner.id}",
            )
            data["face_image"] = img
            data["face_pic_b64"] = img
        return data

    @api.onchange("partner_id")
    def _onchange_partner_id_copy_face(self):
        for rec in self:
            if rec.partner_id and not rec.face_image and rec.partner_id.image_1920:
                img = self.env["res.partner"]._prepare_biometric_face_b64(
                    rec.partner_id.image_1920,
                    log_context=f"person_onchange_partner:{rec.partner_id.id or 'new'}",
                )
                rec.face_image = img
                rec.face_pic_b64 = img

    _global_user_id_uniq = models.Constraint(
        "unique(global_user_id)",
        "El ID global debe ser único.",
    )
    _partner_id_uniq = models.Constraint(
        "unique(partner_id)",
        "Solo puede existir una persona de control de acceso por contacto.",
    )
    _global_user_id_range = models.Constraint(
        "CHECK(global_user_id IS NULL OR (global_user_id >= 1 AND global_user_id <= 10000))",
        "El ID global debe estar entre 1 y 10000.",
    )

    @api.constrains("active", "global_user_id", "site_ids")
    def _check_active_requirements(self):
        for rec in self:
            if rec.active and rec.global_user_id is None:
                raise ValidationError("Las personas activas deben tener un ID global (1..10000).")
            if rec.active and not rec.site_ids:
                raise ValidationError("Las personas activas deben estar asignadas a al menos un sitio.")

    @api.constrains("partner_id")
    def _check_unique_partner_id(self):
        for rec in self:
            if not rec.partner_id:
                continue
            duplicate = self.search(
                [
                    ("partner_id", "=", rec.partner_id.id),
                    ("id", "!=", rec.id),
                ],
                limit=1,
            )
            if duplicate:
                raise ValidationError("Solo puede existir una persona de control de acceso por contacto.")

    @api.model_create_multi
    def create(self, vals_list):
        used_ids = self._used_global_user_ids()
        normalized_vals_list = []
        for vals in vals_list:
            data = self._normalize_face_vals(vals)
            data = self._fill_face_from_partner(data)
            if not data.get("global_user_id"):
                next_id = self._next_available_global_user_id(used_ids)
                if not next_id:
                    raise ValidationError("No hay IDs globales disponibles (1..10000).")
                data["global_user_id"] = next_id
            used_ids.add(int(data["global_user_id"]))
            normalized_vals_list.append(data)

        records = super().create(normalized_vals_list)
        Change = self.env["access_control.sync_change"].sudo()
        for rec in records:
            if rec.active and rec.global_user_id and rec.site_ids:
                Change.queue_upsert_for_person(
                    rec,
                    reason="person_create",
                    include_face_pic=bool(rec.face_pic_b64),
                    clear_face_pic=not bool(rec.face_pic_b64),
                )
        return records

    def write(self, vals):
        vals = self._normalize_face_vals(vals)
        vals = self._fill_face_from_partner(vals)
        # Al dar de baja, se libera el ID global para reutilización futura.
        if vals.get("active") is False and "global_user_id" not in vals:
            vals["global_user_id"] = False
        before = {
            rec.id: {
                "active": rec.active,
                "access_state": rec.access_state,
                "global_user_id": rec.global_user_id,
                "site_ids": set(rec.site_ids.ids),
                "face_pic_b64": rec.face_pic_b64 or False,
            }
            for rec in self
        }

        res = super().write(vals)

        Change = self.env["access_control.sync_change"].sudo()
        Site = self.env["access_control.site"].sudo()

        for rec in self:
            prev = before[rec.id]
            prev_active = prev["active"]
            prev_access_state = prev["access_state"]
            prev_gid = prev["global_user_id"]
            prev_sites = prev["site_ids"]
            prev_face = prev["face_pic_b64"] or False

            new_active = rec.active
            new_access_state = rec.access_state
            new_gid = rec.global_user_id
            new_sites = set(rec.site_ids.ids)
            new_face = rec.face_pic_b64 or False
            face_changed = prev_face != new_face
            access_state_changed = prev_access_state != new_access_state

            prev_sync_sites = {sid for sid in prev_sites if prev_active and prev_gid}
            new_sync_sites = {sid for sid in new_sites if new_active and new_gid}

            # En transición activo->inactivo, forzar delete en todos los sitios previos.
            if prev_active and not new_active and prev_gid:
                for site_id in sorted(prev_sync_sites):
                    Change.queue_delete(prev_gid, [site_id], reason="person_write_deactivated")
                continue

            removed_sites = prev_sync_sites - new_sync_sites
            for site_id in sorted(removed_sites):
                Change.queue_delete(prev_gid, [site_id], reason="person_write_removed")

            # If global user id changed, old id must be removed from sites that remain active.
            if prev_gid and new_gid and prev_gid != new_gid:
                for site_id in sorted(prev_sync_sites & new_sync_sites):
                    Change.queue_delete(prev_gid, [site_id], reason="person_write_gid_changed")

            # Any valid current state should be upserted for current sync sites.
            for site_id in sorted(new_sync_sites):
                include_face_pic = bool(new_face) and (
                    face_changed or access_state_changed or site_id not in prev_sync_sites
                )
                clear_face_pic = (not new_face) and (
                    face_changed or access_state_changed or site_id not in prev_sync_sites
                )
                Change.queue_upsert_for_person(
                    rec,
                    site_ids=Site.browse(site_id),
                    reason="person_write_upsert",
                    include_face_pic=include_face_pic,
                    clear_face_pic=clear_face_pic,
                )

        return res

    def unlink(self):
        before = [
            {
                "global_user_id": rec.global_user_id,
                "site_ids": set(rec.site_ids.ids),
                "active": rec.active,
            }
            for rec in self
        ]

        res = super().unlink()

        Change = self.env["access_control.sync_change"].sudo()
        for prev in before:
            if prev["active"] and prev["global_user_id"] and prev["site_ids"]:
                Change.queue_delete(
                    prev["global_user_id"],
                    list(prev["site_ids"]),
                    reason="person_unlink",
                )

        return res

    def action_assign_global_user_id(self):
        """Asigna el ID global disponible más bajo (1..10000)."""
        used = self._used_global_user_ids()
        for rec in self:
            if rec.global_user_id:
                continue
            chosen = self._next_available_global_user_id(used)
            if not chosen:
                raise ValidationError("No hay IDs globales disponibles (1..10000).")
            rec.global_user_id = chosen
            used.add(chosen)
        return True

    def _notify(self, title, message, typ="success"):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": message,
                "type": typ,
                "sticky": False,
            },
        }

    def action_activate(self):
        for rec in self:
            if rec.active:
                continue
            if not rec.site_ids:
                raise ValidationError("Asigna al menos un sitio antes de activar esta persona.")
            if not rec.global_user_id:
                raise ValidationError("Asigna un ID global (1..10000) antes de activar esta persona.")
            rec.active = True
            rec.site_ids.write({"force_sync": True})
        return self._notify("Activado", "Persona activada y marcada para sincronización.")

    def action_deactivate(self):
        for rec in self:
            if not rec.active:
                continue
            rec.active = False
            if rec.site_ids:
                rec.site_ids.write({"force_sync": True})
        return self._notify(
            "Desactivado",
            "Persona desactivada, marcada para sincronización y con ID global liberado.",
            typ="warning",
        )

    def register_access_event(self, occurred_at, result=None, site=None, device=None):
        for rec in self:
            if not occurred_at:
                continue
            if rec.last_access_at and occurred_at <= rec.last_access_at:
                continue
            rec.sudo().write(
                {
                    "last_access_at": occurred_at,
                    "last_access_result": result or False,
                    "last_access_site_id": site.id if site else False,
                    "last_access_device_id": device.id if device else False,
                }
            )
        return True
