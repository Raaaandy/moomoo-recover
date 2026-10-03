import unittest
from recognize import recognize
from test_cycles import event


class RecognizeTests(unittest.TestCase):
    def test_single_put_roundtrip_and_close(self):
        opening=event('open','2026-09-20 10:00:00',2,True,5,2)[0]
        opening['code']=opening['code'].replace('C','P')
        close=dict(opening,id='closed',pair_id='close',side='SELL',qty='1',price='7',time='2026-09-21 10:00:00')
        result=recognize([opening,close],[])
        self.assertEqual(result['strategy'],'买 Put')
        self.assertTrue(result['roundtrip'])
        opening['strategy']='买 Put'
        self.assertEqual(recognize([close],[opening])['action'],'平仓')
        self.assertEqual(recognize([close],[opening])['strategy'],'买 Put')
    def test_four_verticals(self):
        for typ,opening,expected in [('C',True,'CDS'),('C',False,'CCS'),('P',True,'PCS'),('P',False,'PDS')]:
            rows=event('p','2026-09-20 10:00:00',1,opening,5,2)
            for r in rows:r['code']=r['code'].replace('C',typ)
            self.assertEqual(recognize(rows,[],mode='open')['strategy'],expected)

    def test_close_uses_opening(self):
        opened=event('o','2026-09-20 10:00:00',2,True,5,2)
        closed=event('c','2026-09-21 10:00:00',1,False,6,2)
        r=recognize(closed,opened)
        self.assertEqual((r['strategy'],r['action']),('CDS','平仓'))
        self.assertEqual(r['matched_openings'],1)

    def test_explicit_close_missing_history(self):
        rows=event('c','2026-09-21 10:00:00',1,False,6,2)
        r=recognize(rows,[],mode='close')
        self.assertEqual(r['strategy'],'CDS')
        self.assertTrue(r['warning'])

    def test_mismatch(self):
        for field,value in [('account','other'),('qty','2'),('code','US.SPY261016C510000'),('code','US.QQQ261023C510000'),('code','US.QQQ')]:
            rows=event('p','2026-09-20 10:00:00',1,True,5,2)
            rows[1][field]=value
            with self.assertRaises(ValueError):recognize(rows,[])
