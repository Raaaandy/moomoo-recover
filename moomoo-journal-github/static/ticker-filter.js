const tickerBar=document.createElement('div');tickerBar.className='ticker-filter';
tickerBar.innerHTML='<label>按股票／标的筛选<select id="tradeTicker"><option value="">全部标的</option></select></label><label class="classified-toggle"><input type="checkbox" id="showClassifiedTrades">显示已归类成交</label><span id="tradeTickerCount"></span><button type="button" class="quiet" id="resetTradeTicker">重置标的</button>';
document.querySelector('.trades .section-head').after(tickerBar);
const tickerEmpty=document.createElement('p');tickerEmpty.className='ticker-empty';tickerEmpty.hidden=true;tickerEmpty.textContent='当前范围内没有这个标的的成交，点击「显示全部」或调整上方日期。';document.querySelector('.trades .table-wrap').after(tickerEmpty);
function tradeUnderlying(r){return r.code.replace(/^[A-Z]+\./,'').replace(/\d{6}[CP]\d+$/,'')}
function tradeIsClassified(r){return (r.asset==='stock' && cycleData.some(c=>c.asset==='stock'&&!c.incomplete&&c.fills.some(f=>f.id===r.id))) || !!r.pair_id || (r.asset==='option' && !!r.strategy?.trim() && r.strategy.trim()!=='待分类')}
function applyTradeTicker(){
  const picked=$('tradeTicker').value,counts=new Map();
  rows.forEach(r=>{const name=tradeUnderlying(r);counts.set(name,(counts.get(name)||0)+1)});
  if(picked&&!counts.has(picked))counts.set(picked,0);
  $('tradeTicker').innerHTML='<option value="">全部标的</option>'+[...counts].sort(([a],[b])=>a.localeCompare(b)).map(([name,n])=>`<option value="${esc(name)}">${esc(name)} · ${n} 笔</option>`).join('');$('tradeTicker').value=picked;
  let shown=0,hiddenClassified=0;
  const showClassified=$('showClassifiedTrades').checked;
  $('rows').querySelectorAll('tr[data-i]').forEach(el=>{const row=rows[+el.dataset.i],matches=!picked||tradeUnderlying(row)===picked;const excluded=!showClassified&&tradeIsClassified(row);const visible=matches&&!excluded;el.hidden=!visible;if(visible)shown++;if(matches&&excluded)hiddenClassified++});
  $('rows').querySelectorAll('.group-row,.pair-box-heading').forEach(el=>{let next=el.nextElementSibling,visible=false;while(next){if(next.classList.contains('group-row')||(el.classList.contains('pair-box-heading')&&next.classList.contains('pair-box-heading')))break;if(next.hasAttribute('data-i')&&!next.hidden){visible=true;break}next=next.nextElementSibling}el.hidden=!visible});
  $('tradeTickerCount').textContent=`显示 ${shown} / ${rows.length} 笔${hiddenClassified?` · 已隐藏 ${hiddenClassified} 笔已归类`:''}`;
  tickerEmpty.textContent=hiddenClassified?'当前标的下的成交已归类，可勾选「显示已归类成交」查看。':'当前范围内没有这个标的的成交，请重置标的或调整上方日期。';
  tickerEmpty.hidden=!rows.length||!!shown;
}
$('tradeTicker').onchange=()=>guard(async()=>{await saveFill();applyTradeTicker()});
$('showClassifiedTrades').onchange=()=>guard(async()=>{await saveFill();applyTradeTicker()});
$('resetTradeTicker').onclick=()=>{$('tradeTicker').value='';applyTradeTicker()};
const beforeTickerRows=renderRows;renderRows=function(){beforeTickerRows();applyTradeTicker()};
