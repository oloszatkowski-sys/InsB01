import json
import random
import time
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from config import load_config
from users_manager import UsersManager, mask_login
from notifier import Notifier
from logger import log
from bot_lock import BotLock
from timezone_utils import (
    WARSAW_TZ,
    UTC_TZ,
    now_warsaw,
    now_utc,
    today_warsaw,
    format_warsaw,
    format_utc,
    time_to_minutes,
    minutes_to_time,
    get_iso_week_key,
    get_delay_str,
    get_current_polish_tzname
)

DATA_DIR = Path(__file__).resolve().parent / "data"
WEEKLY_SCHEDULE_FILE = DATA_DIR / "weekly_schedule.json"
LEGACY_SCHEDULE_STATE_FILE = DATA_DIR / "schedule_state.json"
LEGACY_MULTI_STATE_FILE = DATA_DIR / "multi_schedule_state.json"

DAY_NAMES_PL = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"]

class MultiScheduler:
    """Zunifikowany, świadomy strefy czasowej (Europe/Warsaw) harmonogram sesji wielu użytkowników."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_config()
        self.users_mgr = UsersManager()
        self.notifier = Notifier(self.config)
        self.weekly_file = WEEKLY_SCHEDULE_FILE

    def clean_legacy_states(self) -> None:
        """Usuwa przestarzałe pliki stanu, zapewniając jeden spójny mechanizm terminów."""
        for legacy in [LEGACY_SCHEDULE_STATE_FILE, LEGACY_MULTI_STATE_FILE]:
            if legacy.exists():
                try:
                    legacy.unlink(missing_ok=True)
                    log(f"[*] Usunięto nieaktualny plik stanu: {legacy.name}")
                except Exception as e:
                    log(f"[!] Błąd usuwania starego pliku {legacy.name}: {e}")

    def reset_schedule(self) -> Dict[str, Any]:
        """Przeprowadza kontrolowany reset harmonogramu i generuje świeży plan na bieżący tydzień."""
        log("[*] Inicjalizacja kontrolowanego resetu harmonogramu...")
        self.clean_legacy_states()
        if self.weekly_file.exists():
            try:
                self.weekly_file.unlink(missing_ok=True)
            except Exception:
                pass
        
        new_plan = self.get_or_create_weekly_schedule(force_new=True)
        log("[+] Wygenerowano nowy, świeży plan tygodnia (Europe/Warsaw).")
        return new_plan

    def get_or_create_weekly_schedule(self, force_new: bool = False) -> Dict[str, Any]:
        """Pobiera lub tworzy spójny harmonogram na cały bieżący tydzień w strefie Europe/Warsaw."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        week_key = get_iso_week_key()

        if not force_new and self.weekly_file.exists():
            try:
                with open(self.weekly_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("week_key") == week_key and "days" in data:
                        self._export_markdown_plan(data)
                        return data
            except Exception:
                pass

        # Tworzymy nowy harmonogram dla bieżącego tygodnia
        self.clean_legacy_states()
        users = self.users_mgr.get_active_users()
        win_start = time_to_minutes(self.config.get("random_window_start", "15:46"))
        win_end = time_to_minutes(self.config.get("random_window_end", "21:57"))
        if win_end <= win_start + 60:
            win_end = win_start + 300

        # Minimalny odstęp pomiędzy różnymi użytkownikami tego samego dnia (minuty)
        min_user_gap = int(self.config.get("min_user_gap_minutes", 45))

        miss_mode = self.config.get("miss_days_mode", "none")
        miss_count = int(self.config.get("miss_days_count", 0))
        miss_fixed = self.config.get("miss_fixed_days", [])

        # Obliczamy poniedziałek bieżącego tygodnia w Polsce
        today_pl = today_warsaw()
        monday = today_pl - timedelta(days=today_pl.weekday())

        days_schedule: Dict[str, Any] = {}

        for day_idx in range(7):
            day_date = monday + timedelta(days=day_idx)
            day_name = DAY_NAMES_PL[day_idx]
            day_date_str = day_date.isoformat()

            day_slots = []
            
            # Aby schemat nie powtarzał się każdego dnia, tasujemy kolejność użytkowników per dzień
            shuffled_users = list(users)
            # Deterministyczne tasowanie per dzień tygodnia
            day_seed = f"order_{week_key}_{day_date_str}"
            rng = random.Random(day_seed)
            rng.shuffle(shuffled_users)

            # Wyznaczamy dostępne pasma czasowe dla użytkowników w tym dniu
            total_users = max(len(shuffled_users), 1)
            total_span = win_end - win_start
            sub_window = max(total_span // total_users, min_user_gap + 15)

            for u_idx, u in enumerate(shuffled_users):
                u_id = u.get("id") or u.get("login")
                nick = u.get("nickname", "Uczeń")
                login = u.get("login", "")
                slot_id = f"{day_date_str}_{u_id}"

                # Sprawdzenie dnia wolnego
                is_off = False
                if miss_mode == "fixed" and day_idx in miss_fixed:
                    is_off = True
                elif miss_mode == "random" and miss_count > 0:
                    seed_str = f"off_{day_date_str}_{u_id}"
                    off_rng = random.Random(seed_str)
                    is_off = off_rng.random() < (miss_count / 7.0)

                if is_off:
                    day_slots.append({
                        "slot_id": slot_id,
                        "user_id": u_id,
                        "nickname": nick,
                        "login": login,
                        "is_off_day": True,
                        "scheduled_minutes": 0,
                        "scheduled_time": "Wolne",
                        "status": "Dzień wolny",
                        "completed": True,
                        "started_at": None,
                        "completed_at": None,
                        "duration_seconds": None,
                        "accuracy_percent": None,
                        "error": None
                    })
                else:
                    # Losujemy godzinę w dedykowanym sektorze dnia z jitterem
                    sector_start = win_start + u_idx * sub_window
                    sector_end = min(sector_start + sub_window - min_user_gap, win_end)
                    if sector_end <= sector_start:
                        sector_start = win_start
                        sector_end = win_end

                    time_seed = f"time_{day_date_str}_{u_id}_{week_key}"
                    time_rng = random.Random(time_seed)
                    chosen_min = time_rng.randint(sector_start, sector_end)

                    day_slots.append({
                        "slot_id": slot_id,
                        "user_id": u_id,
                        "nickname": nick,
                        "login": login,
                        "is_off_day": False,
                        "scheduled_minutes": chosen_min,
                        "scheduled_time": minutes_to_time(chosen_min),
                        "status": "Oczekuje",
                        "completed": False,
                        "started_at": None,
                        "completed_at": None,
                        "duration_seconds": None,
                        "accuracy_percent": None,
                        "error": None
                    })

            # Rozwiązywanie ewentualnych kolizji z zachowaniem minimalnego odstępu (min_user_gap)
            active_slots = [s for s in day_slots if not s["is_off_day"]]
            active_slots.sort(key=lambda x: x["scheduled_minutes"])

            for i in range(1, len(active_slots)):
                prev_min = active_slots[i - 1]["scheduled_minutes"]
                curr_min = active_slots[i]["scheduled_minutes"]
                if curr_min - prev_min < min_user_gap:
                    new_min = prev_min + min_user_gap
                    if new_min > win_end:
                        # Przesuń w tył pierwszy lub dopasuj
                        new_min = win_end
                    active_slots[i]["scheduled_minutes"] = new_min
                    active_slots[i]["scheduled_time"] = minutes_to_time(new_min)

            days_schedule[str(day_idx)] = {
                "day_name": day_name,
                "date": day_date_str,
                "slots": day_slots
            }

        result = {
            "week_key": week_key,
            "timezone": "Europe/Warsaw",
            "tzname": get_current_polish_tzname(),
            "created_at_warsaw": format_warsaw(),
            "created_at_utc": format_utc(),
            "days": days_schedule
        }

        self._save_weekly_schedule(result)
        return result

    def _save_weekly_schedule(self, data: Dict[str, Any]) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(self.weekly_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self._export_markdown_plan(data)

    def _export_markdown_plan(self, data: Dict[str, Any]) -> None:
        """Eksportuje czytelny plik PLAN_TYGODNIA.md dla użytkownika i GitHuba."""
        lines = [
            "# 🗓️ Harmonogram Tygodniowy InstaLing Multi-User",
            "",
            f"> **Strefa czasowa:** `Europe/Warsaw` ({data.get('tzname', 'CET')})  ",
            f"> **Tydzień ISO:** `{data.get('week_key', '')}`  ",
            f"> **Ostatnia synchronizacja:** `{format_warsaw()}`  ",
            "",
            "| Dzień tygodnia | Data | Uczeń | Login | Godzina (PL) | Status | Rozpoczęto | Ukończono | Wynik |",
            "|---|---|---|---|---|---|---|---|---|"
        ]

        days = data.get("days", {})
        for day_idx in range(7):
            day_obj = days.get(str(day_idx), {})
            d_name = day_obj.get("day_name", DAY_NAMES_PL[day_idx])
            d_date = day_obj.get("date", "")
            slots = day_obj.get("slots", [])

            for s in slots:
                nick = s.get("nickname", "Uczeń")
                mask = mask_login(s.get("login", ""))
                sched_t = s.get("scheduled_time", "--:--")
                is_off = s.get("is_off_day", False)
                comp = s.get("completed", False)
                started = s.get("started_at") or "-"
                completed = s.get("completed_at") or "-"
                acc = s.get("accuracy_percent")
                words_tot = s.get("words_total")
                words_cor = s.get("words_correct")

                if is_off:
                    st_str = "🏖️ Dzień wolny"
                    res_str = "-"
                elif comp:
                    st_str = "✅ Ukończono"
                    res_str = f"{words_cor}/{words_tot} ({acc}%)" if acc is not None else "Tak"
                elif s.get("status") == "W trakcie":
                    st_str = "▶️ W trakcie..."
                    res_str = "-"
                elif s.get("status") == "Błąd":
                    st_str = "⚠️ Błąd"
                    res_str = s.get("error") or "Błąd"
                else:
                    st_str = "⏳ Oczekuje"
                    res_str = "-"

                lines.append(f"| {d_name} | `{d_date}` | **{nick}** | `{mask}` | **{sched_t}** | {st_str} | {started} | {completed} | {res_str} |")

        md_content = "\n".join(lines) + "\n"

        root_md = Path(__file__).resolve().parent / "PLAN_TYGODNIA.md"
        data_md = DATA_DIR / "PLAN_TYGODNIA.md"
        try:
            with open(root_md, "w", encoding="utf-8") as f:
                f.write(md_content)
            with open(data_md, "w", encoding="utf-8") as f:
                f.write(md_content)
        except Exception as e:
            log(f"[!] Błąd zapisu PLAN_TYGODNIA.md: {e}")

    def get_today_slots(self) -> List[Dict[str, Any]]:
        """Pobiera sloty na dzisiejszy dzień w Polsce."""
        weekly = self.get_or_create_weekly_schedule()
        today_pl = today_warsaw()
        current_weekday = today_pl.weekday()
        day_data = weekly.get("days", {}).get(str(current_weekday), {})
        return day_data.get("slots", [])

    def update_slot_result(self, slot_id: str, result: Dict[str, Any]) -> None:
        """Aktualizuje stan konkretnego slotu (rozpoczęcie, zakończenie, statystyki) w weekly_schedule.json."""
        weekly = self.get_or_create_weekly_schedule()
        success = result.get("success", False)
        updated = False

        for day_idx, day_obj in weekly.get("days", {}).items():
            for slot in day_obj.get("slots", []):
                if slot.get("slot_id") == slot_id:
                    if success:
                        slot["completed"] = True
                        slot["status"] = "Ukończono"
                        slot["started_at"] = result.get("started_at_warsaw")
                        slot["completed_at"] = result.get("completed_at_warsaw")
                        slot["duration_seconds"] = result.get("duration_seconds")
                        slot["accuracy_percent"] = result.get("accuracy_percent")
                        slot["words_total"] = result.get("words_total")
                        slot["words_correct"] = result.get("words_correct")
                        slot["error"] = None
                    else:
                        slot["completed"] = False
                        slot["status"] = "Błąd"
                        slot["started_at"] = result.get("started_at_warsaw")
                        slot["completed_at"] = result.get("completed_at_warsaw")
                        slot["error"] = result.get("error", "Nieznany błąd")
                    updated = True
                    break
            if updated:
                break

        if updated:
            self._save_weekly_schedule(weekly)

    def get_due_slots(self) -> List[Dict[str, Any]]:
        """Zwraca listę slotów na dziś, które nadeszły i nie zostały jeszcze ukończone."""
        slots = self.get_today_slots()
        now_pl = now_warsaw()
        current_minutes = now_pl.hour * 60 + now_pl.minute

        due = [
            s for s in slots
            if not s["is_off_day"] and not s.get("completed", False) and s["scheduled_minutes"] <= current_minutes
        ]
        due.sort(key=lambda x: x["scheduled_minutes"])
        return due

    def run_due_cycle(self, trigger_reason: str = "harmonogram", max_sessions: int = 1) -> List[Dict[str, Any]]:
        """
        Sprawdza harmonogram i wykonuje oczekujące sesje.
        Domyślnie wykonuje MAKSYMALNIE JEDNĄ sesję na wywołanie (max_sessions=1),
        co uniemożliwia jednoczesne lub bezpośrednie wykonywanie 2 sekcji naraz!
        """
        due_slots = self.get_due_slots()
        if not due_slots:
            return []

        from bot import InstaLingBot
        bot = InstaLingBot(self.config)
        users_map = {u.get("id") or u.get("login"): u for u in self.users_mgr.get_active_users()}

        executed_results = []

        # Bierzemy maksymalnie max_sessions (domyślnie 1)
        slots_to_run = due_slots[:max_sessions]

        for slot in slots_to_run:
            u_id = slot["user_id"]
            user_obj = users_map.get(u_id)
            if not user_obj:
                continue

            nick = slot["nickname"]
            slot_id = slot["slot_id"]

            # Blokada zapobiegająca jednoczesnemu workflow
            if not BotLock.acquire(u_id, nick):
                log(f"[!] Nie można pobrać blokady dla {nick}. Pomijam ten cykl.")
                continue

            now_pl = now_warsaw()
            current_min = now_pl.hour * 60 + now_pl.minute
            delay_text = get_delay_str(slot["scheduled_minutes"], current_min)

            log("\n" + "=" * 62)
            log("🕒 [START ZADANIA] InstaLing Auto-Bot")
            log("-" * 62)
            log(f"🌍 Czas UTC:         {format_utc()}")
            log(f"🇵🇱 Czas w Polsce:     {format_warsaw(now_pl)}")
            log(f"👤 Uczeń:             {nick} ({mask_login(slot['login'])})")
            log(f"⏰ Planowana sesja:   {slot['scheduled_time']} ({get_current_polish_tzname()})")
            log(f"⏱️ Przesunięcie:      {delay_text}")
            log(f"🎯 Przyczyna:        {trigger_reason}")
            log("=" * 62)

            started_at_warsaw = format_warsaw(now_pl)

            try:
                res = bot.run_session(user=user_obj)
                res["started_at_warsaw"] = started_at_warsaw
                res["completed_at_warsaw"] = format_warsaw(now_warsaw())
                
                # Zapisujemy stan w weekly_schedule.json
                self.update_slot_result(slot_id, res)
                executed_results.append(res)

                if res.get("success"):
                    log(f"[+] Zadanie dla {nick} zakończone sukcesem i odnotowane w harmonogramie.")
                else:
                    log(f"[!] Zadanie dla {nick} zakończone błędem: {res.get('error')}")

            finally:
                BotLock.release()

        return executed_results

    def run_single_user(self, nickname_or_login: str, trigger_reason: str = "ręczne uruchomienie") -> Dict[str, Any]:
        """Uruchamia sesję dla konkretnego użytkownika w bezpieczny, izolowany sposób."""
        from bot import InstaLingBot
        users = self.users_mgr.get_active_users()
        target_user = None
        for u in users:
            if u.get("nickname", "").lower() == nickname_or_login.lower() or u.get("login", "") == nickname_or_login:
                target_user = u
                break

        if not target_user:
            return {"success": False, "error": f"Nie znaleziono użytkownika: {nickname_or_login}"}

        nick = target_user.get("nickname", "Uczeń")
        u_id = target_user.get("id") or target_user.get("login")

        if not BotLock.acquire(u_id, nick):
            return {"success": False, "error": f"Inna sesja dla {nick} lub innego użytkownika jest już w toku (aktywna blokada)."}

        now_pl = now_warsaw()
        log("\n" + "=" * 62)
        log("🕒 [START ZADANIA INDYWIDUALNEGO] InstaLing Auto-Bot")
        log("-" * 62)
        log(f"🌍 Czas UTC:         {format_utc()}")
        log(f"🇵🇱 Czas w Polsce:     {format_warsaw(now_pl)}")
        log(f"👤 Uczeń:             {nick} ({mask_login(target_user.get('login'))})")
        log(f"🎯 Przyczyna:        {trigger_reason}")
        log("=" * 62)

        started_at = format_warsaw(now_pl)
        bot = InstaLingBot(self.config)

        try:
            res = bot.run_session(user=target_user)
            res["started_at_warsaw"] = started_at
            res["completed_at_warsaw"] = format_warsaw(now_warsaw())

            # Dopasowujemy dzisiejszy slot jeśli istnieje
            today_str = today_warsaw().isoformat()
            slot_id = f"{today_str}_{u_id}"
            self.update_slot_result(slot_id, res)
            return res
        finally:
            BotLock.release()

    def publish_today_plan_to_discord(self) -> None:
        """Wysyła plan na dziś (w 100% zgodny z planem tygodnia i strefą Europe/Warsaw) do kanału #plan-na-dzis."""
        slots = self.get_today_slots()
        self.notifier.send_daily_plan(slots)

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
                    "is_off": s.get("is_off_day", False),
                    "status": s.get("status", "Oczekuje"),
                    "completed": s.get("completed", False),
                    "completed_at": s.get("completed_at")
                })
            weekly_report[day_name] = entries

        self.notifier.send_weekly_plan(weekly_report)
