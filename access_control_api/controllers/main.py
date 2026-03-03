# -*- coding: utf-8 -*-
import json
from odoo import http, fields
from odoo.http import request


class AccessControlApi(http.Controller):

    def _auth_ok(self):
        auth = request.httprequest.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return False, "missing_token"
        token = auth.split(" ", 1)[1].strip()
        expected = request.env["ir.config_parameter"].sudo().get_param("access_control.api_token")
        if not expected:
            return False, "server_token_not_configured"
        if token != expected:
            return False, "invalid_token"
        return True, None

    def _payload_data(self, payload):
        data = request.params or payload or {}
        try:
            rpc_params = (request.jsonrequest or {}).get("params") or {}
            if isinstance(rpc_params, dict):
                data = {**data, **rpc_params}
        except Exception:
            pass
        return data

    def _as_int(self, value, default=None):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _normalize_modality(self, modality):
        if not modality:
            return None
        m = str(modality).strip().lower()
        if m in ("face", "palm"):
            return m
        return None

    def _person_sync_payload(self, person):
        face = person.credential_ids.filtered(lambda c: c.active and c.credential_type == "face")[:1]
        palm = person.credential_ids.filtered(lambda c: c.active and c.credential_type == "palm")[:1]

        return {
            "globalUserId": person.global_user_id,
            "name": person.name or "",
            "externalRef": person.external_ref or "",
            "active": bool(person.active),
            "modalities": {
                "face": {
                    "enrolled": bool(face and face.biometric_b64),
                    "templateB64": face.biometric_b64 if face else None,
                    "format": face.biometric_format if face else None,
                },
                "palm": {
                    "enrolled": bool(palm and palm.biometric_b64),
                    "templateB64": palm.biometric_b64 if palm else None,
                    "format": palm.biometric_format if palm else None,
                },
            },
        }

    @http.route(
        "/api/access/validate",
        type="jsonrpc",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def validate(self, **payload):
        ok, reason = self._auth_ok()
        if not ok:
            return {"allowed": False, "reason": reason, "openMs": None}
        return {"allowed": False, "reason": "deprecated_endpoint", "openMs": None}

    @http.route(
        "/api/access/sync_users",
        type="jsonrpc",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def sync_users(self, **payload):
        ok, reason = self._auth_ok()
        if not ok:
            return {"ok": False, "reason": reason, "users": [], "devices": [], "siteCode": None}
        return {
            "ok": False,
            "reason": "deprecated_endpoint_use_sync_delta",
            "users": [],
            "devices": [],
            "siteCode": None,
        }

    @http.route(
        "/api/access/sync/delta",
        type="jsonrpc",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def sync_delta(self, **payload):
        ok, reason = self._auth_ok()
        if not ok:
            return {
                "ok": False,
                "reason": reason,
                "siteCode": None,
                "cursor": 0,
                "nextCursor": 0,
                "upserts": [],
                "deletes": [],
            }

        data = self._payload_data(payload)

        site_code = (data.get("siteCode") or data.get("site_code") or "").strip()
        device_code = (data.get("deviceCode") or data.get("device_code") or "").strip()
        cursor = self._as_int(data.get("cursor"), default=0) or 0
        limit = self._as_int(data.get("limit"), default=500) or 500
        limit = max(1, min(limit, 2000))

        if not site_code:
            return {
                "ok": False,
                "reason": "missing_site_code",
                "siteCode": None,
                "cursor": cursor,
                "nextCursor": cursor,
                "upserts": [],
                "deletes": [],
            }

        Site = request.env["access_control.site"].sudo()
        site = Site.search([("code", "=", site_code), ("active", "=", True)], limit=1)
        if not site:
            return {
                "ok": False,
                "reason": "site_not_found",
                "siteCode": site_code,
                "cursor": cursor,
                "nextCursor": cursor,
                "upserts": [],
                "deletes": [],
            }

        if device_code:
            Device = request.env["access_control.device"].sudo()
            device = Device.search(
                [
                    ("device_code", "=", device_code),
                    ("site_id", "=", site.id),
                    ("active", "=", True),
                ],
                limit=1,
            )
            if not device:
                return {
                    "ok": False,
                    "reason": "device_not_found",
                    "siteCode": site_code,
                    "deviceCode": device_code,
                    "cursor": cursor,
                    "nextCursor": cursor,
                    "upserts": [],
                    "deletes": [],
                }

        Person = request.env["access_control.person"].sudo()
        Change = request.env["access_control.sync_change"].sudo()

        # Bootstrap: return full active snapshot for the site.
        if cursor <= 0:
            persons = Person.search(
                [
                    ("active", "=", True),
                    ("global_user_id", "!=", False),
                    ("site_ids", "in", site.id),
                ],
                order="global_user_id asc",
            )
            upserts = [self._person_sync_payload(p) for p in persons]
            max_cursor = Change.search([], order="id desc", limit=1).id or 0
            return {
                "ok": True,
                "reason": "bootstrap",
                "siteCode": site_code,
                "deviceCode": device_code or None,
                "cursor": cursor,
                "nextCursor": max_cursor,
                "hasMore": False,
                "upserts": upserts,
                "deletes": [],
            }

        changes = Change.search(
            [("site_id", "=", site.id), ("id", ">", cursor)],
            order="id asc",
            limit=limit,
        )

        if not changes:
            return {
                "ok": True,
                "reason": "no_changes",
                "siteCode": site_code,
                "deviceCode": device_code or None,
                "cursor": cursor,
                "nextCursor": cursor,
                "hasMore": False,
                "upserts": [],
                "deletes": [],
            }

        latest_by_gid = {}
        for ch in changes:
            gid = ch.global_user_id
            if not gid:
                continue
            latest_by_gid[gid] = ch

        upserts = []
        deletes = []
        for gid, change in sorted(latest_by_gid.items()):
            if change.action == "delete":
                deletes.append({"globalUserId": gid})
                continue

            person = change.person_id
            if not person.exists() or not person.active or not person.global_user_id or site.id not in person.site_ids.ids:
                deletes.append({"globalUserId": gid})
                continue

            upserts.append(self._person_sync_payload(person))

        next_cursor = changes[-1].id
        has_more = len(changes) >= limit

        return {
            "ok": True,
            "reason": "delta",
            "siteCode": site_code,
            "deviceCode": device_code or None,
            "cursor": cursor,
            "nextCursor": next_cursor,
            "hasMore": has_more,
            "upserts": upserts,
            "deletes": deletes,
        }

    @http.route(
        "/api/access/enroll/next",
        type="jsonrpc",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def enroll_next(self, **payload):
        ok, reason = self._auth_ok()
        if not ok:
            return {"ok": False, "reason": reason, "request": None}

        data = self._payload_data(payload)

        site_code = (data.get("siteCode") or data.get("site_code") or "").strip()
        device_code = (data.get("deviceCode") or data.get("device_code") or "").strip()
        modality = self._normalize_modality(data.get("modality"))

        if not site_code:
            return {"ok": False, "reason": "missing_site_code", "request": None}

        Site = request.env["access_control.site"].sudo()
        site = Site.search([("code", "=", site_code), ("active", "=", True)], limit=1)
        if not site:
            return {"ok": False, "reason": "site_not_found", "request": None}

        if device_code:
            Device = request.env["access_control.device"].sudo()
            device = Device.search(
                [
                    ("device_code", "=", device_code),
                    ("site_id", "=", site.id),
                    ("active", "=", True),
                ],
                limit=1,
            )
            if not device:
                return {"ok": False, "reason": "device_not_found", "request": None}

        domain = [("site_id", "=", site.id), ("status", "=", "requested")]
        if modality:
            domain.append(("modality", "=", modality))

        Req = request.env["access_control.enroll_request"].sudo()
        req = Req.search(domain, limit=1, order="create_date asc")
        if not req:
            return {"ok": True, "reason": "no_pending", "request": None}

        person = req.person_id
        cred = req.credential_id
        return {
            "ok": True,
            "reason": "pending",
            "request": {
                "requestId": req.id,
                "credentialId": cred.id,
                "personId": person.id if person else None,
                "siteCode": site.code,
                "deviceCode": device_code or None,
                "globalUserId": person.global_user_id if person else None,
                "name": person.name if person else None,
                "modality": cred.credential_type,
                "biometricFormat": cred.biometric_format,
            },
        }

    @http.route(
        "/api/access/enroll/ack",
        type="jsonrpc",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def enroll_ack(self, **payload):
        ok, reason = self._auth_ok()
        if not ok:
            return {"ok": False, "reason": reason}

        data = self._payload_data(payload)
        request_id = data.get("request_id") or data.get("requestId")
        request_id = self._as_int(request_id)
        if not request_id:
            return {"ok": False, "reason": "missing_request_id"}

        Req = request.env["access_control.enroll_request"].sudo()
        req = Req.browse(request_id)
        if not req.exists():
            return {"ok": False, "reason": "request_not_found"}

        if req.status == "requested":
            req.status = "enrolling"
            req.credential_id.enroll_status = "enrolling"
        return {"ok": True, "reason": "ack"}

    @http.route(
        "/api/access/enroll/complete",
        type="jsonrpc",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def enroll_complete(self, **payload):
        ok, reason = self._auth_ok()
        if not ok:
            return {"ok": False, "reason": reason}

        data = self._payload_data(payload)

        request_id = self._as_int(data.get("request_id") or data.get("requestId"))
        status = (data.get("status") or "").strip().lower()
        modality = self._normalize_modality(data.get("modality"))

        if not request_id:
            return {"ok": False, "reason": "missing_request_id"}
        if status not in ("active", "error"):
            return {"ok": False, "reason": "invalid_status"}

        Req = request.env["access_control.enroll_request"].sudo()
        req = Req.browse(request_id)
        if not req.exists():
            return {"ok": False, "reason": "request_not_found"}

        cred = req.credential_id
        if modality and cred.credential_type != modality:
            return {"ok": False, "reason": "modality_mismatch"}

        if status == "active":
            biometric_b64 = data.get("biometric_b64") or data.get("biometricB64") or data.get("templateB64")
            biometric_format = data.get("biometric_format") or data.get("biometricFormat") or cred.biometric_format
            quality = data.get("quality")
            if not biometric_b64:
                return {"ok": False, "reason": "missing_biometric_b64"}

            cred.write(
                {
                    "biometric_b64": biometric_b64,
                    "biometric_format": biometric_format,
                    "enroll_status": "active",
                    "active": True,
                }
            )
            req.write(
                {
                    "status": "done",
                    "enrolled_at": fields.Datetime.now(),
                    "quality": quality,
                }
            )
            if cred.person_id and cred.person_id.site_ids:
                cred.person_id.site_ids.write({"force_sync": True})

            return {"ok": True, "reason": "stored"}

        error_code = data.get("error_code") or data.get("errorCode")
        error_message = data.get("error_message") or data.get("errorMessage")
        cred.enroll_status = "error"
        req.write(
            {
                "status": "error",
                "error_code": error_code,
                "error_message": error_message,
            }
        )
        return {"ok": True, "reason": "error_saved"}

    @http.route(
        "/api/access/events/access",
        type="jsonrpc",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def events_access(self, **payload):
        ok, reason = self._auth_ok()
        if not ok:
            return {"ok": False, "reason": reason, "received": 0, "duplicates": 0, "invalid": 0}

        data = self._payload_data(payload)

        raw_events = data.get("events")
        if isinstance(raw_events, dict):
            events = [raw_events]
        elif isinstance(raw_events, list):
            events = raw_events
        else:
            event_single = {
                "eventId": data.get("eventId") or data.get("event_id"),
                "deviceCode": data.get("deviceCode") or data.get("device_code"),
                "siteCode": data.get("siteCode") or data.get("site_code"),
                "globalUserId": data.get("globalUserId") or data.get("global_user_id"),
                "modality": data.get("modality"),
                "result": data.get("result") or data.get("status"),
                "occurredAt": data.get("occurredAt") or data.get("occurred_at"),
            }
            events = [event_single] if event_single["eventId"] else []

        if not events:
            return {"ok": False, "reason": "missing_events", "received": 0, "duplicates": 0, "invalid": 0}

        Device = request.env["access_control.device"].sudo()
        Site = request.env["access_control.site"].sudo()
        Person = request.env["access_control.person"].sudo()
        Event = request.env["access_control.access_event"].sudo()

        received = 0
        duplicates = 0
        invalid = 0

        for item in events:
            event_id = (item.get("eventId") or item.get("event_id") or "").strip()
            if not event_id:
                invalid += 1
                continue

            if Event.search_count([("event_id", "=", event_id)]):
                duplicates += 1
                continue

            site_code = (item.get("siteCode") or item.get("site_code") or "").strip()
            device_code = (item.get("deviceCode") or item.get("device_code") or "").strip()
            global_user_id = self._as_int(item.get("globalUserId") or item.get("global_user_id"))

            site = Site.search([("code", "=", site_code)], limit=1) if site_code else False
            device = Device.search([("device_code", "=", device_code)], limit=1) if device_code else False
            person = Person.search([("global_user_id", "=", global_user_id)], limit=1) if global_user_id else False

            modality = (item.get("modality") or "").strip().lower()
            if modality not in ("face", "palm"):
                modality = "unknown"

            result = (item.get("result") or item.get("status") or "").strip().lower()
            if result not in ("allowed", "denied", "error"):
                result = "denied"

            occurred_at_raw = item.get("occurredAt") or item.get("occurred_at")
            try:
                occurred_at = fields.Datetime.to_datetime(occurred_at_raw) if occurred_at_raw else fields.Datetime.now()
            except Exception:
                occurred_at = fields.Datetime.now()

            Event.create(
                {
                    "event_id": event_id,
                    "site_id": site.id if site else (device.site_id.id if device and device.site_id else False),
                    "device_id": device.id if device else False,
                    "device_code": device_code or False,
                    "person_id": person.id if person else False,
                    "global_user_id": global_user_id,
                    "modality": modality,
                    "result": result,
                    "occurred_at": occurred_at,
                    "raw_payload": json.dumps(item, ensure_ascii=True, default=str),
                }
            )
            received += 1

        return {
            "ok": True,
            "reason": "stored",
            "received": received,
            "duplicates": duplicates,
            "invalid": invalid,
        }
