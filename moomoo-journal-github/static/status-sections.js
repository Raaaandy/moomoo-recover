// Move existing cards so their editors and event listeners remain intact.
let closedCyclesExpanded = false, closedExecutionsExpanded = false;
function separateCycleStatuses() {
  const host = $('cycleCards');
  const cards = [...host.querySelectorAll('[data-cycle]')];
  if (!cards.length) return;
  const cycles = new Map(cycleData.map(c => [c.id, c]));
  const groups = [
    {key: 'open', title: '持仓中', hint: '包括部分平仓的交易', cards: []},
    {key: 'closed', title: '已结束', hint: '已全部平仓，可统一复盘', cards: []},
    {key: 'pending', title: '待核对', hint: '开平仓记录或调整后的持仓尚未确认', cards: []}
  ];
  for (const card of cards) {
    const status = cycles.get(card.dataset.cycle)?.status;
    const index = status === '已平仓' ? 1 : ['持仓中', '部分平仓'].includes(status) ? 0 : 2;
    groups[index].cards.push(card);
  }
  const sections = groups.filter(g => g.key !== 'pending' || g.cards.length).map(g => {
    const section = document.createElement(g.key === 'closed' ? 'details' : 'section');
    if (g.key === 'closed') {
      section.open = closedCyclesExpanded;
      section.addEventListener('toggle', () => { if (section.isConnected) closedCyclesExpanded = section.open; });
    }
    section.className = `trade-status-section status-${g.key}`;
    const heading = document.createElement(g.key === 'closed' ? 'summary' : 'div');
    heading.className = 'trade-status-heading';
    const title = document.createElement('h3');
    title.textContent = `${g.title} · ${g.cards.length} 笔交易`;
    const hint = document.createElement('span');
    hint.textContent = g.key === 'closed' ? '点击展开 / 收起已平仓交易' : g.hint;
    heading.append(title, hint);
    section.append(heading, ...g.cards);
    if (!g.cards.length) {
      const empty = document.createElement('p');
      empty.className = 'cycle-help';
      empty.textContent = `当前筛选范围内暂无${g.title}的完整交易。`;
      section.append(empty);
    }
    return section;
  });
  host.replaceChildren(...sections);
}
function compactExecutionCards() {
  const host = $('executionCards');
  if (!host) return;
  const closed = document.createElement('details');
  closed.className = 'closed-executions';
  closed.open = closedExecutionsExpanded;
  closed.addEventListener('toggle', () => { if (closed.isConnected) closedExecutionsExpanded = closed.open; });
  const heading = document.createElement('summary');
  const body = document.createElement('div');
  body.className = 'closed-execution-grid';
  let count = 0;
  for (const item of [...host.children]) {
    const cards = item.matches('[data-execution]') ? [item] : [...item.querySelectorAll('[data-execution]')];
    if (!cards.length) continue;
    // Shared executions stay visible if any associated lifecycle remains open.
    const fullyClosed = cards.every(card => {
      const related = cycleData.filter(c => c.fills.some(r => r.pair_id === card.dataset.execution));
      return related.length > 0 && related.every(c => c.status === '已平仓');
    });
    if (fullyClosed) { body.append(item); count += cards.length; }
  }
  if (count) {
    heading.textContent = `已平仓组合 · ${count} 张卡片（点击展开 / 收起）`;
    closed.append(heading, body);
    host.append(closed);
  }
}
const loadCyclesBeforeStatusSections = loadCycles;
loadCycles = async function(q) {
  await loadCyclesBeforeStatusSections(q);
  separateCycleStatuses();
  linkPanel.hidden=q.asset==='stock';
  if(q.asset!=='stock') compactExecutionCards();
  applyTradeTicker();
};
