# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class AccessPerson(models.Model):
    _name = "access_control.person"
    _description = "Access Control Person (to sync to devices)"
    _rec_name = "partner_id"

    active = fields.Boolean(default=False, index=True)

    name = fields.Char(related="partner_id.name", store=True, readonly=True, index=True)

    site_ids = fields.Many2many(
        "access_control.site",
        "access_control_person_site_rel",
        "person_id",
        "site_id",
        string="Sites",
    )

    # Global sequential user id used by SpeedFace devices (1..10000)
    global_user_id = fields.Integer(string="Global User ID", index=True)
    # Compatibility alias for existing saved filters/list layouts in database.
    f18_user_id = fields.Integer(related="global_user_id", readonly=False)

    partner_id = fields.Many2one("res.partner", string="Partner", required=True, index=True)
    face_image = fields.Binary(string="Face Photo", attachment=True)
    face_pic_b64 = fields.Text(string="Face Pic (Base64)")
    has_face_pic = fields.Boolean(string="Has Face Pic", compute="_compute_has_face_pic", store=False)

    @api.depends("face_image", "face_pic_b64")
    def _compute_has_face_pic(self):
        for rec in self:
            rec.has_face_pic = bool(rec.face_pic_b64 and str(rec.face_pic_b64).strip())

    @api.model
    def _normalize_face_vals(self, vals):
        data = dict(vals or {})

        def _clean(value):
            return "".join(str(value).split()) if value else False

        if "face_image" in data:
            cleaned = _clean(data.get("face_image"))
            data["face_image"] = cleaned
            data["face_pic_b64"] = cleaned
        elif "face_pic_b64" in data:
            cleaned = _clean(data.get("face_pic_b64"))
            data["face_pic_b64"] = cleaned
            data["face_image"] = cleaned
        return data

    _sql_constraints = [
        ("uniq_global_user_id", "unique(global_user_id)", "Global User ID must be unique."),
        (
            "check_global_user_id_range",
            "CHECK(global_user_id IS NULL OR (global_user_id >= 1 AND global_user_id <= 10000))",
            "Global User ID must be between 1 and 10000.",
        ),
    ]

    @api.constrains("active", "global_user_id", "site_ids")
    def _check_active_requirements(self):
        for rec in self:
            if rec.active and rec.global_user_id is None:
                raise ValidationError("Active people must have a Global User ID (1..10000).")
            if rec.active and not rec.site_ids:
                raise ValidationError("Active people must be assigned to at least one Site.")

    @api.model_create_multi
    def create(self, vals_list):
        normalized_vals_list = [self._normalize_face_vals(vals) for vals in vals_list]
        records = super().create(normalized_vals_list)
        Change = self.env["access_control.sync_change"].sudo()
        for rec in records:
            if rec.active and rec.global_user_id and rec.site_ids:
                Change.queue_upsert_for_person(rec, reason="person_create")
        return records

    def write(self, vals):
        vals = self._normalize_face_vals(vals)
        before = {
            rec.id: {
                "active": rec.active,
                "global_user_id": rec.global_user_id,
                "site_ids": set(rec.site_ids.ids),
            }
            for rec in self
        }

        res = super().write(vals)

        Change = self.env["access_control.sync_change"].sudo()
        Site = self.env["access_control.site"].sudo()

        for rec in self:
            prev = before[rec.id]
            prev_active = prev["active"]
            prev_gid = prev["global_user_id"]
            prev_sites = prev["site_ids"]

            new_active = rec.active
            new_gid = rec.global_user_id
            new_sites = set(rec.site_ids.ids)

            prev_sync_sites = {sid for sid in prev_sites if prev_active and prev_gid}
            new_sync_sites = {sid for sid in new_sites if new_active and new_gid}

            removed_sites = prev_sync_sites - new_sync_sites
            for site_id in sorted(removed_sites):
                Change.queue_delete(prev_gid, [site_id], reason="person_write_removed")

            # If global user id changed, old id must be removed from sites that remain active.
            if prev_gid and new_gid and prev_gid != new_gid:
                for site_id in sorted(prev_sync_sites & new_sync_sites):
                    Change.queue_delete(prev_gid, [site_id], reason="person_write_gid_changed")

            # Any valid current state should be upserted for current sync sites.
            for site_id in sorted(new_sync_sites):
                Change.queue_upsert_for_person(
                    rec,
                    site_ids=Site.browse(site_id),
                    reason="person_write_upsert",
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
        """Assign the lowest available Global User ID (1..10000)."""
        for rec in self:
            if rec.global_user_id:
                continue
            self.env.cr.execute(
                """
                SELECT global_user_id
                  FROM access_control_person
                 WHERE global_user_id IS NOT NULL
                """
            )
            used = {row[0] for row in self.env.cr.fetchall() if row and row[0]}
            chosen = None
            for i in range(1, 10001):
                if i not in used:
                    chosen = i
                    break
            if not chosen:
                raise ValidationError("No available Global User IDs (1..10000).")
            rec.global_user_id = chosen
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
                raise ValidationError("Please assign at least one Site before activating this person.")
            if not rec.global_user_id:
                raise ValidationError("Please assign a Global User ID (1..10000) before activating this person.")
            rec.active = True
            rec.site_ids.write({"force_sync": True})
        return self._notify("Activated", "Person activated and marked for sync.")

    def action_deactivate(self):
        for rec in self:
            if not rec.active:
                continue
            rec.active = False
            if rec.site_ids:
                rec.site_ids.write({"force_sync": True})
        return self._notify("Deactivated", "Person deactivated and marked for sync.", typ="warning")
