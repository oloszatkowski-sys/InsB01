import json
import random
import time
import urllib.request
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
        """
        Pobiera lub tworzy spójny harmonogram na cały bieżący tydzień w strefie Europe/Warsaw.
        W obrębie tego samego tygodnia (ISO week) harmonogram jest STABILNY i NIE ulega zmianie!
        """
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        week_key = get_iso_week_key()

        if not force_new and self.weekly_file.exists():
            try:
                with open(self.weekly_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("week_key") == week_key and "days" in data:
                        # Uzupełniamy ewentualny brakujący klucz countdown_sent
                        for d in data.get("days", {}).values():
                            for s in d.get("slots", []):
                                if "countdown_sent" not in s:
                                    s["countdown_sent"] = bool(s.get("completed", False))
                        self._export_markdown_plan(data)
                        return data
            except Exception:
                pass

        # Tworzymy nowy harmonogram dla nowego tygodnia
        self.clean_legacy_states()
        users = self.users_mgr.get_active_users()

        # Okna czasowe w strefie Europe/Warsaw:
        # 1. Okno poranne: 06:43 - 07:34 (403 - 454 min)
        # 2. Okno popołudniowo-wieczorne: 15:37 - 22:39 (937 - 1359 min)
        morn_start = time_to_minutes(self.config.get("morning_window_start", "06:43"))
        morn_end = time_to_minutes(self.config.get("morning_window_end", "07:34"))
        if morn_end <= morn_start:
            morn_end = morn_start + 51

        eve_start = time_to_minutes(self.config.get("random_window_start", "15:37"))
        eve_end = time_to_minutes(self.config.get("random_window_end", "22:39"))
        if eve_end <= eve_start + 60:
            eve_end = eve_start + 422

        morn_chance = float(self.config.get("morning_session_chance_percent", 8.0))
        min_user_gap = int(self.config.get("min_user_gap_minutes", 45))

        # Obliczamy dni wolne w tygodniu dla każdego ucznia (Anty-Detekcja):
        # - 50% szansy na 1 odpuszczoną sesję w tygodniu
        # - 15% szansy na 2 odpuszczone sesje w tygodniu
        # - 35% szansy na 0 odpuszczonych (pełny tydzień)
        user_off_days_map: Dict[str, set] = {}
        for u in users:
            u_id = u.get("id") or u.get("login")
            miss_seed = f"miss_prob_{week_key}_{u_id}"
            miss_rng = random.Random(miss_seed)
            roll = miss_rng.uniform(0, 100)
            if roll < 50.0:
                num_off = 1
            elif roll < 65.0:
                num_off = 2
            else:
                num_off = 0

            if num_off > 0:
                user_off_days_map[u_id] = set(miss_rng.sample(range(7), k=num_off))
            else:
                user_off_days_map[u_id] = set()

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
            day_seed = f"order_{week_key}_{day_date_str}"
            rng = random.Random(day_seed)
            rng.shuffle(shuffled_users)

            active_today = [
                u for u in shuffled_users
                if day_idx not in user_off_days_map.get(u.get("id") or u.get("login"), set())
            ]
            off_today = [
                u for u in shuffled_users
                if day_idx in user_off_days_map.get(u.get("id") or u.get("login"), set())
            ]

            # Sloty dla dni wolnych
            for u in off_today:
                u_id = u.get("id") or u.get("login")
                nick = u.get("nickname", "Uczeń")
                login = u.get("login", "")
                slot_id = f"{day_date_str}_{u_id}"
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
                    "countdown_sent": True,
                    "started_at": None,
                    "completed_at": None,
                    "duration_seconds": None,
                    "accuracy_percent": None,
                    "error": None
                })

            # Przydział sesji aktywnych:
            # Okno poranne (06:43-07:34) lub popołudniowo-wieczorne (15:37-22:39)
            morn_roll = rng.uniform(0, 100)
            morn_user = None
            eve_users = list(active_today)

            # Maksymalnie 1 uczeń w oknie porannym (mieści się z odstępem min 45m)
            if active_today and morn_roll < morn_chance:
                morn_user = active_today[0]
                eve_users = active_today[1:]

            if morn_user:
                u_id = morn_user.get("id") or morn_user.get("login")
                nick = morn_user.get("nickname", "Uczeń")
                login = morn_user.get("login", "")
                slot_id = f"{day_date_str}_{u_id}"

                time_seed = f"time_morn_{day_date_str}_{u_id}_{week_key}"
                time_rng = random.Random(time_seed)
                chosen_min = time_rng.randint(morn_start, morn_end)

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
                    "countdown_sent": False,
                    "started_at": None,
                    "completed_at": None,
                    "duration_seconds": None,
                    "accuracy_percent": None,
                    "error": None
                })

            # Sloty dla okna wieczornego (15:37 - 22:39)
            if eve_users:
                total_eve = len(eve_users)
                total_span = eve_end - eve_start
                sub_window = max(total_span // total_eve, min_user_gap + 15)

                for e_idx, u in enumerate(eve_users):
                    u_id = u.get("id") or u.get("login")
                    nick = u.get("nickname", "Uczeń")
                    login = u.get("login", "")
                    slot_id = f"{day_date_str}_{u_id}"

                    sector_start = eve_start + e_idx * sub_window
                    sector_end = min(sector_start + sub_window - min_user_gap, eve_end)
                    if sector_end <= sector_start:
                        sector_start = eve_start
                        sector_end = eve_end

                    time_seed = f"time_eve_{day_date_str}_{u_id}_{week_key}"
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
                        "countdown_sent": False,
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
                    if new_min > eve_end:
                        new_min = eve_end
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
        today_pl = today_warsaw()
        today_str = today_pl.isoformat()

        # Obliczamy statystyki tygodnia
        total_slots = 0
        completed_slots = 0
        pending_slots = 0
        off_slots = 0

        days = data.get("days", {})
        for day_idx in range(7):
            day_obj = days.get(str(day_idx), {})
            for s in day_obj.get("slots", []):
                if s.get("is_off_day"):
                    off_slots += 1
                elif s.get("completed"):
                    completed_slots += 1
                    total_slots += 1
                else:
                    pending_slots += 1
                    total_slots += 1

        lines = [
            "# 🗓️ Harmonogram Tygodniowy InstaLing Multi-User",
            "",
            "> **Automatycznie synchronizowany plan sesji w strefie `Europe/Warsaw` z pełną ochroną anty-detekcyjną.**",
            "",
            f"- 🇵🇱 **Strefa czasowa:** `Europe/Warsaw` ({data.get('tzname', 'CET')})",
            f"- 📅 **Tydzień ISO:** `{data.get('week_key', '')}`",
            f"- 📊 **Status tygodnia:** Ukończono **{completed_slots}** z **{total_slots}** sesji (Pozostało: **{pending_slots}**)",
            f"- 🔄 **Ostatnia aktualizacja:** `{format_warsaw()}`",
            "",
            "| Dzień tygodnia | Data | Uczeń | Login | Plan (PL) | Status | Rozpoczęto | Ukończono | Wynik |",
            "|---|---|---|---|---|---|---|---|---|"
        ]

        for day_idx in range(7):
            day_obj = days.get(str(day_idx), {})
            d_name = day_obj.get("day_name", DAY_NAMES_PL[day_idx])
            d_date = day_obj.get("date", "")
            slots = day_obj.get("slots", [])

            is_today = (d_date == today_str)
            day_label = f"👉 **{d_name} (DZIŚ)**" if is_today else d_name

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
                    res_str = f"**{words_cor}/{words_tot}** ({acc}%)" if acc is not None else "Tak"
                elif s.get("status") == "W trakcie":
                    st_str = "▶️ W trakcie..."
                    res_str = "-"
                elif s.get("status") == "Błąd":
                    st_str = "⚠️ Błąd"
                    res_str = s.get("error") or "Błąd"
                else:
                    st_str = "⏳ Oczekuje"
                    res_str = "-"

                lines.append(f"| {day_label} | `{d_date}` | **{nick}** | `{mask}` | **{sched_t}** | {st_str} | {started} | {completed} | {res_str} |")

        lines.extend([
            "",
            "---",
            "### 📌 Informacje o harmonogramie:",
            "- 🕒 **Okna sesji (Europe/Warsaw):** Poranne **06:43 – 07:34** (rzadko 8%) oraz Popołudniowo-wieczorne **15:37 – 22:39** (głównie).",
            "- 🛡️ **Odstępy anty-kolizyjne:** Pomiędzy sesjami różnych uczniów zachowywany jest odstęp minimum **45 minut**.",
            "- ⏰ **Wbudowany zegar bota:** Sesje uruchamiają się punktualnie o wyznaczonej godzinie (po jednej sekcji naraz).",
            "- ☀️ **Codzienny przegląd o 06:30:** GitHub Actions każdego ranka weryfikuje gotowość i publikuje plan na dany dzień.",
            "- 🔒 **Niezmienność planu:** Harmonogram wylosowany na dany tydzień obowiązuje od poniedziałku do niedzieli."
        ])

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
                    slot["countdown_sent"] = True
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

    def mark_slot_in_progress(self, slot_id: str, started_at: str) -> None:
        """Oznacza slot jako 'W trakcie' w momencie wybicia godziny zegara."""
        weekly = self.get_or_create_weekly_schedule()
        updated = False
        for day_obj in weekly.get("days", {}).values():
            for slot in day_obj.get("slots", []):
                if slot.get("slot_id") == slot_id:
                    slot["status"] = "W trakcie"
                    slot["started_at"] = started_at
                    updated = True
                    break
            if updated:
                break
        if updated:
            self._save_weekly_schedule(weekly)

    def wait_for_slot_if_approaching(self, max_wait_seconds: int = 7200) -> Optional[Dict[str, Any]]:
        """
        Wbudowany precyzyjny zegar bota (Europe/Warsaw):
        Sprawdza harmonogram na dziś. Jeśli kolejna zaplanowana sesja już nadeszła lub ma
        wystartować w ciągu najbliższych 120 minut (7200 sekund), zegar przejmuje kontrolę,
        utrzymuje proces w gotowości i odlicza z dokładnością do 0.05s aż do DOKŁADNEJ sekundy
        planowanego startu (np. 21:07:00), całkowicie eliminując opóźnienia kolejki GitHub Actions!
        Uwzględnia też twardą ochronę odstępu min_user_gap (45 min) po poprzedniej sesji.
        """
        slots = self.get_today_slots()
        now_pl = now_warsaw()
        min_user_gap = int(self.config.get("min_user_gap_minutes", 45))

        # Szukamy najbliższego oczekującego slotu na dziś
        pending = [
            s for s in slots
            if not s["is_off_day"] and not s.get("completed", False)
        ]
        if not pending:
            return None

        pending.sort(key=lambda x: x["scheduled_minutes"])
        next_slot = pending[0]

        sched_min = next_slot["scheduled_minutes"]
        target_hour = sched_min // 60
        target_minute = sched_min % 60
        target_dt = now_pl.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)

        # Runtime Anti-Collision: wyliczamy najwcześniejszy dozwolony czas po poprzedniej sesji (+45 min)
        earliest_allowed_dt = target_dt
        for s in slots:
            comp_at = s.get("completed_at")
            if comp_at:
                try:
                    parts = comp_at.split()
                    if len(parts) >= 2:
                        comp_dt = datetime.strptime(f"{parts[0]} {parts[1]}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=WARSAW_TZ)
                        allowed_after_comp = comp_dt + timedelta(minutes=min_user_gap)
                        if allowed_after_comp > earliest_allowed_dt:
                            earliest_allowed_dt = allowed_after_comp
                except Exception:
                    pass

        effective_target_dt = max(target_dt, earliest_allowed_dt)
        seconds_until = (effective_target_dt - now_pl).total_seconds()

        # Jeśli godzina (oraz wymagany odstęp 45 min) już nadeszła, slot jest natychmiast gotowy!
        if seconds_until <= 0:
            return next_slot

        # Jeśli sesja ma wystartować w oknie do max_wait_seconds (domyślnie do 120 min):
        if 0 < seconds_until <= max_wait_seconds:
            nick = next_slot["nickname"]
            sched_t = next_slot["scheduled_time"]
            eff_str = effective_target_dt.strftime("%H:%M:%S")
            log("\n" + "═" * 62)
            log(f"🕒 [WBUDOWANY ZEGAR BOTA] Namierzono nadchodzącą sesję: {nick}")
            log("─" * 62)
            log(f"⏰ Godzina w planie:    {sched_t} (Europe/Warsaw)")
            log(f"🎯 Punktualny start o:  {eff_str} ({get_current_polish_tzname()})")
            log(f"🇵🇱 Aktualny czas:       {now_pl.strftime('%H:%M:%S')} ({get_current_polish_tzname()})")
            log(f"⏳ Czas do wybicia:     {int(seconds_until)}s (~{seconds_until/60:.1f} min)")
            log(f"🔒 Zegar bota przejął kontrolę — czekam na dokładną sekundę {eff_str}...")
            log("═" * 62 + "\n")

            last_log_min = -1
            while True:
                now_pl = now_warsaw()
                rem_sec = (effective_target_dt - now_pl).total_seconds()
                if rem_sec <= 0:
                    break
                rem_min = int(rem_sec // 60)
                if rem_min != last_log_min and (rem_min % 5 == 0 or rem_min <= 3):
                    last_log_min = rem_min
                    log(f"[🕒 ZEGAR BOTA] {now_pl.strftime('%H:%M:%S')} PL ➔ Czekam na {nick} ({eff_str}) — pozostało {int(rem_sec // 60)}m {int(rem_sec % 60):02d}s")
                if rem_sec > 60:
                    sleep_part = min(rem_sec - 30, 15.0)
                elif rem_sec > 2:
                    sleep_part = 0.5
                else:
                    sleep_part = max(0.05, rem_sec)
                time.sleep(sleep_part)

            # Na GitHub Actions po dłuższym oczekiwaniu pobieramy ewentualne zmiany z repozytorium
            import os
            import subprocess
            if os.getenv("GITHUB_ACTIONS") == "true":
                try:
                    subprocess.run(
                        ["git", "pull", "--rebase", "--autostash", "-X", "theirs", "origin", "main"],
                        cwd=str(Path(__file__).resolve().parent),
                        timeout=15,
                        capture_output=True
                    )
                except Exception:
                    pass

            # Po wybudzeniu odświeżamy stan z dysku, upewniając się, że slot nadal oczekuje
            fresh_slots = self.get_today_slots()
            for fs in fresh_slots:
                if fs.get("slot_id") == next_slot.get("slot_id"):
                    if fs.get("completed", False):
                        log(f"[i] Slot dla {nick} został już ukończony w międzyczasie.")
                        return None
                    next_slot = fs
                    break

            log(f"[+] [WBUDOWANY ZEGAR] Wybiła dokładnie godzina {now_warsaw().strftime('%H:%M:%S')}! Odpalam sesję dla {nick} co do sekundy!")
            return next_slot

        return None

    def get_due_slots(self) -> List[Dict[str, Any]]:
        """Zwraca listę slotów na dziś, które nadeszły i nie zostały jeszcze ukończone z gwarancją odstępu."""
        slots = self.get_today_slots()
        now_pl = now_warsaw()
        current_minutes = now_pl.hour * 60 + now_pl.minute
        min_user_gap = int(self.config.get("min_user_gap_minutes", 45))

        for s in slots:
            comp_at = s.get("completed_at")
            if comp_at:
                try:
                    parts = comp_at.split()
                    if len(parts) >= 2:
                        dt_str = f"{parts[0]} {parts[1]}"
                        comp_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=WARSAW_TZ)
                        diff_sec = (now_pl - comp_dt).total_seconds()
                        if 0 <= diff_sec < (min_user_gap * 60):
                            rem_min = int(min_user_gap - (diff_sec / 60))
                            log(f"[i] Ochrona odstępu: Ostatnia sesja zakończyła się o {comp_at}. Wymagany odstęp: {min_user_gap} min. Kolejne konto wystartuje dopiero za ok. {rem_min} min.")
                            return []
                except Exception:
                    pass

        due = [
            s for s in slots
            if not s["is_off_day"] and not s.get("completed", False) and s["scheduled_minutes"] <= current_minutes
        ]
        due.sort(key=lambda x: x["scheduled_minutes"])
        return due

    def run_due_cycle(self, trigger_reason: str = "harmonogram", max_sessions: int = 1, max_wait_seconds: int = 7200) -> List[Dict[str, Any]]:
        """
        Zunifikowany cykl zegara bota:
        Sprawdza harmonogram i uruchamia sesję natychmiast (jeśli jej pora już minęła)
        lub przełącza wbudowany zegar w tryb precyzyjnego oczekiwania (do max_wait_seconds,
        domyślnie 120 minut), aby odpalić sesję co do sekundy (0.05s precyzji).
        Wykonuje MAKSYMALNIE JEDNĄ sesję na wywołanie (max_sessions=1).
        """
        slot_ready = self.wait_for_slot_if_approaching(max_wait_seconds=max_wait_seconds)
        if not slot_ready:
            return []

        due_slots = [slot_ready]

        from bot import InstaLingBot
        bot = InstaLingBot(self.config)
        users_map = {u.get("id") or u.get("login"): u for u in self.users_mgr.get_active_users()}

        executed_results = []
        slots_to_run = due_slots[:max_sessions]

        for slot in slots_to_run:
            u_id = slot["user_id"]
            user_obj = users_map.get(u_id)
            if not user_obj:
                continue

            nick = slot["nickname"]
            slot_id = slot["slot_id"]

            if not BotLock.acquire(u_id, nick):
                log(f"[!] Nie można pobrać blokady dla {nick}. Pomijam ten cykl.")
                continue

            now_pl = now_warsaw()
            current_min = now_pl.hour * 60 + now_pl.minute
            delay_text = get_delay_str(slot["scheduled_minutes"], current_min)

            log("\n" + "═" * 62)
            log("🕒 [START ZADANIA] InstaLing Auto-Bot")
            log("─" * 62)
            log(f"🌍 Czas UTC:         {format_utc()}")
            log(f"🇵🇱 Czas w Polsce:     {format_warsaw(now_pl)}")
            log(f"👤 Uczeń:             {nick} ({mask_login(slot['login'])})")
            log(f"⏰ Planowana sesja:   {slot['scheduled_time']} ({get_current_polish_tzname()})")
            log(f"⏱️ Punktualność:      {delay_text}")
            log(f"🎯 Przyczyna:        {trigger_reason}")
            log("═" * 62)

            started_at_warsaw = format_warsaw(now_pl)
            self.mark_slot_in_progress(slot_id, started_at_warsaw)

            try:
                # Powiadomienie o rozpoczęciu sesji na Discordzie (BEZ PINGU)
                try:
                    self.notifier.send_session_start(
                        user=user_obj,
                        scheduled_time=slot.get("scheduled_time", "--:--"),
                        started_pl=started_at_warsaw
                    )
                except Exception as e:
                    log(f"[!] Błąd wysyłania powiadomienia startowego: {e}")

                res = bot.run_session(user=user_obj)
                res["started_at_warsaw"] = started_at_warsaw
                res["completed_at_warsaw"] = format_warsaw(now_warsaw())
                
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
            # Powiadomienie o rozpoczęciu sesji na Discordzie (BEZ PINGU)
            try:
                self.notifier.send_session_start(
                    user=target_user,
                    scheduled_time=now_pl.strftime("%H:%M"),
                    started_pl=started_at
                )
            except Exception as e:
                log(f"[!] Błąd wysyłania powiadomienia startowego: {e}")

            res = bot.run_session(user=target_user)
            res["started_at_warsaw"] = started_at
            res["completed_at_warsaw"] = format_warsaw(now_warsaw())

            today_str = today_warsaw().isoformat()
            slot_id = f"{today_str}_{u_id}"
            self.update_slot_result(slot_id, res)
            return res
        finally:
            BotLock.release()

    def publish_today_plan_to_discord(self) -> None:
        """Wysyła plan na dziś (w 100% zgodny z planem tygodnia i strefą Europe/Warsaw) do kanału #plan-na-dzis."""
        today_pl = today_warsaw()
        day_name = DAY_NAMES_PL[today_pl.weekday()]
        slots = self.get_today_slots()
        self.notifier.send_daily_plan(slots, day_name=day_name, date_str=today_pl.isoformat())

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

        self.notifier.send_weekly_plan(weekly_report, week_key=weekly.get("week_key", ""))

    def run_morning_check(self) -> Dict[str, Any]:
        """
        Codzienny przegląd o 06:30 (Europe/Warsaw):
        1. Weryfikuje stały plan tygodnia (generuje nowy TYLKO po zmianie tygodnia na kolejny).
        2. Aktualizuje plik PLAN_TYGODNIA.md (oznacza dzisiejszy dzień).
        3. Wysyła plan na dziś do #plan-na-dzis.
        4. W poniedziałki wysyła plan tygodnia do #plan-tygodnia.
        5. Wysyła poranny meldunek na ntfy.sh dla obserwowanych uczniów.
        6. Sprawdza dostępność serwisu InstaLing.
        """
        today_pl = today_warsaw()
        today_str = today_pl.isoformat()
        day_name = DAY_NAMES_PL[today_pl.weekday()]
        week_key = get_iso_week_key()

        log("\n" + "=" * 62)
        log("☀️ [PORANNY PRZEGLĄD 06:30] InstaLing Auto-Bot")
        log("-" * 62)
        log(f"🇵🇱 Czas w Polsce:     {format_warsaw()}")
        log(f"📅 Data i dzień:      {today_str} ({day_name})")
        log(f"🗓️ Tydzień ISO:       {week_key}")
        log("=" * 62)

        # 1. Pobieramy lub tworzymy harmonogram (zachowuje godziny w trakcie tygodnia!)
        weekly = self.get_or_create_weekly_schedule()

        # 2. Sprawdzamy czy to nowy tydzień
        if weekly.get("last_weekly_plan_week") != week_key:
            log(f"[*] Nowy tydzień ISO ({week_key})! Publikuję plan tygodnia na Discordzie...")
            self.publish_weekly_plan_to_discord()
            weekly["last_weekly_plan_week"] = week_key

        # 3. Publikujemy dzisiejszy plan na Discordzie
        log(f"[*] Publikuję plan na dziś ({day_name}) na Discordzie (#plan-na-dzis)...")
        self.publish_today_plan_to_discord()
        weekly["last_daily_plan_date"] = today_str
        weekly["last_morning_check_date"] = today_str

        # 4. Sprawdzamy sloty i wysyłamy ntfy.sh
        today_slots = self.get_today_slots()
        slots_summary = []
        for s in today_slots:
            nick = s.get("nickname", "Uczeń")
            t = s.get("scheduled_time", "--:--")
            off = s.get("is_off_day", False)
            if off:
                slots_summary.append(f"• {nick}: 🏖️ Dzień wolny")
            else:
                slots_summary.append(f"• {nick}: ⏰ {t}")

        # Powiadomienie ntfy.sh dla kont z track_in_ntfy: true
        ntfy_user = self.users_mgr.get_ntfy_user()
        if ntfy_user:
            topic = self.config.get("ntfy_topic", "").strip() or f"instaling_{ntfy_user.get('login', 'user')}"
            self.notifier.send_morning_ntfy(topic, today_str, day_name, slots_summary)

        # 5. Aktualizacja kanału #statystyki zbiorczym raportem
        try:
            self.notifier.send_bot_global_statistics()
        except Exception as e:
            log(f"[!] Błąd wysyłania statystyk bota: {e}")

        # 6. Sprawdzenie łączności z InstaLing
        status_ok = True
        try:
            req = urllib.request.Request(
                "https://instaling.pl/teacher.php?page=login",
                headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    log("[+] Serwis InstaLing odpowiada poprawnie (HTTP 200).")
        except Exception as e:
            log(f"[!] Ostrzeżenie przy sprawdzaniu łączności: {e}")
            status_ok = False

        self._save_weekly_schedule(weekly)
        log("[+] Poranny przegląd 06:30 zakończony sukcesem.\n")
        return {"success": True, "date": today_str, "slots": today_slots, "instaling_online": status_ok}

    def check_and_publish_daily_announcements(self) -> None:
        """Publikuje plan tygodnia w poniedziałki oraz plan na dziś każdego ranka jeśli jeszcze nie został wysłany."""
        weekly = self.get_or_create_weekly_schedule()
        today_str = today_warsaw().isoformat()
        week_key = get_iso_week_key()
        need_save = False

        if weekly.get("last_weekly_plan_week") != week_key:
            log(f"[*] Nowy tydzień ({week_key})! Publikuję plan tygodnia na Discordzie...")
            self.publish_weekly_plan_to_discord()
            weekly["last_weekly_plan_week"] = week_key
            need_save = True

        if weekly.get("last_daily_plan_date") != today_str:
            log(f"[*] Nowy dzień ({today_str})! Publikuję plan na dziś na Discordzie...")
            self.publish_today_plan_to_discord()
            weekly["last_daily_plan_date"] = today_str
            need_save = True

        if need_save:
            self._save_weekly_schedule(weekly)
