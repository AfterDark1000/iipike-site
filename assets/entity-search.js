/* Fast local filtering; no network calls or automatic edits. */
(() => {
  'use strict';
  const input = document.getElementById('entity-filter');
  const status = document.getElementById('entity-filter-status');
  if (!input || !status) return;
  const sections = [...document.querySelectorAll('[data-entity-section]')];
  const cards = [...document.querySelectorAll('.entity-tile')];
  const normalize = text => (text || '').toLocaleLowerCase('ru-RU').normalize('NFKC').trim();
  const update = () => {
    const query = normalize(input.value);
    let shown = 0;
    cards.forEach(card => {
      const match = normalize(card.querySelector('strong')?.textContent).includes(query);
      card.hidden = !match;
      if (match) shown++;
    });
    sections.forEach(section => {
      section.hidden = ![...section.querySelectorAll('.entity-tile')].some(card => !card.hidden);
    });
    status.textContent = query ? ('Найдено: ' + shown) : ('В справочнике ' + cards.length + ' названий');
  };
  input.addEventListener('input', update);
})();
