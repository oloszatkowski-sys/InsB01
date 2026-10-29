import urllib.request
import urllib.parse
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from logger import log
from users_manager import mask_login

def make_progress_bar(pct: float, length: int = 10) -> str:
    """Generuje wizualny pasek postępu skuteczności (np. ▓▓▓▓▓▓░░░░ 60.0%)."""
    pct = max(0.0, min(100.0, float(pct)))
    filled = int(round(length * (pct / 100.0)))
    filled = max(0, min(length, filled))
    bar = "▓" * filled + "░" * (length - filled)
    return f"`{bar}` **{pct:.1f}%**"

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
        """Wysyła estetyczne powiadomienie o ROZPOCZĘCIU sesji na kanał #sekcja (bez pingu)."""
        sekcja_wh = self._get_webhook("webhook_sekcja")
        if not sekcja_wh:
            return

        nickname = user.get("nickname", "Uczeń")
        masked = mask_login(user.get("login", ""))

        title = f"▶️ InstaLing Auto-Bot — Rozpoczęto Sesję: {nickname}"
        color = 0x3498DB  # Błękit informacyjny
        desc = f"Rozpoczęto automatyczną sesję dla ucznia **{nickname}** (`{masked}`)."
        fields = [
            {
                "name": "👤 Uczeń",
                "value": f"**{nickname}** (`{masked}`)",
                "inline": True
            },
            {
                "name": "⏰ Godzina planowana",
                "value": f"`{scheduled_time}`",
                "inline": True
            },
            {
                "name": "🇵🇱 Czas startu (PL)",
                "value": f"`{started_pl[11:19]}`",
                "inline": True
            },
            {
                "name": "🎯 Status",
                "value": "⏳ *Sesja w toku... Trwa logowanie i rozwiązywanie zadań.*",
                "inline": False
            }
        ]

        # WYSYŁKA BEZ PINGU (content=None)
        self._send_discord_embed(
            webhook_url=sekcja_wh,
            title=title,
            description=desc,
            color=color,
            fields=fields,
            content=None
        )

    def send_session_summary(self, result: Dict[str, Any], user: Dict[str, Any], session_logs: Optional[List[str]] = None) -> None:
        """Wysyła estetyczne, bogate podsumowanie ukończonej sesji na Discord i ntfy.sh."""
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

        # 1. KANAŁ #sekcja
        sekcja_wh = self._get_webhook("webhook_sekcja")
        ping_role = self.config.get("discord_ping", "@everyone")

        if success:
            title = f"🏆 InstaLing Auto-Bot — Sesja Ukończona!"
            color = 0x2ECC71  # Szmaragdowa zieleń
            desc = f"Sesja dla ucznia **{nickname}** została pomyślnie zrealizowana bez żadnych komplikacji."
            
            fields = [
                {
                    "name": "👤 Uczeń",
                    "value": f"**{nickname}** (`{masked}`)",
                    "inline": True
                },
                {
                    "name": "📊 Skuteczność",
                    "value": make_progress_bar(acc),
                    "inline": True
                },
                {
                    "name": "⏱️ Czas trwania",
                    "value": f"**{duration_s:.1f}s** (~{duration_s/60:.1f} min)",
                    "inline": True
                },
                {
                    "name": "🇵🇱 Ramy czasowe (PL)",
                    "value": f"`{started_pl[11:19]}` ➔ `{completed_pl[11:19]}`",
                    "inline": True
                },
                {
                    "name": "📝 Wynik słówek",
                    "value": f"✅ Poprawne: **{correct}**\n❌ Błędy: **{mistakes}**\n🎯 Łącznie: **{total}**",
                    "inline": True
                },
                {
                    "name": "🛡️ Anty-Detekcja",
                    "value": "• Naturalne opóźnienia\n• Symulacja klawiatury\n• Bezpieczne wylogowanie",
                    "inline": True
                }
            ]

            words_details = result.get("words_details", [])
            if words_details:
                w_lines = []
                for item in words_details[:18]:
                    prompt = item.get("prompt", "")
                    ans = item.get("answer", "")
                    st = item.get("status", "")
                    if st == "poprawnie":
                        tag = "✅"
                    elif st == "nowe":
                        tag = "🆕 *(Zapamiętano)*"
                    elif st == "autokorekta":
                        tag = "🔄 *(Autokorekta)*"
                    elif st == "celowy_blad":
                        tag = "🎯 *(Celowy błąd)*"
                    else:
                        tag = "⚠️"
                    w_lines.append(f"{tag} `{prompt}` ➔ **{ans}**")

                if len(words_details) > 18:
                    w_lines.append(f"*(...oraz {len(words_details) - 18} dodatkowych słówek)*")

                fields.append({
                    "name": f"📚 Słówka w tej sesji ({len(words_details)}):",
                    "value": "\n".join(w_lines),
                    "inline": False
                })
        else:
            title = f"⚠️ InstaLing Auto-Bot — Błąd Sesji"
            color = 0xE74C3C  # Szkarłatna czerwień
            err = result.get("error", "Nieznany błąd wykonania")
            desc = f"Sesja dla ucznia **{nickname}** nie mogła zostać w pełni ukończona."
            fields = [
                {
                    "name": "👤 Uczeń",
                    "value": f"**{nickname}** (`{masked}`)",
                    "inline": True
                },
                {
                    "name": "🇵🇱 Czas błędu",
                    "value": f"`{completed_pl}`",
                    "inline": True
                },
                {
                    "name": "❌ Komunikat błędu",
                    "value": f"```{err[:300]}```",
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

        # 2. KANAŁ #logi-bota
        logs_wh = self._get_webhook("webhook_logi_bota") or self.config.get("discord_logs_webhook_url", "").strip()
        if not logs_wh:
            logs_wh = sekcja_wh

        if logs_wh and session_logs:
            self._send_discord_logs(logs_wh, nickname, masked, session_logs)

        # 3. KANAŁ #statystyki
        stats_wh = self._get_webhook("webhook_statystyki")
        if stats_wh and stats_wh != sekcja_wh and success:
            stat_fields = [
                {"name": "👤 Uczeń", "value": f"**{nickname}**", "inline": True},
                {"name": "📈 Skuteczność", "value": make_progress_bar(acc), "inline": True},
                {"name": "🎯 Wynik", "value": f"{correct}/{total} poprawnych", "inline": True},
                {"name": "⏱️ Czas trwania", "value": f"{duration_s:.1f}s", "inline": True},
                {"name": "🇵🇱 Start", "value": f"`{started_pl[11:19]}`", "inline": True},
                {"name": "🇵🇱 Koniec", "value": f"`{completed_pl[11:19]}`", "inline": True}
            ]
            self._send_discord_embed(
                webhook_url=stats_wh,
                title=f"📊 Raport Statystyk: {nickname}",
                description=f"Nowy wpis w historii dla konta `{masked}`.",
                color=0x3498DB,
                fields=stat_fields
            )
            # Automatycznie aktualizujemy zbiorczy dashboard bota na kanale #statystyki
            try:
                self.send_bot_global_statistics()
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
        """Wysyła czytelny, estetyczny plan na dziś do kanału #plan-na-dzis."""
        wh = self._get_webhook("webhook_plan_na_dzis")
        if not wh:
            return

        lines = []
        completed_count = 0
        total_active = 0

        for p in plan_entries:
            nick = p.get("nickname", "Uczeń")
            mask = mask_login(p.get("login", ""))
            time_str = p.get("scheduled_time", "--:--")
            is_off = p.get("is_off_day", False)
            completed = p.get("completed", False)
            completed_at = p.get("completed_at")
            acc = p.get("accuracy_percent")
            w_cor = p.get("words_correct")
            w_tot = p.get("words_total")

            if is_off:
                lines.append(f"🏖️ **{nick}** (`{mask}`) ➔ *Dzień wolny (antydetekcja)*")
            elif completed:
                completed_count += 1
                total_active += 1
                res_info = f" • Wynik: **{w_cor}/{w_tot}** ({acc}%)" if acc is not None else ""
                end_hour = completed_at[11:16] if completed_at and len(completed_at) >= 16 else "dzisiaj"
                lines.append(f"✅ **{nick}** (`{mask}`) ➔ **{time_str}** *(Ukończono o {end_hour}{res_info})*")
            elif p.get("status") == "W trakcie":
                total_active += 1
                lines.append(f"▶️ **{nick}** (`{mask}`) ➔ **{time_str}** *(Sesja w toku...)*")
            elif p.get("status") == "Błąd":
                total_active += 1
                lines.append(f"⚠️ **{nick}** (`{mask}`) ➔ **{time_str}** *(Błąd - ponowienie wkrótce)*")
            else:
                total_active += 1
                lines.append(f"⏳ **{nick}** (`{mask}`) ➔ **{time_str}** *(Oczekuje na swoją godzinę)*")

        header = f"**Data:** `{date_str}` ({day_name})\n**Postęp sesji:** `{completed_count}/{total_active}` ukończonych dzisiaj\n\n"
        desc = header + "\n".join(lines)
        desc += "\n\n💡 *Każdy uczeń ma własny przedział czasowy z zachowaniem min. 45 min odstępu bez kolizji.*"

        self._send_discord_embed(
            webhook_url=wh,
            title="📅 Harmonogram Sesji Na Dziś (Europe/Warsaw)",
            description=desc,
            color=0x9B59B6
        )

    def send_weekly_plan(self, weekly_data: Dict[str, Any], week_key: str = "") -> None:
        """Wysyła trwały plan tygodnia do kanału #plan-tygodnia."""
        wh = self._get_webhook("webhook_plan_tygodnia")
        if not wh:
            return

        desc = f"**Tydzień ISO:** `{week_key}` | **Strefa:** `Europe/Warsaw`\n*Harmonogram jest wylosowany na cały tydzień i nie ulega zmianie w trakcie tygodnia.*\n\n"

        for day_name, entries in weekly_data.items():
            desc += f"🗓️ **{day_name}:**\n"
            for e in entries:
                nick = e.get("nickname", "Uczeń")
                t = e.get("time", "--:--")
                off = e.get("is_off", False)
                comp = e.get("completed", False)
                comp_at = e.get("completed_at")
                if off:
                    status = "🏖️ *Wolne*"
                elif comp:
                    status = f"✅ `{t}` *(Ukończono {comp_at[11:16] if comp_at else ''})*"
                else:
                    status = f"⏳ `{t}`"
                desc += f"  • `{nick}`: {status}\n"
            desc += "\n"

        self._send_discord_embed(
            webhook_url=wh,
            title="🗓️ Oficjalny Plan Tygodnia InstaLing",
            description=desc,
            color=0x1ABC9C
        )

    def send_bot_global_statistics(self, storage=None, users_mgr=None) -> None:
        """Wysyła całościowy, bogaty raport statystyk działania bota na dedykowany kanał #statystyki."""
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
            user_lines.append(f"• **{nick}** (`{mask}`): **{u_count}** sesji | Śr. **{u_acc}%** | Ost: `{last_date}`")

        fields = [
            {
                "name": "📚 Baza Słówek",
                "value": f"**{len(words)}** unikalnych słówek",
                "inline": True
            },
            {
                "name": "🏆 Ogólna Skuteczność",
                "value": make_progress_bar(avg_acc),
                "inline": True
            },
            {
                "name": "🔄 Wszystkie Sesje",
                "value": f"Łącznie: **{total_sessions}** (✅ {successful_sessions} | ❌ {failed_sessions})",
                "inline": True
            },
            {
                "name": "⏱️ Łączny Czas Nauki",
                "value": f"**{total_time_min:.1f}** min (~{total_time_min/60:.1f}h)",
                "inline": True
            },
            {
                "name": "🛡️ Status Anty-Detekcji",
                "value": "✅ Europe/Warsaw\n✅ Min. 45 min odstępu\n✅ Ludzkie pisanie",
                "inline": True
            },
            {
                "name": "👥 Aktywność Uczniów",
                "value": "\n".join(user_lines) if user_lines else "Brak aktywnych uczniów",
                "inline": False
            }
        ]

        self._send_discord_embed(
            webhook_url=stats_wh,
            title="📊 Globalny Panel Statystyk InstaLing Auto-Bot",
            description="Aktualne zestawienie telemetryczne, stan bazy wiedzy oraz postępy wszystkich kont.",
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
                    "text": "InstaLing Auto-Bot • Europe/Warsaw • 100% Anty-Detekcja"
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
        try:
            recent = log_lines[-22:] if len(log_lines) > 22 else log_lines
            log_text = "\n".join(recent)
            if len(log_text) > 1850:
                log_text = log_text[-1850:]

            payload = {
                "content": f"📋 **Przebieg sesji ucznia `{nickname}` (`{masked}`):**\n```text\n{log_text}\n```"
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                webhook_url,
                data=data,
                headers={"Content-Type": "application/json", "User-Agent": "InstaLingBot/2.0"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                log("[Powiadomienie] Wysłano logi na kanał Discord")
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
