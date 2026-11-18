import argparse
import json
import math
import os
import signal
import sys
from pathlib import Path
from urllib.parse import urlparse

from .coupons import money_cents, parse_card
from .report import brl, export
from .storage import Storage

DEFAULT_URL = "https://www.aliexpress.com/ssr/300003448/glo-coupon-center-8ymmrs"


def percentage(value):
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 100:
        raise argparse.ArgumentTypeError("Informe um percentual entre 0 e 100")
    return number


def parser():
    root = argparse.ArgumentParser(description="Alie: busca local de cupons de loja, sem IA ou API paga.")
    root.add_argument("--data-dir", default=os.environ.get("ALIE_DATA_DIR", "data"))
    sub = root.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="Abrir Chromium e coletar cupons da central")
    scan.add_argument("--url", default=DEFAULT_URL)
    scan.add_argument("--selenium-url", default=os.environ.get("SELENIUM_URL", "http://browser:4444"))
    scan.add_argument("--no-prompt", action="store_true", help="Usar sessão já configurada, sem aguardar Enter")
    duration = scan.add_mutually_exclusive_group()
    duration.add_argument("--rounds", type=int, default=3, help="Total de varreduras, recarregando a página entre elas (padrão: 3)")
    duration.add_argument("--loop", action="store_true", help="Continuar as varreduras até receber uma interrupção")
    scan.add_argument("--round-pause", type=float, default=30, help="Espera em segundos entre rodadas no modo contínuo")
    scan.add_argument("--max-scrolls", type=int, help="Teto opcional de rolagens por rodada. Por padrão, vai até o fim da página")
    scan.add_argument("--idle-rounds", type=int, default=6, help="Etapas sem novos resultados no fim da página")
    scan.add_argument("--delay", type=float, default=3, help="Espera em segundos após cada rolagem ou recarga")
    scan.add_argument("--selector", help="Seletor CSS dos cartões, caso o layout mude")
    scan.add_argument("--debug", action="store_true", help="Salvar cartões brutos e captura da página")
    imp = sub.add_parser("import-cards", help="Reprocessar JSON de cartões sem abrir navegador")
    imp.add_argument("file", type=Path)
    imp.add_argument("--source-url", default=DEFAULT_URL)
    report = sub.add_parser("export", help="Exportar uma coleta salva; padrão: a mais recente")
    report.add_argument("--run", type=int)
    sub.add_parser("runs", help="Listar histórico de coletas")
    for child in (scan, imp, report):
        child.add_argument("--min-percent", type=percentage, default=80)
        child.add_argument("--min-discount", default="0", help="Desconto nominal mínimo em reais, ex.: 100,00")
    return root


def show(storage, args, run_id=None, *, list_coupons=True):
    run_id, rows = storage.results(run_id, args.min_percent, money_cents(args.min_discount))
    if run_id is None or not storage.metadata(run_id):
        print("Coleta não encontrada.", file=sys.stderr)
        return 1
    directory = export(storage.directory, run_id, rows, storage.metadata(run_id))
    print(f"\n{len(rows)} candidatos nos filtros. Arquivos: {directory}")
    for row in rows[:30] if list_coupons else ():
        print(f'{row["percent"]:6.2f}% | {brl(row["discount_cents"])} / {brl(row["minimum_cents"])}'
              f' | {row["store"] or "loja não identificada"} | {row["store_url"]}')
    return 0


def main():
    root = parser()
    args = root.parse_args()
    storage = Storage(args.data_dir)
    if args.command == "runs":
        for row in storage.db.execute("SELECT id,started_at,status,(SELECT COUNT(*) FROM sightings WHERE run_id=runs.id) FROM runs ORDER BY id DESC"):
            print(f"{row[0]} | {row[1]} | {row[2]} | {row[3]} cupons")
        return 0
    try:
        money_cents(args.min_discount)
    except ValueError as exc:
        root.error(str(exc))
    if args.command == "export":
        return show(storage, args, args.run)
    if args.command == "import-cards":
        cards = json.loads(args.file.read_text(encoding="utf-8"))
        if not isinstance(cards, list) or not all(isinstance(c, dict) and isinstance(c.get("text"), str) for c in cards):
            root.error("O arquivo deve conter uma lista de objetos com o campo text")
        run_id = storage.start(args.source_url)
        for card in cards:
            coupon = parse_card(card, args.source_url)
            if coupon:
                storage.save(run_id, coupon)
        storage.finish(run_id, "imported")
        return show(storage, args, run_id)
    parsed = urlparse(args.url)
    if parsed.scheme != "https" or not (parsed.hostname == "aliexpress.com" or (parsed.hostname or "").endswith(".aliexpress.com")):
        root.error("Use uma URL HTTPS do AliExpress")
    if (args.max_scrolls is not None and args.max_scrolls < 0) or args.idle_rounds < 1 or not math.isfinite(args.delay) or args.delay < 1:
        root.error("Use max-scrolls >= 0, idle-rounds >= 1 e delay >= 1 segundo")
    if args.rounds < 1:
        root.error("Use rounds >= 1")
    if not math.isfinite(args.round_pause) or args.round_pause < 1:
        root.error("Use round-pause >= 1 segundo")
    from .browser import collect, connect

    def stop_scan(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_scan)
    driver = None
    run_id = None
    exit_code = 0
    try:
        driver = connect(args.selenium_url)
        driver.get(args.url)
        print("Abra http://localhost:7900/?autoconnect=1&resize=scale para ver o navegador.\n"
              "Entre na sua conta se necessário, selecione Brasil / BRL e abra a central de cupons.\n"
              "O perfil será preservado no volume Docker.", flush=True)
        if not args.no_prompt:
            input("Quando os cupons estiverem visíveis, pressione Enter neste terminal: ")
        else:
            import time
            time.sleep(args.delay)
        current = urlparse(driver.current_url)
        if current.scheme != "https" or not (current.hostname == "aliexpress.com" or (current.hostname or "").endswith(".aliexpress.com")):
            raise ValueError("O navegador precisa estar em uma página HTTPS do AliExpress")
        run_id = storage.start(driver.current_url)
        count = collect(driver, args, storage, run_id,
                        lambda: show(storage, args, run_id, list_coupons=False))
        storage.finish(run_id, "completed" if count else "no-coupons-detected")
    except (KeyboardInterrupt, EOFError):
        if run_id:
            storage.finish(run_id, "interrupted")
        print("\nColeta interrompida; resultados já encontrados foram preservados.")
        exit_code = 130
    except Exception as exc:
        if run_id:
            storage.finish(run_id, "failed")
        print(f"Falha na coleta: {exc}", file=sys.stderr)
        exit_code = 1
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
    if run_id:
        show(storage, args, run_id)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
