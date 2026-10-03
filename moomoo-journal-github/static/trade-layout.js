// Keep all drag destinations next to the scrollable source list.
const tradeWorkspace=document.querySelector('.workspace');
const tradeEditor=tradeWorkspace.querySelector('.editor');
const tradeRail=document.createElement('div');tradeRail.className='trade-rail';
tradeEditor.before(tradeRail);
tradeRail.appendChild($('strategyDrop'));
if(typeof linkPanel!=='undefined')tradeRail.appendChild(linkPanel);
tradeRail.appendChild(tradeEditor);
$('strategyDrop').querySelector('h3').textContent='拖入成交 · 单张期权 / 两腿策略';
$('strategyDrop').querySelector('.fine').textContent='单张 Call / Put 可单独分类，也可放入同合约的开仓和平仓统一复盘。两腿价差支持 PDS / CDS / PCS / CCS。';
$('basketMode').parentNode.firstChild.textContent='这些成交属于';
const baseRenderBasket=renderBasket;
renderBasket=function(){baseRenderBasket();if(!basket.size)$('basketLegs').innerHTML='<p>从左侧拖入成交，或点击「＋组合」<br>单张 Call／Put：1 条成交或 2 条开平仓<br>价差策略：2 条不同合约的腿</p>'};
renderBasket();
for(const role of ['open','close']){
  const slot=$(role+'Slot'),oldDrop=slot.ondrop;
  slot.ondrop=e=>{
    if(e.dataTransfer.getData('application/x-journal-execution')){oldDrop(e);return}
    e.preventDefault();slot.classList.remove('drag-over');
    const r=rows.find(x=>x.id===e.dataTransfer.getData('text/plain'));
    if(r?.asset!=='option'){toast('请拖入期权成交或组合卡');return}
    guard(async()=>{
      await persist();
      const payload={ids:[r.id],mode:role};
      const preview=await api('/api/recognize',payload);
      const saved=await api('/api/recognize',{...payload,save:true,confirmed_strategy:preview.strategy});
      await load();chooseExecution(saved.pair_id,role);
    });
  };
}
linkPanel.querySelector('.fine').textContent='单张 Call / Put 可直接从左侧拖入开仓、平仓框；价差先识别两条腿，再放入组合卡。';
