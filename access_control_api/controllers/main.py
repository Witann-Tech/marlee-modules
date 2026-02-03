# -*- coding: utf-8 -*-
import json
from datetime import datetime, timedelta, timezone

from odoo import http
from odoo.http import request


def _iso(dt):
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_since(since_str):
    if not since_str:
        return None
    try:
        # Accept both Z and offset
        if since_str.endswith("Z"):
            return datetime.fromisoformat(since_str.replace("Z", "+00:00"))
        return datetime.fromisoformat(since_str)
    except Exception:
        return None


class AccessControlV1Controller(http.Controller):
    """Standalone F18 + SyncWorker contract endpoints (v1).
    NOTE: These routes are HTTP JSON (NOT JSON-RPC).
    """

    # ---------------------------
    # Auth helpers
    # ---------------------------
    def _require_bearer(self):
        auth = request.httprequest.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return False, ("missing_token", 401)
        token = auth.split(" ", 1)[1].strip()
        expected = request.env["ir.config_parameter"].sudo().get_param("access_control.api_token")
        if not expected:
            return False, ("server_token_not_configured", 500)
        if token != expected:
            return False, ("invalid_token", 403)
        return True, None

    def _json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False)
        return request.make_response(
            body,
            headers=[("Content-Type", "application/json; charset=utf-8")],
            status=status,
        )

    # ---------------------------
    # Contract endpoints
    # ---------------------------

    @http.route(
        "/api/access-control/v1/sites/<string:site_code>/ping",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def ping(self, site_code, **kwargs):
        ok, err = self._require_bearer()
        if not ok:
            code, status = err
            return self._json({"error": {"code": code}}, status=status)

        now = datetime.now(timezone.utc)
        return self._json(
            {
                "site_code": site_code,
                "server_time": _iso(now),
                "min_worker_version": "1.0.0",
                "features": {
                    "delta_sync": True,
                    "enroll_sessions": True,
                    "attendance_ingest": False,
                },
                "recommended_poll_seconds": 120,
            }
        )

    @http.route(
        "/api/access-control/v1/sites/<string:site_code>/status",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def status(self, site_code, **kwargs):
        ok, err = self._require_bearer()
        if not ok:
            code, status = err
            return self._json({"error": {"code": code}}, status=status)

        Site = request.env["access_control.site"].sudo()
        site = Site.search([("code", "=", site_code), ("active", "=", True)], limit=1)
        if not site:
            return self._json({"error": {"code": "site_not_found", "message": "Site not found"}}, status=404)

        # site_version derived from latest write_date (ms) across relevant models in this site.
        # This is monotonic and changes on updates.
        # NOTE: For v1 we derive from timestamps; later you may replace with a strict counter.
        Person = request.env["access_control.person"].sudo()
        Finger = request.env["access_control.fingerprint"].sudo()

        # persons in site: either explicit site linkage not modeled; for now we assume one site dataset,
        # or you can filter by external_ref prefix etc. Minimal: no filter.
        # If you need per-site partitioning, add site_id to person and filter here.
        latest = None

        def consider(dt):
            nonlocal latest
            if dt and (latest is None or dt > latest):
                latest = dt

        # Consider site record itself
        consider(site.write_date)

        # Persons
        p = Person.search([], order="write_date desc", limit=1)
        if p:
            consider(p.write_date)

        # Fingerprints
        f = Finger.search([], order="write_date desc", limit=1)
        if f:
            consider(f.write_date)

        if latest is None:
            latest = datetime.now(timezone.utc)

        site_version = int(latest.replace(tzinfo=timezone.utc).timestamp() * 1000)

        return self._json(
            {
                "site_code": site_code,
                "server_time": _iso(datetime.now(timezone.utc)),
                "site_version": site_version,
                "force_sync": bool(site.force_sync),
                "recommended_poll_seconds": 120,
            }
        )

    @http.route(
        "/api/access-control/v1/sites/<string:site_code>/updates",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def updates(self, site_code, **kwargs):
        ok, err = self._require_bearer()
        if not ok:
            code, status = err
            return self._json({"error": {"code": code}}, status=status)

        Site = request.env["access_control.site"].sudo()
        site = Site.search([("code", "=", site_code), ("active", "=", True)], limit=1)
        if not site:
            return self._json({"error": {"code": "site_not_found", "message": "Site not found"}}, status=404)

        args = request.httprequest.args
        since_str = args.get("since")
        limit = int(args.get("limit") or 500)
        limit = min(max(limit, 1), 2000)

        since_dt = _parse_since(since_str)
        if since_dt is None:
            # default: last 30 days
            since_dt = datetime.now(timezone.utc) - timedelta(days=30)

        Person = request.env["access_control.person"].sudo()

        # NOTE: v1 assumes persons are global. If you add site_id to persons, filter here.
        persons = Person.search([("write_date", ">", since_dt)], order="write_date asc", limit=limit)

        changes = []
        max_dt = since_dt

        for p in persons:
            wd = p.write_date
            if wd and wd.tzinfo is None:
                wd = wd.replace(tzinfo=timezone.utc)

            if wd and wd > max_dt:
                max_dt = wd

            if not p.active:
                # When inactive => delete
                changes.append(
                    {
                        "op": "delete_person",
                        "person_id": str(p.id),
                        "reason": "inactive",
                        "f18_user_id": int(p.f18_user_id) if p.f18_user_id else None,
                        "updated_at": _iso(wd),
                    }
                )
                continue

            if not p.f18_user_id:
                # This is a contract violation; return explicit error so UX can fix it.
                return self._json(
                    {
                        "error": {
                            "code": "missing_f18_user_id",
                            "message": f"Person {p.id} has no f18_user_id assigned.",
                            "details": {"person_id": p.id},
                        }
                    },
                    status=409,
                )

            changes.append(
                {
                    "op": "upsert_person",
                    "person": {
                        "person_id": str(p.id),
                        "external_ref": p.external_ref or "",
                        "name": p.name,
                        "active": True,
                        "site_code": site_code,
                        "f18_user_id": int(p.f18_user_id),
                        "updated_at": _iso(wd),
                    },
                }
            )

            # Pin (if present)
            if p.pin:
                changes.append(
                    {
                        "op": "upsert_pin",
                        "pin": {
                            "credential_id": f"pin-{p.id}",
                            "person_id": str(p.id),
                            "f18_user_id": int(p.f18_user_id),
                            "type": "pin",
                            "value": p.pin,
                            "active": True,
                            "version": int(wd.timestamp()) if wd else 1,
                            "updated_at": _iso(wd),
                        },
                    }
                )

        next_since = max_dt
        return self._json(
            {
                "site_code": site_code,
                "server_time": _iso(datetime.now(timezone.utc)),
                "since": _iso(since_dt),
                "next_since": _iso(next_since),
                "has_more": False,
                "changes": changes,
            }
        )

    @http.route(
        "/api/access-control/v1/sites/<string:site_code>/people/<string:person_id>/fingerprints",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def fingerprints(self, site_code, person_id, **kwargs):
        ok, err = self._require_bearer()
        if not ok:
            code, status = err
            return self._json({"error": {"code": code}}, status=status)

        Finger = request.env["access_control.fingerprint"].sudo()
        fps = Finger.search([("person_id", "=", int(person_id)), ("active", "=", True)], order="finger_index asc")

        out = []
        for fp in fps:
            wd = fp.write_date
            if wd and wd.tzinfo is None:
                wd = wd.replace(tzinfo=timezone.utc)

            out.append(
                {
                    "credential_id": str(fp.id),
                    "finger_index": int(fp.finger_index),
                    "format": fp.format,
                    "template_b64": fp.template_b64,
                    "active": True,
                    "version": int(fp.version or 1),
                    "updated_at": _iso(wd),
                }
            )

        return self._json({"person_id": str(person_id), "fingerprints": out})

    # ---------------------------
    # Enrollment endpoints (minimal scaffolding)
    # ---------------------------

    @http.route(
        "/api/access-control/v1/sites/<string:site_code>/enroll/sessions",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def enroll_start(self, site_code, **kwargs):
        ok, err = self._require_bearer()
        if not ok:
            code, status = err
            return self._json({"error": {"code": code}}, status=status)

        payload = request.get_json_data(silent=True) or {}
        person_id = payload.get("person_id")
        mode = payload.get("mode") or "fingerprint"
        requested_by = payload.get("requested_by") or ""

        if not person_id:
            return self._json({"error": {"code": "missing_person_id"}}, status=422)

        Person = request.env["access_control.person"].sudo()
        person = Person.browse(int(person_id))
        if not person.exists():
            return self._json({"error": {"code": "person_not_found"}}, status=404)

        Sess = request.env["access_control.enroll_session"].sudo()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=20)
        sess = Sess.create(
            {
                "site_code": site_code,
                "person_id": person.id,
                "mode": mode,
                "status": "pending",
                "requested_by": requested_by,
                "expires_at": expires_at,
            }
        )

        return self._json(
            {
                "session_id": str(sess.id),
                "site_code": site_code,
                "person_id": str(person.id),
                "mode": mode,
                "status": "pending",
                "expires_at": _iso(expires_at),
            },
            status=201,
        )

    @http.route(
        "/api/access-control/v1/sites/<string:site_code>/enroll/sessions/<string:session_id>/claim",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def enroll_claim(self, site_code, session_id, **kwargs):
        ok, err = self._require_bearer()
        if not ok:
            code, status = err
            return self._json({"error": {"code": code}}, status=status)

        payload = request.get_json_data(silent=True) or {}
        worker_id = payload.get("worker_id") or ""
        device_id = payload.get("device_id") or ""

        Sess = request.env["access_control.enroll_session"].sudo()
        sess = Sess.browse(int(session_id))
        if not sess.exists() or sess.site_code != site_code:
            return self._json({"error": {"code": "session_not_found"}}, status=404)

        if sess.status not in ("pending",):
            return self._json(
                {
                    "error": {
                        "code": "session_already_claimed",
                        "message": "This session is not pending.",
                        "details": {"status": sess.status},
                    }
                },
                status=409,
            )

        sess.write({"status": "claimed", "claimed_by": worker_id, "device_id": device_id})

        return self._json(
            {
                "session_id": str(sess.id),
                "status": "claimed",
                "claimed_by": worker_id,
                "device_id": device_id,
                "expires_at": _iso(sess.expires_at),
            }
        )

    @http.route(
        "/api/access-control/v1/sites/<string:site_code>/enroll/sessions/<string:session_id>/complete",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def enroll_complete(self, site_code, session_id, **kwargs):
        ok, err = self._require_bearer()
        if not ok:
            code, status = err
            return self._json({"error": {"code": code}}, status=status)

        payload = request.get_json_data(silent=True) or {}
        result = payload.get("result") or "success"
        fingerprints = payload.get("fingerprints") or []

        Sess = request.env["access_control.enroll_session"].sudo()
        sess = Sess.browse(int(session_id))
        if not sess.exists() or sess.site_code != site_code:
            return self._json({"error": {"code": "session_not_found"}}, status=404)

        if sess.status not in ("claimed", "pending"):
            return self._json({"error": {"code": "session_not_claimed"}}, status=409)

        created = []
        if result == "success" and sess.mode == "fingerprint":
            Finger = request.env["access_control.fingerprint"].sudo()
            for fp in fingerprints:
                finger_index = int(fp.get("finger_index") or 1)
                fmt = fp.get("format") or "zk_vx10"
                tpl = fp.get("template_b64") or ""
                if not tpl:
                    continue

                # Upsert per finger index
                existing = Finger.search([("person_id", "=", sess.person_id.id), ("finger_index", "=", finger_index)], limit=1)
                if existing:
                    existing.write({"template_b64": tpl, "format": fmt, "active": True, "version": (existing.version or 0) + 1})
                    created.append({"credential_id": str(existing.id), "type": "fingerprint", "finger_index": finger_index, "version": int(existing.version)})
                else:
                    rec = Finger.create({"person_id": sess.person_id.id, "finger_index": finger_index, "format": fmt, "template_b64": tpl, "version": 1})
                    created.append({"credential_id": str(rec.id), "type": "fingerprint", "finger_index": finger_index, "version": 1})

            sess.write({"status": "completed"})
        else:
            sess.write({"status": "failed", "error_code": payload.get("error_code"), "error_message": payload.get("error_message")})

        return self._json(
            {
                "session_id": str(sess.id),
                "status": sess.status,
                "created_credentials": created,
                "site_version": int(datetime.now(timezone.utc).timestamp() * 1000),
                "server_time": _iso(datetime.now(timezone.utc)),
            }
        )
