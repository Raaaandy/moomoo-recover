from collections import defaultdict
from decimal import Decimal


def build_campaign(info, members, rows):
    stages={r['pair_id']:r['stage'] for r in members}
    fills=sorted([dict(r,allocated_qty=r['qty'],stage=stages[r['pair_id']]) for r in rows if r['pair_id'] in stages],key=lambda r:(r['time'],r['id']))
    if not fills:return None
    balances=defaultdict(Decimal);cash=Decimal(0);spent=Decimal(0);received=Decimal(0)
    for r in fills:
        sign=1 if r['side'].startswith('BUY') else -1
        qty=Decimal(r['qty']);flow=-sign*qty*Decimal(r['price']);cash+=flow;balances[r['code']]+=sign*qty
        if r['stage']=='平仓':received+=flow
        else:spent-=flow
    closed=all(x==0 for x in balances.values())
    first_stage=[r for r in fills if r['stage']=='开仓']
    qty=first_stage[0]['qty'] if first_stage else '0'
    return dict(id=info['id'],account=fills[0]['account'],strategy=info['strategy'],title=info['title'],codes=sorted(balances),first_time=fills[0]['time'],last_time=fills[-1]['time'],fills=fills,opened_qty=qty,closed_qty=qty if closed else '0',remaining_qty='0' if closed else '待核对',gross_points=str(cash) if closed else None,closed_basis_points=str(spent) if closed else None,close_proceeds_points=str(received) if closed else None,status='已平仓' if closed else '调整中 · 盈亏待核对',incomplete=not closed,campaign=True)
