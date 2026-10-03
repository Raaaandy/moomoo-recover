"""Stock lifecycles, grouped until flat; realized cost uses FIFO lots."""
from collections import defaultdict, deque
from decimal import Decimal as D


def build_stock_cycles(rows):
    groups = defaultdict(list)
    for r in rows:
        if r.get('asset') == 'stock':
            groups[r['account'], r['code']].append(r)
    result = []
    for (account, code), fills in groups.items():
        current = None
        lots = deque()
        for r in sorted(fills, key=lambda x: (x['time'], x['id'])):
            qty, price = D(str(r['qty'])), D(str(r['price']))
            side = r['side']
            if qty <= 0 or side not in ('BUY', 'SELL', 'SELL_SHORT', 'BUY_BACK'):
                continue
            direction = 1 if side.startswith('BUY') else -1
            if current is None:
                valid = side in ('BUY', 'SELL_SHORT')
                current = dict(id='stock:'+r['id'], asset='stock', account=account,
                    strategy='正股做多' if direction == 1 else '正股做空', codes=[code],
                    first_time=r['time'], last_time=r['time'], fills=[], opened_qty=D(0),
                    closed_qty=D(0), remaining_qty=D(0), gross_points=D(0),
                    closed_basis_points=D(0), close_proceeds_points=D(0), incomplete=not valid)
                result.append(current)
                position_direction = direction
            stage = '买入 / 加仓' if direction == 1 else '卖出 / 减仓'
            current['fills'].append(dict(r, allocated_qty=str(qty), stage=stage))
            current['last_time'] = r['time']
            if direction == position_direction:
                lots.append([qty, price])
                current['opened_qty'] += qty
                current['remaining_qty'] += qty
            else:
                remaining = qty
                while remaining and lots:
                    lot = lots[0]
                    used = min(remaining, lot[0])
                    current['closed_basis_points'] += used * lot[1] * position_direction
                    current['close_proceeds_points'] += used * price * position_direction
                    current['closed_qty'] += used
                    current['remaining_qty'] -= used
                    lot[0] -= used
                    remaining -= used
                    if not lot[0]: lots.popleft()
                if remaining:
                    current['incomplete'] = True
            if not lots:
                current = None
        for c in [x for x in result if x['account'] == account and x['codes'] == [code]]:
            c['status'] = '待核对开仓记录' if c['incomplete'] else '已平仓' if not c['remaining_qty'] else '部分平仓' if c['closed_qty'] else '持仓中'
            c['gross_points'] = c['close_proceeds_points'] - c['closed_basis_points']
            for key in ('gross_points', 'closed_basis_points', 'close_proceeds_points'):
                c[key] = None if c['incomplete'] else str(c[key])
            for key in ('opened_qty', 'closed_qty', 'remaining_qty'):
                c[key] = str(c[key])
    return result
