import unittest
from stocks import build_stock_cycles


def fill(i, side, qty, price, account='a'):
    return dict(id=str(i), time=str(i), account=account, code='US.QQQ',
                asset='stock', side=side, qty=str(qty), price=str(price))


class StockTests(unittest.TestCase):
    def test_add_partial_and_flat(self):
        rows = [fill(1,'BUY',10,100), fill(2,'BUY',10,110), fill(3,'SELL',15,120)]
        c = build_stock_cycles(rows)[0]
        self.assertEqual((c['status'],c['gross_points'],c['remaining_qty']),('部分平仓','250','5'))
        rows += [fill(4,'SELL',5,105),fill(5,'BUY',1,90)]
        cycles = build_stock_cycles(rows)
        self.assertEqual(len(cycles),2)
        self.assertEqual((cycles[0]['status'],cycles[0]['gross_points']),('已平仓','225'))

    def test_missing_and_overclose(self):
        self.assertIsNone(build_stock_cycles([fill(1,'SELL',1,100)])[0]['gross_points'])
        self.assertIsNone(build_stock_cycles([fill(1,'BUY',1,90),fill(2,'SELL',2,100)])[0]['gross_points'])

    def test_short_and_accounts(self):
        c = build_stock_cycles([fill(1,'SELL_SHORT',2,100),fill(2,'BUY_BACK',2,90)])[0]
        self.assertEqual(c['gross_points'],'20')
        self.assertEqual(len(build_stock_cycles([fill(1,'BUY',1,100),fill(2,'SELL',1,120,'b')])),2)
