import os
import tempfile
import unittest
from unittest.mock import patch
import io
from pathlib import Path

Path('test-output').mkdir(exist_ok=True)
TEMP = tempfile.TemporaryDirectory(dir='test-output')
os.environ['JOURNAL_DATA'] = TEMP.name
import app
from pypdf import PdfReader


class JournalTest(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()
        self.h = {'X-Journal-Token': app.TOKEN}
        with app.db() as c:
            c.execute('DELETE FROM fills')
            c.execute('DELETE FROM reviews')
        self.row = dict(deal_id='100', order_id='900', code='US.QQQ', stock_name='纳指 ETF', trd_side='BUY', qty=2, price=500.5, create_time='2026-09-24 09:30:01', status='OK')
        app.upsert('123', [self.row])
        self.q = {'start':'2026-09-24', 'end':'2026-09-24'}

    def test_duplicate_keeps_notes_and_partial_fills(self):
        self.client.post('/api/fill', json={'id':'123:100','thesis':'突破买入','notes':'等待确认','bias':'看多'}, headers=self.h)
        app.upsert('123', [self.row, self.row | {'deal_id':'101', 'qty':3}])
        rows=app.selection(self.q)
        self.assertEqual(len(rows),2)
        self.assertEqual(next(r for r in rows if r['deal_id']=='100')['thesis'],'突破买入')
        app.upsert('456',[self.row])
        self.assertEqual(len(app.selection(self.q)),3)

    def test_date_symbol_account_bias_filters(self):
        app.upsert('123',[self.row | {'deal_id':'102','create_time':'2026-09-25 00:00:00'}])
        self.assertEqual(len(app.selection(self.q)),1)
        self.assertEqual(len(app.selection(self.q | {'symbol':'SPY'})),0)
        self.assertEqual(len(app.selection(self.q | {'account':'456'})),0)
        self.assertEqual(len(app.selection(self.q | {'bias':'看跌'})),0)
        self.assertEqual(self.client.get('/api/fills?start=2026-09-25&end=2026-09-24').status_code,400)

    def test_csrf(self):
        self.assertEqual(self.client.post('/api/fill',json={}).status_code,403)

    def test_single_roundtrip_drag_save(self):
        opening=self.row | {'deal_id':'single-open','code':'US.QQQ261016P500000','qty':2,'price':5,'create_time':'2026-09-23 10:00:00'}
        closing=opening | {'deal_id':'single-close','trd_side':'SELL','qty':1,'price':7,'create_time':'2026-09-24 10:00:00'}
        app.upsert('123',[opening,closing])
        payload={'ids':['123:single-open','123:single-close'],'mode':'auto'}
        r=self.client.post('/api/recognize',json=payload,headers=self.h)
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.json['strategy'],'买 Put')
        r=self.client.post('/api/recognize',json=payload | {'save':True,'confirmed_strategy':'买 Put'},headers=self.h)
        self.assertEqual(r.status_code,200)
        cycle=next(c for c in self.client.get('/api/cycles',query_string=self.q).json['cycles'] if c['strategy']=='买 Put')
        self.assertEqual(cycle['gross_pnl'],'200.00')
        self.assertEqual(cycle['remaining_qty'],'1')
        r=self.client.post('/api/recognize',json=payload | {'save':True,'confirmed_strategy':'买 Put'},headers=self.h)
        self.assertEqual(r.status_code,200)

    def test_manual_lifecycle_link_preview_save_unlink(self):
        from test_cycles import event
        for r in event('manual-a','2026-09-23 10:00:00',1,True,5,2)+event('manual-b','2026-09-23 11:00:00',1,True,6,2)+event('manual-c','2026-09-24 10:00:00',1,False,7,2):
            app.upsert('a',[{'deal_id':r['id'],'code':r['code'],'qty':r['qty'],'price':r['price'],'trd_side':r['side'],'create_time':r['time']}])
            with app.db() as c:c.execute('UPDATE fills SET pair_id=?,strategy=? WHERE id=?',(r['pair_id'],r['strategy'],'a:'+r['id']))
        payload={'open_pair':'manual-b','close_pair':'manual-c'}
        preview=self.client.post('/api/lifecycle-link',json=payload,headers=self.h)
        self.assertEqual(preview.status_code,200)
        self.assertEqual(preview.json['gross_pnl'],'100.00')
        with app.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM lifecycle_links').fetchone()[0],0)
        self.assertEqual(self.client.post('/api/lifecycle-link',json=payload | {'save':True},headers=self.h).status_code,200)
        cycle=self.client.get('/api/cycles',query_string=self.q | {'asset':'option'}).json['cycles'][0]
        self.assertEqual(cycle['id'],'manual-b')
        self.assertEqual(cycle['gross_pnl'],'100.00')
        self.assertEqual(self.client.post('/api/lifecycle-link',json={'open_pair':'manual-c','close_pair':'manual-a'},headers=self.h).status_code,400)
        self.client.post('/api/lifecycle-link',json={'close_pair':'manual-c','unlink':True},headers=self.h)
        cycle=self.client.get('/api/cycles',query_string=self.q | {'asset':'option'}).json['cycles'][0]
        self.assertEqual(cycle['id'],'manual-a')
        self.assertEqual(cycle['gross_pnl'],'200.00')

    def test_drag_recognize_save_and_conflict(self):
        from test_cycles import event
        for r in event('drag','2026-09-24 10:00:00',1,True,5,2):
            app.upsert('a',[{'deal_id':r['id'],'code':r['code'],'qty':r['qty'],'price':r['price'],'trd_side':r['side'],'create_time':r['time'],'status':'OK'}])
        payload={'ids':['a:drag0','a:drag1'],'mode':'open'}
        response=self.client.post('/api/recognize',json=payload,headers=self.h)
        self.assertEqual(response.json['strategy'],'CDS')
        self.assertFalse(app.selection(self.q | {'asset':'option'})[0]['pair_id'])
        response=self.client.post('/api/recognize',json=payload | {'save':True,'confirmed_strategy':'CDS'},headers=self.h)
        self.assertEqual(response.status_code,200)
        pair=response.json['pair_id']
        self.assertTrue(pair)
        self.assertEqual(self.client.post('/api/recognize',json=payload | {'save':True,'confirmed_strategy':'CDS'},headers=self.h).json['pair_id'],pair)
        with app.db() as c:c.execute("UPDATE fills SET pair_id='other' WHERE id='a:drag1'")
        self.assertEqual(self.client.post('/api/recognize',json=payload,headers=self.h).status_code,400)

    def test_cycle_review_and_net_pnl(self):
        from test_cycles import event
        for r in event('open','2026-09-23 10:00:00',1,True,5,2)+event('close','2026-09-24 10:00:00',1,False,7,3):
            app.upsert('a',[{'deal_id':r['id'],'code':r['code'],'qty':r['qty'],'price':r['price'],'trd_side':r['side'],'create_time':r['time'],'status':'OK'}])
            with app.db() as c:
                c.execute('UPDATE fills SET pair_id=?,strategy=? WHERE id=?',(r['pair_id'],r['strategy'],'a:'+r['id']))
        response=self.client.get('/api/cycles',query_string=self.q | {'asset':'option'})
        cycle=response.json['cycles'][0]
        self.assertEqual(cycle['gross_pnl'],'100.00')
        self.assertEqual(len(cycle['fills']),4)
        self.assertEqual(self.client.post('/api/cycle',json={'id':'open','thesis':'统一判断','notes':'统一复盘','multiplier':'100','fees':'4.50'},headers=self.h).status_code,200)
        updated=self.client.get('/api/cycles',query_string=self.q | {'asset':'option'}).json['cycles'][0]
        self.assertEqual(updated['net_pnl'],'95.50')
        self.assertEqual(updated['notes'],'统一复盘')
        response=self.client.get('/api/summary.pdf',query_string=self.q)
        content=''.join(p.extract_text() for p in PdfReader(io.BytesIO(response.data)).pages)
        self.assertIn('95.50',content)
        self.assertIn('统一复盘',content)

    def test_pair_unique_and_roll_three_choices(self):
        anchor=self.row | {'deal_id':'p1','code':'US.QQQ260925P500000'}
        other=anchor | {'deal_id':'p2','code':'US.QQQ260925P490000','trd_side':'SELL'}
        app.upsert('123',[anchor,other])
        payload={'id':'123:p1','strategy':'PDS','thesis':'保留判断','notes':'保留笔记'}
        self.assertEqual(self.client.post('/api/fill',json=payload,headers=self.h).status_code,200)
        info=self.client.get('/api/pair',query_string={'id':'123:p1'}).json
        self.assertEqual(len(info['linked']),1)
        app.upsert('123',[anchor,other])
        self.assertEqual(self.client.get('/api/pair',query_string={'id':'123:p1'}).json['pair_id'],info['pair_id'])
        self.client.post('/api/pair',json={'id':'123:p1','unlink':True},headers=self.h)
        app.upsert('123',[anchor | {'deal_id':'p3','code':'US.QQQ261002P500000'},other | {'deal_id':'p4','code':'US.QQQ261002P490000'}])
        self.client.post('/api/fill',json=payload,headers=self.h)
        info=self.client.get('/api/pair',query_string={'id':'123:p1'}).json
        self.assertFalse(info['linked'])
        self.assertEqual(len(info['candidates']),3)
        result=self.client.post('/api/pair',json={'id':'123:p1','other_id':'123:p2'},headers=self.h)
        self.assertEqual(result.status_code,200)
        info=self.client.get('/api/pair',query_string={'id':'123:p1'}).json
        self.assertEqual(info['linked'][0]['strategy'],'PDS')
        self.assertEqual(app.selection(self.q | {'asset':'option'})[0]['notes'],'保留笔记')
        self.assertEqual(self.client.post('/api/pair',json={'id':'123:p3','other_id':'123:p1'},headers=self.h).status_code,400)

    def test_strategy_classification_persistence_and_pdf(self):
        option=self.row | {'deal_id':'200','code':'US.QQQ260925P500000','trd_side':'SELL'}
        app.upsert('123',[option])
        self.assertEqual(len(app.selection(self.q | {'asset':'stock'})),1)
        self.assertEqual(app.selection(self.q | {'asset':'option'})[0]['strategy_label'],'待分类')
        r=self.client.post('/api/fill',json={'id':'123:200','strategy':'铁鹰','thesis':'区间交易','notes':'平仓腿','bias':'中性'},headers=self.h)
        self.assertEqual(r.status_code,200)
        app.upsert('123',[option])
        rows=app.selection(self.q | {'asset':'option','strategy':'铁鹰'})
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['notes'],'平仓腿')
        self.assertEqual(rows[0]['option_type'],'Put')
        content=''.join(p.extract_text() for p in PdfReader(app.pdf(app.selection(self.q),self.q,'')).pages)
        self.assertIn('股票 / ETF',content)
        self.assertIn('期权 · 铁鹰',content)
        self.assertEqual(app.scope(self.q),app.scope(self.q | {'asset':'','strategy':''}))
        self.assertNotEqual(app.scope(self.q),app.scope(self.q | {'asset':'option'}))

    def test_account_failure_is_json(self):
        with patch('app.context', side_effect=PermissionError('SDK log denied')):
            response=self.client.post('/api/accounts',json={},headers=self.h)
        self.assertEqual(response.status_code,500)
        self.assertTrue(response.is_json)
        self.assertIn('权限',response.json['error'])

    def test_review_scope_and_pdf_long_chinese(self):
        text='复盘：等待突破确认，严格遵守止损计划。\n'*250
        self.client.post('/api/review',json=self.q | {'notes':'本周耐心等待。'},headers=self.h)
        self.client.post('/api/fill',json={'id':'123:100','thesis':'突破 <500> & 回踩','notes':text,'bias':'看多'},headers=self.h)
        response=self.client.get('/api/summary.pdf',query_string=self.q)
        self.assertEqual(response.status_code,200)
        reader=PdfReader(io.BytesIO(response.data))
        content=''.join(p.extract_text() for p in reader.pages)
        self.assertIn('本周耐心等待',content)
        self.assertIn('突破 <500> & 回踩',content)
        self.assertGreater(len(reader.pages),2)
        self.assertEqual(self.client.get('/api/fills',query_string=self.q | {'symbol':'QQQ'}).json['review'],'')
        output=Path('test-output');output.mkdir(exist_ok=True)
        (output/'summary-check.pdf').write_bytes(response.data)

    def test_unreachable_opend(self):
        with self.assertRaisesRegex(ValueError,'OpenD'):
            app.context(app.DEFAULTS | {'port':1})

    def test_sync_uses_sdk_compatible_seconds(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        ctx=MagicMock()
        frame=MagicMock()
        frame.to_dict.return_value=[self.row]
        def history(**kw):
            from datetime import datetime
            datetime.strptime(kw['start'], '%Y-%m-%d %H:%M:%S')
            datetime.strptime(kw['end'], '%Y-%m-%d %H:%M:%S')
            return 0,frame
        ctx.history_deal_list_query.side_effect=history
        mm=SimpleNamespace(RET_OK=0,TrdEnv=SimpleNamespace(REAL='REAL'))
        with patch('app.context',return_value=(mm,ctx)), patch('app.settings',return_value=app.DEFAULTS | {'account':'123'}):
            app.sync('2026-09-24','2026-09-24')
        self.assertIn('同步完成',app.STATUS['message'])
        ctx.close.assert_called_once()


if __name__=='__main__':
    unittest.main()
