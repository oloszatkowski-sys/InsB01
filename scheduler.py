"""
Moduł kompatybilności wstecznej dla starszych odwołań (Scheduler).
Przekierowuje wszystkie operacje do uniwersalnego MultiScheduler (Europe/Warsaw).
"""

from typing import Dict, Any, List, Optional
from datetime import date
from multi_scheduler import MultiScheduler, DAY_NAMES_PL
from timezone_utils import now_warsaw, today_warsaw, format_warsaw, get_current_polish_tzname

DAY_NAMES = DAY_NAMES_PL

class Scheduler:
    """Wrapper kompatybilności wstecznej delegujący do MultiScheduler."""

    def __init__(self, config: Dict[str, Any], storage: Any = None):
        self.config = config
        self.storage = storage
        self.multi = MultiScheduler(config)

    def check_execution_status(self) -> Dict[str, Any]:
        """Zwraca spójny status harmonogramu w czasie polskim (Europe/Warsaw)."""
        now_pl = now_warsaw()
        today = today_warsaw()
        slots = self.multi.get_today_slots()
        
        # Wyznaczamy ogólny status na dziś
        due = self.multi.get_due_slots()
        completed_count = sum(1 for s in slots if s.get("completed", False))
        total_slots = len(slots)
        
        planned_times = [s.get("scheduled_time", "--:--") for s in slots if not s.get("is_off_day")]
        planned_time_str = ", ".join(planned_times) if planned_times else "Brak zadań"

        return {
            "now": format_warsaw(now_pl),
            "today": today.isoformat(),
            "weekday_name": DAY_NAMES_PL[today.weekday()],
            "timezone": "Europe/Warsaw",
            "tzname": get_current_polish_tzname(),
            "is_workday": any(not s.get("is_off_day", False) for s in slots),
            "is_done": (completed_count >= total_slots) if total_slots > 0 else False,
            "planned_time": planned_time_str,
            "can_run_now": len(due) > 0,
            "due_count": len(due),
            "slots": slots
        }
