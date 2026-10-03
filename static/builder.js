const basket=new Map();let recognition=null,recognitionVersion=0;
function bindDrag(){
  document.querySelectorAll('#rows tr[data-i]').forEach(el=>{
    const row=rows[+el.dataset.i];if(row.asset!=='option')return;
    el.draggable=true;el.title='拖到右侧组合识别框';
    el.ondragstart=e=>{e.dataTransfer.setData('text/plain',row.id);e.dataTransfer.effectAllowed='copy'};
    const b=document.createElement('button');b.className='basket-add';b.textContent='＋ 组合';b.type='button';b.setAttribute('aria-label','添加 '+row.code+' 到组合识别');
    b.onclick=e=>{e.stopPropagation();addBasket(row)};el.lastElementChild.appendChild(b);
  });
}
function addBasket(row){
  if(basket.has(row.id)){toast('已在组合框中');return}
  if(basket.size>=2){toast('可放入单张期权开平仓或两腿组合；请先保存当前选择');return}
  basket.set(row.id,row);renderBasket();
}
function renderBasket(){
  recognition=null;++recognitionVersion;$('confirmBasket').disabled=true;
  $('basketLegs').innerHTML=[...basket.values()].map(r=>`<div class="basket-leg"><b>${esc(r.code)}</b><small>${esc(r.time)} · ${esc(sideName[r.side]||r.side)} ${esc(r.qty)} @ ${esc(r.price)}</small><button type="button" data-remove="${esc(r.id)}">移出</button></div>`).join('')||'<p>将左侧的两条期权成交拖到这里<br>也可以点击每行的「＋ 组合」</p>';
  $('basketLegs').querySelectorAll('[data-remove]').forEach(b=>b.onclick=()=>{basket.delete(b.dataset.remove);renderBasket()});
  $('basketResult').textContent='';
  if(basket.size)guard(previewBasket);
}
async function previewBasket(){
  const version=++recognitionVersion;recognition=null;$('confirmBasket').disabled=true;
  $('basketResult').textContent='正在识别…';
  try{
    const result=await api('/api/recognize',{ids:[...basket.keys()],mode:$('basketMode').value});
    if(version!==recognitionVersion)return;
    recognition=result;$('basketResult').innerHTML=`<h3>${esc(result.strategy)} · ${esc(result.action)}</h3><p>${esc(result.explanation)}</p><p>${esc(result.warning||'已根据现有开仓记录确认平仓策略。')}</p>`;$('confirmBasket').disabled=false;
  }catch(e){if(version===recognitionVersion)$('basketResult').textContent=e.message}
}
const drop=$('strategyDrop');
drop.ondragover=e=>{e.preventDefault();e.dataTransfer.dropEffect='copy';drop.classList.add('drag-over')};
drop.ondragleave=e=>{if(!drop.contains(e.relatedTarget))drop.classList.remove('drag-over')};
drop.ondrop=e=>{e.preventDefault();drop.classList.remove('drag-over');const r=rows.find(x=>x.id===e.dataTransfer.getData('text/plain'));if(r?.asset==='option')addBasket(r);else toast('请拖入列表中的期权成交')};
$('basketMode').onchange=()=>{if(basket.size)guard(previewBasket)};
$('clearBasket').onclick=()=>{basket.clear();renderBasket()};
$('confirmBasket').onclick=()=>guard(async()=>{
  if(!recognition)return;const strategy=recognition.strategy;$('confirmBasket').disabled=true;
  try{await persist();await api('/api/recognize',{ids:[...basket.keys()],mode:$('basketMode').value,save:true,confirmed_strategy:strategy});basket.clear();renderBasket();await load();toast(strategy+' 已保存并关联；原 Thesis 和笔记保留')}
  catch(e){await previewBasket();throw e}
});
renderBasket();
