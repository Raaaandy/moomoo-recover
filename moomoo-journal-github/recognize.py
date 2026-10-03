import re
from decimal import Decimal
from cycles import build_cycles, canonical


def recognize(legs, history, mode='auto'):
    if mode not in ('auto','open','close'):
        raise ValueError('请选择开仓、平仓或自动判断')
    if len(legs) not in (1,2):
        raise ValueError('请放入单张期权或两条期权成交。')
    if len({r['id'] for r in legs})!=len(legs):
        raise ValueError('不能重复添加同一笔成交')
    parsed=[]
    for r in legs:
        m=re.fullmatch(r'US\.([A-Z0-9.]+?)(\d{6})([CP])(\d+)',r['code'].upper())
        if not m:
            raise ValueError('组合识别仅支持美股期权，请勿加入股票或 ETF')
        side=1 if r['side'].startswith('BUY') else -1 if r['side'].startswith('SELL') else 0
        if not side or Decimal(r['qty'])<=0:
            raise ValueError('成交方向或数量无效')
        parsed.append((m,side,r))
    if len(legs)==1 or legs[0]['code']==legs[1]['code']:
        ordered=sorted(parsed,key=lambda x:(x[2]['time'],x[2]['id']))
        first=ordered[0]
        if len(ordered)==2:
            if legs[0]['account']!=legs[1]['account'] or ordered[0][1]==ordered[1][1] or ordered[0][2]['time']==ordered[1][2]['time']:
                raise ValueError('单张期权的开平仓需同账户、同合约、不同时刻且买卖相反')
            if Decimal(ordered[1][2]['qty'])>Decimal(ordered[0][2]['qty']):
                raise ValueError('平仓数量超过所选开仓数量，请补充开仓记录')
            if mode=='close':
                raise ValueError('框中包含开仓和平仓，请选择自动判断或开仓')
            direction=first[1];action='开仓 → 平仓';closing=False;matched=0;warning='按较早成交作为开仓；请核对买卖顺序。'
        else:
            matches=[]
            for c in build_cycles([r for r in history if r['id']!=first[2]['id'] and r['time']<first[2]['time']]):
                if c['account']==first[2]['account'] and c['codes']==[first[2]['code']] and not c['incomplete'] and Decimal(c['remaining_qty'])>0:
                    opening=c['fills'][0]['side'].startswith('BUY')
                    if opening!=(first[1]==1):matches.append(c)
            evidence=sum((Decimal(c['remaining_qty']) for c in matches),Decimal(0))>=Decimal(first[2]['qty'])
            closing=mode=='close' or (mode=='auto' and (evidence or first[2]['side']=='BUY_BACK'))
            direction=-first[1] if closing else first[1];action='平仓' if closing else '开仓';matched=len(matches) if evidence else 0
            warning='未找到足量开仓，盈亏需补齐记录。' if closing and not evidence else '未确认开仓历史，请核对开仓／平仓选择。' if mode=='auto' and not evidence else ''
        typ='Call' if first[0][3]=='C' else 'Put'
        return dict(strategy=('买 ' if direction==1 else '卖 ')+typ,action=action,warning=warning,
                    explanation=f"{first[0][1]} · {first[0][2]} 到期 · {typ} · 执行价 {Decimal(first[0][4])/1000}",matched_openings=matched,single=True,roundtrip=len(legs)==2)
    a,b=sorted(parsed,key=lambda x:int(x[0][4]))
    if legs[0]['account']!=legs[1]['account'] or a[0][1]!=b[0][1]:
        raise ValueError('两条腿必须属于同一账户和同一标的')
    if a[0][2]!=b[0][2] or a[0][3]!=b[0][3] or a[0][4]==b[0][4] or a[1]==b[1]:
        raise ValueError('当前识别 PDS、CDS、PCS、CCS：需同到期、同 Call/Put、不同执行价且买卖相反。')
    if Decimal(legs[0]['qty'])!=Decimal(legs[1]['qty']):
        raise ValueError('两条腿数量不同，请选等量成交；比例价差暂不自动归类')
    structure=('CDS' if a[1]==1 else 'CCS') if a[0][3]=='C' else ('PCS' if a[1]==1 else 'PDS')
    inverse={'CDS':'CCS','CCS':'CDS','PDS':'PCS','PCS':'PDS'}
    first=min(r['time'] for r in legs)
    selected_ids={r['id'] for r in legs}
    prior=[r for r in history if r['id'] not in selected_ids and r['time']<first]
    matches=[]
    for c in build_cycles(prior):
        if c['account']!=legs[0]['account'] or set(c['codes'])!={r['code'] for r in legs} or c['incomplete'] or Decimal(c['remaining_qty'])<=0:
            continue
        opening={r['code']:r['side'].startswith('BUY') for r in c['fills'][:2]}
        if all(opening[r['code']]!=r['side'].startswith('BUY') for r in legs):
            matches.append(c)
    available=sum((Decimal(c['remaining_qty']) for c in matches),Decimal(0))
    match_names={canonical(c['strategy']).upper() for c in matches}
    evidence=bool(matches) and available>=Decimal(legs[0]['qty']) and len(match_names)==1 and next(iter(match_names))==inverse[structure]
    closing=mode=='close' or (mode=='auto' and (evidence or any(r['side']=='BUY_BACK' for r in legs)))
    strategy=inverse[structure] if closing else structure
    warning=''
    if closing and not evidence:
        warning='未找到足量且已关联的开仓记录；可保存平仓分类，但盈亏需要补齐开仓记录。'
    elif mode=='auto' and not closing:
        warning='按开仓结构识别；若这两条实际是平仓，请把下方改为“平仓”后确认。'
    return dict(strategy=strategy, action='平仓' if closing else '开仓',warning=warning,
                explanation=f"{a[0][1]} · {a[0][2]} 到期 · {'Call' if a[0][3]=='C' else 'Put'}：低执行价 {Decimal(a[0][4])/1000} {'买入' if a[1]==1 else '卖出'}，高执行价 {Decimal(b[0][4])/1000} {'买入' if b[1]==1 else '卖出'}。",
                matched_openings=len(matches) if evidence else 0)
