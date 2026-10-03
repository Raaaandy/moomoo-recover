let executionGroups=[],openExecution='',closeExecution='',linkVersion=0;
const linkPanel=document.createElement('section');linkPanel.className='life-link';
linkPanel.innerHTML='<h3>拖拽关联开仓与平仓</h3><p class="fine">先把两条腿关联成组合，再将下方组合卡放入对应方框。支持分批平仓；同一次开仓可以关联多次平仓。</p><div class="life-slots"><div id="openSlot" tabindex="0">① 拖入开仓组合</div><div id="closeSlot" tabindex="0">② 拖入平仓组合</div></div><div id="linkPreview" role="status"></div><button class="primary" id="confirmLife" disabled>确认关联并统一复盘</button><button class="quiet" id="clearLife">清空选择</button><details><summary>展开可拖拽的组合成交</summary><div id="executionCards"></div></details>';
$('cycleCards').before(linkPanel);
function slotText(id,fallback){const g=executionGroups.find(x=>x.id===id);return g?`${esc(g.strategy)} · ${esc(g.time)}<br>${g.legs.map(r=>esc(r.code)+' '+esc(sideName[r.side]||r.side)+' '+esc(r.qty)).join('<br>')}`:fallback}
async function previewLife(){
  const version=++linkVersion;$('confirmLife').disabled=true;
  $('openSlot').innerHTML=slotText(openExecution,'① 拖入开仓组合');$('closeSlot').innerHTML=slotText(closeExecution,'② 拖入平仓组合');
  $('linkPreview').textContent='';if(!openExecution||!closeExecution)return;
  try{const r=await api('/api/lifecycle-link',{open_pair:openExecution,close_pair:closeExecution});if(version!==linkVersion)return;$('linkPreview').textContent=`${r.strategy} · ${r.status} · 完整交易毛盈亏 ${r.gross_pnl} USD（乘数 ${r.multiplier}，未扣费用）· 剩余 ${r.remaining_qty} 组`;$('confirmLife').disabled=false}catch(e){if(version===linkVersion)$('linkPreview').textContent=e.message}
}
function chooseExecution(id,role){if(role==='open')openExecution=id;else closeExecution=id;guard(previewLife)}
for(const role of ['open','close']){const slot=$(role+'Slot');slot.ondragover=e=>{e.preventDefault();slot.classList.add('drag-over')};slot.ondragleave=()=>slot.classList.remove('drag-over');slot.ondrop=e=>{e.preventDefault();slot.classList.remove('drag-over');const id=e.dataTransfer.getData('application/x-journal-execution');if(executionGroups.some(x=>x.id===id))chooseExecution(id,role);else toast('请拖入下方的组合成交卡')};}
async function loadExecutions(q){
  const r=await api('/api/executions?'+new URLSearchParams(q));executionGroups=r.groups;
  if(!executionGroups.some(g=>g.id===openExecution))openExecution='';if(!executionGroups.some(g=>g.id===closeExecution))closeExecution='';
  $('executionCards').innerHTML=r.groups.map(g=>`<article draggable="true" class="execution-card" data-execution="${esc(g.id)}"><b>${esc(g.strategy)} · ${esc(g.time)}</b>${g.legs.map(x=>`<small>${esc(x.code)} · ${esc(sideName[x.side]||x.side)} ${esc(x.qty)} @ ${esc(x.price)}</small>`).join('')}<button class="quiet" data-role="open">放入开仓框</button><button class="quiet" data-role="close">放入平仓框</button>${g.open_pair?'<span>已手动关联开仓</span><button class="quiet" data-role="unlink">解除手动关联</button>':''}</article>`).join('')||'<p>当前区间暂无组合成交。请先在逐笔成交处关联两条期权腿。</p>';
  $('executionCards').querySelectorAll('[data-execution]').forEach(el=>{el.ondragstart=e=>{e.dataTransfer.setData('application/x-journal-execution',el.dataset.execution);e.dataTransfer.effectAllowed='copy'};el.querySelectorAll('[data-role]').forEach(b=>b.onclick=()=>guard(async()=>{if(b.dataset.role==='unlink'){await persist();await api('/api/lifecycle-link',{close_pair:el.dataset.execution,unlink:true});await load();toast('已解除手动关联，恢复自动匹配')}else chooseExecution(el.dataset.execution,b.dataset.role)}))});
  await previewLife();
}
$('clearLife').onclick=()=>{openExecution='';closeExecution='';guard(previewLife)};
$('confirmLife').onclick=()=>guard(async()=>{$('confirmLife').disabled=true;await persist();await api('/api/lifecycle-link',{open_pair:openExecution,close_pair:closeExecution,save:true});openExecution='';closeExecution='';await load();toast('开平仓已关联，请在完整交易卡中统一复盘')});
const originalLoadCycles=loadCycles;loadCycles=async function(q){await originalLoadCycles(q);if(q.asset!=='stock')await loadExecutions(q)};
