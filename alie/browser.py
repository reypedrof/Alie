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


def collect_round(driver, args, storage, run_id, script, seen, raw):
    round_cards = set()
    idle = 0
    previous = None
    for step in range(args.max_scrolls + 1):
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
        # Encerrar por ausência de novos cartões brutos; ofertas rejeitadas também
        # podem ocupar várias páginas antes de aparecer um cupom suportado.
        print(f"Etapa {step:03}: {len(cards)} cartões visíveis, +{fresh} cupons, {len(seen)} únicos.", flush=True)
        state = (len(round_cards), driver.execute_script("return document.documentElement.scrollHeight"))
        if state == previous:
            idle += 1
        else:
            idle = 0
        previous = state
        if idle >= args.idle_rounds or step >= args.max_scrolls:
            break
        driver.execute_script("""
          const els = [document.scrollingElement, ...document.querySelectorAll('main, section, div')];
          const scrollable = els.filter(el => el && el.clientHeight > 150 &&
            el.scrollHeight > el.clientHeight + 50 &&
            (el === document.scrollingElement || /auto|scroll/.test(getComputedStyle(el).overflowY)));
          for (const el of scrollable) el.scrollBy(0, Math.max(500, el.clientHeight * 0.8));
        """)
        time.sleep(args.delay)


def collect(driver, args, storage, run_id, publish_round):
    script = Path(__file__).with_name("extract.js").read_text(encoding="utf-8")
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
            driver.execute_script("window.scrollTo(0, 0)")
        before = len(seen)
        collect_round(driver, args, storage, run_id, script, seen, raw)
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
