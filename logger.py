import sys
import os
from datetime import datetime
from pathlib import Path

# Zapewniamy natychmiastowe opróżnianie bufora i kodowanie UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

DATA_DIR = Path(__file__).resolve().parent / "data"
LOG_FILE = DATA_DIR / "bot.log"
MEMORY_LOGS = []
MAX_MEMORY_LOGS = 300

def get_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def log(msg: str) -> None:
    """Zapisuje log natychmiast do konsoli, pamięci RAM i pliku data/bot.log."""
    ts = get_timestamp()
    line = f"[{ts}] {msg}"
    
    # 1. Konsola (z wymuszonym flush)
    try:
        print(line, flush=True)
    except Exception:
        # Fallback dla trudnych znaków w starszych konsolach
        safe_line = line.encode("ascii", errors="replace").decode("ascii")
        print(safe_line, flush=True)

    # 2. Pamięć RAM (dla panelu Web)
    MEMORY_LOGS.append(line)
    if len(MEMORY_LOGS) > MAX_MEMORY_LOGS:
        MEMORY_LOGS.pop(0)

    # 3. Plik data/bot.log
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def get_recent_logs() -> list:
    """Zwraca ostatnie logi."""
    if MEMORY_LOGS:
        return list(MEMORY_LOGS)
    if LOG_FILE.exists():
        try:
            with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                lines = [l.strip() for l in f.readlines() if l.strip()]
                return lines[-MAX_MEMORY_LOGS:]
        except Exception:
            return []
    return []
