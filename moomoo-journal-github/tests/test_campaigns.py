import unittest
from campaigns import build_campaign

class CampaignTests(unittest.TestCase):
    def test_expansion_counts_intermediate_close_once(self):
        data=[('a','745','BUY','5.00'),('a','750','SELL_SHORT','2.00'),('b','750','BUY_BACK','1.50'),('b','755','SELL_SHORT','1.00'),('c','745','SELL','4.00'),('c','755','BUY_BACK','.50')]
        rows=[dict(id=str(i),account='a',pair_id=p,code='US.QQQ261002C'+strike+'000',side=side,price=price,qty='1.0',time=p) for i,(p,strike,side,price) in enumerate(data)]
        members=[dict(pair_id=p,stage=s) for p,s in [('a','开仓'),('b','扩大价差'),('c','平仓')]]
        c=build_campaign(dict(id='test',strategy='CDS',title='扩大敞口'),members,rows)
        self.assertEqual(c['status'],'已平仓')
        self.assertEqual(c['gross_points'],'0.000')
        self.assertEqual(c['closed_basis_points'],'3.500')
        self.assertEqual(c['close_proceeds_points'],'3.500')
        self.assertIsNone(build_campaign(dict(id='test',strategy='CDS',title='扩大敞口'),members,rows[:-2])['gross_points'])
