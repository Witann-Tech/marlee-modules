"""Deterministic commercial primitives. No ORM, clock or browser dependencies."""

import hashlib
import json
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta


RULES_VERSION = 1


def canonical_json(value):
    # Browser JSON.stringify drops the decimal part of integral numbers.
    # Normalize on both signing and verification, including nested quote data.
    def normalize(item):
        if isinstance(item, float) and item.is_integer():
            return int(item)
        if isinstance(item, dict):
            return {key: normalize(entry) for key, entry in item.items()}
        if isinstance(item, (list, tuple)):
            return [normalize(entry) for entry in item]
        return item

    return json.dumps(normalize(value), sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def period(start, interval, unit, *, aligned=False):
    """Return inclusive start/end and the exclusive next billing boundary."""
    start = date.fromisoformat(start) if isinstance(start, str) else start
    if not isinstance(start, date) or int(interval) < 1:
        raise ValueError('A period requires an explicit start and a positive interval.')
    units = {'day': 'days', 'week': 'weeks', 'month': 'months', 'year': 'years'}
    if unit not in units:
        raise ValueError('Unsupported billing interval.')
    next_date = (
        start.replace(day=1) + relativedelta(months=1)
        if aligned else start + relativedelta(**{units[unit]: int(interval)})
    )
    return start, next_date - timedelta(days=1), next_date


def validate_period(start, end, next_date):
    start, end = date.fromisoformat(start), date.fromisoformat(end)
    if end < start:
        raise ValueError('The paid period ends before it starts.')
    if next_date and date.fromisoformat(next_date) != end + timedelta(days=1):
        raise ValueError('The next billing date must follow the inclusive end.')
    return start, end
