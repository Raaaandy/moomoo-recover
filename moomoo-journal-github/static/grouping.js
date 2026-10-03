// Presentation only: the source records, pairing and calculations stay unchanged.
function frameTradeRows(){
  const table=$('rows'), seen=new Set();
  for(const anchor of [...table.querySelectorAll('tr[data-i]')]){
    const r=rows[+anchor.dataset.i];if(!r?.pair_id||seen.has(r.pair_id))continue;seen.add(r.pair_id);
    const members=[...table.querySelectorAll('tr[data-i]')].filter(el=>rows[+el.dataset.i]?.pair_id===r.pair_id);
    const heading=document.createElement('tr');heading.className='pair-box-heading';
    const cell=document.createElement('td');cell.colSpan=4;cell.textContent=`同一组两腿 · ${r.strategy||'待分类'} · ${r.pair_id} · 当前显示 ${members.length} 笔`;heading.appendChild(cell);anchor.before(heading);
    let last=heading;members.forEach((el,i)=>{last.after(el);el.classList.add('pair-box-row');if(i===members.length-1)el.classList.add('pair-box-last');last=el});
  }
}
function frameCycleFills(){
  document.querySelectorAll('[data-cycle]').forEach(card=>{
    const c=cycleData.find(x=>x.id===card.dataset.cycle);if(!c)return;
    const nodes=[...card.querySelectorAll('.cycle-fill')], groups=new Map();
    c.fills.forEach((r,i)=>{if(!nodes[i])return;const key=r.pair_id||r.id;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(nodes[i])});
    let n=0;for(const [pair,nodes] of groups){const box=document.createElement('fieldset');box.className='execution-box';const legend=document.createElement('legend');legend.textContent=(c.asset==='stock'?c.fills.find(r=>r.id===pair).stage:c.campaign?c.fills.find(r=>r.pair_id===pair).stage:pair===c.id?'开仓组合':c.incomplete?'待核对组合':`平仓组合 ${++n}`)+' · '+pair;box.appendChild(legend);nodes[0].before(box);nodes.forEach(node=>box.appendChild(node));}
  });
}
function frameExecutionCards(){
  const host=$('executionCards');if(!host)return;
  const uses=new Map();cycleData.forEach(c=>new Set(c.fills.map(r=>r.pair_id)).forEach(id=>uses.set(id,(uses.get(id)||0)+1)));
  for(const c of cycleData){
    const ids=new Set(c.fills.map(r=>r.pair_id));
    const cards=[...host.querySelectorAll(':scope > [data-execution]')].filter(el=>ids.has(el.dataset.execution)&&uses.get(el.dataset.execution)===1);
    if(!cards.length)continue;
    const frame=document.createElement('fieldset');frame.className='lifecycle-box';const legend=document.createElement('legend');legend.textContent=`同一笔交易 · ${c.codes[0].replace(/^US\./,'').replace(/\d{6}[CP]\d+$/,'')} ${c.strategy} · ${c.status}`;frame.appendChild(legend);cards[0].before(frame);
    cards.sort((a,b)=>executionGroups.find(g=>g.id===a.dataset.execution).time.localeCompare(executionGroups.find(g=>g.id===b.dataset.execution).time));
    for(const card of cards){const badge=document.createElement('div');badge.className='execution-role';badge.textContent=c.campaign?c.fills.find(r=>r.pair_id===card.dataset.execution).stage:card.dataset.execution===c.id?(c.incomplete?'待核对开仓记录':'① 开仓组合'):'② 平仓组合';card.prepend(badge);frame.appendChild(card)}
  }
}
const unframedRows=renderRows;renderRows=function(){unframedRows();frameTradeRows()};
const unframedCycles=loadCycles;loadCycles=async function(q){await unframedCycles(q);frameCycleFills();frameExecutionCards()};
