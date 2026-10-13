from __future__ import annotations
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
        self.deliberate_errors_pool = set() # słówka celowo pomylone raz, by nie mylić ich przy powtórce

    def human_type(self, selector: str, text: str) -> None:
        """Symuluje naturalne pisanie na klawiaturze z opóźnieniami i sporadycznymi literówkami."""
        locator = self.page.locator(selector)
        locator.click()
        locator.fill("") # wyczyść pole
        
        speed_min = self.config.get("typing_speed_min_ms", 70) / 1000.0
        speed_max = self.config.get("typing_speed_max_ms", 160) / 1000.0
        typo_chance = self.config.get("typo_chance_percent", 5) / 100.0

        for char in text:
            # Losowa literówka
            lower_char = char.lower()
            if lower_char in KEYBOARD_NEIGHBORS and random.random() < typo_chance:
                wrong_char = random.choice(KEYBOARD_NEIGHBORS[lower_char])
                locator.press_sequentially(wrong_char, delay=int(random.uniform(speed_min, speed_max) * 1000))
                time.sleep(random.uniform(0.2, 0.45))
                self.page.keyboard.press("Backspace")
                time.sleep(random.uniform(0.1, 0.25))

            # Właściwy znak
            locator.press_sequentially(char, delay=int(random.uniform(speed_min, speed_max) * 1000))
            time.sleep(random.uniform(speed_min, speed_max))

    def human_read_delay(self) -> None:
        """Symuluje czas potrzebny człowiekowi na przeczytanie zdania."""
        t_min = self.config.get("read_time_min_s", 1.8)
        t_max = self.config.get("read_time_max_s", 3.8)
        time.sleep(random.uniform(t_min, t_max))

    def find_element_text(self, selectors: list) -> str:
        """Zwraca tekst pierwszego pasującego i widocznego selektora."""
        for sel in selectors:
            try:
                loc = self.page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    text = loc.first.inner_text().strip()
                    if text:
                        return text
            except Exception:
                continue
        return ""

    def get_prompt_and_sentence(self) -> Tuple[str, str]:
        """Wycina polski prompt (słowo) oraz kontekst zdania z ekranu."""
        # Selektory słowa po polsku
        prompt_selectors = [
            "#word", ".word", "#polish_word", ".polish_word",
            "#learning_card .word", "#card_word", ".translations"
        ]
        prompt = self.find_element_text(prompt_selectors)

        # Selektory zdania z luką
        sentence_selectors = [
            "#usage", ".usage", "#sentence", ".sentence",
            "#question", ".question", "#learning_card .usage"
        ]
        sentence = self.find_element_text(sentence_selectors)

        return prompt, sentence

    def find_input_selector(self) -> Optional[str]:
        candidates = ["input#answer", "input[name='answer']", "input.answer", "input[type='text']"]
        for sel in candidates:
            try:
                loc = self.page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    return sel
            except Exception:
                continue
        return None

    def find_check_button(self) -> Optional[Locator]:
        candidates = [
            "#check", "button#check", "input#check",
            "button:has-text('Sprawdź')", "div.btn-check", ".btn_check"
        ]
        for sel in candidates:
            try:
                loc = self.page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    return loc.first
            except Exception:
                continue
        return None

    def find_next_button(self) -> Optional[Locator]:
        candidates = [
            "#nextword", "button#nextword", "input#nextword",
            "button:has-text('Następne')", "button:has-text('Dalej')",
            ".next_button", "#next_word"
        ]
        for sel in candidates:
            try:
                loc = self.page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    return loc.first
            except Exception:
                continue
        return None

    def extract_correct_answer_from_page(self) -> str:
        """Pobiera wyświetloną przez platformę poprawną odpowiedź w przypadku błędu."""
        candidates = [
            "#word_return", ".return_word", "#word_return_container",
            "#correct_answer", ".correct_answer", "#answer_result",
            ".answer_box .correct"
        ]
        ans = self.find_element_text(candidates)
        if ans:
            # Często tekst to 'Poprawna odpowiedź: cat' lub samo słowo
            if ":" in ans:
                ans = ans.split(":")[-1].strip()
            return ans
        
        # Fallback: szukanie w widocznym kontenerze błędu
        try:
            container = self.page.locator("#word_return_container, .answer_box")
            if container.count() > 0 and container.first.is_visible():
                txt = container.first.inner_text().strip()
                if txt:
                    return txt.split("\n")[-1].strip()
        except Exception:
            pass

        return ""

    def is_session_finished(self) -> bool:
        """Sprawdza czy pojawił się ekran podsumowania lub gratulacji."""
        indicators = [
            "text=Gratulacje", "text=ukończyłeś sesję", "text=Koniec sesji",
            "#return_main", "a:has-text('Wróć do strony głównej')",
            "text=Dokończono sesję"
        ]
        for sel in indicators:
            try:
                loc = self.page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    return True
            except Exception:
                continue
        return False

    def handle_single_word(self) -> bool:
        """Rozwiązuje pojedyncze zadanie słówkowe. Zwraca True jeśli zadanie obsłużone, False jeśli koniec."""
        if self.is_session_finished():
            return False

        input_sel = self.find_input_selector()
        if not input_sel:
            # Może jeszcze ładuje się strona lub to koniec
            time.sleep(1.0)
            if self.is_session_finished():
                return False
            input_sel = self.find_input_selector()
            if not input_sel:
                return False

        # Pobieramy kontekst i polskie słówko
        prompt, sentence = self.get_prompt_and_sentence()
        self.human_read_delay()

        known_answer = self.storage.get_word(prompt, sentence)
        target_acc = self.config.get("target_accuracy_percent", 91)
        word_id = f"{prompt}_{sentence}"

        is_first_encounter = known_answer is None
        should_make_deliberate_mistake = (
            known_answer is not None and
            word_id not in self.deliberate_errors_pool and
            random.random() > (target_acc / 100.0)
        )

        if is_first_encounter or should_make_deliberate_mistake:
            # 1. Nie znamy słowa LUB celowy błąd dla statystyk
            if should_make_deliberate_mistake:
                self.deliberate_errors_pool.add(word_id)
                print(f"[~] Celowy błąd dla symulacji ucznia: '{prompt}'")
                # Wpisujemy celowo literówkę lub zbędny znak
                fake_ans = known_answer[:-1] if len(known_answer) > 2 else "x"
                self.human_type(input_sel, fake_ans)
            else:
                print(f"[?] Nowe słówko nieznane w bazie: '{prompt}' (zdanie: '{sentence[:30]}...')")
                # Wpisujemy pusty lub pojedynczy znak, aby poznać poprawną odpowiedź
                self.human_type(input_sel, "-")

            check_btn = self.find_check_button()
            if check_btn:
                check_btn.click()
            else:
                self.page.keyboard.press("Enter")

            time.sleep(1.2)
            # Odczytujemy poprawną odpowiedź z serwisu InstaLing
            correct_ans = self.extract_correct_answer_from_page()
            if correct_ans:
                print(f"[+] ZAPAMIĘTANO DO BAZY: '{prompt}' -> '{correct_ans}'")
                self.storage.record_word(correct_ans, prompt, sentence)

            self.session_mistakes_count += 1
        else:
            # 2. Słówko znane - wpisujemy bezbłędnie
            print(f"[✓] Znaleziono w bazie: '{prompt}' -> '{known_answer}'")
            self.human_type(input_sel, known_answer)

            check_btn = self.find_check_button()
            if check_btn:
                check_btn.click()
            else:
                self.page.keyboard.press("Enter")

            time.sleep(1.0)
            self.session_correct_count += 1

        self.session_words_count += 1

        # Klikamy 'Następne słówko'
        next_btn = self.find_next_button()
        if next_btn:
            time.sleep(random.uniform(0.6, 1.4))
            next_btn.click()
            time.sleep(random.uniform(0.7, 1.2))

        return True
