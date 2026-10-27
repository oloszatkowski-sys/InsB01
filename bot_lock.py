import os
import json
import time
from pathlib import Path
from typing import Optional, Dict, Any
from timezone_utils import now_warsaw, now_utc, format_warsaw
from logger import log

LOCK_FILE = Path(__file__).resolve().parent / "data" / "bot.lock"
MAX_LOCK_AGE_SEC = 900  # 15 minut

class BotLock:
    """Zarządza blokadą plikową zapobiegającą równoczesnemu uruchamianiu sesji przez dwa workflow."""
    
    @staticmethod
    def acquire(user_id: str, nickname: str) -> bool:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        # Sprawdzamy czy blokada już istnieje
        if LOCK_FILE.exists():
            try:
                with open(LOCK_FILE, "r", encoding="utf-8") as f:
                    lock_data = json.load(f)
                
                lock_time = lock_data.get("timestamp_epoch", 0)
                age = time.time() - lock_time
                
                # Sprawdzenie czy blokada jest przedawniona (np. po awarii/crashu)
                if age < MAX_LOCK_AGE_SEC:
                    active_user = lock_data.get("nickname", "Nieznany")
                    started = lock_data.get("started_warsaw", "N/A")
                    log(f"[BLOKADA] Inne zadanie jest aktualnie w toku! (Użytkownik: {active_user}, rozpoczęto: {started}, wiek: {age:.0f}s). Pomijam duplikat.")
                    return False
                else:
                    log(f"[BLOKADA] Znaleziono przedawnioną blokadę ({age:.0f}s > {MAX_LOCK_AGE_SEC}s). Automatyczne usunięcie starej blokady.")
                    LOCK_FILE.unlink(missing_ok=True)
            except Exception as e:
                log(f"[BLOKADA] Błąd odczytu pliku blokady: {e}. Czyszczenie pliku.")
                LOCK_FILE.unlink(missing_ok=True)

        # Zakładamy nową blokadę
        payload = {
            "pid": os.getpid(),
            "user_id": user_id,
            "nickname": nickname,
            "timestamp_epoch": time.time(),
            "started_warsaw": format_warsaw(now_warsaw()),
            "started_utc": now_utc().isoformat()
        }
        try:
            with open(LOCK_FILE, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            log(f"[BLOKADA] Błąd podczas tworzenia pliku blokady: {e}")
            return False

    @staticmethod
    def release() -> None:
        try:
            if LOCK_FILE.exists():
                LOCK_FILE.unlink(missing_ok=True)
        except Exception as e:
            log(f"[BLOKADA] Błąd podczas zwalniania blokady: {e}")

    @staticmethod
    def is_locked() -> bool:
        if not LOCK_FILE.exists():
            return False
        try:
            with open(LOCK_FILE, "r", encoding="utf-8") as f:
                lock_data = json.load(f)
            age = time.time() - lock_data.get("timestamp_epoch", 0)
            return age < MAX_LOCK_AGE_SEC
        except Exception:
            return False
