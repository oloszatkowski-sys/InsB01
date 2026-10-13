import time
import random
from typing import Dict, Any, Optional, Tuple, TYPE_CHECKING
from storage import Storage

if TYPE_CHECKING:
    from playwright.sync_api import Page, Locator

KEYBOARD_NEIGHBORS = {
    'q': 'wa', 'w': 'qes', 'e': 'wrd', 'r': 'etf', 't': 'ryg', 'y': 'tuh', 'u': 'yij',
    'i': 'uok', 'o': 'ipl', 'p': 'ol', 'a': 'qwsz', 's': 'awedxz', 'd': 'serfcx',
    'f': 'drtgvc', 'g': 'ftyhbv', 'h': 'gyujnb', 'j': 'huikmn', 'k': 'jiolm', 'l': 'kop',
    'z': 'asx', 'x': 'zsdc', 'c': 'xdfv', 'v': 'cfgb', 'b': 'vghn', 'n': 'bhjm', 'm': 'njk'
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
        """Symuluje naturalne pisanie na klawiaturze z opóźnieniami i sporadycznymi literówkami."""
        locator = self.page.locator(selector).first
        locator.click(force=True)
        locator.fill("")

        speed_min = self.config.get("typing_speed_min_ms", 75) / 1000.0
        speed_max = self.config.get("typing_speed_max_ms", 170) / 1000.0
        typo_chance = self.config.get("typo_chance_percent", 5) / 100.0

        for char in text:
            lower_char = char.lower()
            if lower_char in KEYBOARD_NEIGHBORS and random.random() < typo_chance:
                wrong_char = random.choice(KEYBOARD_NEIGHBORS[lower_char])
                locator.press_sequentially(wrong_char, delay=int(random.uniform(speed_min, speed_max) * 1000))
                time.sleep(random.uniform(0.2, 0.4))
                self.page.keyboard.press("Backspace")
                time.sleep(random.uniform(0.1, 0.25))

            locator.press_sequentially(char, delay=int(random.uniform(speed_min, speed_max) * 1000))
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

        # Polski prompt
        trans_loc = self.page.locator("#question_translation, .translation").first
        if trans_loc.count() > 0 and trans_loc.is_visible():
            prompt = trans_loc.inner_text().strip()

        # Zdanie z luką
        usage_loc = self.page.locator("#question_usage, #usage").first
        if usage_loc.count() > 0 and usage_loc.is_visible():
            sentence = usage_loc.inner_text().strip()

        return prompt, sentence

    def extract_correct_answer_from_page(self) -> str:
        """Pobiera wyświetlone poprawne słówko z szarej ramki po błędzie."""
        # W nowym interfejsie InstaLing poprawne słowo jest w #word
        ans_loc = self.page.locator("#word, .word, #word_return, .return_word").first
        if ans_loc.count() > 0 and ans_loc.is_visible():
            txt = ans_loc.inner_text().strip()
            if txt:
                return txt

        # Fallback z JS
        cand = self.page.evaluate("""() => {
            const w = document.getElementById('word');
            if (w && w.innerText) return w.innerText.trim();
            const el = Array.from(document.querySelectorAll('div, span')).find(e => {
                const t = e.innerText ? e.innerText.trim() : '';
                return e.offsetParent !== null && e.children.length === 0 && t.length > 1 && !['Niepoprawnie', 'Poprawnie', 'Następne', 'Zgłoś błąd'].includes(t);
            });
            return el ? el.innerText.trim() : '';
        }""")
        return cand or ""

    def is_session_finished(self) -> bool:
        """Sprawdza czy sesja została ukończona (ekran gratulacji lub powrotu)."""
        body_txt = self.page.inner_text("body").lower()
        if "gratulacje" in body_txt or "ukończyłeś sesję" in body_txt or "koniec sesji" in body_txt:
            return True
        return False

    def handle_single_word(self) -> bool:
        """Rozwiązuje pojedyncze zadanie słówkowe. Zwraca True jeśli zadanie obsłużone, False jeśli koniec."""
        if self.is_session_finished():
            return False

        # Sprawdzamy czy pole input#answer jest gotowe
        ans_loc = self.page.locator("input#answer").first
        try:
            ans_loc.wait_for(state="visible", timeout=6000)
        except Exception:
            # Może to koniec sesji
            if self.is_session_finished():
                return False
            # Sprawdźmy czy nie ma przypadkiem przycisku Kontynuuj sesję
            cont_btn = self.page.get_by_text("Kontynuuj sesję").first
            if cont_btn.count() > 0 and cont_btn.is_visible():
                cont_btn.click(force=True)
                time.sleep(2.0)
            return True

        prompt, sentence = self.get_prompt_and_sentence()
        self.human_read_delay()

        known_answer = self.storage.get_word(prompt, sentence)
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
                print(f"[~] Celowy błąd dla statystyk ucznia: '{prompt}'")
                fake = known_answer[:-1] if len(known_answer) > 2 else "x"
                self.human_type("input#answer", fake)
            else:
                print(f"[?] Nowe słówko (brak w bazie): '{prompt}'")
                self.human_type("input#answer", "-")

            # Klikamy Sprawdź
            check_btn = self.page.locator("#check, button:has-text('Sprawdź')").first
            check_btn.click(force=True)
            time.sleep(1.8)

            # Odczytujemy poprawną odpowiedź z ekranu
            correct_ans = self.extract_correct_answer_from_page()
            if correct_ans:
                print(f"[+] ZAPAMIĘTANO SŁÓWKO: '{prompt}' -> '{correct_ans}'")
                self.storage.record_word(correct_ans, prompt, sentence)

            self.session_mistakes_count += 1
        else:
            print(f"[✓] Znaleziono w bazie: '{prompt}' -> '{known_answer}'")
            self.human_type("input#answer", known_answer)

            check_btn = self.page.locator("#check, button:has-text('Sprawdź')").first
            check_btn.click(force=True)
            time.sleep(1.5)
            self.session_correct_count += 1

        self.session_words_count += 1

        # Klikamy 'Następne'
        next_btn = self.page.locator("#nextword, button:has-text('Następne'), a:has-text('Następne')").first
        if next_btn.count() > 0 and next_btn.is_visible():
            time.sleep(random.uniform(0.8, 1.6))
            next_btn.click(force=True)
            time.sleep(random.uniform(1.0, 1.8))

        return True
