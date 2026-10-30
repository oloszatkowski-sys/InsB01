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
    """Zamienia sekundy na czytelny czas po polsku, np. '5 min 15 sek'."""
    if seconds is None:
        return "brak danych"
    total_sec = max(1, int(round(float(seconds))))
    mins = total_sec // 60
    secs = total_sec % 60
    if mins > 0 and secs > 0:
        return f"{mins} min {secs} sek"
    elif mins > 0:
        return f"{mins} min"
    return f"{secs} sek"


def format_short_datetime_pl(dt_str: Optional[str]) -> str:
    """Zamienia pełną datę '2026-10-29 21:12:16 CET' na czytelne '29.10 o godz. 21:12'."""
    if not dt_str or dt_str == "Brak":
        return "jeszcze nie wykonano"
    try:
        date_part = dt_str[:10].split("-")
        time_part = dt_str[11:16]
        if len(date_part) == 3 and time_part:
            return f"{date_part[2]}.{date_part[1]} o godz. {time_part}"
    except Exception:
        pass
    return str(dt_str)[:16]


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

    def send_session_start(self, user: Dict[str, Any], scheduled_time: str, started_pl: str) -> None:
        """Wysyła jasne, uporządkowane po kolei powiadomienie o ROZPOCZĘCIU sesji na kanał #sekcja."""
        sekcja_wh = self._get_webhook("webhook_sekcja")
        if not sekcja_wh:
            return

        nickname = user.get("nickname", "Uczeń")
        start_hms = started_pl[11:19] if started_pl and len(started_pl) >= 19 else scheduled_time

        desc = (
            f"👤 **Uczeń:** **{nickname}**\n"
            f"⏰ **Miało być wykonane o:** **`{scheduled_time}`**\n"
            f"▶️ **Rozpoczęto o godzinie:** **`{start_hms}`**\n"
            f"⏳ **Status:** Bot zalogował się na konto i teraz rozwiązuje słówka..."
        )

        self._send_discord_embed(
            webhook_url=sekcja_wh,
            title=f"▶️ Rozpoczęto sesję — {nickname}",
            description=desc,
            color=0x3498DB
        )

    def send_session_summary(self, result: Dict[str, Any], user: Dict[str, Any], session_logs: Optional[List[str]] = None) -> None:
        """Wysyła pełne, uporządkowane po kolei podsumowanie sesji na kanał #sekcja, #logi-bota, #statystyki i ntfy."""
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

        start_hms = started_pl[11:19] if started_pl and len(started_pl) >= 19 else "--:--:--"
        end_hms = completed_pl[11:19] if completed_pl and len(completed_pl) >= 19 else "--:--:--"
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
            title = f"✅ Sesja wykonana — {nickname}"
            color = 0x2ECC71
            desc = (
                f"👤 **Uczeń:** **{nickname}**\n"
                f"⏰ **Miało być wykonane o:** **`{scheduled_time}`**\n"
                f"▶️ **Rozpoczęto o godzinie:** **`{start_hms}`**\n"
                f"🏁 **Wykonano (zakończono) o:** **`{end_hms}`**\n"
                f"⏱️ **Czas trwania sesji:** **{dur_nice}**\n\n"
                f"🎯 **Wynik z pytań:** **{correct} poprawnych na {total} pytań** (**{acc:.0f}%**)\n"
                f"❌ **Pomyłki w trakcie sesji:** **{mistakes}**\n"
                f"🆕 **Nowe słówka poznane dzisiaj:** **{new_words_count}**\n"
                f"🔄 **Poprawione słówka (autokorekta):** **{autocorrect_count}**"
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
                for idx, item in enumerate(items_list[:20], start=1):
                    prompt = item["prompt"]
                    ans = item["answer"]
                    st = item["status"]
                    if st == "nowe":
                        w_lines.append(f"`{idx:02d}.` {prompt} ➔ **{ans}** — 🆕 *nowe słówko*")
                    elif st == "autokorekta":
                        w_lines.append(f"`{idx:02d}.` {prompt} ➔ **{ans}** — 🔄 *poprawione*")
                    elif st == "celowy_blad":
                        w_lines.append(f"`{idx:02d}.` {prompt} ➔ **{ans}** — ❌ *drobny błąd*")
                    else:
                        w_lines.append(f"`{idx:02d}.` {prompt} ➔ **{ans}** — ✅ *poprawnie*")

                if len(items_list) > 20:
                    w_lines.append(f"*...oraz {len(items_list) - 20} innych słówek*")

                fields.append({
                    "name": f"📚 Słówka z tej sesji po kolei ({len(items_list)}):",
                    "value": "\n".join(w_lines),
                    "inline": False
                })
        else:
            title = f"⚠️ Problem z sesją — {nickname}"
            color = 0xE74C3C
            err = result.get("error", "Nieznany błąd")
            desc = (
                f"👤 **Uczeń:** **{nickname}**\n"
                f"⏰ **Miało być wykonane o:** **`{scheduled_time}`**\n"
                f"🕒 **Czas próby:** **`{end_hms}`**\n"
                f"🔄 **Status:** Nie udało się dokończyć sesji — bot spróbuje ponownie.\n"
                f"❌ **Powód:** `{err[:200]}`"
            )
            fields = []

        if sekcja_wh:
            self._send_discord_embed(
                webhook_url=sekcja_wh,
                title=title,
                description=desc,
                color=color,
                fields=fields,
                content=ping_role if ping_role else None
            )

        # #logi-bota
        logs_wh = self._get_webhook("webhook_logi_bota") or self.config.get("discord_logs_webhook_url", "").strip()
        if logs_wh and session_logs:
            self._send_discord_logs(logs_wh, nickname, masked, session_logs)

        # #statystyki
        stats_wh = self._get_webhook("webhook_statystyki")
        if stats_wh and stats_wh != sekcja_wh and success:
            try:
                self.send_bot_global_statistics(latest_user=nickname, latest_acc=acc, latest_score=f"{correct}/{total}")
            except Exception as e:
                log(f"[!] Błąd wysyłania statystyk: {e}")

        # ntfy.sh
        if user.get("track_in_ntfy", False):
            ntfy_topic = self.config.get("ntfy_topic", "").strip() or f"instaling_{user.get('login', 'user').strip()}"
            if success:
                self._send_ntfy(
                    ntfy_topic,
                    f"InstaLing: {nickname} zrobione! ({correct}/{total})",
                    (
                        f"Uczen: {nickname}\n"
                        f"Mialo byc o: {scheduled_time}\n"
                        f"Wykonano: {start_hms[:5]} - {end_hms[:5]} ({dur_nice})\n"
                        f"Wynik: {correct}/{total} ({acc:.0f}%)\n"
                        f"Nowe slowka: {new_words_count}"
                    ),
                    priority="default",
                    tags="white_check_mark,mortarboard"
                )

    def send_morning_ntfy(self, topic: str, date_str: str, day_name: str, slots_summary: List[str]) -> None:
        title = f"InstaLing — Plan na dzis ({day_name})"
        msg = f"Plan sesji na dzis ({format_date_pl(date_str)}):\n\n" + "\n".join(slots_summary)
        self._send_ntfy(topic, title, msg, priority="default", tags="calendar")

    def send_daily_plan(self, plan_entries: List[Dict[str, Any]], day_name: str = "", date_str: str = "") -> None:
        """Wysyła przejrzysty plan na dziś (po kolei osoba pod osobą ze wszystkimi informacjami) na #plan-na-dzis."""
        wh = self._get_webhook("webhook_plan_na_dzis")
        if not wh:
            return

        if not date_str:
            date_str = today_warsaw().isoformat()
        nice_date = format_date_pl(date_str)

        from storage import Storage
        history_list = Storage().history

        sorted_entries = sorted(
            plan_entries,
            key=lambda x: (1 if x.get("is_off_day") else 0, x.get("scheduled_minutes", 9999))
        )

        fields = []
        completed_count = 0
        total_active = 0

        for idx, p in enumerate(sorted_entries, start=1):
            nick = p.get("nickname", "Uczeń")
            time_str = p.get("scheduled_time", "--:--")
            is_off = p.get("is_off_day", False)
            completed = p.get("completed", False)
            started_at = p.get("started_at")
            completed_at = p.get("completed_at")
            dur_s = p.get("duration_seconds")
            w_cor = p.get("words_correct")
            w_tot = p.get("words_total")
            acc = p.get("accuracy_percent")
            new_w = p.get("new_words_count")

            if is_off:
                fields.append({
                    "name": f"🏖️ {idx}. {nick} — DZIEŃ WOLNY",
                    "value": "• **Status:** Dzisiaj ma dzień wolny (brak zaplanowanej sesji)",
                    "inline": False
                })
            elif completed:
                completed_count += 1
                total_active += 1
                start_hm = started_at[11:19] if started_at and len(started_at) >= 19 else time_str
                end_hm = completed_at[11:19] if completed_at and len(completed_at) >= 19 else time_str
                dur_nice = format_duration_pl(dur_s)

                hist_info = lookup_history_details(nick, completed_at, history_list)
                if new_w is None:
                    new_w = hist_info["new_words"]

                score_line = f"**{w_cor} poprawnych na {w_tot} pytań** (**{acc:.0f}%**)" if w_cor is not None and w_tot is not None and acc is not None else "Wykonano"
                val = (
                    f"• ⏰ **Miało być wykonane o:** **`{time_str}`**\n"
                    f"• 🏁 **Wykonano w godzinach:** **`{start_hm}` ➔ `{end_hm}`**\n"
                    f"• ⏱️ **Czas trwania nauki:** **{dur_nice}**\n"
                    f"• 🎯 **Wynik:** {score_line}\n"
                    f"• 🆕 **Nowe słówka poznane na sesji:** **{new_w}**"
                )
                fields.append({
                    "name": f"✅ {idx}. {nick} — WYKONANO",
                    "value": val,
                    "inline": False
                })
            elif p.get("status") == "W trakcie":
                total_active += 1
                start_hm = started_at[11:19] if started_at and len(started_at) >= 19 else time_str
                val = (
                    f"• ⏰ **Miało być wykonane o:** **`{time_str}`**\n"
                    f"• ▶️ **Rozpoczęto o godzinie:** **`{start_hm}`**\n"
                    f"• ⏳ **Status:** Bot właśnie rozwiązuje słówka..."
                )
                fields.append({
                    "name": f"▶️ {idx}. {nick} — TERAZ W TRAKCIE",
                    "value": val,
                    "inline": False
                })
            elif p.get("status") == "Błąd":
                total_active += 1
                val = (
                    f"• ⏰ **Miało być wykonane o:** **`{time_str}`**\n"
                    f"• ⚠️ **Status:** Wystąpił problem — bot spróbuje ponownie w kolejnym cyklu"
                )
                fields.append({
                    "name": f"⚠️ {idx}. {nick} — DO PONOWIENIA",
                    "value": val,
                    "inline": False
                })
            else:
                total_active += 1
                unix_ts = to_discord_unix(date_str, time_str)
                live_timer = f" (<t:{unix_ts}:R>)" if unix_ts else ""
                val = (
                    f"• ⏰ **Zaplanowana godzina wykonania:** **`{time_str}`**{live_timer}\n"
                    f"• 📌 **Status:** Oczekuje w kolejce — zegar bota odpali sesję punktualnie o **`{time_str}`**"
                )
                fields.append({
                    "name": f"⏳ {idx}. {nick} — OCZEKUJE NA WYKONANIE",
                    "value": val,
                    "inline": False
                })

        all_done = (completed_count == total_active and total_active > 0)
        color = 0x2ECC71 if all_done else 0x5865F2

        desc = (
            f"📅 **Dzień:** **{day_name}** ({nice_date})\n"
            f"📊 **Postęp dzisiejszego dnia:** wykonano **{completed_count} z {total_active}** zaplanowanych sesji.\n"
            f"Poniżej dokładne informacje po kolei dla każdego ucznia:"
        )

        self._send_discord_embed(
            webhook_url=wh,
            title=f"📅 Plan na dziś — {day_name} ({nice_date})",
            description=desc,
            color=color,
            fields=fields
        )

    def send_weekly_plan(self, weekly_data: Dict[str, Any], week_key: str = "") -> None:
        """Wysyła dokładny plan całego tygodnia dzień po dniu (po kolei, pełna szerokość) na kanał #plan-tygodnia."""
        wh = self._get_webhook("webhook_plan_tygodnia")
        if not wh:
            return

        from storage import Storage
        history_list = Storage().history

        today_weekday = today_warsaw().weekday()
        fields = []

        for idx, (day_name, entries) in enumerate(weekly_data.items()):
            day_date = entries[0].get("date", "") if entries else ""
            nice_date = f" ({format_date_pl(day_date)})" if day_date else ""
            field_title = f"👉 {day_name}{nice_date} — DZISIAJ" if idx == today_weekday else f"🗓️ {day_name}{nice_date}"

            # Sortujemy chronologicznie w danym dniu
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
                started_at = e.get("started_at")
                comp_at = e.get("completed_at")
                dur_s = e.get("duration_seconds")
                w_cor = e.get("words_correct")
                w_tot = e.get("words_total")
                acc = e.get("accuracy_percent")
                new_w = e.get("new_words_count")

                if is_off:
                    lines.append(f"🏖️ **{nick}** — *dzień wolny*")
                elif comp:
                    start_hm = started_at[11:16] if started_at and len(started_at) >= 16 else t
                    end_hm = comp_at[11:16] if comp_at and len(comp_at) >= 16 else t
                    dur_nice = format_duration_pl(dur_s)
                    hist_info = lookup_history_details(nick, comp_at, history_list)
                    if new_w is None:
                        new_w = hist_info["new_words"]

                    score_part = f"**{w_cor}/{w_tot}** ({acc:.0f}%)" if w_cor is not None and w_tot is not None and acc is not None else "zrobione"
                    lines.append(
                        f"✅ **{nick}** — miało być: **`{t}`** ➔ wykonano: **`{start_hm}–{end_hm}`** "
                        f"• czas: **{dur_nice}** • wynik: {score_part} • nowe słówka: **{new_w}**"
                    )
                else:
                    lines.append(
                        f"⏳ **{nick}** — zaplanowano na godz.: **`{t}`** *(oczekuje na wykonanie)*"
                    )

            fields.append({
                "name": field_title,
                "value": "\n".join(lines) if lines else "Brak wpisów",
                "inline": False
            })

        desc = (
            "Pełna rozpiska na cały tydzień po kolei od Poniedziałku do Niedzieli.\n"
            "Przy każdej osobie widać o której miało być wykonane, o której wykonano, czas nauki, wynik i nowe słówka:"
        )

        self._send_discord_embed(
            webhook_url=wh,
            title="🗓️ Plan całego tygodnia (Poniedziałek – Niedziela)",
            description=desc,
            color=0x1ABC9C,
            fields=fields
        )

    def send_bot_global_statistics(
        self,
        storage=None,
        users_mgr=None,
        latest_user: Optional[str] = None,
        latest_acc: Optional[float] = None,
        latest_score: Optional[str] = None
    ) -> None:
        """Wysyła uporządkowane po kolei statystyki każdego ucznia i bazy słówek na kanał #statystyki."""
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

        successful_sessions = sum(1 for h in history if h.get("success", False))
        fields = []

        for idx, u in enumerate(active_users, start=1):
            nick = u.get("nickname", "Uczeń")
            mask = mask_login(u.get("login", ""))
            u_hist = [h for h in history if h.get("nickname") == nick or h.get("masked_login") == mask]
            u_count = len(u_hist)
            u_tot_words = sum(h.get("words_total", 0) for h in u_hist)
            u_cor_words = sum(h.get("words_correct", 0) for h in u_hist)
            u_acc = round(sum(h.get("accuracy_percent", 0) for h in u_hist) / u_count) if u_count > 0 else 0
            u_dur_s = sum(h.get("duration_seconds", 0) for h in u_hist)
            u_dur_min = round(u_dur_s / 60)

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

            last_raw = u_hist[-1].get("completed_at_warsaw", "Brak") if u_hist else "Brak"
            last_nice = format_short_datetime_pl(last_raw)

            val = (
                f"• ✅ **Wykonane sesje:** **{u_count}**\n"
                f"• 🎯 **Rozwiązane pytania łącznie:** **{u_cor_words}** poprawnych na **{u_tot_words}** (**{u_acc}%**)\n"
                f"• 🆕 **Poznane nowe słówka:** **{u_new}**\n"
                f"• ⏱️ **Łączny czas nauki:** **{u_dur_min} min**\n"
                f"• 🕒 **Ostatnio wykonana sesja:** **{last_nice}**"
            )
            fields.append({
                "name": f"👤 {idx}. {nick}",
                "value": val,
                "inline": False
            })

        fields.append({
            "name": "📚 Baza słówek i podsumowanie ogólne",
            "value": (
                f"• **Wszystkie zapamiętane słówka w bazie bota:** **{len(words)} słówek**\n"
                f"• **Wszystkie ukończone sesje (wszystkie konta):** **{successful_sessions}**"
            ),
            "inline": False
        })

        desc = "Szczegółowe statystyki każdego ucznia po kolei:"
        if latest_user and latest_score:
            desc = (
                f"🆕 **Ostatnio wykonana sesja:** **{latest_user}** — wynik **{latest_score}** (**{latest_acc:.0f}%**)\n"
                f"Poniżej znajdują się szczegółowe statystyki każdego ucznia po kolei:"
            )

        self._send_discord_embed(
            webhook_url=stats_wh,
            title="📊 Statystyki wszystkich kont (po kolei)",
            description=desc,
            color=0x2980B9,
            fields=fields
        )

    def _send_discord_embed(
        self,
        webhook_url: str,
        title: str,
        description: str,
        color: int,
        fields: Optional[List[Dict[str, Any]]] = None,
        content: Optional[str] = None
    ) -> None:
        try:
            embed_obj = {
                "title": title,
                "description": description,
                "color": color,
                "footer": {
                    "text": "InstaLing Bot • Wysłano z GitHub Actions"
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

    def _send_discord_logs(self, webhook_url: str, nickname: str, masked: str, log_lines: List[str]) -> None:
        try:
            recent = log_lines[-20:] if len(log_lines) > 20 else log_lines
            log_text = "\n".join(recent)
            if len(log_text) > 1500:
                log_text = "...\n" + log_text[-1500:]

            self._send_discord_embed(
                webhook_url=webhook_url,
                title=f"📋 Przebieg sesji po kolei — {nickname}",
                description=f"```text\n{log_text}\n```",
                color=0x34495E
            )
        except Exception as e:
            log(f"[!] Błąd wysyłania logów na Discord: {e}")

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
