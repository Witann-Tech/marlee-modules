# -*- coding: utf-8 -*-
import base64
import json
import logging
from odoo import http, fields
from odoo.http import request

_logger = logging.getLogger(__name__)


class AccessControlApi(http.Controller):
    _BOOTSTRAP_CURSOR_STRIDE = 100000

    def _touch_device_telemetry(self, device, heartbeat=False, sync=False, error_marker=False):
        if not device or not device.exists():
            return False
        vals = {}
        now = fields.Datetime.now()
        if heartbeat:
            vals["last_heartbeat_at"] = now
        if sync:
            vals["last_sync_at"] = now
        if error_marker is True:
            vals["last_error"] = False
        elif isinstance(error_marker, str):
            vals["last_error"] = error_marker
        if not vals:
            return False
        device.sudo().write(vals)
        return True

    def _mark_people_synced(self, people, synced_at=None):
        people = people.exists() if people else people
        if not people:
            return False
        synced_at = synced_at or fields.Datetime.now()
        pins = people.mapped("global_user_id")
        people.with_context(skip_access_sync_queue=True).sudo().write({"last_sf_sync_at": synced_at})
        _logger.info(
            "access_sync marked_last_sf_sync person_ids=%s pins=%s synced_at=%s",
            people.ids,
            pins,
            fields.Datetime.to_string(synced_at),
        )
        return True

    def _bootstrap_cursor_encode(self, snapshot_cursor, offset):
        snapshot_cursor = max(0, int(snapshot_cursor or 0))
        offset = max(0, int(offset or 0))
        return -(((snapshot_cursor + 1) * self._BOOTSTRAP_CURSOR_STRIDE) + offset)

    def _bootstrap_cursor_decode(self, cursor):
        if (cursor or 0) >= 0:
            return 0, 0
        raw = abs(int(cursor))
        snapshot_plus = raw // self._BOOTSTRAP_CURSOR_STRIDE
        offset = raw % self._BOOTSTRAP_CURSOR_STRIDE
        snapshot_cursor = max(0, snapshot_plus - 1)
        return snapshot_cursor, offset

    def _site_bootstrap_result(self, site, site_code, device_serial, cursor, limit, include_biophoto=True, reason="bootstrap"):
        Person = site.env["access_control.person"].sudo()
        domain = [
            ("active", "=", True),
            ("global_user_id", "!=", False),
            ("site_ids", "in", site.id),
        ]
        if cursor < 0:
            snapshot_cursor, offset = self._bootstrap_cursor_decode(cursor)
        else:
            snapshot_cursor = self._site_change_max_cursor(site)
            offset = 0

        persons = Person.search(domain, order="global_user_id asc", offset=offset, limit=limit)
        total = Person.search_count(domain)
        upserts = [
            self._person_sync_payload(
                person,
                include_face_pic=bool(include_biophoto and person.face_pic_b64),
                clear_face_pic=bool(include_biophoto and not person.face_pic_b64),
            )
            for person in persons
        ]
        self._mark_people_synced(persons)
        next_offset = offset + len(upserts)
        has_more = next_offset < total
        next_cursor = (
            self._bootstrap_cursor_encode(snapshot_cursor, next_offset)
            if has_more
            else snapshot_cursor
        )
        return {
            "ok": True,
            "reason": reason,
            "siteCode": site_code,
            "deviceSerial": device_serial or None,
            "cursor": cursor,
            "nextCursor": next_cursor,
            "hasMore": has_more,
            "upserts": upserts,
            "deletes": [],
        }

    def _site_biophoto_result(self, site, site_code, device_serial, cursor, limit, reason="biophoto"):
        Person = site.env["access_control.person"].sudo()
        domain = [
            ("active", "=", True),
            ("global_user_id", "!=", False),
            ("site_ids", "in", site.id),
            ("face_pic_b64", "!=", False),
        ]
        if cursor < 0:
            snapshot_cursor, offset = self._bootstrap_cursor_decode(cursor)
        else:
            snapshot_cursor = self._site_change_max_cursor(site)
            offset = 0

        persons = Person.search(domain, order="global_user_id asc", offset=offset, limit=limit)
        total = Person.search_count(domain)
        upserts = [
            self._person_sync_payload(
                person,
                include_face_pic=True,
                clear_face_pic=False,
            )
            for person in persons
        ]
        self._mark_people_synced(persons)
        next_offset = offset + len(upserts)
        has_more = next_offset < total
        next_cursor = (
            self._bootstrap_cursor_encode(snapshot_cursor, next_offset)
            if has_more
            else snapshot_cursor
        )
        return {
            "ok": True,
            "reason": reason,
            "siteCode": site_code,
            "deviceSerial": device_serial or None,
            "cursor": cursor,
            "nextCursor": next_cursor,
            "hasMore": has_more,
            "upserts": upserts,
            "deletes": [],
        }

    def _site_change_max_cursor(self, site):
        Change = site.env["access_control.sync_change"].sudo()
        return Change.search([("site_id", "=", site.id)], order="id desc", limit=1).id or 0

    def _is_valid_user_api_key(self, token):
        """Support Odoo user API keys created from user preferences."""
        ApiKeys = request.env["res.users.apikeys"].sudo()
        scopes = ("rpc", "odoo", "api")
        for scope in scopes:
            try:
                uid = ApiKeys._check_credentials(scope=scope, key=token)
            except TypeError:
                try:
                    uid = ApiKeys._check_credentials(scope, token)
                except Exception:
                    uid = False
            except Exception:
                uid = False
            if uid:
                return True
        return False

    def _auth_ok(self):
        auth = request.httprequest.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return False, "missing_token"
        token = auth.split(" ", 1)[1].strip()
        ICP = request.env["ir.config_parameter"].sudo()
        expected = ICP.get_param("access_control.api_token") or ICP.get_param("access_control_api.api_token")

        if expected and token == expected:
            return True, None

        if self._is_valid_user_api_key(token):
            return True, None

        if expected:
            return False, "invalid_token"
        return False, "server_token_not_configured"

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

    def _as_bool(self, value, default=None):
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value).strip().lower()
        if text in ("1", "true", "t", "yes", "y", "on"):
            return True
        if text in ("0", "false", "f", "no", "n", "off"):
            return False
        return default

    def _normalize_modality(self, modality):
        if not modality:
            return None
        m = str(modality).strip().lower()
        if m in ("face",):
            return m
        return None

    def _person_sync_payload(self, person, include_face_pic=True, clear_face_pic=False, priority=False):
        payload = {
            "globalUserId": person.global_user_id,
            "name": person.name or "",
            "active": bool(person.active),
            "accessGroup": 0 if person.access_state == "suspended" else 1,
        }
        if priority:
            payload["priority"] = True
        if clear_face_pic:
            _logger.info("sync_delta facePicB64=null pin=%s person_id=%s", person.global_user_id, person.id)
            payload["facePicB64"] = None
        elif include_face_pic:
            face_b64 = person.env["res.partner"].sudo()._normalize_image_b64(person.face_pic_b64)
            if face_b64:
                try:
                    raw = base64.b64decode(face_b64, validate=True)
                    _logger.info(
                        "sync_delta facePicB64 included pin=%s person_id=%s jpeg_bytes=%s b64_len=%s",
                        person.global_user_id,
                        person.id,
                        len(raw),
                        len(face_b64),
                    )
                except Exception:
                    _logger.warning(
                        "sync_delta invalid facePicB64 pin=%s person_id=%s",
                        person.global_user_id,
                        person.id,
                    )
                    face_b64 = None
            else:
                _logger.warning(
                    "sync_delta requested facePicB64 but no valid image pin=%s person_id=%s",
                    person.global_user_id,
                    person.id,
                )
            if face_b64:
                payload["facePicB64"] = face_b64
        return payload

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
        ["/api/access/topology", "/api/access/inventory"],
        type="jsonrpc",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def topology(self, **payload):
        ok, reason = self._auth_ok()
        if not ok:
            return {"ok": False, "reason": reason, "sites": []}

        data = self._payload_data(payload)
        filter_site_code = (data.get("siteCode") or data.get("site_code") or "").strip()

        Site = request.env["access_control.site"].sudo()
        domain = [("active", "=", True)]
        if filter_site_code:
            domain.append(("code", "=", filter_site_code))
        sites_rs = Site.search(domain, order="id asc")
        if filter_site_code and not sites_rs:
            return {"ok": False, "reason": "site_not_found", "sites": []}

        sites = []
        total_devices = 0
        for site in sites_rs:
            devices = []
            for d in site.device_ids.sorted(key=lambda rec: rec.id):
                devices.append(
                    {
                        "active": bool(d.active),
                        "name": d.name,
                        "deviceSerial": d.device_serial,
                        "siteCode": site.code,
                        "userCapacity": d.user_capacity,
                        "lastHeartbeatAt": fields.Datetime.to_string(d.last_heartbeat_at) if d.last_heartbeat_at else None,
                        "lastSyncAt": fields.Datetime.to_string(d.last_sync_at) if d.last_sync_at else None,
                        "lastError": d.last_error or None,
                    }
                )

            total_devices += len(devices)
            sites.append(
                {
                    "siteCode": site.code,
                    "devices": devices,
                }
            )

        _logger.info("endpoint=inventory loaded sites=%s devices=%s", len(sites), total_devices)
        return {"ok": True, "reason": "ok", "sites": sites}

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
        device_serial = (
            data.get("deviceSerial")
            or data.get("device_serial")
            or data.get("deviceCode")
            or data.get("device_code")
            or ""
        ).strip()
        cursor = self._as_int(data.get("cursor"), default=0) or 0
        limit = self._as_int(data.get("limit"), default=500) or 500
        limit = max(1, min(limit, 2000))
        only_biophoto = self._as_bool(
            data.get("onlyBiophoto", data.get("forceBiophoto")),
            default=False,
        )
        include_biophoto = self._as_bool(
            data.get("includeBiophoto", data.get("includeFaces")),
            default=True,
        )
        if only_biophoto:
            include_biophoto = True

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

        device = False
        if device_serial:
            Device = request.env["access_control.device"].sudo()
            device = Device.search(
                [
                    ("device_serial", "=", device_serial),
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
                    "deviceSerial": device_serial,
                    "cursor": cursor,
                    "nextCursor": cursor,
                    "upserts": [],
                    "deletes": [],
                }

        Person = request.env["access_control.person"].sudo()
        Change = request.env["access_control.sync_change"].sudo()
        site_max_cursor = self._site_change_max_cursor(site)

        if only_biophoto:
            self._touch_device_telemetry(device, heartbeat=True, sync=True, error_marker=True)
            return self._site_biophoto_result(
                site,
                site_code,
                device_serial,
                cursor,
                limit,
                reason="biophoto" if cursor < 0 else "biophoto_bootstrap",
            )

        # Bootstrap cursor (0 or negative internal cursor) returns a paged snapshot.
        if cursor <= 0:
            self._touch_device_telemetry(device, heartbeat=True, sync=True, error_marker=True)
            return self._site_bootstrap_result(
                site,
                site_code,
                device_serial,
                cursor,
                limit,
                include_biophoto=include_biophoto,
                reason="bootstrap",
            )

        changes = Change.search(
            [("site_id", "=", site.id), ("id", ">", cursor)],
            order="id asc",
            limit=limit,
        )

        if not changes:
            if cursor > site_max_cursor:
                self._touch_device_telemetry(device, heartbeat=True, sync=True, error_marker=True)
                _logger.warning(
                    "sync_delta stale cursor detected site=%s device=%s cursor=%s site_max_cursor=%s; returning bootstrap snapshot",
                    site_code,
                    device_serial or None,
                    cursor,
                    site_max_cursor,
                )
                return self._site_bootstrap_result(
                    site,
                    site_code,
                    device_serial,
                    cursor,
                    limit,
                    include_biophoto=include_biophoto,
                    reason="stale_cursor_bootstrap",
                )
            self._touch_device_telemetry(device, heartbeat=True, sync=True, error_marker=True)
            return {
                "ok": True,
                "reason": "no_changes",
                "siteCode": site_code,
                "deviceSerial": device_serial or None,
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
            state = latest_by_gid.setdefault(
                gid,
                {
                    "change": ch,
                    "include_face_pic": False,
                    "clear_face_pic": False,
                    "priority": False,
                },
            )
            state["change"] = ch
            if ch.priority:
                state["priority"] = True
            if ch.action == "delete":
                state["include_face_pic"] = False
                state["clear_face_pic"] = False
                continue
            if ch.include_face_pic:
                state["include_face_pic"] = True
                state["clear_face_pic"] = False
            elif ch.clear_face_pic:
                state["include_face_pic"] = False
                state["clear_face_pic"] = True

        upserts = []
        deletes = []
        synced_people = Person.browse()
        for gid, state in sorted(latest_by_gid.items()):
            change = state["change"]
            if change.action == "delete":
                payload = {"globalUserId": gid}
                if state["priority"]:
                    payload["priority"] = True
                deletes.append(payload)
                if change.person_id.exists():
                    synced_people |= change.person_id
                else:
                    person = Person.search([("global_user_id", "=", gid)], limit=1)
                    if person:
                        synced_people |= person
                continue

            person = change.person_id
            if not person.exists():
                person = Person.search([("global_user_id", "=", gid)], limit=1)
            if not person.exists() or not person.active or not person.global_user_id or site.id not in person.site_ids.ids:
                payload = {"globalUserId": gid}
                if state["priority"]:
                    payload["priority"] = True
                deletes.append(payload)
                if person.exists():
                    synced_people |= person
                continue

            upserts.append(
                self._person_sync_payload(
                    person,
                    include_face_pic=bool(include_biophoto and state["include_face_pic"]),
                    clear_face_pic=bool(include_biophoto and state["clear_face_pic"]),
                    priority=bool(state["priority"]),
                )
            )
            synced_people |= person

        next_cursor = changes[-1].id
        has_more = len(changes) >= limit
        self._mark_people_synced(synced_people)
        self._touch_device_telemetry(device, heartbeat=True, sync=True, error_marker=True)
        _logger.info(
            "sync_delta site=%s device=%s cursor=%s next_cursor=%s upserts=%s deletes=%s include_biophoto=%s",
            site_code,
            device_serial or None,
            cursor,
            next_cursor,
            len(upserts),
            len(deletes),
            include_biophoto,
        )

        return {
            "ok": True,
            "reason": "delta",
            "siteCode": site_code,
            "deviceSerial": device_serial or None,
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
        return {"ok": False, "reason": "deprecated_enroll_disabled", "request": None}

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
        return {"ok": False, "reason": "deprecated_enroll_disabled"}

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
        return {"ok": False, "reason": "deprecated_enroll_disabled"}

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
                "deviceSerial": data.get("deviceSerial") or data.get("device_serial") or data.get("deviceCode") or data.get("device_code"),
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
            device_serial = (
                item.get("deviceSerial")
                or item.get("device_serial")
                or item.get("deviceCode")
                or item.get("device_code")
                or ""
            ).strip()
            global_user_id = self._as_int(item.get("globalUserId") or item.get("global_user_id"))

            site = Site.search([("code", "=", site_code)], limit=1) if site_code else False
            device = Device.search([("device_serial", "=", device_serial)], limit=1) if device_serial else False
            person = Person.search([("global_user_id", "=", global_user_id)], limit=1) if global_user_id else False

            modality = (item.get("modality") or "").strip().lower()
            if modality not in ("face",):
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
                    "device_serial": device_serial or False,
                    "person_id": person.id if person else False,
                    "global_user_id": global_user_id,
                    "modality": modality,
                    "result": result,
                    "occurred_at": occurred_at,
                    "raw_payload": json.dumps(item, ensure_ascii=True, default=str),
                }
            )
            if person:
                person.register_access_event(
                    occurred_at=occurred_at,
                    result=result,
                    site=site if site else (device.site_id if device and device.site_id else False),
                    device=device,
                )
            self._touch_device_telemetry(device, heartbeat=True, error_marker=True)
            received += 1

        return {
            "ok": True,
            "reason": "stored",
            "received": received,
            "duplicates": duplicates,
            "invalid": invalid,
        }
