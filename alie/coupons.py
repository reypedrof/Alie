import hashlib
import re
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlparse


MONEY = re.compile(r"R\$\s*([\d]+(?:[.,\s\u00a0\u202f][\d]+)*)", re.I)
DISCOUNT = re.compile(r"\boff\b|desconto|economize|\bsave\b", re.I)
MINIMUM = re.compile(r"pedidos?|orders?|compras?|spend|m[ií]nim|acima|\bover\b", re.I)


def money_cents(value: str) -> int:
    """Aceita BRL pt-BR e BRL com formatação inglesa, sem usar float."""
    value = re.sub(r"\s", "", value)
    if not re.fullmatch(r"\d+(?:[.,]\d+)*", value):
        raise ValueError(f"Valor monetário inválido: {value}")
    if "," in value and "." in value:
        decimal = "," if value.rfind(",") > value.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        value = value.replace(thousands, "").replace(decimal, ".")
    elif "," in value or "." in value:
        sep = "," if "," in value else "."
        parts = value.split(sep)
        if len(parts[-1]) == 3 and all(len(p) == 3 for p in parts[1:]):
            value = "".join(parts)
        elif len(parts) == 2 and len(parts[-1]) in (1, 2):
            value = value.replace(sep, ".")
        else:
            raise ValueError("Separadores monetários ambíguos")
    try:
        amount = Decimal(value)
        if amount.as_tuple().exponent < -2:
            raise ValueError("Valor com mais de duas casas decimais")
        return int(amount * 100)
    except InvalidOperation as exc:
        raise ValueError("Valor inválido") from exc


def store_url(href: str) -> str:
    parsed = urlparse(urljoin("https://www.aliexpress.com", href))
    if parsed.scheme != "https" or not (parsed.hostname == "aliexpress.com" or
                                            (parsed.hostname or "").endswith(".aliexpress.com")):
        return ""
    match = re.search(r"/(?:store|store-home)/([0-9]+)", parsed.path)
    return f"https://www.aliexpress.com/store/{match[1]}" if match else ""


@dataclass(frozen=True)
class Coupon:
    key: str
    discount_cents: int
    minimum_cents: int
    store: str
    store_url: str
    code: str
    text: str
    source_url: str

    @property
    def ratio(self):
        return self.discount_cents / self.minimum_cents

    def to_dict(self):
        return {**asdict(self), "percent": round(self.ratio * 100, 2),
                "residual_cents": self.minimum_cents - self.discount_cents}


def parse_card(card: dict, source_url: str) -> Coupon | None:
    text = card.get("text", "").strip()
    matches = list(MONEY.finditer(text))
    # Não misturar cupons de cartões/pais que contenham múltiplas ofertas.
    if len(matches) != 2 or len(text) > 1800:
        return None
    if not DISCOUNT.search(text) or not MINIMUM.search(text):
        return None
    # Rejeitar cupons percentuais: o teto em reais não é o desconto fixo.
    if re.search(r"\d\s*%", text):
        return None
    first, second = matches
    prefix = text[:first.start()]
    middle = text[first.end():second.start()]
    # Os cartões suportados dizem desconto primeiro, mínimo depois.
    if not DISCOUNT.search(prefix + middle) or not MINIMUM.search(middle):
        return None
    try:
        discount = money_cents(first[1])
        minimum = money_cents(second[1])
    except ValueError:
        return None
    if discount <= 0 or minimum <= 0 or discount > minimum:
        return None
    url = store_url(card.get("store_url", ""))
    store = str(card.get("store", "")).strip()
    code_match = re.search(r"(?:c[oó]digo|code)\s*[:：]\s*([A-Z0-9_-]{3,40})", text, re.I)
    code = code_match[1] if code_match else ""
    normalized = " ".join(text.split())
    identity = [url or store or normalized, discount, minimum, code]
    key = hashlib.sha256(repr(identity).encode()).hexdigest()[:24]
    return Coupon(key, discount, minimum, store, url, code, text, source_url)
