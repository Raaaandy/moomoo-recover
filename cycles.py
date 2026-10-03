"""Build strategy lifecycles from user-confirmed two-leg execution groups."""
from collections import defaultdict
from decimal import Decimal


def dec(value):
    return Decimal(str(value))


def canonical(value):
    s = value.strip().lower()
    return {'牛市看涨价差':'cds','call debit spread':'cds','熊市看跌价差':'pds','put debit spread':'pds',
            '牛市看跌价差':'pcs','put credit spread':'pcs','熊市看涨价差':'ccs','call credit spread':'ccs'}.get(s,s)


def build_cycles(rows, links=None):
    links=links or {}
    pairs = defaultdict(list)
    for r in rows:
        if r.get('pair_id'):
            pairs[r['pair_id']].append(r)
    active = defaultdict(list)
    result = []
    for pair_id, legs in sorted(pairs.items(), key=lambda item: (min(r['time'] for r in item[1]),item[0])):
        legs = sorted(legs,key=lambda r:r['code'])
        if len(legs) not in (1,2) or (len(legs)==2 and legs[0]['code']==legs[1]['code']):
            continue
        amounts = [dec(r['qty']) for r in legs]
        if min(amounts)<=0 or (len(amounts)==2 and amounts[0]!=amounts[1]):
            continue
        directions = tuple(1 if r['side'].startswith('BUY') else -1 if r['side'].startswith('SELL') else 0 for r in legs)
        if 0 in directions or (len(directions)==2 and directions[0]==directions[1]):
            continue
        strategy = canonical(legs[0]['strategy'])
        if len(legs)==2 and strategy != canonical(legs[1]['strategy']):
            continue
        key=(legs[0]['account'],tuple(r['code'] for r in legs),strategy)
        qty=amounts[0]
        cash=sum(-dec(r['price'])*d for r,d in zip(legs,directions))
        opposite=tuple(-d for d in directions)
        target=links.get(pair_id)
        matches=[x for x in active[key] if x['_directions']==opposite and x['_remaining']>0 and (x['id']==target if target else x['id'] not in set(links.values()))]
        available=sum((x['_remaining'] for x in matches),Decimal(0))
        # Never split an over-close into a guessed new opening position.
        if matches and qty<=available:
            rest=qty
            for cycle in matches:
                used=min(rest,cycle['_remaining'])
                cycle['_gross']+=(cycle['_entry_cash']+cash)*used
                cycle['_remaining']-=used
                cycle['fills'].extend([dict(r,allocated_qty=str(used)) for r in legs])
                cycle['last_time']=max(r['time'] for r in legs)
                rest-=used
                if not rest:
                    break
            continue
        expected={'cds':(1,-1),'pds':(-1,1),'pcs':(1,-1),'ccs':(-1,1)}.get(strategy)
        # Codes have variable-width strikes; sort by numeric strike for direction checking.
        import re
        strikes=[int(re.search(r'[CP](\d+)$',r['code'])[1]) for r in legs]
        numeric_dirs=directions if len(legs)==1 or strikes[0]<strikes[1] else directions[::-1]
        if len(legs)==1:
            expected=(1,) if strategy in ('买 call','买 put') else (-1,) if strategy in ('卖 call','卖 put') else None
        invalid = bool(matches) or (expected is not None and numeric_dirs!=expected)
        cycle={'id':pair_id,'account':legs[0]['account'],'strategy':legs[0]['strategy'],
               'codes':[r['code'] for r in legs],'first_time':min(r['time'] for r in legs),
               'last_time':max(r['time'] for r in legs),'fills':[dict(r,allocated_qty=str(qty)) for r in legs],
               'opened_qty':str(qty),'_remaining':qty,'_entry_cash':cash,'_gross':Decimal(0),
               '_directions':directions,'incomplete':invalid}
        result.append(cycle)
        if not invalid:
            active[key].append(cycle)
    for c in result:
        c['remaining_qty']=str(c['_remaining'])
        c['closed_qty']=str(dec(c['opened_qty'])-c['_remaining'])
        c['gross_points']=str(c['_gross']) if not c['incomplete'] else None
        c['closed_basis_points']=str(-c['_entry_cash']*(dec(c['opened_qty'])-c['_remaining'])) if not c['incomplete'] else None
        c['close_proceeds_points']=str(c['_gross']-c['_entry_cash']*(dec(c['opened_qty'])-c['_remaining'])) if not c['incomplete'] else None
        c['status']='待核对开仓记录' if c['incomplete'] else '已平仓' if not c['_remaining'] else '部分平仓' if dec(c['closed_qty'])>0 else '持仓中'
        for k in list(c):
            if k.startswith('_'):
                del c[k]
    return result
