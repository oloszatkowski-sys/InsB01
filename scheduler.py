import random
from datetime import datetime, date, timedelta, time
from typing import Dict, Any, Tuple, Optional, List
from storage import Storage

DAY_NAMES = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"]

class Scheduler:
    def __init__(self, config: Dict[str, Any], storage: Storage):
        self.config = config
        self.storage = storage

    def _parse_time_str(self, t_str: str) -> time:
        parts = t_str.split(":")
        return time(int(parts[0]), int(parts[1]))

    def get_or_create_weekly_plan(self, current_date: date) -> Dict[str, Any]:
        """Pobiera lub generuje plan tygodnia (dni wolne + wyznaczone godziny)."""
        state = self.storage.get_schedule_state()
        year, week_num, _ = current_date.isocalendar()
        current_week_key = f"{year}-W{week_num:02d}"

        if state.get("week_key") != current_week_key:
            # Nowy tydzień - generujemy nowy harmonogram dni wolnych
            mode = self.config.get("miss_days_mode", "random")
            miss_count = int(self.config.get("miss_days_count", 1))
            
            if mode == "random" and miss_count > 0:
                # Losujemy np. 1 lub 2 dni w tygodniu (od pon do ndz: 0..6)
                off_days = random.sample(range(7), min(miss_count, 7))
            elif mode == "fixed":
                off_days = self.config.get("miss_fixed_days", [5, 6])
            else:
                off_days = []

            state = {
                "week_key": current_week_key,
                "off_days": sorted(off_days),
                "daily_times": {},       # "YYYY-MM-DD" -> "HH:MM"
                "completed_dates": []     # lista dat "YYYY-MM-DD"
            }
            self.storage.save_schedule_state(state)

        return state

    def get_planned_time_for_date(self, d: date) -> str:
        """Zwraca lub losuje godzinę wykonania dla danego dnia."""
        state = self.get_or_create_weekly_plan(d)
        d_str = d.isoformat()
        
        if d_str in state.get("daily_times", {}):
            return state["daily_times"][d_str]

        # Wyznaczamy godzinę w oparciu o config
        mode = self.config.get("schedule_mode", "random")
        if mode == "fixed":
            target_str = self.config.get("fixed_time", "17:30")
        else:
            start_t = self._parse_time_str(self.config.get("random_window_start", "14:30"))
            end_t = self._parse_time_str(self.config.get("random_window_end", "20:45"))
            
            # Losowa minuta pomiędzy start a end
            start_minutes = start_t.hour * 60 + start_t.minute
            end_minutes = end_t.hour * 60 + end_t.minute
            if end_minutes <= start_minutes:
                end_minutes = start_minutes + 60

            chosen_minutes = random.randint(start_minutes, end_minutes)
            # Dodaj jitter +/- minuty
            jitter_max = int(self.config.get("random_jitter_minutes", 10))
            if jitter_max > 0:
                chosen_minutes += random.randint(-jitter_max, jitter_max)

            # Ograniczenie do doby
            chosen_minutes = max(6 * 60, min(chosen_minutes, 23 * 60 + 50))
            hh = chosen_minutes // 60
            mm = chosen_minutes % 60
            target_str = f"{hh:02d}:{mm:02d}"

        state.setdefault("daily_times", {})[d_str] = target_str
        self.storage.save_schedule_state(state)
        return target_str

    def should_run_today(self, d: date) -> Tuple[bool, str]:
        """Sprawdza czy dzisiaj bot w ogóle ma pracować (czy to nie wylosowany dzień wolny)."""
        state = self.get_or_create_weekly_plan(d)
        weekday = d.weekday()  # 0=Poniedziałek, 6=Niedziela
        
        if weekday in state.get("off_days", []):
            day_name = DAY_NAMES[weekday]
            return False, f"Dzisiaj ({day_name}) jest zaplanowany dzień wolny (symulacja zapomnienia ucznia)."
        return True, "Dzień roboczy."

    def is_already_done_today(self, d: date) -> bool:
        state = self.get_or_create_weekly_plan(d)
        return d.isoformat() in state.get("completed_dates", [])

    def mark_done_today(self, d: date) -> None:
        state = self.get_or_create_weekly_plan(d)
        d_str = d.isoformat()
        completed = state.get("completed_dates", [])
        if d_str not in completed:
            completed.append(d_str)
            state["completed_dates"] = completed
            self.storage.save_schedule_state(state)

    def check_execution_status(self) -> Dict[str, Any]:
        """Zwraca pełny status gotowości do uruchomienia w danym momencie."""
        now = datetime.now()
        today = now.date()
        state = self.get_or_create_weekly_plan(today)
        is_workday, reason_day = self.should_run_today(today)
        is_done = self.is_already_done_today(today)
        planned_time_str = self.get_planned_time_for_date(today)
        planned_time = self._parse_time_str(planned_time_str)
        
        scheduled_dt = datetime.combine(today, planned_time)
        can_run_now = is_workday and (not is_done) and (now >= scheduled_dt)

        return {
            "now": now.strftime("%Y-%m-%d %H:%M:%S"),
            "today": today.isoformat(),
            "weekday_name": DAY_NAMES[today.weekday()],
            "is_workday": is_workday,
            "day_reason": reason_day,
            "is_done": is_done,
            "planned_time": planned_time_str,
            "scheduled_datetime": scheduled_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "can_run_now": can_run_now,
            "off_days_this_week": [DAY_NAMES[i] for i in state.get("off_days", [])]
        }
