// Executado somente na página aberta. Não clica em coletar, comprar ou pagar.
const customSelector = arguments[0];
const currency = /R\$\s*\d[\d.,\s\u00a0\u202f]*/gi;
const valid = el => {
  const text = el.innerText || '';
  return text.length <= 1800 && (text.match(currency) || []).length === 2 &&
    /off|desconto|economize|\bsave\b/i.test(text) &&
    /pedidos?|orders?|compras?|spend|m[ií]nim|acima|\bover\b/i.test(text);
};
const visible = el => !!(el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden');
const candidates = customSelector ? [...document.querySelectorAll(customSelector)] :
  [...document.querySelectorAll('div, article, li, section')].filter(el => visible(el) && valid(el));
// Partir do menor cartão e subir somente enquanto continuar sendo uma única oferta.
// O pai pode conter o link da loja que não está no bloco dos valores.
const cards = new Set();
for (const el of candidates) {
  if (!customSelector && [...el.children].some(valid)) continue;
  let card = el;
  if (!customSelector) {
    while (card.parentElement && card.parentElement !== document.body &&
           card.parentElement !== document.documentElement && valid(card.parentElement)) {
      card = card.parentElement;
    }
  }
  cards.add(card);
}
return [...cards].map(el => {
  const links = [...el.querySelectorAll('a[href]')];
  const store = links.find(a => /\/(store|store-home)\/\d+/.test(a.href));
  return {
    text: el.innerText,
    store: store ? (store.innerText || store.title || '').trim() : '',
    store_url: store ? store.href : ''
  };
});
