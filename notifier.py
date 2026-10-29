import urllib.request
import urllib.parse
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from logger import log
from users_manager import mask_login
from timezone_utils import WARSAW_TZ, now_warsaw, today_warsaw


def make_progress_bar(pct: float, length: int = 10) -> str:
    """Generuje prosty pasek postępu."""
    pct = max(0.0, min(100.0, float(pct)))
    filled = int(round(length * (pct / 100.0)))
    filled = max(0, min(length, filled))
    bar = "▓" * filled + "░" * (length - filled)
    return f"`{bar}` **{pct:.0f}%**"


def to_discord_unix(date_str: str, time_str: str) -> Optional[int]:
    """Konwertuje datę (YYYY-MM-DD) i godzinę (HH:MM) w strefie Europe/Warsaw na znacznik UNIX dla Discorda."""
    try:
        clean_time = time_str.strip()[:5]
        dt = datetime.strptime(f"{date_str} {clean_time}", "%Y-%m-%d %H:%M").replace(tzinfo=WARSAW_TZ)
        return int(dt.timestamp())
    except Exception:
        return None


def format_date_pl(date_str: str) -> str:
    """Zamienia datę RRRR-MM-DD na czytelny format DD.MM.RRRR (np. 29.10.2026)."""
    try:
        parts = date_str.strip()[:10].split("-")
        if len(parts) == 3:
            return f"{parts[2]}.{parts[1]}.{parts[0]}"
    except Exception:
        pass
    return date_str


def format_short_datetime_pl(dt_str: str) -> str:
    """Zamienia pełną datę '2026-10-29 16:56:41 CET' na czytelne '29.10 o godz. 16:56'."""
    if not dt_str or dt_str == "Brak":
        return "jeszcze nie robiono"
    try:
        date_part = dt_str[:10].split("-")
        time_part = dt_str[11:16]
        if len(date_part) == 3 and time_part:
            return f"{date_part[2]}.{date_part[1]} o godz. {time_part}"
    except Exception:
        pass
    return dt_str[:16]


class Notifier:
    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def _get_webhook(self, key: str) -> Optional[str]:
        """Pobiera dedykowany webhook dla danego kanału lub fallback do głównego discord_webhook_url."""
        url = self.config.get(key, "").strip()
        if not url:
            url = self.config.get("discord_webhook_url", "").strip()
        return url if url else None

    def send_session_start(self, user: Dict[str, Any], scheduled_time: str, started_pl: str) -> None:
        """Wysyła proste, bardzo czytelne powiadomienie o ROZPOCZĘCIU sesji na kanał #sekcja (bez pingu)."""
        sekcja_wh = self._get_webhook("webhook_sekcja")
        if not sekcja_wh:
            return

        nickname = user.get("nickname", "Uczeń")
        start_hour = started_pl[11:16] if started_pl and len(started_pl) >= 16 else scheduled_time

        title = f"▶️ Start: {nickname} zaczyna robić InstaLing!"
        color = 0x3498DB  # Błękitny
        desc = (
            f"Bot właśnie zalogował się na konto **{nickname}** i rozwiązuje dzisiejsze słówka.\n\n"
            f"⏰ **Godzina z planu:** **{scheduled_time}**\n"
            f"🕒 **Rozpoczęto o:** **{start_hour}**"
        )

        self._send_discord_embed(
            webhook_url=sekcja_wh,
            title=title,
            description=desc,
            color=color,
            fields=None,
            content=None
        )

    def send_session_summary(self, result: Dict[str, Any], user: Dict[str, Any], session_logs: Optional[List[str]] = None) -> None:
        """Wysyła bardzo proste i przejrzyste podsumowanie ukończonej sesji na Discord i ntfy.sh."""
        success = result.get("success", False)
        total = result.get("words_total", 0)
        correct = result.get("words_correct", 0)
        mistakes = result.get("words_mistakes", 0)
        acc = result.get("accuracy_percent", 0.0)
        duration_s = result.get("duration_seconds", 0)

        nickname = user.get("nickname", "Uczeń")
        masked = mask_login(user.get("login", ""))
        started_pl = result.get("started_at_warsaw", "N/A")
        completed_pl = result.get("completed_at_warsaw", "N/A")
        start_h = started_pl[11:16] if started_pl and len(started_pl) >= 16 else "--:--"
        end_h = completed_pl[11:16] if completed_pl and len(completed_pl) >= 16 else "--:--"
        minutes_taken = max(1, round(duration_s / 60))

        # 1. KANAŁ #sekcja — Główne, super czytelne podsumowanie sesji
        sekcja_wh = self._get_webhook("webhook_sekcja")
        ping_role = self.config.get("discord_ping", "@everyone")

        if success:
            title = f"✅ Gotowe! {nickname} zrobił dzisiaj InstaLing!"
            color = 0x2ECC71  # Zielony
            desc = (
                f"👤 **Kto:** **{nickname}**\n"
                f"🎯 **Wynik:** **{correct} poprawnych na {total} słówek** (**{acc:.0f}%**)\n"
                f"🕒 **Godzina:** **{start_h} – {end_h}** *(czas nauki: ok. {minutes_taken} min)*"
            )
            fields = []

            words_details = result.get("words_details", [])
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
                    if st == "poprawnie":
                        w_lines.append(f"`{idx}.` {prompt} ➔ **{ans}** ✅")
                    elif st == "nowe":
                        w_lines.append(f"`{idx}.` {prompt} ➔ **{ans}** 🆕 *(nowe słówko)*")
                    elif st == "autokorekta":
                        w_lines.append(f"`{idx}.` {prompt} ➔ **{ans}** 🔄 *(poprawione)*")
                    elif st == "celowy_blad":
                        w_lines.append(f"`{idx}.` {prompt} ➔ **{ans}** ❌ *(drobna pomyłka)*")
                    else:
                        w_lines.append(f"`{idx}.` {prompt} ➔ **{ans}**")

                if len(items_list) > 20:
                    w_lines.append(f"*...i jeszcze {len(items_list) - 20} innych słówek*")

                fields.append({
                    "name": f"📚 Jakie słówka były dzisiaj na sesji ({len(items_list)}):",
                    "value": "\n".join(w_lines),
                    "inline": False
                })
        else:
            title = f"⚠️ Problem z sesją — {nickname}"
            color = 0xE74C3C  # Czerwony
            err = result.get("error", "Nieznany błąd")
            desc = (
                f"Nie udało się dokończyć sesji dla **{nickname}** o godz. **{end_h}**.\n"
                f"🔄 Bot za chwilę spróbuje ponownie.\n\n"
                f"**Powód:** `{err[:200]}`"
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

        # 2. KANAŁ #logi-bota — Krok po kroku co robił bot
        logs_wh = self._get_webhook("webhook_logi_bota") or self.config.get("discord_logs_webhook_url", "").strip()
        if logs_wh and session_logs:
            self._send_discord_logs(logs_wh, nickname, masked, session_logs)

        # 3. KANAŁ #statystyki — Czytelne podsumowanie wszystkich kont
        stats_wh = self._get_webhook("webhook_statystyki")
        if stats_wh and stats_wh != sekcja_wh and success:
            try:
                self.send_bot_global_statistics(latest_user=nickname, latest_acc=acc, latest_score=f"{correct}/{total}")
            except Exception as e:
                log(f"[!] Błąd wysyłania globalnych statystyk: {e}")

        # 4. POWIADOMIENIE NTFY.SH (na telefon)
        if user.get("track_in_ntfy", False):
            ntfy_topic = self.config.get("ntfy_topic", "").strip()
            if not ntfy_topic:
                login = user.get("login", "user").strip()
                ntfy_topic = f"instaling_{login}"

            if success:
                ntfy_title = f"InstaLing: {nickname} zrobil sesje! ({correct}/{total})"
                ntfy_msg = (
                    f"Gotowe! {nickname} zrobil dzisiaj InstaLing.\n"
                    f"Wynik: {correct} na {total} slowek ({acc:.0f}%)\n"
                    f"Godzina: {start_h} - {end_h}"
                )
                self._send_ntfy(ntfy_topic, ntfy_title, ntfy_msg, priority="default", tags="white_check_mark,mortarboard")
            else:
                ntfy_title = f"InstaLing: Problem z sesja dla {nickname}"
                ntfy_msg = f"Bot sprobuje ponownie. Powod: {result.get('error', 'Blad')}"
                self._send_ntfy(ntfy_topic, ntfy_title, ntfy_msg, priority="high", tags="warning")

    def send_morning_ntfy(self, topic: str, date_str: str, day_name: str, slots_summary: List[str]) -> None:
        """Wysyła poranny plan dnia na telefon (ntfy.sh)."""
        title = f"InstaLing: Plan na dzis ({day_name})"
        msg = f"Kto i o ktorej robi dzisiaj InstaLing ({format_date_pl(date_str)}):\n\n" + "\n".join(slots_summary)
        self._send_ntfy(topic, title, msg, priority="default", tags="calendar,alarm_clock")

    def send_daily_plan(self, plan_entries: List[Dict[str, Any]], day_name: str = "", date_str: str = "") -> None:
        """Wysyła bardzo jasny, prosty plan na dziś do kanału #plan-na-dzis."""
        wh = self._get_webhook("webhook_plan_na_dzis")
        if not wh:
            return

        if not date_str:
            date_str = today_warsaw().isoformat()
        nice_date = format_date_pl(date_str)

        completed_count = 0
        total_active = 0
        student_blocks = []

        # Sortujemy według godziny (osoby z dniem wolnym na końcu)
        sorted_entries = sorted(
            plan_entries,
            key=lambda x: (1 if x.get("is_off_day") else 0, x.get("scheduled_minutes", 9999))
        )

        for p in sorted_entries:
            nick = p.get("nickname", "Uczeń")
            time_str = p.get("scheduled_time", "--:--")
            is_off = p.get("is_off_day", False)
            completed = p.get("completed", False)
            completed_at = p.get("completed_at")
            acc = p.get("accuracy_percent")
            w_cor = p.get("words_correct")
            w_tot = p.get("words_total")

            unix_ts = to_discord_unix(date_str, time_str) if not is_off else None
            live_timer = f" (<t:{unix_ts}:R>)" if unix_ts else ""

            if is_off:
                student_blocks.append(
                    f"🏖️ **{nick}** — **Dziś ma wolne**\n"
                    f"┗ 💤 *Dzisiaj bot nie robi dla niego sesji*"
                )
            elif completed:
                completed_count += 1
                total_active += 1
                score_str = f" • 🎯 Wynik: **{w_cor}/{w_tot} słówek** ({acc:.0f}%)" if acc is not None else ""
                end_hour = completed_at[11:16] if completed_at and len(completed_at) >= 16 else time_str
                student_blocks.append(
                    f"✅ **{nick}** — **ZROBIONE!**\n"
                    f"┗ 🕒 Zrobiono o godz. **{end_hour}**{score_str}"
                )
            elif p.get("status") == "W trakcie":
                total_active += 1
                student_blocks.append(
                    f"▶️ **{nick}** — **TERAZ ROBI SŁÓWKA!**\n"
                    f"┗ ⏰ Godzina z planu: **{time_str}**"
                )
            elif p.get("status") == "Błąd":
                total_active += 1
                student_blocks.append(
                    f"⚠️ **{nick}** — **Problem o godz. {time_str}**\n"
                    f"┗ 🔄 *Bot za chwilę spróbuje ponownie*"
                )
            else:
                total_active += 1
                student_blocks.append(
                    f"⏳ **{nick}** — **Zrobi o godz. {time_str}**{live_timer}\n"
                    f"┗ 📌 *Czeka na swoją godzinę*"
                )

        all_done = (completed_count == total_active and total_active > 0)
        color = 0x2ECC71 if all_done else 0x5865F2

        if all_done:
            status_header = f"🎉 **Wszyscy dzisiaj zrobili już InstaLing! ({completed_count}/{total_active})**"
        else:
            status_header = f"📌 **Zrobione dzisiaj: {completed_count} z {total_active} osób**"

        desc = (
            "\n\n".join(student_blocks)
            + "\n\n──────────────────────────────\n"
            + status_header
        )

        self._send_discord_embed(
            webhook_url=wh,
            title=f"📅 Kto i o której robi dziś InstaLing? ({day_name}, {nice_date})",
            description=desc,
            color=color,
            fields=None
        )

    def send_weekly_plan(self, weekly_data: Dict[str, Any], week_key: str = "") -> None:
        """Wysyła prostą, przejrzystą rozpiskę na cały tydzień do kanału #plan-tygodnia."""
        wh = self._get_webhook("webhook_plan_tygodnia")
        if not wh:
            return

        today_pl = today_warsaw()
        today_weekday = today_pl.weekday()

        desc = "Rozpiska godzin, o których bot robi InstaLing w poszczególne dni tygodnia:"

        fields = []
        for idx, (day_name, entries) in enumerate(weekly_data.items()):
            is_today = (idx == today_weekday)
            field_title = f"👉 {day_name} (DZISIAJ)" if is_today else f"🗓️ {day_name}"

            lines = []
            for e in entries:
                nick = e.get("nickname", "Uczeń")
                t = e.get("time", "--:--")
                off = e.get("is_off", False)
                comp = e.get("completed", False)
                if off:
                    lines.append(f"🏖️ **{nick}** — *Wolne*")
                elif comp:
                    lines.append(f"✅ **{nick}** — **{t}** *(zrobione)*")
                else:
                    lines.append(f"⏳ **{nick}** — godz. **{t}**")

            fields.append({
                "name": field_title,
                "value": "\n".join(lines) if lines else "Brak wpisów",
                "inline": True
            })

        self._send_discord_embed(
            webhook_url=wh,
            title="🗓️ Plan na cały tydzień (Poniedziałek – Niedziela)",
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
        """Wysyła proste i czytelne podsumowanie wszystkich kont na kanał #statystyki."""
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

        user_lines = []
        for u in active_users:
            nick = u.get("nickname", "Uczeń")
            mask = mask_login(u.get("login", ""))
            u_hist = [h for h in history if h.get("nickname") == nick or h.get("masked_login") == mask]
            u_count = len(u_hist)
            u_acc = round(sum(h.get("accuracy_percent", 0) for h in u_hist) / u_count) if u_count > 0 else 0
            last_raw = u_hist[-1].get("completed_at_warsaw", "Brak") if u_hist else "Brak"
            last_nice = format_short_datetime_pl(last_raw)
            user_lines.append(
                f"👤 **{nick}**\n"
                f"┗ ✅ Zrobione sesje: **{u_count}** • 🎯 Średni wynik: **{u_acc}%** • 🕒 Ostatnio: **{last_nice}**"
            )

        header = ""
        if latest_user and latest_score:
            header = (
                f"🆕 **Ostatnio zrobione:** **{latest_user}** — wynik **{latest_score} słówek** ({latest_acc:.0f}%)\n"
                f"──────────────────────────────\n"
            )

        desc = (
            header
            + "\n\n".join(user_lines)
            + "\n\n──────────────────────────────\n"
            + f"📚 **Zapamiętane słówka w bazie bota:** **{len(words)} słówek**\n"
            + f"🏆 **Wszystkie wykonane sesje łącznie:** **{successful_sessions}**"
        )

        self._send_discord_embed(
            webhook_url=stats_wh,
            title="📊 Podsumowanie kont — ile już zrobiono?",
            description=desc,
            color=0x2980B9,
            fields=None
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
                    "text": "InstaLing Bot • Wysłano automatycznie z GitHuba"
                },
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            if fields:
                embed_obj["fields"] = fields

            payload = {
                "embeds": [embed_obj]
            }
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
                log(f"[Powiadomienie] Wysłano embed '{title}' na Discord")
        except Exception as e:
            log(f"[!] Błąd wysyłania powiadomienia Discord: {e}")

    def _send_discord_logs(self, webhook_url: str, nickname: str, masked: str, log_lines: List[str]) -> None:
        """Wysyła logi przebiegu sesji na kanał #logi-bota."""
        try:
            recent = log_lines[-24:] if len(log_lines) > 24 else log_lines
            log_text = "\n".join(recent)
            if len(log_text) > 1800:
                log_text = "...\n" + log_text[-1800:]

            self._send_discord_embed(
                webhook_url=webhook_url,
                title=f"📋 Przebieg sesji krok po kroku — {nickname}",
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
                log(f"[Powiadomienie] Wysłano push ntfy.sh do tematu '{topic}'")
        except Exception as e:
            log(f"[!] Błąd wysyłania ntfy: {e}")
