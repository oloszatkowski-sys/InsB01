import urllib.request
import urllib.parse
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from logger import log
from users_manager import mask_login
from timezone_utils import WARSAW_TZ, now_warsaw, today_warsaw

def make_progress_bar(pct: float, length: int = 10) -> str:
    """Generuje wizualny pasek postępu (np. ▓▓▓▓▓▓▓▓░░ 80.0%)."""
    pct = max(0.0, min(100.0, float(pct)))
    filled = int(round(length * (pct / 100.0)))
    filled = max(0, min(length, filled))
    bar = "▓" * filled + "░" * (length - filled)
    return f"`{bar}` **{pct:.1f}%**"

def to_discord_unix(date_str: str, time_str: str) -> Optional[int]:
    """Konwertuje datę (YYYY-MM-DD) i godzinę (HH:MM) w strefie Europe/Warsaw na znacznik UNIX dla zegara Discorda."""
    try:
        clean_time = time_str.strip()[:5]
        dt = datetime.strptime(f"{date_str} {clean_time}", "%Y-%m-%d %H:%M").replace(tzinfo=WARSAW_TZ)
        return int(dt.timestamp())
    except Exception:
        return None

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
        """Wysyła schludne powiadomienie o ROZPOCZĘCIU sesji na kanał #sekcja (bez pingu)."""
        sekcja_wh = self._get_webhook("webhook_sekcja")
        if not sekcja_wh:
            return

        nickname = user.get("nickname", "Uczeń")
        masked = mask_login(user.get("login", ""))
        now_ts = int(now_warsaw().timestamp())

        title = f"▶️ Sesja w toku — {nickname}"
        color = 0x3498DB  # Błękit informacyjny
        desc = (
            f"Wbudowany zegar bota wybił godzinę nauki dla ucznia **{nickname}** (`{masked}`).\n"
            f"⏳ *Trwa logowanie i rozwiązywanie słówek...*"
        )
        fields = [
            {
                "name": "👤 Uczeń",
                "value": f"**{nickname}**\n`{masked}`",
                "inline": True
            },
            {
                "name": "⏰ Planowany czas",
                "value": f"**`{scheduled_time}`**\n*(Europe/Warsaw)*",
                "inline": True
            },
            {
                "name": "🇵🇱 Start zegara",
                "value": f"**`{started_pl[11:19]}`**\n<t:{now_ts}:R>",
                "inline": True
            }
        ]

        self._send_discord_embed(
            webhook_url=sekcja_wh,
            title=title,
            description=desc,
            color=color,
            fields=fields,
            content=None
        )

    def send_session_summary(self, result: Dict[str, Any], user: Dict[str, Any], session_logs: Optional[List[str]] = None) -> None:
        """Wysyła schludne, uporządkowane podsumowanie ukończonej sesji na odpowiednie kanały Discord i ntfy.sh."""
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
        now_ts = int(now_warsaw().timestamp())

        # 1. KANAŁ #sekcja — Główne podsumowanie sesji
        sekcja_wh = self._get_webhook("webhook_sekcja")
        ping_role = self.config.get("discord_ping", "@everyone")

        if success:
            title = f"🏆 Sesja Ukończona — {nickname}"
            color = 0x2ECC71  # Szmaragdowa zieleń
            desc = f"✅ Codzienna sesja dla ucznia **{nickname}** (`{masked}`) została pomyślnie zrealizowana (<t:{now_ts}:R>)."

            fields = [
                {
                    "name": "📊 Skuteczność",
                    "value": make_progress_bar(acc),
                    "inline": True
                },
                {
                    "name": "📝 Wynik słówek",
                    "value": f"✅ **{correct}** popr. • ❌ **{mistakes}** bł. *(łącznie {total})*",
                    "inline": True
                },
                {
                    "name": "⏱️ Czas nauki",
                    "value": f"**{duration_s:.0f}s** *(~{duration_s/60:.1f} min)*",
                    "inline": True
                },
                {
                    "name": "🕒 Przebieg czasowy (PL)",
                    "value": f"`{started_pl[11:19]}` ➔ `{completed_pl[11:19]}`",
                    "inline": True
                },
                {
                    "name": "👤 Konto ucznia",
                    "value": f"**{nickname}** (`{masked}`)",
                    "inline": True
                },
                {
                    "name": "🛡️ Bezpieczeństwo",
                    "value": "✅ Anty-Detekcja • Odstęp 45m+",
                    "inline": True
                }
            ]

            words_details = result.get("words_details", [])
            if words_details:
                # Schludna deduplikacja słówek: pomijamy puste '_____' z pierwszego kroku autokorekty,
                # zachowując docelowe słówko i najważniejszy status (nowe > autokorekta > celowy_blad > poprawnie)
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
                        # Aktualizujemy odpowiedź jeśli poprzednia była samymi podkreślnikami '____'
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
                        tag = "✅"
                        suffix = ""
                    elif st == "nowe":
                        tag = "🆕"
                        suffix = " *(nowe)*"
                    elif st == "autokorekta":
                        tag = "🔄"
                        suffix = " *(autokorekta)*"
                    elif st == "celowy_blad":
                        tag = "🎯"
                        suffix = " *(celowy błąd)*"
                    else:
                        tag = "⚠️"
                        suffix = ""
                    w_lines.append(f"`{idx:02d}.` {tag} {prompt} ➔ **{ans}**{suffix}")

                if len(items_list) > 20:
                    w_lines.append(f"*...oraz {len(items_list) - 20} innych słówek*")

                fields.append({
                    "name": f"📚 Zestawienie słówek z sesji ({len(items_list)} unikalnych):",
                    "value": "\n".join(w_lines),
                    "inline": False
                })
        else:
            title = f"⚠️ Błąd Sesji — {nickname}"
            color = 0xE74C3C  # Szkarłatna czerwień
            err = result.get("error", "Nieznany błąd wykonania")
            desc = f"Sesja dla ucznia **{nickname}** (`{masked}`) napotkała problem i zostanie ponowiona."
            fields = [
                {
                    "name": "👤 Uczeń",
                    "value": f"**{nickname}** (`{masked}`)",
                    "inline": True
                },
                {
                    "name": "🇵🇱 Czas zdarzenia",
                    "value": f"`{completed_pl}`",
                    "inline": True
                },
                {
                    "name": "❌ Szczegóły techniczne",
                    "value": f"```text\n{err[:300]}\n```",
                    "inline": False
                }
            ]

        if sekcja_wh:
            self._send_discord_embed(
                webhook_url=sekcja_wh,
                title=title,
                description=desc,
                color=color,
                fields=fields,
                content=ping_role if ping_role else None
            )

        # 2. KANAŁ #logi-bota — Tylko czyste logi konsoli w estetycznym embedzie
        logs_wh = self._get_webhook("webhook_logi_bota") or self.config.get("discord_logs_webhook_url", "").strip()
        if logs_wh and session_logs:
            self._send_discord_logs(logs_wh, nickname, masked, session_logs)

        # 3. KANAŁ #statystyki — Jeden spójny, schludny panel statystyk po sesji
        stats_wh = self._get_webhook("webhook_statystyki")
        if stats_wh and stats_wh != sekcja_wh and success:
            try:
                self.send_bot_global_statistics(latest_user=nickname, latest_acc=acc, latest_score=f"{correct}/{total}")
            except Exception as e:
                log(f"[!] Błąd wysyłania globalnych statystyk: {e}")

        # 4. POWIADOMIENIE NTFY.SH (DLA UŻYTKOWNIKÓW Z track_in_ntfy: true)
        if user.get("track_in_ntfy", False):
            ntfy_topic = self.config.get("ntfy_topic", "").strip()
            if not ntfy_topic:
                login = user.get("login", "user").strip()
                ntfy_topic = f"instaling_{login}"

            if success:
                ntfy_title = f"🎓 InstaLing: {nickname} zaliczył sesję! ({acc}%)"
                ntfy_msg = (
                    f"✅ Sukces!\n"
                    f"• Wynik: {correct}/{total} poprawnych ({acc}%)\n"
                    f"• Czas trwania: {duration_s:.0f}s (~{duration_s/60:.1f} min)\n"
                    f"• Czas PL: {started_pl[11:16]} ➔ {completed_pl[11:16]}"
                )
                self._send_ntfy(ntfy_topic, ntfy_title, ntfy_msg, priority="default", tags="white_check_mark,mortarboard,robot")
            else:
                ntfy_title = f"⚠️ InstaLing: Błąd sesji dla {nickname}"
                ntfy_msg = f"❌ Błąd: {result.get('error', 'Nieznany')}\nCzas PL: {completed_pl}"
                self._send_ntfy(ntfy_topic, ntfy_title, ntfy_msg, priority="high", tags="warning,x,robot")

    def send_morning_ntfy(self, topic: str, date_str: str, day_name: str, slots_summary: List[str]) -> None:
        """Wysyła poranny meldunek o 06:30 na ntfy.sh."""
        title = f"☀️ InstaLing: Plan na dziś ({day_name})"
        msg = f"📅 Data: {date_str} ({day_name})\n\nZaplanowane godziny:\n" + "\n".join(slots_summary)
        msg += "\n\nOdstęp anty-kolizyjny: min. 45 min."
        self._send_ntfy(topic, title, msg, priority="default", tags="calendar,alarm_clock,robot")

    def send_daily_plan(self, plan_entries: List[Dict[str, Any]], day_name: str = "", date_str: str = "") -> None:
        """Wysyła schludny, nowoczesny plan na dziś z żywym zegarem Discorda (<t:UNIX:R>) do kanału #plan-na-dzis."""
        wh = self._get_webhook("webhook_plan_na_dzis")
        if not wh:
            return

        if not date_str:
            date_str = today_warsaw().isoformat()

        completed_count = 0
        total_active = 0
        student_blocks = []

        # Sortujemy wpisy chronologicznie (dni wolne na końcu)
        sorted_entries = sorted(
            plan_entries,
            key=lambda x: (1 if x.get("is_off_day") else 0, x.get("scheduled_minutes", 9999))
        )

        for p in sorted_entries:
            nick = p.get("nickname", "Uczeń")
            mask = mask_login(p.get("login", ""))
            time_str = p.get("scheduled_time", "--:--")
            is_off = p.get("is_off_day", False)
            completed = p.get("completed", False)
            completed_at = p.get("completed_at")
            acc = p.get("accuracy_percent")
            w_cor = p.get("words_correct")
            w_tot = p.get("words_total")

            unix_ts = to_discord_unix(date_str, time_str) if not is_off else None
            live_timer = f" • <t:{unix_ts}:R>" if unix_ts else ""

            if is_off:
                student_blocks.append(
                    f"🏖️ **{nick}** (`{mask}`)\n"
                    f"┗ 💤 *Dzień wolny (losowa przerwa anty-detekcyjna)*"
                )
            elif completed:
                completed_count += 1
                total_active += 1
                res_info = f" • Wynik: **{w_cor}/{w_tot}** (`{acc}%`)" if acc is not None else ""
                end_hour = completed_at[11:19] if completed_at and len(completed_at) >= 19 else "dzisiaj"
                student_blocks.append(
                    f"✅ **{nick}** (`{mask}`)\n"
                    f"┗ ⏰ Plan: `{time_str}` • Ukończono o **`{end_hour}`**{res_info}"
                )
            elif p.get("status") == "W trakcie":
                total_active += 1
                student_blocks.append(
                    f"▶️ **{nick}** (`{mask}`)\n"
                    f"┗ ⚡ **Sesja aktualnie w toku!** *(Plan: `{time_str}`)*"
                )
            elif p.get("status") == "Błąd":
                total_active += 1
                student_blocks.append(
                    f"⚠️ **{nick}** (`{mask}`)\n"
                    f"┗ 🔄 Plan: `{time_str}` *(Wystąpił błąd — oczekiwanie na ponowienie)*"
                )
            else:
                total_active += 1
                student_blocks.append(
                    f"⏳ **{nick}** (`{mask}`)\n"
                    f"┗ ⏰ Start: **`{time_str}`**{live_timer}"
                )

        pct_done = (completed_count / total_active * 100.0) if total_active > 0 else 100.0
        color = 0x2ECC71 if completed_count == total_active and total_active > 0 else 0x9B59B6

        desc = (
            f"📅 **Dzień:** `{date_str}` (**{day_name}**) • 🇵🇱 **Strefa:** `Europe/Warsaw`\n"
            f"📊 **Postęp dnia:** {make_progress_bar(pct_done)} (`{completed_count}/{total_active}`)\n\n"
            + "\n\n".join(student_blocks)
        )

        fields = [
            {
                "name": "🕒 Okna czasowe bota",
                "value": "🌅 Rano: `06:43–07:34` *(8%)*\n🌙 Wieczór: `15:37–22:39` *(92%)*",
                "inline": True
            },
            {
                "name": "🛡️ Synchronizacja Zegara",
                "value": "⏰ Wbudowany zegar (`0.5s`)\n🔒 Odstęp min. **45 min**",
                "inline": True
            }
        ]

        self._send_discord_embed(
            webhook_url=wh,
            title=f"📅 Harmonogram Sesji Na Dziś — {day_name}",
            description=desc,
            color=color,
            fields=fields
        )

    def send_weekly_plan(self, weekly_data: Dict[str, Any], week_key: str = "") -> None:
        """Wysyła schludny, przejrzysty plan tygodnia do kanału #plan-tygodnia."""
        wh = self._get_webhook("webhook_plan_tygodnia")
        if not wh:
            return

        today_pl = today_warsaw()
        today_weekday = today_pl.weekday()
        day_names_list = list(weekly_data.keys())

        desc = (
            f"🗓️ **Tydzień ISO:** `{week_key}` • 🇵🇱 **Strefa:** `Europe/Warsaw`\n"
            f"🕒 **Okna sesji:** `06:43–07:34` *(rzadko)* oraz `15:37–22:39` *(głównie)*\n"
            f"🔒 *Stały rozkład tygodnia z gwarancją min. 45 min odstępu między kontami.*"
        )

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
                comp_at = e.get("completed_at")
                if off:
                    lines.append(f"🏖️ **{nick}**: *Wolne*")
                elif comp:
                    end_h = comp_at[11:16] if comp_at and len(comp_at) >= 16 else ""
                    end_tag = f" *(o {end_h})*" if end_h else ""
                    lines.append(f"✅ **{nick}**: `{t}`{end_tag}")
                else:
                    lines.append(f"⏳ **{nick}**: **`{t}`**")

            fields.append({
                "name": field_title,
                "value": "\n".join(lines) if lines else "Brak wpisów",
                "inline": True
            })

        self._send_discord_embed(
            webhook_url=wh,
            title="🗓️ Oficjalny Plan Tygodnia InstaLing",
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
        """Wysyła pojedynczy, schludny panel statystyk działania bota na dedykowany kanał #statystyki."""
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

        total_sessions = len(history)
        successful_sessions = sum(1 for h in history if h.get("success", False))
        failed_sessions = total_sessions - successful_sessions

        total_words_solved = sum(h.get("words_total", 0) for h in history)
        total_words_correct = sum(h.get("words_correct", 0) for h in history)
        avg_acc = round((total_words_correct / total_words_solved * 100), 1) if total_words_solved > 0 else 0.0

        total_time_s = sum(h.get("duration_seconds", 0) for h in history)
        total_time_min = total_time_s / 60.0

        user_lines = []
        for u in active_users:
            nick = u.get("nickname", "Uczeń")
            mask = mask_login(u.get("login", ""))
            u_hist = [h for h in history if h.get("nickname") == nick or h.get("masked_login") == mask]
            u_count = len(u_hist)
            u_acc = round(sum(h.get("accuracy_percent", 0) for h in u_hist) / u_count, 1) if u_count > 0 else 0.0
            last_date = u_hist[-1].get("completed_at_warsaw", "Brak")[5:16] if u_hist else "Brak"
            user_lines.append(
                f"👤 **{nick}** (`{mask}`)\n"
                f"┗ Sesje: **{u_count}** • Śr. {make_progress_bar(u_acc, length=8)} • Ost.: `{last_date}`"
            )

        desc = "Aktualne zestawienie telemetryczne, stan słownika oraz postępy wszystkich kont."
        if latest_user and latest_score:
            desc = (
                f"🆕 **Ostatnia sesja:** **{latest_user}** — wynik **{latest_score}** (`{latest_acc}%`)\n"
                f"──────────────────────────────────────────"
            )

        fields = [
            {
                "name": "📚 Słownik Bota",
                "value": f"**{len(words)}** słówek",
                "inline": True
            },
            {
                "name": "🏆 Średnia Skuteczność",
                "value": make_progress_bar(avg_acc, length=8),
                "inline": True
            },
            {
                "name": "🔄 Wykonane Sesje",
                "value": f"✅ **{successful_sessions}** (❌ {failed_sessions})",
                "inline": True
            },
            {
                "name": "⏱️ Łączny Czas Nauki",
                "value": f"**{total_time_min:.1f} min** (~{total_time_min/60:.1f}h)",
                "inline": True
            },
            {
                "name": "✍️ Przerobione Słówka",
                "value": f"**{total_words_correct}/{total_words_solved}** popr.",
                "inline": True
            },
            {
                "name": "🛡️ Zegar i Ochrona",
                "value": "⏰ Precyzja `0.5s` • `45m+`",
                "inline": True
            },
            {
                "name": "👥 Statystyki Poszczególnych Uczniów",
                "value": "\n\n".join(user_lines) if user_lines else "Brak aktywnych uczniów",
                "inline": False
            }
        ]

        self._send_discord_embed(
            webhook_url=stats_wh,
            title="📊 Panel Statystyk — InstaLing Auto-Bot",
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
                    "text": "InstaLing Auto-Bot • Wbudowany Zegar (Europe/Warsaw) • Anty-Detekcja"
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
        """Wysyła logi przebiegu sesji w czystym, ciemnym embedzie na kanał #logi-bota."""
        try:
            recent = log_lines[-24:] if len(log_lines) > 24 else log_lines
            log_text = "\n".join(recent)
            if len(log_text) > 1800:
                log_text = "...\n" + log_text[-1800:]

            self._send_discord_embed(
                webhook_url=webhook_url,
                title=f"📋 Logi Konsoli — {nickname} ({masked})",
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
