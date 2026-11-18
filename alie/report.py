import csv
import html
import json
from pathlib import Path


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
              "residual_at_minimum_brl", "text", "source_url"]
    with (directory / "coupons.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter=";")
        writer.writeheader()
        for row in rows:
            values = {**row, "discount_brl": brl(row["discount_cents"]),
                      "minimum_brl": brl(row["minimum_cents"]),
                      "residual_at_minimum_brl": brl(row["residual_cents"])}
            writer.writerow({key: csv_safe(values[key]) for key in fields})
    write_html(directory, run_id, rows, metadata)
    return directory


def write_html(directory, run_id, rows, metadata):
    esc = html.escape
    body = []
    for row in rows:
        label = esc(row["store"] or "Loja não identificada")
        if row["store_url"]:
            label = f'<a href="{esc(row["store_url"], quote=True)}" target="_blank" rel="noopener noreferrer">{label}</a>'
        discount = row["discount_cents"]
        body.append(f'<tr data-discount-cents="{discount}"><td>{label}</td><td>{brl(discount)}</td>'
                    f'<td>{brl(row["minimum_cents"])}</td><td>{row["percent"]:.2f}%</td>'
                    f'<td>{brl(row["residual_cents"])}</td><td>{esc(row["code"])}</td>'
                    f'<td><details><summary>Ver texto e restrições</summary><pre>{esc(row["text"])}</pre></details></td></tr>')
    document = '''<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Alie — cupons de loja</title><style>
body{font:16px system-ui;background:#111827;color:#e5e7eb;margin:32px}
h1{color:#6ee7b7}a{color:#93c5fd}table{border-collapse:collapse;width:100%;background:#1f2937}
th,td{padding:14px;text-align:left;border-bottom:1px solid #374151}th{color:#6ee7b7}
pre{white-space:pre-wrap;max-width:440px;font:inherit}.scroll{overflow:auto}p{max-width:1000px;line-height:1.6}
.filters{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:20px 0}
.filters input,.filters select,.filters button{font:inherit;padding:8px;color:inherit;background:#1f2937;border:1px solid #6b7280;border-radius:6px}
</style><h1>Cupons de loja</h1>'''
    document += f'<p>Coleta {run_id} · {len(rows)} candidatos · situação: {esc(metadata.get("status", ""))}'
    document += f' · iniciada em {esc(metadata.get("started_at", ""))} (UTC).</p>'
    document += '<p>Ordenados por percentual e depois por desconto nominal. “Restante” é mínimo menos cupom: '
    document += 'não inclui preço de um produto real, moedas, frete ou impostos. '
    document += 'Validade, produtos elegíveis e pagamento separado precisam ser conferidos no AliExpress.</p>'
    document += '''<div class="filters">
<label>Desconto <select id="discount-mode"><option value="above">Acima de</option><option value="below">Abaixo de</option></select></label>
<label>Valor (R$) <input id="discount-limit" type="text" inputmode="decimal" placeholder="100,00" aria-describedby="discount-status"></label>
<button id="clear-discount" type="button">Limpar filtro</button>
<span id="discount-status" role="status"></span>
</div>'''
    document += '<div class="scroll"><table><thead><tr><th>Loja</th><th>Desconto</th><th>Mínimo</th>'
    document += '<th>Percentual</th><th>Restante no mínimo</th><th>Código</th><th>Detalhes</th></tr></thead><tbody>'
    document += "".join(body) or '<tr><td colspan="7">Nenhum cupom passou pelos filtros desta coleta.</td></tr>'
    document += '''</tbody></table></div>
<script>
const mode = document.getElementById('discount-mode');
const limit = document.getElementById('discount-limit');
const filterStatus = document.getElementById('discount-status');
const rows = [...document.querySelectorAll('[data-discount-cents]')];

function filterCoupons() {
  const value = limit.value.trim();
  const match = /^(\\d{1,3}(?:\\.\\d{3})+|\\d+)(?:,([0-9]{1,2}))?$/.exec(value)
    || /^(\\d+)\\.([0-9]{1,2})$/.exec(value);
  const threshold = match
    ? Number(match[1].replaceAll('.', '')) * 100 + Number((match[2] || '').padEnd(2, '0'))
    : NaN;
  const invalid = value !== '' && !Number.isSafeInteger(threshold);
  limit.setAttribute('aria-invalid', String(invalid));
  let visible = 0;
  for (const row of rows) {
    const discount = Number(row.dataset.discountCents);
    row.hidden = value !== '' && !invalid && !(mode.value === 'above'
      ? discount > threshold : discount < threshold);
    if (!row.hidden) visible++;
  }
  filterStatus.textContent = invalid ? 'Digite um valor válido em reais, como 100,00.'
    : `${visible} de ${rows.length} cupons`;
}

mode.addEventListener('change', filterCoupons);
limit.addEventListener('input', filterCoupons);
document.getElementById('clear-discount').addEventListener('click', () => {
  limit.value = '';
  filterCoupons();
  limit.focus();
});
filterCoupons();
</script></html>'''
    (Path(directory) / "report.html").write_text(document, encoding="utf-8")
