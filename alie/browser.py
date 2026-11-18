import json
import time
from pathlib import Path

from .coupons import parse_card


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


def collect(driver, args, storage, run_id):
    script = Path(__file__).with_name("extract.js").read_text(encoding="utf-8")
    seen = set()
    idle = 0
    raw = {}
    for step in range(args.max_scrolls + 1):
        cards = driver.execute_script(script, args.selector)
        before = len(seen)
        for card in cards:
            raw[json.dumps(card, sort_keys=True, ensure_ascii=False)] = card
            coupon = parse_card(card, driver.current_url)
            if coupon:
                seen.add(coupon.key)
                storage.save(run_id, coupon)
        fresh = len(seen) - before
        # Encerrar por ausência de novos cartões brutos; ofertas rejeitadas também
        # podem ocupar várias páginas antes de aparecer um cupom suportado.
        print(f"Etapa {step:03}: {len(cards)} cartões visíveis, +{fresh} cupons, {len(seen)} únicos.", flush=True)
        state = (len(raw), driver.execute_script("return document.documentElement.scrollHeight"))
        if step and state == previous:
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
    if args.debug:
        directory = storage.directory / f"run-{run_id}"
        directory.mkdir(exist_ok=True)
        (directory / "cards.json").write_text(json.dumps(list(raw.values()), ensure_ascii=False, indent=2), encoding="utf-8")
        driver.save_screenshot(str(directory / "page.png"))
    if not seen:
        print("Nenhum cupom BRL reconhecido. Confira login, moeda BRL, página carregada e seletor.\n"
              "Isso não comprova ausência de cupons. Use --debug para guardar cartões e uma captura.")
    return len(seen)
