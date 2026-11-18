import csv
import html
import json
import re
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from zoneinfo import ZoneInfo

from .coupons import MONEY


SAO_PAULO = ZoneInfo("America/Sao_Paulo")
COLUMNS = (
    ("store", "Loja", "text", "ascending"),
    ("discount", "Desconto", "number", "descending"),
    ("minimum", "Compra mínima", "number", "ascending"),
    ("percent", "% no mínimo", "number", "descending"),
    ("remaining", "Fica a pagar no mínimo", "number", "ascending"),
    ("code", "Cupom", "text", "ascending"),
    ("first-seen", "Encontrado em", "date", "descending"),
)
STATUS_LABELS = {
    "running": "Em andamento",
    "completed": "Concluída",
    "interrupted": "Interrompida",
    "failed": "Falha na coleta",
    "no-coupons-detected": "Sem cupons detectados",
    "imported": "Importada",
}
THEME_SCRIPT = '''<script>
const themeKey = 'alie-report-theme';
const systemTheme = window.matchMedia('(prefers-color-scheme: dark)');
let savedTheme = null;
try {
  const theme = localStorage.getItem(themeKey);
  if (theme === 'dark' || theme === 'light') savedTheme = theme;
} catch { /* O navegador pode bloquear o armazenamento local. */ }

function updateTheme() {
  const dark = savedTheme ? savedTheme === 'dark' : systemTheme.matches;
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  document.getElementById('theme-toggle')?.setAttribute('aria-pressed', String(dark));
}
updateTheme();
</script>'''


def readable_text(value):
    return " ".join(re.sub(r"[\ue000-\uf8ff]", "", value).split())


def sao_paulo_time(value):
    return datetime.fromisoformat(value).astimezone(SAO_PAULO).strftime("%d/%m/%Y %H:%M:%S") if value else "—"


def coupon_code(row):
    if row["code"]:
        return row["code"]
    text = row["text"]
    amounts = list(MONEY.finditer(text))
    if len(amounts) != 2:
        return ""
    # Na central, o código sem rótulo aparece em linha própria entre os dois valores.
    lines = text[amounts[0].end():amounts[1].start()].split("\n")[1:-1]
    candidates = [line.strip() for line in lines if re.fullmatch(r"[A-Z0-9_-]{4,40}", line.strip())]
    return candidates[0] if len(candidates) == 1 else ""


def brl(cents):
    return f"R$ {cents / 100:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def csv_safe(value):
    value = str(value)
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def export(directory, run_id, rows, metadata):
    directory = Path(directory) / f"run-{run_id}"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "coupons.json").write_text(json.dumps(
        {"run_id": run_id, "run": metadata, "coupons": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = ["store", "store_url", "code", "discount_brl", "minimum_brl", "percent",
              "residual_at_minimum_brl", "first_seen_at", "last_seen_at", "text", "source_url"]
    with (directory / "coupons.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter=";")
        writer.writeheader()
        for row in rows:
            values = {**row, "discount_brl": brl(row["discount_cents"]),
                      "minimum_brl": brl(row["minimum_cents"]),
                      "residual_at_minimum_brl": brl(row["residual_cents"])}
            writer.writerow({key: csv_safe(values.get(key) or "") for key in fields})
    write_html(directory, run_id, rows, metadata)
    return directory


def write_html(directory, run_id, rows, metadata):
    esc = html.escape
    body = []
    stores = {}
    for row in rows:
        name = readable_text(row["store"])
        store_url = row["store_url"]
        key = f"url:{store_url}" if store_url else f"name:{name.casefold()}"
        if not name:
            name = f"Loja {store_url.rsplit('/', 1)[-1]}" if store_url else "Loja não identificada"
        store = stores.setdefault(key, {"id": esc(key), "name": name, "count": 0})
        store["count"] += 1
        label = esc(name)
        if row["store_url"]:
            label = f'<a href="{esc(row["store_url"], quote=True)}" target="_blank" rel="noopener noreferrer">{label}</a>'
        discount = row["discount_cents"]
        first_seen = row.get("first_seen_at") or ""
        observed = f'<time datetime="{esc(first_seen)}">{sao_paulo_time(first_seen)}</time>' if first_seen else '—'
        code = coupon_code(row)
        code_html = (f'<button class="copy-code" type="button" data-copy-code="{esc(code)}" '
                     f'aria-label="Copiar cupom {esc(code)}"><span class="coupon-token">{esc(code)}</span>'
                     '<span class="copy-label" aria-hidden="true">Copiar</span>'
                     '<span class="copy-label copy-feedback" aria-hidden="true">Copiado</span></button>') if code else '<span class="no-code">Sem código</span>'
        percent = f'{row["percent"]:.2f}'.replace(".", ",").rstrip("0").rstrip(",")
        body.append(f'<tr data-store-id="{store["id"]}" data-discount-cents="{discount}">'
                    f'<td class="store-name" data-sort-value="{esc(name)}">{label}</td>'
                    f'<td class="number discount" data-sort-value="{discount}">{brl(discount)}</td>'
                    f'<td class="number" data-sort-value="{row["minimum_cents"]}">{brl(row["minimum_cents"])}</td>'
                    f'<td class="number" data-sort-value="{row["percent"]}"><span class="percent">{percent}%</span></td>'
                    f'<td class="number" data-sort-value="{row["residual_cents"]}">{brl(row["residual_cents"])}</td>'
                    f'<td data-sort-value="{esc(code)}">{code_html}</td>'
                    f'<td class="date" data-sort-value="{esc(first_seen)}">{observed}</td></tr>')
    style = Path(__file__).with_name("report.css").read_text(encoding="utf-8")
    document = f'''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Alie — Cupons de loja</title>{THEME_SCRIPT}<style>{style}</style></head><body>
<header class="topbar"><div class="wrap"><span class="brand-mark" aria-hidden="true">A</span>
<span class="brand-name">Alie</span><span class="brand-context">AliExpress</span>
<button class="button theme-toggle" id="theme-toggle" type="button" aria-pressed="false" hidden>
<span aria-hidden="true">☾</span> Modo escuro</button></div></header>
<main class="wrap">
<div class="hero"><div><h1>Cupons de loja</h1>
<p class="run-info">Coleta {run_id} · <strong>{esc(STATUS_LABELS.get(metadata.get("status"), "Sem informação"))}</strong>'''
    if rounds_completed := metadata.get("rounds_completed"):
        document += f' · Rodadas concluídas: {rounds_completed}'
    if started_at := metadata.get("started_at"):
        document += f' · Início em {sao_paulo_time(started_at)}'
    document += f'''</p></div>
<dl class="metrics"><div><dt>Cupons na lista</dt><dd>{len(rows)}</dd></div>
<div><dt>Lojas na lista</dt><dd>{len(stores)}</dd></div></dl></div>
<section class="panel filter-panel" aria-labelledby="filter-heading">
<h2 id="filter-heading">Filtrar cupons</h2>
<div class="filter-controls">
<label class="field">Mostrar descontos <select id="discount-mode"><option value="above">Acima de</option><option value="below">Abaixo de</option></select></label>
<label class="field">Valor em reais <input id="discount-limit" type="text" inputmode="decimal" placeholder="Ex.: 20,00" aria-describedby="discount-error"></label>
<button class="button" id="clear-discount" type="button">Limpar valor</button>
</div><p class="filter-error" id="discount-error" role="status"></p>'''
    if stores:
        document += '''<details class="store-filter" id="store-filter">
<summary>Escolher lojas <span id="store-selection">Todas selecionadas</span></summary>
<div class="store-actions">
<input class="store-search" id="store-search" type="search" placeholder="Buscar pelo nome da loja" aria-label="Buscar pelo nome da loja">
<button class="button" id="select-all-stores" type="button">Marcar todas</button>
<button class="button" id="clear-stores" type="button">Desmarcar todas</button>
</div><div class="store-list">'''
        for store in sorted(stores.values(), key=lambda item: item["name"].casefold()):
            document += (f'<label><input type="checkbox" data-store-filter value="{store["id"]}" checked>'
                         f'<span class="store-filter-name">{esc(store["name"])} '
                         f'<small>({store["count"]})</small></span></label>')
        document += '</div><p class="store-empty" id="store-empty" hidden>Nenhuma loja com esse nome.</p></details>'
    document += f'''</section>
<section class="panel results" aria-labelledby="results-heading">
<div class="results-head"><h2 id="results-heading">Cupons encontrados</h2>
<span class="result-count" id="discount-status" role="status">{len(rows)} de {len(rows)} cupons</span></div>
<div class="table-tools"><p class="table-guide" id="table-guide">Selecione um título para ordenar ou clique em Copiar.
<span class="scroll-hint">Deslize a tabela para ver as outras colunas.</span></p>
<details class="glossary"><summary>Como ler os valores</summary><dl>
<div><dt>Compra mínima</dt><dd> — Quanto o pedido deve somar para usar o cupom.</dd></div>
<div><dt>% no mínimo</dt><dd> — Quanto o desconto representa se a compra atingir exatamente o mínimo.</dd></div>
<div><dt>Fica a pagar no mínimo</dt><dd> — Compra mínima menos desconto, antes de frete, impostos e outros ajustes.</dd></div>
<div><dt>Encontrado em</dt><dd> — Primeira vez que o coletor viu o cupom, no horário de São Paulo.</dd></div>
</dl></details></div>
<div class="table-scroll" role="region" tabindex="0" aria-labelledby="results-heading" aria-describedby="table-guide">
<table id="coupon-table"><thead><tr>'''
    for key, label, kind, direction in COLUMNS:
        document += (f'<th scope="col"><button class="sort-heading" type="button" data-sort-key="{key}" '
                     f'data-sort-type="{kind}" data-sort-direction="{direction}">{label}'
                     '<span class="sort-icon" aria-hidden="true"></span></button></th>')
    document += '</tr></thead><tbody>'
    document += "".join(body)
    empty_state = " hidden" if rows else ""
    document += (f'<tr id="no-matches"{empty_state}><td colspan="{len(COLUMNS)}">'
                 'Nenhum cupom com esses filtros. Tente outro valor ou marque mais lojas.</td></tr>')
    document += '''</tbody></table></div></section></main>
<div class="copy-status" id="copy-status" role="status"></div>
<script>
const themeToggle = document.getElementById('theme-toggle');
themeToggle.hidden = false;
updateTheme();
systemTheme.addEventListener('change', updateTheme);
themeToggle.addEventListener('click', () => {
  savedTheme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  try { localStorage.setItem(themeKey, savedTheme); } catch { /* O tema muda nesta página mesmo assim. */ }
  updateTheme();
});

const mode = document.getElementById('discount-mode');
const limit = document.getElementById('discount-limit');
const filterStatus = document.getElementById('discount-status');
const discountError = document.getElementById('discount-error');
const copyStatus = document.getElementById('copy-status');
const rows = [...document.querySelectorAll('[data-discount-cents]')];
const headings = [...document.querySelectorAll('[data-sort-key]')];
const storeFilters = [...document.querySelectorAll('[data-store-filter]')];
const storeFilter = document.getElementById('store-filter');
const storeSelection = document.getElementById('store-selection');
const storeSearch = document.getElementById('store-search');
const noMatches = document.getElementById('no-matches');
const preferencesKey = 'alie-report-preferences';
const preferences = { hiddenStores: new Set(), sortKey: 'percent', direction: 'descending' };

try {
  const saved = JSON.parse(sessionStorage.getItem(preferencesKey)) || {};
  if (saved.mode === 'above' || saved.mode === 'below') mode.value = saved.mode;
  if (typeof saved.limit === 'string') limit.value = saved.limit;
  if (headings.some(heading => heading.dataset.sortKey === saved.sortKey)
      && ['ascending', 'descending'].includes(saved.direction)) {
    preferences.sortKey = saved.sortKey;
    preferences.direction = saved.direction;
  }
  preferences.hiddenStores = new Set(saved.hiddenStores || []);
  if (storeFilter && typeof saved.storesOpen === 'boolean') storeFilter.open = saved.storesOpen;
  for (const input of storeFilters) input.checked = !preferences.hiddenStores.has(input.value);
} catch { /* O armazenamento pode estar indisponível ao abrir um arquivo local. */ }

function savePreferences() {
  for (const input of storeFilters) {
    if (input.checked) preferences.hiddenStores.delete(input.value);
    else preferences.hiddenStores.add(input.value);
  }
  try {
    sessionStorage.setItem(preferencesKey, JSON.stringify({
      mode: mode.value, limit: limit.value, sortKey: preferences.sortKey,
      direction: preferences.direction, hiddenStores: [...preferences.hiddenStores], storesOpen: storeFilter?.open,
    }));
  } catch { /* Os filtros continuam funcionando nesta página. */ }
}

function sortableValue(value, type) {
  if (value === '') return null;
  if (type === 'text') return value;
  const number = type === 'date' ? Date.parse(value) : Number(value);
  return Number.isFinite(number) ? number : null;
}

function sortCoupons() {
  const column = headings.findIndex(heading => heading.dataset.sortKey === preferences.sortKey);
  const type = headings[column].dataset.sortType;
  const direction = preferences.direction === 'ascending' ? 1 : -1;
  const sorted = rows.map(row => ({row, value: sortableValue(row.cells[column].dataset.sortValue, type)}));
  sorted.sort((a, b) => {
    if (a.value === null) return b.value === null ? 0 : 1;
    if (b.value === null) return -1;
    return direction * (type === 'text' ? a.value.localeCompare(b.value, 'pt-BR') : a.value - b.value);
  });
  for (const [index, heading] of headings.entries()) {
    if (index === column) heading.parentElement.setAttribute('aria-sort', preferences.direction);
    else heading.parentElement.removeAttribute('aria-sort');
  }
  const orderedRows = document.createDocumentFragment();
  for (const {row} of sorted) orderedRows.append(row);
  noMatches.before(orderedRows);
  savePreferences();
}

let copyTimer;
async function copyCoupon(button) {
  const code = button.dataset.copyCode;
  let copied = false;
  try {
    await navigator.clipboard.writeText(code);
    copied = true;
  } catch {
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(button.querySelector('.coupon-token'));
    selection.removeAllRanges();
    selection.addRange(range);
    try { copied = document.execCommand('copy'); } catch { /* O navegador pode bloquear a cópia. */ }
    if (copied) selection.removeAllRanges();
  }
  copyStatus.textContent = copied ? `Cupom ${code} copiado.` : 'Cupom selecionado. Pressione Ctrl+C para copiar.';
  if (copied) {
    button.dataset.copied = '';
    window.setTimeout(() => delete button.dataset.copied, 2000);
  }
  window.clearTimeout(copyTimer);
  if (copied) copyTimer = window.setTimeout(() => { copyStatus.textContent = ''; }, 3500);
}

function filterCoupons() {
  const value = limit.value.trim();
  const match = /^(\\d{1,3}(?:\\.\\d{3})+|\\d+)(?:,([0-9]{1,2}))?$/.exec(value)
    || /^(\\d+)\\.([0-9]{1,2})$/.exec(value);
  const threshold = match
    ? Number(match[1].replaceAll('.', '')) * 100 + Number((match[2] || '').padEnd(2, '0'))
    : NaN;
  const invalid = value !== '' && !Number.isSafeInteger(threshold);
  limit.setAttribute('aria-invalid', String(invalid));
  const selectedStores = new Set(storeFilters.filter(input => input.checked).map(input => input.value));
  let visible = 0;
  for (const row of rows) {
    const discount = Number(row.dataset.discountCents);
    const matchesAmount = value === '' || invalid || (mode.value === 'above'
      ? discount > threshold : discount < threshold);
    row.hidden = !selectedStores.has(row.dataset.storeId) || !matchesAmount;
    if (!row.hidden) visible++;
  }
  noMatches.hidden = visible > 0;
  filterStatus.textContent = `${visible} de ${rows.length} cupons`;
  discountError.textContent = invalid ? 'Digite um valor em reais, como 20,00.' : '';
  if (storeSelection) {
    storeSelection.textContent = selectedStores.size === storeFilters.length ? 'Todas selecionadas'
      : `${selectedStores.size} de ${storeFilters.length} selecionadas`;
  }
  savePreferences();
}

mode.addEventListener('change', filterCoupons);
limit.addEventListener('input', filterCoupons);
for (const heading of headings) heading.addEventListener('click', () => {
  if (preferences.sortKey === heading.dataset.sortKey) {
    preferences.direction = preferences.direction === 'ascending' ? 'descending' : 'ascending';
  } else {
    preferences.sortKey = heading.dataset.sortKey;
    preferences.direction = heading.dataset.sortDirection;
  }
  sortCoupons();
});
document.getElementById('coupon-table').addEventListener('click', event => {
  const button = event.target.closest('[data-copy-code]');
  if (button) copyCoupon(button);
});
for (const input of storeFilters) input.addEventListener('change', filterCoupons);
storeFilter?.addEventListener('toggle', savePreferences);
storeSearch?.addEventListener('input', () => {
  const normalize = value => value.normalize('NFD').replace(/\\p{Diacritic}/gu, '').toLocaleLowerCase('pt-BR');
  const query = normalize(storeSearch.value.trim());
  let found = false;
  for (const input of storeFilters) {
    const label = input.closest('label');
    label.hidden = !normalize(label.querySelector('.store-filter-name').textContent).includes(query);
    found ||= !label.hidden;
  }
  document.getElementById('store-empty').hidden = found;
});
function setStores(checked) {
  if (checked) preferences.hiddenStores.clear();
  for (const input of storeFilters) input.checked = checked;
  filterCoupons();
}
document.getElementById('select-all-stores')?.addEventListener('click', () => setStores(true));
document.getElementById('clear-stores')?.addEventListener('click', () => setStores(false));
document.getElementById('clear-discount').addEventListener('click', () => {
  limit.value = '';
  filterCoupons();
  limit.focus();
});
filterCoupons();
sortCoupons();
</script></body></html>'''
    path = Path(directory) / "report.html"
    # O servidor só vê a versão nova depois de a gravação estar completa.
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(document)
            stream.close()
            temporary.chmod(0o644)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
