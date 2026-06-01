# -*- coding: utf-8 -*-
import base64
import binascii
import io
import logging
import re
from odoo import models, fields, api

try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover - depends on server runtime
    Image = None
    ImageOps = None

_logger = logging.getLogger(__name__)
_RESAMPLE_LANCZOS = getattr(getattr(Image, "Resampling", Image), "LANCZOS", None) if Image else None


class ResPartner(models.Model):
    _inherit = "res.partner"

    access_person_ids = fields.One2many(
        "access_control.person",
        "partner_id",
        string="Control de acceso",
        groups="access_control_api.group_access_control_contact_access",
    )
    camera_capture_helper = fields.Char(
        string="Captura de foto",
        compute="_compute_camera_capture_helper",
        groups="access_control_api.group_access_control_contact_access",
    )
    access_global_user_id = fields.Integer(
        string="ID global",
        compute="_compute_access_summary",
        groups="access_control_api.group_access_control_contact_access",
    )
    access_last_access_at = fields.Datetime(
        string="Último acceso",
        compute="_compute_access_summary",
        groups="access_control_api.group_access_control_contact_access",
    )
    access_origin = fields.Selection(
        [("manual", "Manual"), ("subscription", "Suscripción")],
        string="Origen acceso",
        compute="_compute_access_summary",
        groups="access_control_api.group_access_control_contact_access",
    )
    access_timezone_id = fields.Many2one(
        "access_control.timezone",
        string="Horario de acceso",
        compute="_compute_access_summary",
        groups="access_control_api.group_access_control_contact_access",
    )
    access_authorize_timezone_id = fields.Integer(
        string="Timezone ID",
        compute="_compute_access_summary",
        groups="access_control_api.group_access_control_contact_access",
    )

    @api.model
    def _normalize_image_b64(self, image_b64):
        if not image_b64:
            return False
        if isinstance(image_b64, (bytes, bytearray)):
            try:
                value = image_b64.decode()
            except UnicodeDecodeError:
                _logger.warning("face_b64 invalid_format context=normalize reason=bytes_decode_failed")
                return False
        else:
            value = str(image_b64)
        value = "".join(value.split())
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
        return base64.b64encode(raw).decode()

    @api.model
    def _prepare_biometric_face_b64(self, image_b64, log_context=None):
        context = log_context or "face"
        normalized = self._normalize_image_b64(image_b64)
        if image_b64 and not normalized:
            _logger.warning("face_b64 invalid_format context=%s", context)
            return False
        if not normalized:
            _logger.info("face_b64 empty_image context=%s", context)
            return False
        if not Image or not ImageOps:
            _logger.error("face_b64 jpeg_conversion_error context=%s reason=pillow_missing", context)
            return False
        try:
            raw = base64.b64decode(normalized, validate=True)
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

                target_ratio = 480.0 / 640.0
                current_ratio = (img.width / img.height) if img.height else target_ratio
                if current_ratio > target_ratio:
                    crop_height = img.height
                    crop_width = int(round(crop_height * target_ratio))
                else:
                    crop_width = img.width
                    crop_height = int(round(crop_width / target_ratio))

                left = max(0, (img.width - crop_width) // 2)
                top = max(0, (img.height - crop_height) // 2)
                img = img.crop((left, top, left + crop_width, top + crop_height))
                img = img.resize((480, 640), _RESAMPLE_LANCZOS or Image.LANCZOS)

                if img.size != (480, 640):
                    _logger.error("face_b64 invalid_dimensions context=%s width=%s height=%s", context, img.width, img.height)
                    return False

                payload = None
                for quality in (85, 82, 80):
                    output = io.BytesIO()
                    img.save(output, format="JPEG", quality=quality, optimize=True)
                    candidate = output.getvalue()
                    if len(candidate) <= 500 * 1024:
                        payload = candidate
                        if len(candidate) < 100 * 1024 or len(candidate) > 300 * 1024:
                            _logger.info(
                                "face_b64 size_outside_target context=%s bytes=%s quality=%s",
                                context,
                                len(candidate),
                                quality,
                            )
                        break

                if not payload:
                    _logger.error("face_b64 payload_too_large context=%s bytes=%s", context, len(candidate))
                    return False

                return base64.b64encode(payload).decode()
        except Exception as exc:
            _logger.exception("face_b64 jpeg_conversion_error context=%s error=%s", context, exc)
            return False

    def _compute_camera_capture_helper(self):
        for partner in self:
            partner.camera_capture_helper = False

    @api.depends(
        "access_person_ids.global_user_id",
        "access_person_ids.last_access_at",
        "access_person_ids.managed_by_subscription",
        "access_person_ids.access_timezone_id",
        "access_person_ids.authorize_timezone_id",
    )
    def _compute_access_summary(self):
        Person = self.env["access_control.person"].sudo()
        people = Person.search([("partner_id", "in", self.ids)])
        people_by_partner = {person.partner_id.id: person for person in people}
        for partner in self:
            person = people_by_partner.get(partner.id)
            partner.access_global_user_id = person.global_user_id if person else False
            partner.access_last_access_at = person.last_access_at if person else False
            partner.access_origin = person.access_origin if person else False
            partner.access_timezone_id = person.access_timezone_id if person else False
            partner.access_authorize_timezone_id = person.authorize_timezone_id if person else False

    @api.onchange("image_1920")
    def _onchange_image_1920_sync_access_people(self):
        Person = self.env["access_control.person"].sudo()
        for partner in self:
            img = partner._prepare_biometric_face_b64(partner.image_1920, log_context=f"partner_onchange:{partner.id or 'new'}")
            people = Person.search([("partner_id", "=", partner.id)])
            for person in people:
                person.face_image = img
                person.face_pic_b64 = img

    def _sync_access_person_face(self):
        Person = self.env["access_control.person"].sudo()
        for partner in self:
            people = Person.search([("partner_id", "=", partner.id)])
            if not people:
                continue
            img = self._prepare_biometric_face_b64(partner.image_1920, log_context=f"partner_write:{partner.id}")
            _logger.info(
                "partner_face_sync partner_id=%s people=%s has_face=%s b64_len=%s",
                partner.id,
                people.ids,
                bool(img),
                len(img or ""),
            )
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
