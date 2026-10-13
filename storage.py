import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

DATA_DIR = Path(__file__).resolve().parent / "data"
WORDS_FILE = DATA_DIR / "words.json"
HISTORY_FILE = DATA_DIR / "history.json"
SCHEDULE_STATE_FILE = DATA_DIR / "schedule_state.json"

def normalize_key(text: str) -> str:
    """Oczyszcza tekst ze zbędnych spacji i znaków diakrytycznych przy wyszukiwaniu."""
    if not text:
        return ""
    cleaned = re.sub(r"\s+", " ", text).strip().lower()
    return cleaned

class Storage:
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.words: Dict[str, Dict[str, Any]] = self._load_words()
        self.history: List[Dict[str, Any]] = self._load_history()

    def _load_words(self) -> Dict[str, Dict[str, Any]]:
        if not WORDS_FILE.exists():
            return {}
        try:
            with open(WORDS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def save_words(self) -> None:
        with open(WORDS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.words, f, indent=2, ensure_ascii=False)

    def _load_history(self) -> List[Dict[str, Any]]:
        if not HISTORY_FILE.exists():
            return []
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def save_history(self) -> None:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(self.history, f, indent=2, ensure_ascii=False)

    def get_word(self, prompt: str, sentence: str = "") -> Optional[str]:
        """Szuka słówka najpierw po pełnym kontekście zdania, a potem po samym słowie/podpowiedzi."""
        # 1. Kontekst: zdanie + polskie słowo
        if sentence and prompt:
            combined = normalize_key(f"{sentence} | {prompt}")
            if combined in self.words:
                return self.words[combined]["answer"]

        # 2. Samo zdanie
        if sentence:
            k_sent = normalize_key(sentence)
            if k_sent in self.words:
                return self.words[k_sent]["answer"]

        # 3. Samo polskie słowo
        if prompt:
            k_prompt = normalize_key(prompt)
            if k_prompt in self.words:
                return self.words[k_prompt]["answer"]

        return None

    def record_word(self, answer: str, prompt: str, sentence: str = "") -> None:
        """Zapisuje poznane słówko przypisane do kontekstu zdania i polskiego promptu."""
        answer_clean = answer.strip()
        if not answer_clean:
            return

        now_iso = datetime.now().isoformat()
        
        # Zapisujemy kombinację dla precyzyjnego dopasowania
        if sentence and prompt:
            combined = normalize_key(f"{sentence} | {prompt}")
            self.words[combined] = {
                "answer": answer_clean,
                "prompt": prompt.strip(),
                "sentence": sentence.strip(),
                "updated_at": now_iso,
                "usage_count": self.words.get(combined, {}).get("usage_count", 0) + 1
            }
        
        # Oraz po samym słowie jako fallback
        if prompt:
            k_prompt = normalize_key(prompt)
            self.words[k_prompt] = {
                "answer": answer_clean,
                "prompt": prompt.strip(),
                "sentence": sentence.strip(),
                "updated_at": now_iso,
                "usage_count": self.words.get(k_prompt, {}).get("usage_count", 0) + 1
            }

        self.save_words()

    def record_session(self, entry: Dict[str, Any]) -> None:
        """Zapisuje wykonaną sesję do historii."""
        entry["timestamp"] = datetime.now().isoformat()
        self.history.append(entry)
        self.save_history()

    def get_schedule_state(self) -> Dict[str, Any]:
        if not SCHEDULE_STATE_FILE.exists():
            return {}
        try:
            with open(SCHEDULE_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def save_schedule_state(self, state: Dict[str, Any]) -> None:
        with open(SCHEDULE_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
