import urllib.request
import urllib.parse
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from logger import log
from users_manager import mask_login
from timezone_utils import WARSAW_TZ, now_warsaw, today_warsaw


def to_discord_unix(date_str: str, time_str: str) -> Optional[int]:
    """Konwertuje datę (YYYY-MM-DD) i godzinę (HH:MM) w strefie Europe/Warsaw na znacznik UNIX dla Discorda."""
    try:
        clean_time = time_str.strip()[:5]
        dt = datetime.strptime(f"{date_str} {clean_time}", "%Y-%m-%d %H:%M").replace(tzinfo=WARSAW_TZ)
        return int(dt.timestamp())
    except Exception:
        return None


def format_date_pl(date_str: str) -> str:
    """Zamienia datę RRRR-MM-DD na czytelny format DD.MM.RRRR (np. 30.10.2026)."""
    try:
        parts = date_str.strip()[:10].split("-")
        if len(parts) == 3:
            return f"{parts[2]}.{parts[1]}.{parts[0]}"
    except Exception:
        pass
    return date_str


def format_duration_pl(seconds: Optional[float]) -> str:
    """Zamienia sekundy na czytelny format (np. 342.6 s (~5.7 min))."""
    if seconds is None:
        return "brak danych"
    sec = float(seconds)
    mins = sec / 60.0
    return f"{sec:.1f} s (~{mins:.1f} min)"


def lookup_history_details(nickname: str, completed_at: Optional[str], history_list: List[Dict[str, Any]]) -> Dict[str, int]:
    """Wyszukuje w historii sesji liczbę nowych słówek i autokorekt dla danego wykonania."""
    res = {"new_words": 0, "autocorrect": 0, "mistakes": 0}
    if not history_list:
        return res

    comp_prefix = completed_at[:15] if completed_at and len(completed_at) >= 15 else ""
    matched = None
    for h in reversed(history_list):
        if h.get("nickname") == nickname:
            h_comp = str(h.get("completed_at_warsaw", ""))
            if not comp_prefix or h_comp.startswith(comp_prefix) or h_comp[:10] == comp_prefix[:10]:
                matched = h
                break

    if not matched:
        return res

    res["mistakes"] = int(matched.get("words_mistakes", 0) or 0)
    if "new_words_count" in matched and matched["new_words_count"] is not None:
        res["new_words"] = int(matched["new_words_count"])
        res["autocorrect"] = int(matched.get("autocorrect_count", 0) or 0)
        return res

    details = matched.get("words_details", [])
    res["new_words"] = len({
        w.get("prompt", "").strip()
        for w in details
        if w.get("status") == "nowe" and w.get("prompt", "").strip()
    })
    res["autocorrect"] = len({
        w.get("prompt", "").strip()
        for w in details
        if w.get("status") == "autokorekta" and w.get("prompt", "").strip()
    })
    return res


class Notifier:
    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def _get_webhook(self, key: str) -> Optional[str]:
        url = self.config.get(key, "").strip()
        if not url:
            url = self.config.get("discord_webhook_url", "").strip()
        return url if url else None

    # =========================================================================
    # 1. KANAŁ #sekcja — Powiadomienia o sesji (start + pełne podsumowanie)
    # =========================================================================
    def send_session_start(self, user: Dict[str, Any], scheduled_time: str, started_pl: str) -> None:
        """Powiadomienie o starcie sesji na kanał #sekcja."""
        sekcja_wh = self._get_webhook("webhook_sekcja")
        if not sekcja_wh:
            return

        nickname = user.get("nickname", "Uczeń")
        masked = mask_login(user.get("login", ""))
        start_hms = started_pl[11:19] if started_pl and len(started_pl) >= 19 else started_pl

        desc = (
            f"👤 **Uczeń:** `{nickname}` (`{masked}`)\n"
            f"⏰ **Planowana godzina:** `{scheduled_time}`\n"
            f"▶️ **Rozpoczęcie (PL):** `{start_hms}`\n"
            f"⏳ **Status:** Trwa logowanie i rozwiązywanie pytań..."
        )

        self._send_discord_embed(
            webhook_url=sekcja_wh,
            title=f"🤖 InstaLing Auto-Bot — Start Sesji: {nickname}",
            description=desc,
            color=0x3498DB,
            footer_text="InstaLing Multi-User Manager • Ciemny Styl"
        )

    def send_session_summary(self, result: Dict[str, Any], user: Dict[str, Any], session_logs: Optional[List[str]] = None) -> None:
        """Wysyła pełne, uporządkowane po kolei podsumowanie sesji na #sekcja, #logi-bota, #statystyki i ntfy."""
        success = result.get("success", False)
        total = result.get("words_total", 0)
        correct = result.get("words_correct", 0)
        mistakes = result.get("words_mistakes", max(0, total - correct))
        acc = result.get("accuracy_percent", 0.0)
        duration_s = result.get("duration_seconds", 0.0)

        nickname = user.get("nickname", "Uczeń")
        masked = mask_login(user.get("login", ""))
        scheduled_time = result.get("scheduled_time", "--:--")
        started_pl = result.get("started_at_warsaw", "N/A")
        completed_pl = result.get("completed_at_warsaw", "N/A")

        dur_nice = format_duration_pl(duration_s)

        words_details = result.get("words_details", [])
        new_words_count = result.get("new_words_count")
        if new_words_count is None:
            new_words_count = len({
                w.get("prompt", "").strip()
                for w in words_details
                if w.get("status") == "nowe" and w.get("prompt", "").strip()
            })

        autocorrect_count = result.get("autocorrect_count")
        if autocorrect_count is None:
            autocorrect_count = len({
                w.get("prompt", "").strip()
                for w in words_details
                if w.get("status") == "autokorekta" and w.get("prompt", "").strip()
            })

        sekcja_wh = self._get_webhook("webhook_sekcja")
        ping_role = self.config.get("discord_ping", "@everyone")

        if success:
            title = f"🤖 InstaLing Auto-Bot - Sesja Ukończona: {nickname}"
            color = 0x2ECC71
            desc = (
                f"👤 **Uczeń:** `{nickname}` (`{masked}`)\n"
                f"⏰ **Planowana godzina:** `{scheduled_time}`\n"
                f"**Status:** ✅ Sesja zakończona sukcesem\n"
                f"**Rozpoczęcie (PL):** `{started_pl}`\n"
                f"**Zakończenie (PL):** `{completed_pl}`\n"
                f"**Czas trwania:** `{dur_nice}`\n"
                f"**Rozwiązane słówka:** `{total}`\n"
                f"**Poprawne:** `{correct}` | **Błędy:** `{mistakes}`\n"
                f"**Skuteczność:** `{acc:.1f}%`\n"
                f"**Nowe słówka:** `{new_words_count}`\n"
                f"**Poprawione (autokorekta):** `{autocorrect_count}`\n"
                f"**Akcja końcowa:** Powrót do strony głównej i bezpieczne wylogowanie"
            )

            fields = []
            if words_details:
                priority = {"nowe": 4, "autokorekta": 3, "celowy_blad": 2, "poprawnie": 1, "blad": 0}
                clean_words: Dict[str, Dict[str, str]] = {}
                for item in words_details:
                    prompt = item.get("prompt", "").strip()
                    ans = item.get("answer", "").strip()
                    st = item.get("status", "poprawnie")
                    if not prompt:
                        continue
                    prev = clean_words.get(prompt)
                    if not prev:
                        clean_words[prompt] = {"prompt": prompt, "answer": ans, "status": st}
                    else:
                        if (not prev["answer"] or set(prev["answer"]) <= {"_"}) and ans and not (set(ans) <= {"_"}):
                            prev["answer"] = ans
                        if priority.get(st, 0) > priority.get(prev["status"], 0):
                            prev["status"] = st
                        if ans and not (set(ans) <= {"_"}):
                            prev["answer"] = ans

                w_lines = []
                items_list = list(clean_words.values())
                for idx, item in enumerate(items_list[:25], start=1):
                    prompt = item["prompt"]
                    ans = item["answer"]
                    st = item["status"]
                    if st == "nowe":
                        w_lines.append(f"`{idx:02d}.` {prompt} ➔ **{ans}** 🆕 *(nowe)*")
                    elif st == "autokorekta":
                        w_lines.append(f"`{idx:02d}.` {prompt} ➔ **{ans}** 🔄 *(poprawione)*")
                    elif st == "celowy_blad":
                        w_lines.append(f"`{idx:02d}.` {prompt} ➔ **{ans}** 🎯 *(celowy błąd)*")
                    else:
                        w_lines.append(f"`{idx:02d}.` {prompt} ➔ **{ans}** ✅")

                if len(items_list) > 25:
                    w_lines.append(f"*...oraz {len(items_list) - 25} innych pytań*")

                fields.append({
                    "name": f"📚 Słówka z tej sesji ({len(items_list)} unikalnych):",
                    "value": "\n".join(w_lines),
                    "inline": False
                })
        else:
            title = f"⚠️ InstaLing Auto-Bot - Błąd Sesji: {nickname}"
            color = 0xE74C3C
            err = result.get("error", "Nieznany błąd wykonania")
            desc = (
                f"👤 **Uczeń:** `{nickname}` (`{masked}`)\n"
                f"⏰ **Planowana godzina:** `{scheduled_time}`\n"
                f"**Status:** ❌ Wystąpił problem w trakcie sesji\n"
                f"**Czas zdarzenia:** `{completed_pl}`\n"
                f"**Szczegóły błędu:** `{err[:250]}`\n\n"
                f"🔄 *Bot ponowi próbę wykonania sesji w kolejnym cyklu zegara.*"
            )
            fields = []

        if sekcja_wh:
            self._send_discord_embed(
                webhook_url=sekcja_wh,
                title=title,
                description=desc,
                color=color,
                fields=fields,
                content=ping_role if ping_role else None,
                footer_text="InstaLing Multi-User Manager • Ciemny Styl"
            )

        # Wysyłka rozbudowanych logów na kanał #logi-bota
        logs_wh = self._get_webhook("webhook_logi_bota") or self.config.get("discord_logs_webhook_url", "").strip()
        if logs_wh and session_logs:
            self._send_discord_logs(logs_wh, nickname, masked, session_logs, success)

        # Aktualizacja panelu statystyk na #statystyki
        stats_wh = self._get_webhook("webhook_statystyki")
        if stats_wh and success:
            try:
                self.send_bot_global_statistics(latest_user=nickname, latest_acc=acc, latest_score=f"{correct}/{total}")
            except Exception as e:
                log(f"[!] Błąd wysyłania statystyk: {e}")

        # Powiadomienie push ntfy.sh
        if user.get("track_in_ntfy", False):
            ntfy_topic = self.config.get("ntfy_topic", "").strip() or f"instaling_{user.get('login', 'user').strip()}"
            if success:
                self._send_ntfy(
                    ntfy_topic,
                    f"InstaLing: {nickname} - sesja ukonczona ({correct}/{total})",
                    (
                        f"Uczen: {nickname}\n"
                        f"Plan: {scheduled_time} | Wykonano: {started_pl[11:16]} - {completed_pl[11:16]}\n"
                        f"Czas: {dur_nice}\n"
                        f"Wynik: {correct}/{total} ({acc:.1f}%)\n"
                        f"Nowe slowka: {new_words_count}"
                    ),
                    priority="default",
                    tags="white_check_mark,mortarboard"
                )

    # =========================================================================
    # 2. KANAŁ #logi-bota — Rozbudowane, czytelne logi z logowania i sesji
    # =========================================================================
    def _send_discord_logs(
        self,
        webhook_url: str,
        nickname: str,
        masked: str,
        log_lines: List[str],
        success: bool = True
    ) -> None:
        """
        Wysyła super-rozbudowane, mądrze podzielone logi operacyjne:
        Faza 1: Inicjalizacja i logowanie krok po kroku
        Faza 2: Rozwiązywanie słówek (każde pytanie, odpowiedź, status)
        Faza 3: Zakończenie i bezpieczne wylogowanie
        """
        try:
            # Rozdzielamy linie logów na fazy
            phase_login: List[str] = []
            phase_words: List[str] = []
            phase_exit: List[str] = []

            for line in log_lines:
                clean_l = line.strip()
                if any(k in clean_l for k in ["[START]", "[KONFIGURACJA]", "[PRZEGLĄDARKA]", "[FILTR]", "[NAWIGACJA]", "[SERWER]", "[LOGOWANIE]", "[AUTORYZACJA]", "[PANEL]", "[SESJA]"]):
                    phase_login.append(clean_l)
                elif any(k in clean_l for k in ["[POPRAWNIE", "[NOWE SŁÓWKO", "[ZAPISANO]", "[AUTOKOREKTA", "[CELOWY BŁĄD", "[BŁĄD"]):
                    phase_words.append(clean_l)
                elif any(k in clean_l for k in ["[POWRÓT]", "[WYLOGOWANIE]", "[STATYSTYKA KOŃCOWA]", "[NOWE SŁÓWKA]", "[CZAS SESJI]", "Ukończono"]):
                    phase_exit.append(clean_l)
                else:
                    if not phase_words:
                        phase_login.append(clean_l)
                    else:
                        phase_exit.append(clean_l)

            # Formatowanie bloków kodu
            login_txt = "\n".join(phase_login) if phase_login else "Zalogowano pomyślnie."
            if len(login_txt) > 1000:
                login_txt = login_txt[:980] + "\n..."

            # Jeśli pytań jest dużo, mądrze pokazujemy wszystkie z zachowaniem limitu 1000 znaków
            if phase_words:
                words_txt = "\n".join(phase_words)
                if len(words_txt) > 1000:
                    words_txt = "\n".join(phase_words[:12]) + f"\n... [{len(phase_words) - 16} pytań] ...\n" + "\n".join(phase_words[-4:])
            else:
                words_txt = "Brak zarejestrowanych zdarzeń słówkowych."

            exit_txt = "\n".join(phase_exit) if phase_exit else "Wylogowano bezpiecznie."
            if len(exit_txt) > 800:
                exit_txt = exit_txt[:780] + "\n..."

            color = 0x2ECC71 if success else 0xE74C3C

            fields = [
                {
                    "name": "🔑 1. Przebieg Logowania i Weryfikacja Sesji",
                    "value": f"```text\n{login_txt}\n```",
                    "inline": False
                },
                {
                    "name": f"📚 2. Przebieg Rozwiązywania Zadań ({len(phase_words)} zdarzeń)",
                    "value": f"```text\n{words_txt}\n```",
                    "inline": False
                },
                {
                    "name": "🚪 3. Powrót do Pulpitu i Bezpieczne Wylogowanie",
                    "value": f"```text\n{exit_txt}\n```",
                    "inline": False
                }
            ]

            self._send_discord_embed(
                webhook_url=webhook_url,
                title=f"📋 Dziennik Operacji Konsoli — {nickname} ({masked})",
                description=f"Szczegółowy zapis procesu automatyzacji od uruchomienia przeglądarki do zamknięcia sesji.",
                color=color,
                fields=fields,
                footer_text="InstaLing Bot • Zaawansowana Telemetria"
            )
        except Exception as e:
            log(f"[!] Błąd wysyłania rozbudowanych logów na Discord: {e}")

    # =========================================================================
    # 3. KANAŁ #plan-na-dzis — Przejrzysty harmonogram dnia (styl ze zrzutów)
    # =========================================================================
    def send_daily_plan(self, plan_entries: List[Dict[str, Any]], day_name: str = "", date_str: str = "") -> None:
        """Wysyła harmonogram na dziś identyczny wizualnie ze zrzutem ekranu użytkownika."""
        wh = self._get_webhook("webhook_plan_na_dzis")
        if not wh:
            return

        if not date_str:
            date_str = today_warsaw().isoformat()

        from storage import Storage
        history_list = Storage().history

        sorted_entries = sorted(
            plan_entries,
            key=lambda x: (1 if x.get("is_off_day") else 0, x.get("scheduled_minutes", 9999))
        )

        completed_count = 0
        total_active = 0
        student_lines = []

        for p in sorted_entries:
            nick = p.get("nickname", "Uczeń")
            mask = mask_login(p.get("login", ""))
            time_str = p.get("scheduled_time", "--:--")
            is_off = p.get("is_off_day", False)
            completed = p.get("completed", False)
            completed_at = p.get("completed_at")
            started_at = p.get("started_at")
            dur_s = p.get("duration_seconds")
            w_cor = p.get("words_correct")
            w_tot = p.get("words_total")
            acc = p.get("accuracy_percent")
            new_w = p.get("new_words_count")

            if is_off:
                student_lines.append(f"🏖️ **{nick}** (`{mask}`) ➔ *Dzień wolny*")
            elif completed:
                completed_count += 1
                total_active += 1
                end_hm = completed_at[11:16] if completed_at and len(completed_at) >= 16 else time_str
                hist_info = lookup_history_details(nick, completed_at, history_list)
                if new_w is None:
                    new_w = hist_info["new_words"]

                info_parts = [f"Ukończono o {end_hm}"]
                if dur_s:
                    info_parts.append(f"trwało {dur_s/60:.1f} min")
                if w_cor is not None and w_tot is not None and acc is not None:
                    info_parts.append(f"Wynik: **{w_cor}/{w_tot}** ({acc:.1f}%)")
                if new_w:
                    info_parts.append(f"Nowe: **{new_w}**")

                details_str = " • ".join(info_parts)
                student_lines.append(f"✅ **{nick}** (`{mask}`) ➔ **{time_str}** *({details_str})*")
            elif p.get("status") == "W trakcie":
                total_active += 1
                student_lines.append(f"▶️ **{nick}** (`{mask}`) ➔ **{time_str}** *(Sesja aktualnie w toku!)*")
            elif p.get("status") == "Błąd":
                total_active += 1
                student_lines.append(f"⚠️ **{nick}** (`{mask}`) ➔ **{time_str}** *(Wystąpił błąd — oczekuje na ponowienie)*")
            else:
                total_active += 1
                student_lines.append(f"⏳ **{nick}** (`{mask}`) ➔ **{time_str}** *(Oczekuje na swoją godzinę)*")

        desc = (
            f"**Data:** `{date_str}` ({day_name})\n"
            f"**Postęp sesji:** `{completed_count}/{total_active}` ukończonych dzisiaj\n\n"
            + "\n".join(student_lines)
            + "\n\n💡 *Każdy uczeń ma własny przedział czasowy z zachowaniem min. 45 min odstępu bez kolizji.*"
        )

        color = 0x9B59B6 if completed_count < total_active else 0x2ECC71

        self._send_discord_embed(
            webhook_url=wh,
            title="📅 Harmonogram Sesji Na Dziś (Europe/Warsaw)",
            description=desc,
            color=color,
            footer_text="InstaLing Auto-Bot • Europe/Warsaw • 100% Anty-Detekcja"
        )

    # =========================================================================
    # 4. KANAŁ #plan-tygodnia — Trwały plan tygodnia (styl ze zrzutu)
    # =========================================================================
    def send_weekly_plan(self, weekly_data: Dict[str, Any], week_key: str = "") -> None:
        """Wysyła oficjalny plan tygodnia identyczny wizualnie ze zrzutem ekranu użytkownika."""
        wh = self._get_webhook("webhook_plan_tygodnia")
        if not wh:
            return

        from storage import Storage
        history_list = Storage().history

        today_weekday = today_warsaw().weekday()
        fields = []

        for idx, (day_name, entries) in enumerate(weekly_data.items()):
            is_today = (idx == today_weekday)
            field_title = f"📅 {day_name} (DZISIAJ):" if is_today else f"📅 {day_name}:"

            sorted_day = sorted(
                entries,
                key=lambda x: (1 if x.get("is_off") else 0, x.get("time", "99:99"))
            )

            lines = []
            for e in sorted_day:
                nick = e.get("nickname", "Uczeń")
                t = e.get("time", "--:--")
                is_off = e.get("is_off", False)
                comp = e.get("completed", False)
                comp_at = e.get("completed_at")
                dur_s = e.get("duration_seconds")
                w_cor = e.get("words_correct")
                w_tot = e.get("words_total")
                new_w = e.get("new_words_count")

                if is_off:
                    lines.append(f"• {nick}: 🏖️ *Wolne*")
                elif comp:
                    end_hm = comp_at[11:16] if comp_at and len(comp_at) >= 16 else t
                    hist_info = lookup_history_details(nick, comp_at, history_list)
                    if new_w is None:
                        new_w = hist_info["new_words"]

                    extra = [f"Ukończono {end_hm}"]
                    if dur_s:
                        extra.append(f"{dur_s/60:.1f}m")
                    if w_cor is not None and w_tot is not None:
                        extra.append(f"{w_cor}/{w_tot}")
                    if new_w:
                        extra.append(f"nowe: {new_w}")

                    lines.append(f"• {nick}: ✅ `{t}` *({', '.join(extra)})*")
                else:
                    lines.append(f"• {nick}: ⏳ `{t}`")

            fields.append({
                "name": field_title,
                "value": "\n".join(lines) if lines else "Brak wpisów",
                "inline": False
            })

        desc = (
            f"**Tydzień ISO:** `{week_key}` | **Strefa:** `Europe/Warsaw`\n"
            f"*Harmonogram jest wylosowany na cały tydzień i nie ulega zmianie w trakcie tygodnia.*"
        )

        self._send_discord_embed(
            webhook_url=wh,
            title="🗓️ Oficjalny Plan Tygodnia InstaLing",
            description=desc,
            color=0x1ABC9C,
            fields=fields,
            footer_text="InstaLing Auto-Bot • Europe/Warsaw • 100% Anty-Detekcja"
        )

    # =========================================================================
    # 5. KANAŁ #statystyki — Karty statystyk uczniów (styl ze zrzutu)
    # =========================================================================
    def send_bot_global_statistics(
        self,
        storage=None,
        users_mgr=None,
        latest_user: Optional[str] = None,
        latest_acc: Optional[float] = None,
        latest_score: Optional[str] = None
    ) -> None:
        """Wysyła czytelne karty podsumowania każdego ucznia identyczne ze zrzutem ze strony głównej."""
        stats_wh = self._get_webhook("webhook_statystyki")
        if not stats_wh:
            return

        from storage import Storage
        from users_manager import UsersManager
        storage = storage or Storage()
        users_mgr = users_mgr or UsersManager()

        history = storage.history
        words = storage.words
        active_users = users_mgr.get_active_users()

        fields = []
        for u in active_users:
            nick = u.get("nickname", "Uczeń")
            mask = mask_login(u.get("login", ""))
            u_hist = [h for h in history if h.get("nickname") == nick or h.get("masked_login") == mask]
            u_count = len(u_hist)
            u_tot_words = sum(h.get("words_total", 0) for h in u_hist)
            u_cor_words = sum(h.get("words_correct", 0) for h in u_hist)
            u_acc = round(sum(h.get("accuracy_percent", 0) for h in u_hist) / u_count, 1) if u_count > 0 else 0.0

            u_new = 0
            for h in u_hist:
                if "new_words_count" in h and h["new_words_count"] is not None:
                    u_new += int(h["new_words_count"])
                else:
                    u_new += len({
                        w.get("prompt", "").strip()
                        for w in h.get("words_details", [])
                        if w.get("status") == "nowe" and w.get("prompt", "").strip()
                    })

            val = (
                f"• Liczba ukończonych sesji: **{u_count}**\n"
                f"• Średnia skuteczność: **{u_acc}%**\n"
                f"• Rozwiązane słówka: **{u_cor_words}/{u_tot_words}**\n"
                f"• Poznane nowe słówka: **{u_new}**\n"
                f"• Status profilu: **Aktywny**"
            )
            fields.append({
                "name": f"📊 Podsumowanie Ucznia: {nick} (`{mask}`)",
                "value": val,
                "inline": False
            })

        fields.append({
            "name": "📚 Słownik Bota",
            "value": f"• Baza zapamiętanych słówek: **{len(words)} słówek**\n• Wszystkie ukończone sesje: **{len(history)}**",
            "inline": False
        })

        title = f"📈 Statystyki Kont Uczniów"
        if latest_user and latest_score:
            title = f"📈 Statystyki: Ostatnia sesja {latest_user} ({latest_score})"

        self._send_discord_embed(
            webhook_url=stats_wh,
            title=title,
            description="Aktualne zestawienie postępów i skuteczności poszczególnych kont.",
            color=0x3498DB,
            fields=fields,
            footer_text="InstaLing Multi-User Manager • Ciemny Styl"
        )

    # =========================================================================
    # 6. NOWY KANAŁ #testy — Raporty testowe i weryfikacja systemu
    # =========================================================================
    def send_test_report(self, passed: int, total: int, details: List[str]) -> None:
        """Wysyła szczegółowy raport testów jednostkowych i diagnostyki na dedykowany kanał #testy."""
        testy_wh = self._get_webhook("webhook_testy")
        if not testy_wh:
            return

        all_ok = (passed == total)
        color = 0x2ECC71 if all_ok else 0xE74C3C
        title = "🧪 [TESTY AUTOMATYCZNE] Weryfikacja Systemu InstaLing Auto-Bot"

        desc = (
            f"**Wynik testów:** `{passed}/{total}` zaliczonych pomyślnie\n"
            f"**Status bota:** {'✅ W 100% gotowy do niezawodnego działania' if all_ok else '⚠️ Wykryto ostrzeżenia w konfiguracji'}\n"
            f"**Strefa czasowa:** `Europe/Warsaw` ({now_warsaw().strftime('%Y-%m-%d %H:%M:%S %Z')})\n\n"
            f"**Szczegóły wykonanych testów:**\n"
            + "\n".join(details)
        )

        self._send_discord_embed(
            webhook_url=testy_wh,
            title=title,
            description=desc,
            color=color,
            footer_text="InstaLing Auto-Bot • Diagnostyka Systemu #testy"
        )

    def send_morning_ntfy(self, topic: str, date_str: str, day_name: str, slots_summary: List[str]) -> None:
        title = f"InstaLing — Plan na dzis ({day_name})"
        msg = f"Plan sesji na dzis ({format_date_pl(date_str)}):\n\n" + "\n".join(slots_summary)
        self._send_ntfy(topic, title, msg, priority="default", tags="calendar")

    def _send_discord_embed(
        self,
        webhook_url: str,
        title: str,
        description: str,
        color: int,
        fields: Optional[List[Dict[str, Any]]] = None,
        content: Optional[str] = None,
        footer_text: str = "InstaLing Auto-Bot • Europe/Warsaw • 100% Anty-Detekcja"
    ) -> None:
        try:
            embed_obj = {
                "title": title,
                "description": description,
                "color": color,
                "footer": {
                    "text": footer_text
                },
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            if fields:
                embed_obj["fields"] = fields

            payload = {"embeds": [embed_obj]}
            if content:
                payload["content"] = content

            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                webhook_url,
                data=data,
                headers={"Content-Type": "application/json", "User-Agent": "InstaLingBot/2.0"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                log(f"[Powiadomienie] Wysłano '{title}' na Discord")
        except Exception as e:
            log(f"[!] Błąd wysyłania powiadomienia Discord: {e}")

    def _send_ntfy(self, topic: str, title: str, message: str, priority: str = "default", tags: str = "robot") -> None:
        try:
            url = f"https://ntfy.sh/{urllib.parse.quote(topic)}"
            req = urllib.request.Request(
                url,
                data=message.encode("utf-8"),
                headers={
                    "Title": title.encode("ascii", "replace").decode("ascii"),
                    "Priority": priority,
                    "Tags": tags,
                    "Click": "https://instaling.pl"
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                log(f"[Powiadomienie] Wysłano ntfy.sh do '{topic}'")
        except Exception as e:
            log(f"[!] Błąd wysyłania ntfy: {e}")
