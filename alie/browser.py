import json
import time
from itertools import count
from pathlib import Path

from .coupons import parse_card


LOGIN_DRAWER = ".cosmos-drawer-right:has(button.dialog-close-icon)"


def dismiss_login_drawer(driver, wait_for_appearance=False):
    from selenium.common.exceptions import (
        ElementClickInterceptedException,
        ElementNotInteractableException,
        StaleElementReferenceException,
        TimeoutException,
    )
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    def visible_drawer(browser):
        return next((element for element in browser.find_elements(By.CSS_SELECTOR, LOGIN_DRAWER)
                     if element.is_displayed()), None)

    ignored = (StaleElementReferenceException, ElementNotInteractableException, ElementClickInterceptedException)
    if wait_for_appearance:
        try:
            WebDriverWait(driver, 7, ignored_exceptions=ignored).until(visible_drawer)
        except TimeoutException:
            return
    elif visible_drawer(driver) is None:
        return

    def close_drawer(browser):
        drawer = visible_drawer(browser)
        if drawer is None:
            return True
        for selector in ("button.dialog-close-icon", "button.cosmos-drawer-close"):
            for button in drawer.find_elements(By.CSS_SELECTOR, selector):
                if button.is_displayed() and button.is_enabled():
                    button.click()
                    return True
        return False

    wait = WebDriverWait(driver, 5, ignored_exceptions=ignored)
    try:
        wait.until(close_drawer)
        wait.until(lambda browser: visible_drawer(browser) is None)
    except TimeoutException as exc:
        raise RuntimeError("O painel de login não fechou. Rode sem --no-prompt e feche o painel no navegador antes de pressionar Enter.") from exc
    print("Painel de login fechado.", flush=True)


def connect(remote_url):
    from selenium import webdriver

    options = webdriver.ChromeOptions()
    options.add_argument("--user-data-dir=/home/seluser/alie-profile")
    options.add_argument("--lang=pt-BR")
    options.add_argument("--window-size=1440,1000")
    options.page_load_strategy = "eager"
    driver = webdriver.Remote(command_executor=remote_url, options=options)
    driver.set_page_load_timeout(60)
    driver.set_script_timeout(20)
    return driver


def collect_round(driver, args, storage, run_id, script, scroll, seen, raw):
    round_cards = set()
    idle = 0
    scrolls = 0
    previous = None
    for step in count():
        dismiss_login_drawer(driver, wait_for_appearance=(step == 0))
        cards = driver.execute_script(script, args.selector)
        before = len(seen)
        source_url = driver.current_url
        coupons = {}
        for card in cards:
            card_key = json.dumps(card, sort_keys=True, ensure_ascii=False)
            round_cards.add(card_key)
            if args.debug:
                raw[card_key] = card
            coupon = parse_card(card, source_url)
            if coupon:
                seen.add(coupon.key)
                coupons[coupon.key] = coupon
        if coupons:
            storage.save_many(run_id, coupons.values())
        fresh = len(seen) - before
        position = driver.execute_script(scroll, "measure")
        offset, max_offset = position["offset"], position["maxOffset"]
        print(f"Etapa {step:03}: posição {offset}/{max_offset} px, {len(cards)} cartões, "
              f"+{fresh} cupons, {len(seen)} únicos.", flush=True)
        state = (offset, max_offset, len(round_cards))
        idle = idle + 1 if state == previous else 0
        previous = state
        if position["endMarker"]:
            print("Fim da página confirmado pelo aviso 'Resultados carregados'.", flush=True)
            return
        if idle >= args.idle_rounds:
            if position["atBottom"]:
                print("Fim da página confirmado após esperar por novos resultados.", flush=True)
                return
            raise RuntimeError("A rolagem parou antes do fim da página. Confira a central no navegador.")
        if not position["atBottom"]:
            if args.max_scrolls is not None and scrolls >= args.max_scrolls:
                print("Limite de rolagens atingido. A rodada pode estar incompleta.", flush=True)
                return
            driver.execute_script(scroll, "advance")
            scrolls += 1
        time.sleep(args.delay)


def collect(driver, args, storage, run_id, publish_round):
    script = Path(__file__).with_name("extract.js").read_text(encoding="utf-8")
    scroll = Path(__file__).with_name("scroll.js").read_text(encoding="utf-8")
    seen = set()
    raw = {}
    rounds = count(1) if args.loop else range(1, args.rounds + 1)
    for number in rounds:
        suffix = "" if args.loop else f"/{args.rounds}"
        print(f"\nRodada {number}{suffix}", flush=True)
        if number > 1:
            if args.loop:
                time.sleep(args.round_pause)
                raw.clear()
            driver.execute_script("history.scrollRestoration = 'manual'")
            driver.refresh()
            time.sleep(args.delay)
        driver.execute_script(scroll, "top")
        before = len(seen)
        collect_round(driver, args, storage, run_id, script, scroll, seen, raw)
        print(f"Rodada {number} concluída. {len(seen) - before} novos cupons, {len(seen)} no total.", flush=True)
        storage.complete_round(run_id, number)
        publish_round()
        if args.debug:
            directory = storage.directory / f"run-{run_id}"
            (directory / "cards.json").write_text(json.dumps(list(raw.values()), ensure_ascii=False, indent=2), encoding="utf-8")
            driver.save_screenshot(str(directory / "page.png"))
    if not seen:
        print("Nenhum cupom BRL reconhecido. Confira login, moeda BRL, página carregada e seletor.\n"
              "Isso não comprova ausência de cupons. Use --debug para guardar cartões e uma captura.")
    return len(seen)
