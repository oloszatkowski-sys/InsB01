import json
import random
import time
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional
from config import load_config
from users_manager import UsersManager, mask_login
from notifier import Notifier
from logger import log
from bot import InstaLingBot

DATA_DIR = Path(__file__).resolve().parent / "data"
WEEKLY_SCHEDULE_FILE = DATA_DIR / "weekly_schedule.json"
SCHEDULE_STATE_FILE = DATA_DIR / "multi_schedule_state.json"

DAY_NAMES_PL = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"]

class MultiScheduler:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_config()
        self.users_mgr = UsersManager()
        self.notifier = Notifier(self.config)
        self.weekly_file = WEEKLY_SCHEDULE_FILE
        self.state_file = SCHEDULE_STATE_FILE
        self._load_state()

    def _load_state(self) -> None:
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    self.state = json.load(f)
            except Exception:
                self.state = {}
        else:
            self.state = {}

    def _save_state(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False)

    def _parse_time(self, time_str: str) -> int:
        parts = time_str.strip().split(":")
        return int(parts[0]) * 60 + int(parts[1])

    def _format_time(self, minutes: int) -> str:
        h = (minutes // 60) % 24
        m = minutes % 60
        return f"{h:02d}:{m:02d}"

    def get_current_week_key(self) -> str:
        """Zwraca identyfikator bieżącego tygodnia ISO, np. '2026-W43'."""
        today = date.today()
        year, week_num, _ = today.isocalendar()
        return f"{year}-W{week_num:02d}"

    def get_or_create_weekly_schedule(self, force_new: bool = False) -> Dict[str, Any]:
        """Pobiera lub tworzy spójny harmonogram na cały bieżący tydzień (od poniedziałku do niedzieli)."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        week_key = self.get_current_week_key()

        if not force_new and self.weekly_file.exists():
            try:
                with open(self.weekly_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("week_key") == week_key and "days" in data:
                        return data
            except Exception:
                pass

        # Generujemy nowy, trwały plan tygodnia
        users = self.users_mgr.get_active_users()
        win_start = self._parse_time(self.config.get("random_window_start", "15:46"))
        win_end = self._parse_time(self.config.get("random_window_end", "21:57"))
        if win_end <= win_start:
            win_end = win_start + 300

        miss_mode = self.config.get("miss_days_mode", "none")
        miss_count = int(self.config.get("miss_days_count", 0))
        miss_fixed = self.config.get("miss_fixed_days", [])

        days_schedule = {}

        # Obliczamy daty od poniedziałku do niedzieli bieżącego tygodnia
        today = date.today()
        monday = today - timedelta(days=today.weekday())

        for day_idx in range(7):
            day_date = monday + timedelta(days=day_idx)
            day_name = DAY_NAMES_PL[day_idx]
            day_date_str = day_date.isoformat()

            day_slots = []
            for u in users:
                u_id = u.get("id") or u.get("login")
                nick = u.get("nickname", "Uczeń")
                login = u.get("login", "")

                # Sprawdzenie dnia wolnego
                is_off = False
                if miss_mode == "fixed" and day_idx in miss_fixed:
                    is_off = True
                elif miss_mode == "random" and miss_count > 0:
                    seed_str = f"{day_date_str}_{u_id}"
                    random.seed(seed_str)
                    is_off = random.random() < (miss_count / 7.0)
                    random.seed()

                if is_off:
                    day_slots.append({
                        "user_id": u_id,
                        "nickname": nick,
                        "login": login,
                        "is_off_day": True,
                        "scheduled_minutes": 0,
                        "scheduled_time": "Wolne",
                        "status": "Dzień wolny",
                        "completed": True
                    })
                else:
                    seed_str = f"{day_date_str}_{u_id}_time"
                    random.seed(seed_str)
                    rand_min = random.randint(win_start, win_end)
                    random.seed()

                    day_slots.append({
                        "user_id": u_id,
                        "nickname": nick,
                        "login": login,
                        "is_off_day": False,
                        "scheduled_minutes": rand_min,
                        "scheduled_time": self._format_time(rand_min),
                        "status": "Oczekuje",
                        "completed": False
                    })

            # Rozwiązywanie kolizji w ramach danego dnia
            active = [s for s in day_slots if not s["is_off_day"]]
            active.sort(key=lambda x: x["scheduled_minutes"])

            SLOT_GAP = 15
            for i in range(1, len(active)):
                prev = active[i - 1]["scheduled_minutes"]
                curr = active[i]["scheduled_minutes"]
                if curr - prev < SLOT_GAP:
                    new_min = prev + SLOT_GAP
                    if new_min > win_end:
                        new_min = max(win_start, active[0]["scheduled_minutes"] - SLOT_GAP)
                    active[i]["scheduled_minutes"] = new_min
                    active[i]["scheduled_time"] = self._format_time(new_min)

            days_schedule[str(day_idx)] = {
                "day_name": day_name,
                "date": day_date_str,
                "slots": day_slots
            }

        result = {
            "week_key": week_key,
            "created_at": datetime.now().isoformat(),
            "days": days_schedule
        }

        with open(self.weekly_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        return result

    def generate_today_plan(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Pobiera DOKŁADNIE ten sam plan na dzisiaj, który został zaplanowany w Planie Tygodnia."""
        weekly = self.get_or_create_weekly_schedule()
        today = date.today()
        current_weekday = today.weekday()
        day_data = weekly.get("days", {}).get(str(current_weekday))

        if not day_data:
            # Fallback
            return []

        today_slots = day_data.get("slots", [])

        # Synchronizacja stanu ukończenia z multi_schedule_state.json
        today_str = today.isoformat()
        completed_users = set(self.state.get("completed_today", [])) if self.state.get("date") == today_str else set()

        for slot in today_slots:
            u_id = slot["user_id"]
            if u_id in completed_users:
                slot["completed"] = True
                slot["status"] = "Ukończono"

        return today_slots

    def mark_user_completed(self, user_id: str) -> None:
        """Oznacza sesję danego użytkownika jako ukończoną dzisiaj."""
        today_str = date.today().isoformat()
        if self.state.get("date") != today_str:
            self.state["date"] = today_str
            self.state["completed_today"] = []

        if user_id not in self.state["completed_today"]:
            self.state["completed_today"].append(user_id)
            self._save_state()

    def run_queue_cycle(self) -> None:
        """Sprawdza harmonogram i wykonuje oczekujące sesje jedna po drugiej w ścisłej kolejce."""
        plan = self.generate_today_plan()
        now = datetime.now()
        current_minutes = now.hour * 60 + now.minute

        due_entries = [
            p for p in plan 
            if not p["is_off_day"] and not p.get("completed", False) and p["scheduled_minutes"] <= current_minutes
        ]

        if not due_entries:
            return

        bot = InstaLingBot(self.config)
        users = {u.get("id") or u.get("login"): u for u in self.users_mgr.get_active_users()}

        for entry in due_entries:
            u_id = entry["user_id"]
            user_obj = users.get(u_id)
            if not user_obj:
                continue

            nick = entry["nickname"]
            log(f"\n[KOLEJKA] Rozpoczynam sesje dla uzytkownika: {nick}")

            res = bot.run_session(user=user_obj)
            if res.get("success", False):
                self.mark_user_completed(u_id)

            pause_s = random.uniform(25.0, 45.0)
            log(f"[KOLEJKA] Zakonczono sesje dla {nick}. Odczekanie {pause_s:.0f}s przed kolejna...")
            time.sleep(pause_s)

    def publish_today_plan_to_discord(self) -> None:
        """Wysyła plan na dziś (w 100% zgodny z planem tygodnia) do kanału #plan-na-dzis."""
        plan = self.generate_today_plan()
        self.notifier.send_daily_plan(plan)

    def publish_weekly_plan_to_discord(self) -> None:
        """Wysyła trwały plan bieżącego tygodnia (Pon-Ndz) do kanału #plan-tygodnia."""
        weekly = self.get_or_create_weekly_schedule()
        weekly_report = {}

        for day_idx in range(7):
            day_data = weekly.get("days", {}).get(str(day_idx), {})
            day_name = day_data.get("day_name", DAY_NAMES_PL[day_idx])
            day_slots = day_data.get("slots", [])

            entries = []
            for s in day_slots:
                entries.append({
                    "nickname": s.get("nickname", "Uczeń"),
                    "time": s.get("scheduled_time", "--:--"),
                    "is_off": s.get("is_off_day", False)
                })
            weekly_report[day_name] = entries

        self.notifier.send_weekly_plan(weekly_report)
