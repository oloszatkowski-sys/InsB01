import zoneinfo
from datetime import datetime, date, timedelta
from typing import Optional, Tuple

WARSAW_TZ = zoneinfo.ZoneInfo("Europe/Warsaw")
UTC_TZ = zoneinfo.ZoneInfo("UTC")

def now_warsaw() -> datetime:
    """Zwraca bieżący czas w strefie Europe/Warsaw (z uwzględnieniem CET/CEST)."""
    return datetime.now(WARSAW_TZ)

def now_utc() -> datetime:
    """Zwraca bieżący czas w strefie UTC."""
    return datetime.now(UTC_TZ)

def today_warsaw() -> date:
    """Zwraca dzisiejszą datę kalendarzową w Polsce."""
    return now_warsaw().date()

def format_warsaw(dt: Optional[datetime] = None, include_tz: bool = True) -> str:
    """Formatuje datę i czas po polsku z oznaczeniem strefy (CET lub CEST)."""
    if dt is None:
        dt = now_warsaw()
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=WARSAW_TZ)
    else:
        dt = dt.astimezone(WARSAW_TZ)
    
    tz_str = f" {dt.tzname()}" if include_tz else ""
    return dt.strftime(f"%Y-%m-%d %H:%M:%S{tz_str}")

def format_utc(dt: Optional[datetime] = None) -> str:
    """Formatuje datę i czas w UTC."""
    if dt is None:
        dt = now_utc()
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC_TZ)
    else:
        dt = dt.astimezone(UTC_TZ)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")

def time_to_minutes(time_str: str) -> int:
    """Konwertuje 'HH:MM' na liczbę minut od północy."""
    parts = time_str.strip().split(":")
    return int(parts[0]) * 60 + int(parts[1])

def minutes_to_time(minutes: int) -> str:
    """Konwertuje liczbę minut od północy na format 'HH:MM'."""
    h = (minutes // 60) % 24
    m = minutes % 60
    return f"{h:02d}:{m:02d}"

def get_iso_week_key(d: Optional[date] = None) -> str:
    """Zwraca klucz tygodnia ISO dla daty w Polsce, np. '2026-W44'."""
    if d is None:
        d = today_warsaw()
    year, week_num, _ = d.isocalendar()
    return f"{year}-W{week_num:02d}"

def get_current_polish_tzname() -> str:
    """Zwraca CET (zima) lub CEST (lato)."""
    return now_warsaw().tzname() or "CET"

def get_delay_str(scheduled_minutes: int, actual_minutes: int) -> str:
    """Oblicza opóźnienie/przesunięcie względem harmonogramu."""
    diff = actual_minutes - scheduled_minutes
    if abs(diff) <= 1:
        return "Zgodnie z planem (0 min)"
    elif diff > 0:
        return f"+{diff} min opóźnienia"
    else:
        return f"{diff} min przed czasem"
