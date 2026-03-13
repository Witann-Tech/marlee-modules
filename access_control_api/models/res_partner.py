# -*- coding: utf-8 -*-
import base64
import binascii
import io
import re
from odoo import models, fields, api

try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover - depends on server runtime
    Image = None
    ImageOps = None


class ResPartner(models.Model):
    _inherit = "res.partner"

    access_person_ids = fields.One2many(
        "access_control.person",
        "partner_id",
        string="Control de acceso",
    )
    camera_capture_helper = fields.Char(
        string="Captura de foto",
        compute="_compute_camera_capture_helper",
    )

    @api.model
    def _normalize_image_b64(self, image_b64):
        if not image_b64:
            return False
        value = "".join(str(image_b64).split())
        value = re.sub(r"^data:image/[^;]+;base64,", "", value, flags=re.IGNORECASE)
        value = re.sub(r"[^A-Za-z0-9+/=]", "", value)
        while value and len(value) % 4 == 1:
            value = value[:-1]
        if value and len(value) % 4:
            value += "=" * (4 - (len(value) % 4))
        if not value:
            return False
        try:
            raw = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError):
            return False
        if Image and ImageOps:
            try:
                with Image.open(io.BytesIO(raw)) as img:
                    img = ImageOps.exif_transpose(img)
                    if img.mode not in ("RGB", "L"):
                        img = img.convert("RGBA")
                    if img.mode == "RGBA":
                        background = Image.new("RGB", img.size, (255, 255, 255))
                        background.paste(img, mask=img.split()[-1])
                        img = background
                    elif img.mode != "RGB":
                        img = img.convert("RGB")

                    crop_size = min(img.size)
                    left = max(0, (img.width - crop_size) // 2)
                    top = max(0, (img.height - crop_size) // 2)
                    img = img.crop((left, top, left + crop_size, top + crop_size))
                    img = img.resize((1024, 1024), Image.Resampling.LANCZOS)

                    output = io.BytesIO()
                    img.save(output, format="JPEG", quality=90, optimize=True)
                    raw = output.getvalue()
            except Exception:
                pass
        return base64.b64encode(raw).decode()

    def _compute_camera_capture_helper(self):
        for partner in self:
            partner.camera_capture_helper = False

    @api.onchange("image_1920")
    def _onchange_image_1920_sync_access_people(self):
        for partner in self:
            img = partner._normalize_image_b64(partner.image_1920)
            for person in partner.access_person_ids:
                person.face_image = img
                person.face_pic_b64 = img

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
