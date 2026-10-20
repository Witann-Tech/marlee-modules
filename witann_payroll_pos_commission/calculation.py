"""Calendar and decimal arithmetic independent of the Odoo runtime."""
from calendar import monthrange
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo


def commission_period(date_from, date_to, timezone):
    """Require a calendar fortnight; return its key and previous-month UTC bounds."""
    end = monthrange(date_from.year, date_from.month)[1]
    if (date_from.day, date_to.day) not in ((1, 15), (16, end)) or (
        date_from.year, date_from.month
    ) != (date_to.year, date_to.month):
        raise ValueError('La comisión POS requiere una quincena completa: 1–15 o 16–fin de mes.')
    month_end = date_from.replace(day=1)
    month_start = (month_end - timedelta(days=1)).replace(day=1)
    zone = ZoneInfo(timezone)

    def utc(day):
        return datetime.combine(day, time.min, zone).astimezone(ZoneInfo('UTC')).replace(tzinfo=None)

    return date(date_from.year, date_from.month, date_from.day), month_start, utc(month_start), utc(month_end)


def commission_amount(base, monthly_percent, second_half=False, rounding=0.01):
    """Round the monthly entitlement once; assign any odd cent to the second half."""
    rate = Decimal(str(monthly_percent))
    if not rate.is_finite() or not 0 <= rate <= 100:
        raise ValueError('El porcentaje mensual debe estar entre 0 y 100.')
    unit = Decimal(str(rounding))

    def rounded(value):
        return (value / unit).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * unit

    monthly = rounded(max(Decimal(str(base)), Decimal('0')) * rate / 100)
    first = rounded(monthly / 2)
    return float(monthly - first if second_half else first)
