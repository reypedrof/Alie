const action = arguments[0];
const root = document.scrollingElement;
let target = root;
if (root.scrollHeight - root.clientHeight <= 32) {
  // Algumas centrais rolam a lista dentro da página, em vez de rolar a janela.
  let largest = 0;
  for (const el of document.querySelectorAll('main, section, div')) {
    const rect = el.getBoundingClientRect();
    if (el.clientHeight < 150 || el.scrollHeight <= el.clientHeight + 32 ||
        rect.bottom <= 0 || rect.top >= innerHeight || rect.width < innerWidth / 2) continue;
    const style = getComputedStyle(el);
    if (style.visibility !== 'visible' || !/auto|scroll/.test(style.overflowY)) continue;
    const area = rect.width * Math.min(rect.height, innerHeight);
    if (area > largest) {
      largest = area;
      target = el;
    }
  }
}

if (action === 'advance') {
  target.scrollBy({top: Math.max(1, target.clientHeight * 0.8), behavior: 'instant'});
  return;
}
if (action === 'top') {
  root.scrollTo({top: 0, behavior: 'instant'});
  if (target !== root) target.scrollTo({top: 0, behavior: 'instant'});
  return;
}

const offset = Math.round(target.scrollTop);
const maxOffset = Math.max(0, target.scrollHeight - target.clientHeight);
const atBottom = maxOffset - offset <= 4;
const endText = /^\s*[-–—]?\s*(resultados carregados|todos os resultados foram carregados|all results loaded|no more results)\s*[-–—]?\s*$/i;
const endMarker = atBottom && [...document.querySelectorAll('div, span, p')].some(el =>
  el.children.length === 0 && endText.test(el.textContent) && el.getClientRects().length &&
  getComputedStyle(el).visibility === 'visible');
return {offset, maxOffset, atBottom, endMarker};
