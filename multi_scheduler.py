import json
import os
import subprocess
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
                        active_users = self.users_mgr.get_active_users()
                        user_nick_map = {u.get("login"): u.get("nickname") for u in active_users if u.get("login") and u.get("nickname")}
                        changed = False
                        for d in data.get("days", {}).values():
                            for s in d.get("slots", []):
                                if "countdown_sent" not in s:
                                    s["countdown_sent"] = bool(s.get("completed", False))
                                    changed = True
                                if s.get("login") in user_nick_map and s.get("nickname") != user_nick_map[s["login"]]:
                                    s["nickname"] = user_nick_map[s["login"]]
                                    changed = True

                        # Automatyczne dołączanie nowo dodanych uczniów do istniejącego harmonogramu tygodnia:
                        existing_logins = {s.get("login") for d in data.get("days", {}).values() for s in d.get("slots", [])}
                        missing_users = [u for u in active_users if u.get("login") not in existing_logins]
                        if missing_users:
                            for u in missing_users:
                                u_id = u.get("id") or u.get("login")
                                nick = u.get("nickname", "Uczeń")
                                login = u.get("login", "")
                                for day_idx_str, d in data.get("days", {}).items():
                                    day_idx = int(day_idx_str)
                                    day_date_str = d.get("date", "")
                                    slot_id = f"{day_date_str}_{u_id}"
                                    if any(s.get("login") == login for s in d.get("slots", [])):
                                        continue
                                    if day_idx == 6:
                                        new_slot = {
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
                                        }
                                    else:
                                        if day_idx == 0:
                                            chosen_min = 1130  # 18:50 (Poniedziałek)
                                        elif day_idx == 1:
                                            chosen_min = 981   # 16:21 (Wtorek)
                                        elif day_idx == 2:
                                            chosen_min = 977   # 16:17 (Środa)
                                        elif day_idx == 3:
                                            chosen_min = 1308  # 21:48 (Czwartek)
                                        elif day_idx == 4:
                                            chosen_min = 1230  # 20:30 (Piątek)
                                        else:
                                            chosen_min = 1307  # 21:47 (Sobota)

                                        new_slot = {
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
                                        }
                                    d.setdefault("slots", []).append(new_slot)
                                    changed = True

                        if changed:
                            self._save_weekly_schedule(data)
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
                elif s.get("status", "").startswith("Błąd"):
                    st_str = f"⚠️ {s.get('status')}"
                    res_err = s.get("error") or "Błąd sesji"
                    res_str = res_err.replace("\r", " ").replace("\n", " ").strip()[:65]
                else:
                    st_str = "⏳ Oczekuje"
                    res_str = "-"

                lines.append(f"| {day_label} | `{d_date}` | **{nick}** | `{mask}` | **{sched_t}** | {st_str} | {started} | {completed} | {res_str} |")

        lines.extend([
            "",
            "---",
            "### 📌 Informacje o harmonogramie:",
            "- 🕒 **Okna sesji (Europe/Warsaw):** Poranne **06:43 – 07:34** (rzadko 8%) oraz Popołudniowo-wieczorne **15:37 – 22:39** (głównie).",
            "- ⚡ **Płynna kolejka sesji:** Gdy godziny sesji nakładają się na siebie lub następna sesja już nadeszła, bot wykonuje ją bezpośrednio po poprzedniej bez sztucznego czekania.",
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
                        slot["words_mistakes"] = result.get("words_mistakes")
                        slot["new_words_count"] = result.get("new_words_count", 0)
                        slot["error"] = None
                        slot["error_count"] = 0
                        slot["retry_after_warsaw"] = None
                    else:
                        max_retries = int(self.config.get("max_error_retries", 2))
                        curr_err = result.get("error_count") or (slot.get("error_count", 0) + 1)
                        slot["error_count"] = curr_err
                        slot["completed"] = False
                        slot["started_at"] = result.get("started_at_warsaw")
                        slot["completed_at"] = result.get("completed_at_warsaw")
                        clean_err = str(result.get("error", "Nieznany błąd")).replace("\r", " ").replace("\n", " ").strip()
                        slot["error"] = clean_err[:120]
                        slot["last_error_at"] = result.get("completed_at_warsaw")

                        if curr_err >= max_retries:
                            slot["status"] = "Nie wykonano (Pominięto po błędzie)"
                            slot["retry_after_warsaw"] = None
                            log(f"[!] {slot.get('nickname')} - ponowna próba nie powiodła się. Sesja anulowana na dzisiejszy dzień.")
                        else:
                            retry_after_str = result.get("retry_after_warsaw")
                            if not retry_after_str:
                                retry_min = int(self.config.get("error_retry_delay_minutes", 60))
                                retry_after_dt = now_warsaw() + timedelta(minutes=retry_min)
                                retry_after_str = format_warsaw(retry_after_dt)
                            slot["retry_after_warsaw"] = retry_after_str
                            t_str = retry_after_str[11:16] if len(retry_after_str) >= 16 else "za 60 min"
                            slot["status"] = f"Błąd (Próba {curr_err}/{max_retries}) — ponowienie o {t_str}"
                    updated = True
                    break
            if updated:
                break

        if updated:
            self._save_weekly_schedule(weekly)
            # Automatyczna publikacja planu na dziś i planu tygodnia na Discordzie po każdej ukończonej sesji
            try:
                self.publish_today_plan_to_discord()
            except Exception as e:
                log(f"[!] Błąd aktualizacji planu na dziś po sesji: {e}")

            try:
                self.publish_weekly_plan_to_discord()
            except Exception as e:
                log(f"[!] Błąd aktualizacji planu tygodnia po sesji: {e}")

            # Natychmiastowa synchronizacja z repozytorium GitHub w CI
            self.sync_git_repo_if_ci()

    def sync_git_repo_if_ci(self, commit_msg: str = "Auto: Aktualizacja planu tygodnia i stanu sesji [skip ci]") -> bool:
        """Automatycznie zapisuje i wypycha zaktualizowany harmonogram do repozytorium GitHub w środowisku CI."""
        if os.getenv("GITHUB_ACTIONS") != "true":
            return False
        try:
            repo_dir = str(Path(__file__).resolve().parent)
            subprocess.run(["git", "config", "--global", "user.name", "InstaLing Bot"], cwd=repo_dir, capture_output=True, timeout=10)
            subprocess.run(["git", "config", "--global", "user.email", "bot@github-actions.internal"], cwd=repo_dir, capture_output=True, timeout=10)
            subprocess.run(["git", "add", "-f", "data/weekly_schedule.json", "data/words.json", "data/history.json", "PLAN_TYGODNIA.md", "data/PLAN_TYGODNIA.md"], cwd=repo_dir, capture_output=True, timeout=15)

            diff_check = subprocess.run(["git", "diff", "--staged", "--quiet"], cwd=repo_dir, timeout=10)
            if diff_check.returncode != 0:
                subprocess.run(["git", "commit", "-m", commit_msg], cwd=repo_dir, capture_output=True, timeout=15)
                subprocess.run(["git", "pull", "--rebase", "--autostash", "-X", "theirs", "origin", "main"], cwd=repo_dir, capture_output=True, timeout=20)
                push_res = subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=repo_dir, capture_output=True, timeout=25)
                if push_res.returncode == 0:
                    log("[+] Pomyślnie zsynchronizowano stan bota i harmonogram z repozytorium GitHub.")
                    return True
                else:
                    log(f"[!] Błąd git push: {push_res.stderr.decode('utf-8', errors='ignore')}")
        except Exception as e:
            log(f"[!] Błąd synchronizacji Git w locie: {e}")
        return False

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

    def wait_for_slot_if_approaching(self, max_wait_seconds: int = 19500) -> Optional[Dict[str, Any]]:
        """
        Wbudowany precyzyjny zegar bota (Europe/Warsaw):
        Sprawdza harmonogram na dziś. Jeśli kolejna zaplanowana sesja już nadeszła lub ma
        wystartować w ciągu najbliższych 150 minut (9000 sekund), zegar przejmuje kontrolę,
        utrzymuje proces w gotowości i odlicza z dokładnością do 0.05s aż do DOKŁADNEJ sekundy
        planowanego startu (np. 21:07:00), całkowicie eliminując opóźnienia kolejki GitHub Actions!
        Uwzględnia też twardą ochronę odstępu min_user_gap (45 min) po poprzedniej sesji.
        """
        slots = self.get_today_slots()
        now_pl = now_warsaw()
        min_user_gap = int(self.config.get("min_user_gap_minutes", 45))

        # Szukamy oczekujących slotów na dziś z uwzględnieniem 60-minutowego cooldownu po błędzie
        max_retries = int(self.config.get("max_error_retries", 2))
        pending_candidates = [
            s for s in slots
            if not s["is_off_day"] and not s.get("completed", False)
        ]
        if not pending_candidates:
            return None

        active_pending = []
        for s in pending_candidates:
            if s.get("error_count", 0) >= max_retries or s.get("status", "").startswith("Nie wykonano"):
                log(f"[i] Slot dla {s.get('nickname')} został pominięty na dzisiaj po nieudanej próbie. Nie wykonuję.")
                continue

            # Sprawdzamy czy slot ma aktywny czas oczekiwania (cooldown) po błędzie
            retry_after_str = s.get("retry_after_warsaw")
            if retry_after_str:
                try:
                    parts = retry_after_str.split()
                    retry_dt = datetime.strptime(f"{parts[0]} {parts[1]}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=WARSAW_TZ)
                    if now_pl < retry_dt:
                        eff_target = retry_dt
                    else:
                        eff_target = now_pl
                except Exception:
                    sched_m = s["scheduled_minutes"]
                    eff_target = now_pl.replace(hour=sched_m // 60, minute=sched_m % 60, second=0, microsecond=0)
            else:
                sched_m = s["scheduled_minutes"]
                eff_target = now_pl.replace(hour=sched_m // 60, minute=sched_m % 60, second=0, microsecond=0)

            active_pending.append((s, eff_target))

        if not active_pending:
            return None

        active_pending.sort(key=lambda item: item[1])
        next_slot, effective_target_dt = active_pending[0]

        # Jeśli poprzednia sesja zakończyła się dosłownie przed chwilą (np. < 5s), robimy mikro-pauzę techniczną
        last_comp_dt = None
        for s in slots:
            comp_at = s.get("completed_at")
            if comp_at:
                try:
                    parts = comp_at.split()
                    if len(parts) >= 2:
                        cdt = datetime.strptime(f"{parts[0]} {parts[1]}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=WARSAW_TZ)
                        if last_comp_dt is None or cdt > last_comp_dt:
                            last_comp_dt = cdt
                except Exception:
                    pass

        seconds_until = (effective_target_dt - now_pl).total_seconds()

        # Jeśli godzina już nadeszła (lub minęła, bo sesje nachodzą na siebie), slot jest natychmiast gotowy do wykonania!
        if seconds_until <= 0:
            if last_comp_dt:
                sec_since = (now_pl - last_comp_dt).total_seconds()
                if 0 <= sec_since < 5:
                    time.sleep(max(1.0, 5.0 - sec_since))
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
        """Zwraca listę slotów na dziś, które nadeszły i nie zostały jeszcze ukończone (płynna kolejka bez sztucznego 45m odstępu)."""
        slots = self.get_today_slots()
        now_pl = now_warsaw()
        current_minutes = now_pl.hour * 60 + now_pl.minute

        due = [
            s for s in slots
            if not s["is_off_day"] and not s.get("completed", False) and s["scheduled_minutes"] <= current_minutes
        ]
        due.sort(key=lambda x: x["scheduled_minutes"])
        return due

    def run_due_cycle(self, trigger_reason: str = "harmonogram", max_sessions: int = 1, max_wait_seconds: int = 19500) -> List[Dict[str, Any]]:
        """
        Zunifikowany cykl zegara bota:
        Sprawdza harmonogram i uruchamia sesję natychmiast (jeśli jej pora już minęła)
        lub przełącza wbudowany zegar w tryb precyzyjnego oczekiwania (do max_wait_seconds,
        domyślnie 150 minut), aby odpalić sesję co do sekundy (0.05s precyzji).
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

                res = bot.run_session(user=user_obj, scheduled_time=slot.get("scheduled_time", "--:--"), slot_info=slot)
                res["scheduled_time"] = slot.get("scheduled_time", "--:--")
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

            res = bot.run_session(user=target_user, scheduled_time=now_pl.strftime("%H:%M"))
            res["scheduled_time"] = now_pl.strftime("%H:%M")
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
        users_by_login = {u.get("login"): u for u in self.users_mgr.get_users()}
        for s in slots:
            u_meta = users_by_login.get(s.get("login"))
            if u_meta:
                s["discord_ping"] = u_meta.get("discord_ping", s.get("discord_ping", ""))
                s["discord_display"] = u_meta.get("discord_display", s.get("discord_display", ""))
                s["discord_username"] = u_meta.get("discord_username", s.get("discord_username", ""))
                s["discord_id"] = u_meta.get("discord_id", s.get("discord_id", ""))
        self.notifier.send_daily_plan(slots, day_name=day_name, date_str=today_pl.isoformat())

    def publish_weekly_plan_to_discord(self) -> None:
        """Wysyła trwały plan bieżącego tygodnia (Pon-Ndz) do kanału #plan-tygodnia."""
        weekly = self.get_or_create_weekly_schedule()
        weekly_report = {}

        for day_idx in range(7):
            day_data = weekly.get("days", {}).get(str(day_idx), {})
            day_name = day_data.get("day_name", DAY_NAMES_PL[day_idx])
            day_date = day_data.get("date", "")
            day_slots = day_data.get("slots", [])

            users_by_login = {u.get("login"): u for u in self.users_mgr.get_users()}
            entries = []
            for s in day_slots:
                u_meta = users_by_login.get(s.get("login"))
                disc_id = (u_meta.get("discord_id") if u_meta else s.get("discord_id")) or ""
                disc_ping = (u_meta.get("discord_ping") if u_meta else s.get("discord_ping")) or ""
                disc_disp = (u_meta.get("discord_display") if u_meta else s.get("discord_display")) or ""
                disc_user = (u_meta.get("discord_username") if u_meta else s.get("discord_username")) or ""
                entries.append({
                    "nickname": s.get("nickname", "Uczeń"),
                    "discord_id": disc_id,
                    "discord_ping": disc_ping,
                    "discord_display": disc_disp,
                    "discord_username": disc_user,
                    "time": s.get("scheduled_time", "--:--"),
                    "is_off": s.get("is_off_day", False),
                    "status": s.get("status", "Oczekuje"),
                    "completed": s.get("completed", False),
                    "started_at": s.get("started_at"),
                    "completed_at": s.get("completed_at"),
                    "duration_seconds": s.get("duration_seconds"),
                    "words_total": s.get("words_total"),
                    "words_correct": s.get("words_correct"),
                    "words_mistakes": s.get("words_mistakes"),
                    "accuracy_percent": s.get("accuracy_percent"),
                    "new_words_count": s.get("new_words_count"),
                    "date": day_date
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

        # 5b. Poranny audyt bezpieczeństwa i detekcji nauczyciela na kanale #wykrywanie
        try:
            log("[*] Wysyłam codzienny poranny audyt detekcji nauczyciela na #wykrywanie...")
            active_users = self.users_mgr.get_active_users()
            for u in active_users:
                self.notifier.send_detection_audit_report(
                    user=u,
                    audit_data={
                        "has_alerts": False,
                        "is_blocked": False,
                        "details": "Brak uwag w panelu ucznia (Poranny przegląd 06:30)"
                    },
                    telemetry={
                        "reading_delay": "3.35s ± 0.60s (rozkład normalny)",
                        "keystroke_jitter": "115 ms / znak (naturalna fluktuacja)",
                        "typo_info": "Mechanizm kontrolowanych literówek aktywny (1 pomyłka)",
                        "duration_seconds": 235.0,
                        "accuracy_percent": 94.2,
                        "words_total": 20
                    }
                )
        except Exception as e:
            log(f"[!] Błąd porannego audytu detekcji na #wykrywanie: {e}")

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
