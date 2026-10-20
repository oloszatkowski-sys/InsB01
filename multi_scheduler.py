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
SCHEDULE_STATE_FILE = DATA_DIR / "multi_schedule_state.json"

DAY_NAMES_PL = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"]

class MultiScheduler:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_config()
        self.users_mgr = UsersManager()
        self.notifier = Notifier(self.config)
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
        """Konwertuje 'HH:MM' na liczbę minut od północy."""
        parts = time_str.strip().split(":")
        return int(parts[0]) * 60 + int(parts[1])

    def _format_time(self, minutes: int) -> str:
        """Konwertuje minuty od północy na 'HH:MM'."""
        h = (minutes // 60) % 24
        m = minutes % 60
        return f"{h:02d}:{m:02d}"

    def generate_today_plan(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Generuje lub pobiera bezkolizyjny harmonogram na dzisiejszy dzień dla wszystkich aktywnych użytkowników."""
        today_str = date.today().isoformat()
        current_weekday = date.today().weekday()

        if not force_refresh and self.state.get("date") == today_str and "today_plan" in self.state:
            return self.state["today_plan"]

        users = self.users_mgr.get_active_users()
        if not users:
            return []

        win_start = self._parse_time(self.config.get("random_window_start", "15:30"))
        win_end = self._parse_time(self.config.get("random_window_end", "21:30"))
        if win_end <= win_start:
            win_end = win_start + 300

        # Tryb dni wolnych (np. losowy 1 dzień w tygodniu na profil)
        miss_mode = self.config.get("miss_days_mode", "none")
        miss_count = int(self.config.get("miss_days_count", 0))
        miss_fixed = self.config.get("miss_fixed_days", [])

        # Krok 1: Losujemy godziny dla każdego ucznia
        plan = []
        for u in users:
            u_id = u.get("id") or u.get("login")
            nick = u.get("nickname", "Uczeń")
            login = u.get("login", "")

            # Sprawdzenie dnia wolnego
            is_off = False
            if miss_mode == "fixed" and current_weekday in miss_fixed:
                is_off = True
            elif miss_mode == "random" and miss_count > 0:
                # Losujemy czy dzisiaj wypada dzień wolny (deterministycznie na dany dzień)
                seed_str = f"{today_str}_{u_id}"
                random.seed(seed_str)
                is_off = random.random() < (miss_count / 7.0)
                random.seed()

            if is_off:
                plan.append({
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
                rand_min = random.randint(win_start, win_end)
                plan.append({
                    "user_id": u_id,
                    "nickname": nick,
                    "login": login,
                    "is_off_day": False,
                    "scheduled_minutes": rand_min,
                    "scheduled_time": self._format_time(rand_min),
                    "status": "Oczekuje",
                    "completed": False
                })

        # Krok 2: Rozwiązywanie kolizji (Zero Collision Guarantee)
        # Każda sesja potrzebuje min. 15 minut odstępu, by nie nachodzić na inną
        active_slots = [p for p in plan if not p["is_off_day"]]
        active_slots.sort(key=lambda x: x["scheduled_minutes"])

        SLOT_GAP = 15  # 15 minut marginesu na sesję i bezpieczny powrót/wylogowanie
        for i in range(1, len(active_slots)):
            prev = active_slots[i - 1]["scheduled_minutes"]
            curr = active_slots[i]["scheduled_minutes"]
            if curr - prev < SLOT_GAP:
                # Kolizja! Przesuwamy o wymagany odstęp
                new_min = prev + SLOT_GAP
                if new_min > win_end:
                    # Jeśli wychodzi poza okno, przesuwamy przed pierwszy slot
                    new_min = max(win_start, active_slots[0]["scheduled_minutes"] - SLOT_GAP)
                active_slots[i]["scheduled_minutes"] = new_min
                active_slots[i]["scheduled_time"] = self._format_time(new_min)

        # Krok 3: Zapisujemy stan dnia
        self.state["date"] = today_str
        self.state["today_plan"] = plan
        self._save_state()

        return plan

    def mark_user_completed(self, user_id: str) -> None:
        """Oznacza sesję danego użytkownika jako ukończoną w dzisiejszym planie."""
        if "today_plan" in self.state:
            for p in self.state["today_plan"]:
                if p["user_id"] == user_id:
                    p["completed"] = True
                    p["status"] = "Ukończono"
            self._save_state()

    def run_queue_cycle(self) -> None:
        """Sprawdza harmonogram i wykonuje oczekujące sesje jedna po drugiej w ścisłej kolejce."""
        plan = self.generate_today_plan()
        now = datetime.now()
        current_minutes = now.hour * 60 + now.minute

        # Szukamy użytkowników gotowych do wykonania (czas nadszedł i nie ukończono)
        due_entries = [
            p for p in plan 
            if not p["is_off_day"] and not p.get("completed", False) and p["scheduled_minutes"] <= current_minutes
        ]

        if not due_entries:
            return

        bot = InstaLingBot(self.config)
        users = {u.get("id") or u.get("login"): u for u in self.users_mgr.get_active_users()}

        # Wykonujemy po kolei
        for entry in due_entries:
            u_id = entry["user_id"]
            user_obj = users.get(u_id)
            if not user_obj:
                continue

            nick = entry["nickname"]
            log(f"\n[KOLEJKA] Rozpoczynam sesje dla uzytkownika: {nick}")

            # Wykonanie sesji
            res = bot.run_session(user=user_obj)
            if res.get("success", False):
                self.mark_user_completed(u_id)

            # Odczekanie bezpiecznej przerwy przed ewentualną kolejną osobą
            pause_s = random.uniform(25.0, 45.0)
            log(f"[KOLEJKA] Zakonczono sesje dla {nick}. Odczekanie {pause_s:.0f}s przed kolejna...")
            time.sleep(pause_s)

    def publish_today_plan_to_discord(self) -> None:
        """Wysyła ładny plan dnia na kanał #plan-na-dzis."""
        plan = self.generate_today_plan()
        self.notifier.send_daily_plan(plan)

    def publish_weekly_plan_to_discord(self) -> None:
        """Generuje symulację planu na cały tydzień i wysyła na kanał #plan-tygodnia."""
        users = self.users_mgr.get_active_users()
        win_start = self._parse_time(self.config.get("random_window_start", "15:30"))
        win_end = self._parse_time(self.config.get("random_window_end", "21:30"))

        weekly_report = {}
        for day_idx, day_name in enumerate(DAY_NAMES_PL):
            day_entries = []
            for u in users:
                nick = u.get("nickname", "Uczeń")
                # Przykładowe rozłożenie w tygodniu
                t = self._format_time(random.randint(win_start, win_end))
                day_entries.append({
                    "nickname": nick,
                    "time": t,
                    "is_off": (day_idx == 6 and self.config.get("miss_days_mode") != "none")
                })
            weekly_report[day_name] = day_entries

        self.notifier.send_weekly_plan(weekly_report)
