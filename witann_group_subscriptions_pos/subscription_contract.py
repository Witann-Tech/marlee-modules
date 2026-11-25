"""Deterministic commercial primitives. No ORM, clock or browser dependencies."""

import hashlib
import json
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta


RULES_VERSION = 1
CALENDAR_VERSION = 2


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


def commercial_interval(interval, unit):
    """Native two-week plans represent the gym's inclusive 15-day quincena."""
    return (15, 'day') if (int(interval), unit) == (2, 'week') else (interval, unit)


def period(start, interval, unit, *, aligned=False, monthly_cutoff_day=0, previous_end=None,
           calendar_version=1):
    """Return inclusive bounds using the calendar frozen in a purchase.

    Version 1 replays historical fixed cutoffs without changing paid dates.
    Version 2 subtracts the included start day from a calendar month/year,
    and treats native two-week terms as fifteen inclusive days.
    """
    start = date.fromisoformat(start) if isinstance(start, str) else start
    if not isinstance(start, date) or int(interval) < 1:
        raise ValueError('A period requires an explicit start and a positive interval.')
    units = {'day': 'days', 'week': 'weeks', 'month': 'months', 'year': 'years'}
    if unit not in units:
        raise ValueError('Unsupported billing interval.')
    if calendar_version not in (1, CALENDAR_VERSION):
        raise ValueError('Unsupported commercial calendar version.')
    if calendar_version == CALENDAR_VERSION:
        if monthly_cutoff_day or previous_end:
            raise ValueError('The inclusive calendar cannot use a historical monthly cutoff.')
        interval, unit = commercial_interval(interval, unit)
    if monthly_cutoff_day:
        if aligned or unit != 'month' or int(interval) != 1 or not 1 <= monthly_cutoff_day <= 31:
            raise ValueError('A monthly cutoff requires an unaligned one-month plan and a day from 1 to 31.')
        previous_end = date.fromisoformat(previous_end) if isinstance(previous_end, str) else previous_end
        if previous_end and start != previous_end + timedelta(days=1):
            raise ValueError('A continuing period must start after the previous inclusive end.')
        end = (previous_end or start) + relativedelta(months=1, day=monthly_cutoff_day)
        return start, end, end + timedelta(days=1)
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


def validate_commercial_period(pricing):
    """Check purchased calendar inputs, not just agreement between two outputs.

    The signed inputs survive catalog edits and deferred activation. Old paid
    quotes without this contract keep their historical calendar; newly sealed
    quotes always carry it.
    """
    terms = pricing.get('period_contract')
    if not terms:
        return
    if terms.get('version') not in (1, CALENDAR_VERSION):
        raise ValueError('Unsupported commercial calendar contract.')
    if terms['mode'] == 'source_period':
        expected = (terms['start'], terms['end'], terms['next'])
    elif terms['mode'] == 'term':
        start, end, boundary = period(
            terms['start'], terms['interval'], terms['unit'],
            aligned=terms['aligned'], monthly_cutoff_day=terms['cutoff'],
            previous_end=terms['previous_end'] or None,
            calendar_version=terms['version'],
        )
        expected = (start.isoformat(), end.isoformat(),
                    False if terms['unit'] == 'day' and terms['interval'] == 1 else boundary.isoformat())
    else:
        raise ValueError('Unsupported commercial calendar mode.')
    actual = tuple(pricing.get(key) or False for key in (
        'subscription_start_date', 'subscription_end_date', 'next_billing_date',
    ))
    if actual != expected:
        raise ValueError('The quoted period does not match the purchased term.')
    if terms['mode'] == 'term' and int(pricing.get('monthly_cutoff_day') or 0) != terms['cutoff']:
        raise ValueError('The quoted cutoff does not match the purchased calendar.')
