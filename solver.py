import sys
import time
import random
from typing import Dict, Any, Optional, Tuple, TYPE_CHECKING
from storage import Storage

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

if TYPE_CHECKING:
    from playwright.sync_api import Page, Locator

KEYBOARD_NEIGHBORS = {
    'q': 'wa', 'w': 'qes', 'e': 'wrd', 'r': 'etf', 't': 'ryg', 'y': 'tuh', 'u': 'yij',
    'i': 'uok', 'o': 'ipl', 'p': 'ol', 'a': 'qwsz', 's': 'awedxz', 'd': 'serfcx',
    'f': 'drtgvc', 'g': 'ftyhbv', 'h': 'gyujnb', 'j': 'huikmn', 'k': 'jiolm', 'l': 'kop',
    'z': 'asx', 'x': 'zsdc', 'c': 'xdfv', 'v': 'cfgb', 'b': 'vghn', 'n': 'bhjm', 'm': 'njk'
}

SYSTEM_BLACKLIST = {
    "literówka", "literowka", "niepoprawnie", "poprawnie", "następne", "nastepne",
    "zgłoś błąd", "zglos blad", "pytanie", "odpowiedź", "odpowiedz", "sprawdź", "sprawdz",
    "deklaracja dostępności", "twoja odpowiedź", "twoja odpowiedz", "luka"
}

class InstaLingSolver:
    def __init__(self, page, config: Dict[str, Any], storage: Storage):
        self.page = page
        self.config = config
        self.storage = storage
        self.session_words_count = 0
        self.session_correct_count = 0
        self.session_mistakes_count = 0
        self.deliberate_errors_pool = set()

    def human_type(self, selector: str, text: str) -> None:
        """Symuluje naturalne pisanie na klawiaturze (klawisz po klawiszu) - brak copy/paste."""
        locator = self.page.locator(selector).first
        locator.click(force=True)
        time.sleep(random.uniform(0.15, 0.3))

        # Czyścimy pole za pomocą klawiatury (Ctrl+A -> Backspace) - zero schowka
        self.page.keyboard.press("Control+A")
        time.sleep(0.05)
        self.page.keyboard.press("Backspace")
        time.sleep(random.uniform(0.1, 0.2))

        speed_min = float(self.config.get("typing_speed_min_ms", 75)) / 1000.0
        speed_max = float(self.config.get("typing_speed_max_ms", 170)) / 1000.0
        typo_chance = float(self.config.get("typo_chance_percent", 5)) / 100.0

        for char in text:
            lower_char = char.lower()
            if lower_char in KEYBOARD_NEIGHBORS and random.random() < typo_chance:
                wrong_char = random.choice(KEYBOARD_NEIGHBORS[lower_char])
                self.page.keyboard.type(wrong_char, delay=int(random.uniform(speed_min, speed_max) * 1000))
                time.sleep(random.uniform(0.2, 0.35))
                self.page.keyboard.press("Backspace")
                time.sleep(random.uniform(0.1, 0.2))

            self.page.keyboard.type(char, delay=int(random.uniform(speed_min, speed_max) * 1000))
            time.sleep(random.uniform(speed_min, speed_max))

    def human_read_delay(self) -> None:
        """Symuluje czas potrzebny człowiekowi na przeczytanie zdania."""
        t_min = min(float(self.config.get("read_time_min_s", 1.8)), 4.0)
        t_max = min(float(self.config.get("read_time_max_s", 4.0)), 7.0)
        time.sleep(random.uniform(t_min, t_max))

    def get_prompt_and_sentence(self) -> Tuple[str, str]:
        """Pobiera polskie słowo (prompt) oraz kontekst zdania."""
        prompt = ""
        sentence = ""

        trans_loc = self.page.locator("#question_translation, .translation").first
        if trans_loc.count() > 0 and trans_loc.is_visible():
            prompt = trans_loc.inner_text().strip()

        usage_loc = self.page.locator("#question_usage, #usage").first
        if usage_loc.count() > 0 and usage_loc.is_visible():
            sentence = usage_loc.inner_text().strip()

        return prompt, sentence

    def extract_correct_answer_from_page(self) -> str:
        """Pobiera wyświetlone poprawne słówko z szarej ramki po błędzie z rygorystycznym filtrem."""
        ans_loc = self.page.locator("#word, .word, #word_return, .return_word").first
        if ans_loc.count() > 0 and ans_loc.is_visible():
            txt = ans_loc.inner_text().strip()
            if txt and txt.lower() not in SYSTEM_BLACKLIST and len(txt) > 0:
                return txt

        # Fallback z JS - szuka elementu z odpowiedzią omijając czarną listę słów systemowych
        cand = self.page.evaluate("""() => {
            const w = document.getElementById('word');
            if (w && w.innerText) {
                const t = w.innerText.trim();
                if (t.length > 0) return t;
            }
            const blacklist = ['literówka', 'literowka', 'niepoprawnie', 'poprawnie', 'następne', 'nastepne', 'zgłoś błąd', 'zglos blad', 'pytanie', 'odpowiedź', 'odpowiedz', 'sprawdź', 'sprawdz', 'deklaracja dostępności', 'twoja odpowiedź', 'twoja odpowiedz', 'luka'];
            const el = Array.from(document.querySelectorAll('div, span')).find(e => {
                const t = e.innerText ? e.innerText.trim().toLowerCase() : '';
                return e.offsetParent !== null && e.children.length === 0 && t.length > 1 && !blacklist.includes(t);
            });
            return el ? el.innerText.trim() : '';
        }""")
        if cand and cand.lower() not in SYSTEM_BLACKLIST:
            return cand
        return ""

    def is_session_finished(self) -> bool:
        """Sprawdza czy sesja została ukończona (ekran gratulacji lub powrotu)."""
        body_txt = self.page.inner_text("body").lower()
        if "gratulacje" in body_txt or "ukończyłeś sesję" in body_txt or "koniec sesji" in body_txt:
            return True
        return False

    def handle_single_word(self) -> bool:
        """Rozwiązuje pojedyncze zadanie słówkowe z automatyczną auto-korektą błędnych wpisów."""
        if self.is_session_finished():
            return False

        if not hasattr(self, "consecutive_no_answer"):
            self.consecutive_no_answer = 0

        ans_loc = self.page.locator("input#answer").first
        try:
            ans_loc.wait_for(state="visible", timeout=4000)
            self.consecutive_no_answer = 0
        except Exception:
            if self.is_session_finished():
                return False

            # Szukamy ewentualnych przycisków kontynuacji lub przejścia dalej
            cont_btn = self.page.locator("a:has-text('Kontynuuj sesję'), button:has-text('Kontynuuj'), a:has-text('Rozpocznij sesję'), button:has-text('Rozpocznij'), #nextword, button:has-text('Następne')").first
            if cont_btn.count() > 0 and cont_btn.is_visible():
                try:
                    cont_btn.click(force=True)
                    time.sleep(2.0)
                except Exception:
                    pass
                if self.is_session_finished():
                    return False
                return True

            self.consecutive_no_answer += 1
            if self.consecutive_no_answer >= 3:
                print(f"[!] Pole odpowiedzi nie pojawiło się przez {self.consecutive_no_answer} próby. Sprawdzam czy sesja zakończona...")
                if self.is_session_finished():
                    return False
                print("[!] Brak pytania i brak przycisków. Kończę rozwiązywanie, aby zapobiec zawieszeniu.")
                return False

            time.sleep(1.5)
            return True

        prompt, sentence = self.get_prompt_and_sentence()
        self.human_read_delay()

        known_answer = self.storage.get_word(prompt, sentence)
        # Odrzucamy z bazy słowa systemowe jeśli przypadkowo tam trafiły
        if known_answer and known_answer.lower() in SYSTEM_BLACKLIST:
            known_answer = None

        target_acc = float(self.config.get("target_accuracy_percent", 91))
        word_id = f"{prompt}_{sentence}"

        is_first_encounter = known_answer is None
        should_make_deliberate_mistake = (
            known_answer is not None and
            word_id not in self.deliberate_errors_pool and
            random.random() > (target_acc / 100.0)
        )

        if is_first_encounter or should_make_deliberate_mistake:
            if should_make_deliberate_mistake:
                self.deliberate_errors_pool.add(word_id)
                print(f"[~] Celowy blad dla statystyk ucznia: '{prompt}'")
                fake = known_answer[:-1] if len(known_answer) > 2 else "x"
                self.human_type("input#answer", fake)
            else:
                print(f"[?] Nowe slowko (brak w bazie): '{prompt}'")
                self.human_type("input#answer", "-")

            check_btn = self.page.locator("#check, button:has-text('Sprawdź')").first
            check_btn.click(force=True)
            time.sleep(1.8)

            correct_ans = self.extract_correct_answer_from_page()
            if correct_ans and correct_ans.lower() not in SYSTEM_BLACKLIST:
                print(f"[+] ZAPAMIETANO SLOWKO: '{prompt}' -> '{correct_ans}'")
                self.storage.record_word(correct_ans, prompt, sentence)

            self.session_mistakes_count += 1
        else:
            print(f"[OK] Znaleziono w bazie: '{prompt}' -> '{known_answer}'")
            self.human_type("input#answer", known_answer)

            check_btn = self.page.locator("#check, button:has-text('Sprawdź')").first
            check_btn.click(force=True)
            time.sleep(1.6)

            # --- AUTO-KOREKTA (SELF-HEALING) ---
            # Sprawdzamy czy InstaLing nie zgłosił błędu / literówki
            body_feedback = self.page.inner_text("body").lower()
            if "niepoprawnie" in body_feedback or "literówka" in body_feedback or "literowka" in body_feedback:
                real_ans = self.extract_correct_answer_from_page()
                if real_ans and real_ans.lower() not in SYSTEM_BLACKLIST and real_ans.lower() != known_answer.lower():
                    print(f"[!] AUTOKOREKTA: Baza miala '{known_answer}', poprawiono na: '{real_ans}'!")
                    self.storage.record_word(real_ans, prompt, sentence)
                self.session_mistakes_count += 1
            else:
                self.session_correct_count += 1

        self.session_words_count += 1

        # Klikamy 'Następne'
        next_btn = self.page.locator("#nextword, button:has-text('Następne'), a:has-text('Następne')").first
        if next_btn.count() > 0 and next_btn.is_visible():
            time.sleep(random.uniform(0.8, 1.6))
            next_btn.click(force=True)
            time.sleep(random.uniform(1.0, 1.8))

        return True
