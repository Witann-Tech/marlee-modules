# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ResPartner(models.Model):
    _inherit = "res.partner"

    access_person_ids = fields.One2many(
        "access_control.person",
        "partner_id",
        string="Control de acceso",
    )
    access_person_face_preview = fields.Binary(
        string="Foto biométrica",
        compute="_compute_access_person_face_preview",
    )

    @api.model
    def _normalize_image_b64(self, image_b64):
        return "".join(str(image_b64).split()) if image_b64 else False

    @api.onchange("image_1920")
    def _onchange_image_1920_sync_access_people(self):
        for partner in self:
            img = partner._normalize_image_b64(partner.image_1920)
            for person in partner.access_person_ids:
                person.face_image = img
                person.face_pic_b64 = img

    @api.depends("access_person_ids.face_image", "access_person_ids.face_pic_b64")
    def _compute_access_person_face_preview(self):
        for partner in self:
            person = partner.access_person_ids[:1]
            partner.access_person_face_preview = person.face_image or person.face_pic_b64 or False

    def _sync_access_person_face(self):
        Person = self.env["access_control.person"].sudo()
        for partner in self:
            people = Person.search([("partner_id", "=", partner.id)])
            if not people:
                continue
            img = self._normalize_image_b64(partner.image_1920)
            people.write(
                {
                    "face_image": img,
                    "face_pic_b64": img,
                }
            )

    @api.model_create_multi
    def create(self, vals_list):
        normalized_vals_list = []
        for vals in vals_list:
            data = dict(vals or {})
            if "image_1920" in data:
                data["image_1920"] = self._normalize_image_b64(data.get("image_1920"))
            normalized_vals_list.append(data)

        records = super().create(normalized_vals_list)
        if records:
            records._sync_access_person_face()
        return records

    def write(self, vals):
        data = dict(vals or {})
        if "image_1920" in data:
            data["image_1920"] = self._normalize_image_b64(data.get("image_1920"))

        res = super().write(data)
        if "image_1920" in data:
            self._sync_access_person_face()
        return res
