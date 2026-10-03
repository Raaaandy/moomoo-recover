import unittest
from cycles import build_cycles


def event(pair, time, quantity, opening, long_price, short_price, account='a'):
    return [dict(id=pair+str(i),pair_id=pair,account=account,strategy='CDS',code=code,
                 side=side,qty=str(quantity),price=str(price),time=time,notes='',thesis='')
            for i,(code,side,price) in enumerate([
                ('US.QQQ261016C500000','BUY' if opening else 'SELL',long_price),
                ('US.QQQ261016C510000','SELL' if opening else 'BUY',short_price)])]


class CycleTests(unittest.TestCase):
    def test_single_option_partial_realized_pnl(self):
        a=event('open','2026-09-20 10:00:00',2,True,5,2)[0]
        a['strategy']='买 Call'
        b=dict(a,id='close',pair_id='close',side='SELL',qty='1',price='7',time='2026-09-21 10:00:00')
        cycle=build_cycles([a,b])[0]
        self.assertEqual(cycle['gross_points'],'2')
        self.assertEqual(cycle['remaining_qty'],'1')
        self.assertEqual(cycle['status'],'部分平仓')
    def test_manual_close_overrides_fifo(self):
        rows=event('a','2026-09-20 10:00:00',1,True,5,2)+event('b','2026-09-20 11:00:00',1,True,6,2)+event('c','2026-09-21 10:00:00',1,False,7,2)
        c={x['id']:x for x in build_cycles(rows,{'c':'b'})}
        self.assertEqual(c['a']['remaining_qty'],'1')
        self.assertEqual(c['b']['gross_points'],'1')
        self.assertEqual(c['b']['status'],'已平仓')

    def test_float_formatted_quantity_stays_open(self):
        c=build_cycles(event('a','2026-09-20 10:00:00','1.0',True,5,2))[0]
        self.assertEqual(c['status'],'持仓中')

    def test_round_trip_and_reopen(self):
        rows=event('a','2026-09-20 10:00:00',1,True,5,2)+event('b','2026-09-21 10:00:00',1,False,7,3)
        rows+=event('c','2026-09-22 10:00:00',1,True,6,2)
        cycles=build_cycles(rows)
        self.assertEqual(len(cycles),2)
        self.assertEqual(cycles[0]['gross_points'],'1')
        self.assertEqual(cycles[0]['status'],'已平仓')
        self.assertEqual(len(cycles[0]['fills']),4)
        self.assertEqual(cycles[1]['status'],'持仓中')

    def test_partial_close_and_loss(self):
        rows=event('a','2026-09-20 10:00:00',3,True,5,2)+event('b','2026-09-21 10:00:00',1,False,3,2)
        c=build_cycles(rows)[0]
        self.assertEqual(c['gross_points'],'-2')
        self.assertEqual(c['remaining_qty'],'2')
        self.assertEqual(c['status'],'部分平仓')

    def test_fifo_and_account_isolation(self):
        rows=event('a','2026-09-20 10:00:00',1,True,5,2)+event('b','2026-09-20 11:00:00',1,True,6,2)
        rows+=event('c','2026-09-21 10:00:00',2,False,7,2)
        rows+=event('d','2026-09-22 10:00:00',1,False,8,2,account='other')
        c=build_cycles(rows)
        self.assertEqual([x['gross_points'] for x in c],['2','1',None])
        self.assertEqual(c[2]['status'],'待核对开仓记录')

    def test_overclose_not_guessed(self):
        c=build_cycles(event('a','2026-09-20 10:00:00',1,True,5,2)+event('b','2026-09-21 10:00:00',2,False,7,2))
        self.assertEqual(c[0]['remaining_qty'],'1')
        self.assertIsNone(c[1]['gross_points'])
