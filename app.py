import io
import json
import os
import re
import secrets
import socket
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

from flask import Flask, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import HTTPException
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from cycles import build_cycles as calculate_cycles, dec
from recognize import recognize
from campaigns import build_campaign
from stocks import build_stock_cycles

ROOT = Path(__file__).parent
DATA = Path(os.environ.get('JOURNAL_DATA', ROOT / 'data'))
DATA.mkdir(parents=True, exist_ok=True)
app = Flask(__name__, static_folder='static')
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024
TOKEN = secrets.token_urlsafe(32)
SYNC_LOCK = threading.Lock()
STATUS = {'running': False, 'message': '尚未同步', 'last_sync': None}
DEFAULTS = {'port': 11111, 'firm': 'FUTUINC', 'account': '', 'auto': False, 'lookback': 90}


@contextmanager
def db():
    conn = sqlite3.connect(DATA / 'journal.sqlite3', timeout=20)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS fills (
          id TEXT PRIMARY KEY, account TEXT, deal_id TEXT, order_id TEXT,
          code TEXT, name TEXT, side TEXT, qty TEXT, price TEXT, time TEXT,
          status TEXT, thesis TEXT DEFAULT '', notes TEXT DEFAULT '', bias TEXT DEFAULT '',
          raw TEXT, synced TEXT);
        CREATE INDEX IF NOT EXISTS fills_time ON fills(time);
        CREATE TABLE IF NOT EXISTS reviews (scope TEXT PRIMARY KEY, notes TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS cycle_reviews (id TEXT PRIMARY KEY, thesis TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', multiplier TEXT NOT NULL DEFAULT '100', fees TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS lifecycle_links (close_pair TEXT PRIMARY KEY, open_pair TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS campaigns (id TEXT PRIMARY KEY, strategy TEXT NOT NULL, title TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS campaign_members (pair_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, stage TEXT NOT NULL);
        ''')
        if 'strategy' not in {r[1] for r in c.execute('PRAGMA table_info(fills)')}:
            with sqlite3.connect(DATA / 'before-strategy-update.sqlite3') as backup:
                c.backup(backup)
            c.execute("ALTER TABLE fills ADD COLUMN strategy TEXT NOT NULL DEFAULT ''")
        if 'pair_id' not in {r[1] for r in c.execute('PRAGMA table_info(fills)')}:
            c.commit()
            with sqlite3.connect(DATA / 'before-pair-update.sqlite3') as backup:
                c.backup(backup)
            c.execute("ALTER TABLE fills ADD COLUMN pair_id TEXT NOT NULL DEFAULT ''")


def classify(row):
    r = dict(row)
    option = re.fullmatch(r'US\.([A-Z0-9.]+?)(\d{6})([CP])(\d+)', r['code'].upper())
    r['asset'] = 'option' if option else 'stock'
    r['option_type'] = ('Call' if option[3] == 'C' else 'Put') if option else ''
    r['underlying'] = option[1] if option else r['code']
    r['expiry'] = option[2] if option else ''
    r['strategy_label'] = (r.get('strategy') or '待分类') if option else ''
    return r


def build_cycles(rows):
    with db() as c:
        links=dict(c.execute('SELECT close_pair,open_pair FROM lifecycle_links').fetchall())
        campaigns=[dict(r) for r in c.execute('SELECT * FROM campaigns')]
        members=[dict(r) for r in c.execute('SELECT * FROM campaign_members')]
    excluded={r['pair_id'] for r in members}
    output=calculate_cycles([r for r in rows if r['pair_id'] not in excluded],links)
    for campaign in campaigns:
        result=build_campaign(campaign,[r for r in members if r['campaign_id']==campaign['id']],rows)
        if result:output.append(result)
    output.extend(build_stock_cycles(rows))
    return output


@app.get('/api/executions')
def executions():
    visible={r['pair_id'] for r in selection(request.args) if r['pair_id']}
    with db() as c:
        all_rows=[dict(r) for r in c.execute("SELECT * FROM fills WHERE pair_id<>'' ORDER BY time")]
        links=dict(c.execute('SELECT close_pair,open_pair FROM lifecycle_links').fetchall())
    groups={}
    for r in all_rows:
        if r['pair_id'] in visible:
            groups.setdefault(r['pair_id'],[]).append(r)
    return jsonify(groups=[{'id':k,'legs':v,'strategy':v[0]['strategy'],'time':min(r['time'] for r in v),'open_pair':links.get(k,'')} for k,v in groups.items() if len(v) in (1,2)])


@app.post('/api/lifecycle-link')
def lifecycle_link():
    v=request.get_json()
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        links=dict(c.execute('SELECT close_pair,open_pair FROM lifecycle_links').fetchall())
        close=v.get('close_pair','')
        if v.get('unlink'):
            c.execute('DELETE FROM lifecycle_links WHERE close_pair=?',(close,))
            return jsonify(ok=True)
        opening=v.get('open_pair','')
        if not opening or not close or opening==close:
            raise ValueError('请分别放入开仓组合和平仓组合')
        rows=[dict(r) for r in c.execute("SELECT * FROM fills WHERE pair_id<>''")]
        a=sorted([r for r in rows if r['pair_id']==opening],key=lambda r:r['code'])
        b=sorted([r for r in rows if r['pair_id']==close],key=lambda r:r['code'])
        if len(a) not in (1,2) or len(b)!=len(a):
            raise ValueError('开平仓需同为单张期权，或同为两腿组合')
        if a[0]['account']!=b[0]['account'] or [r['code'] for r in a]!=[r['code'] for r in b]:
            raise ValueError('开平仓需为同账户、完全相同的两张合约。移仓的新合约不能当作旧仓平仓。')
        if max(r['time'] for r in a)>=min(r['time'] for r in b):
            raise ValueError('开仓时间必须早于平仓；请核对两个方框是否放反')
        if any(x['side'].startswith('BUY')==y['side'].startswith('BUY') for x,y in zip(a,b)):
            raise ValueError('平仓的两条腿必须分别与开仓方向相反')
        if opening in links or close in links.values():
            raise ValueError('组合已被用作相反角色，请先解除原来的手动关联')
        if any(r['strategy']!=a[0]['strategy'] for r in a+b):
            raise ValueError('开平仓策略标签不同，请先统一策略标签再关联')
        links[close]=opening
        result=calculate_cycles(rows,links)
        target=next((x for x in result if x['id']==opening),None)
        if not target or target['incomplete'] or not any(r['pair_id']==close for r in target['fills']):
            raise ValueError('数量不足或开仓结构不符，无法关联。请核对已平数量和两腿数量。')
        # Do not invalidate another previously confirmed partial close.
        for cp,op in links.items():
            if not any(x['id']==op and any(r['pair_id']==cp for r in x['fills']) for x in result):
                raise ValueError('此次关联会超过可平数量或影响现有手动关联，请先解除冲突关联')
        review=c.execute('SELECT multiplier FROM cycle_reviews WHERE id=?',(opening,)).fetchone()
        multiplier=dec(review[0]) if review else dec(100)
        if v.get('save'):
            # Keep any existing standalone close review visible in the unified review.
            if links.get(close)==opening and c.execute('SELECT open_pair FROM lifecycle_links WHERE close_pair=?',(close,)).fetchone() is None:
                old=c.execute('SELECT * FROM cycle_reviews WHERE id=?',(close,)).fetchone()
                if old and (old['thesis'] or old['notes']):
                    current=c.execute('SELECT * FROM cycle_reviews WHERE id=?',(opening,)).fetchone()
                    merged=dict(current) if current else {'thesis':'','notes':'','multiplier':'100','fees':''}
                    for field in ('thesis','notes'):
                        if old[field]:
                            merged[field]+='\n\n[平仓组合原记录]\n'+old[field]
                    c.execute('INSERT OR REPLACE INTO cycle_reviews VALUES (?,?,?,?,?)',(opening,merged['thesis'],merged['notes'],merged['multiplier'],merged['fees']))
            c.execute('INSERT OR REPLACE INTO lifecycle_links VALUES (?,?)',(close,opening))
        return jsonify(ok=True,strategy=target['strategy'],status=target['status'],remaining_qty=target['remaining_qty'],gross_pnl=str((dec(target['gross_points'])*multiplier).quantize(dec('.01'))),multiplier=str(multiplier))


def group_key(r):
    return (0, '') if r['asset'] == 'stock' else (1, r['strategy_label'])


def group_label(r):
    return '股票 / ETF' if r['asset'] == 'stock' else '期权 · ' + r['strategy_label']


def settings():
    with db() as c:
        row = c.execute('SELECT value FROM settings WHERE id=1').fetchone()
    return DEFAULTS | (json.loads(row[0]) if row else {})


@app.before_request
def local_only():
    if request.host.split(':')[0] not in ('127.0.0.1', 'localhost'):
        return jsonify(error='仅允许本机访问'), 403
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.headers.get('X-Journal-Token') != TOKEN:
        return jsonify(error='页面已过期，请刷新'), 403


@app.errorhandler(ValueError)
def invalid(e):
    return jsonify(error=str(e)), 400


@app.errorhandler(Exception)
def api_error(e):
    if isinstance(e, HTTPException):
        return jsonify(error=e.description), e.code
    app.logger.exception('Request failed')
    if isinstance(e, PermissionError):
        return jsonify(error='本地服务没有文件访问权限。请通过「打开复盘应用.cmd」重新启动服务后再连接 OpenD。'), 500
    return jsonify(error='本地服务处理失败，请重试；详细原因已记录在后台日志。'), 500


@app.get('/')
def index():
    return send_from_directory(ROOT / 'static', 'index.html')


@app.get('/api/state')
def state():
    cfg = settings()
    return jsonify(token=TOKEN, settings=cfg, status=STATUS, firms=['FUTUINC', 'FUTUSG', 'FUTUAU', 'FUTUSECURITIES', 'FUTUCA', 'FUTUMY', 'FUTUJP'])


@app.post('/api/settings')
def save_settings():
    v = request.get_json()
    port, lookback = int(v.get('port', 11111)), int(v.get('lookback', 90))
    if not 1 <= port <= 65535 or not 1 <= lookback <= 3650:
        raise ValueError('端口或回溯天数不正确')
    cfg = {'port': port, 'lookback': lookback, 'firm': str(v['firm']), 'account': str(v.get('account', '')), 'auto': bool(v.get('auto'))}
    with db() as c:
        c.execute('INSERT OR REPLACE INTO settings VALUES (1,?)', (json.dumps(cfg),))
    return jsonify(ok=True)


def context(cfg):
    try:
        with socket.create_connection(('127.0.0.1', cfg['port']), timeout=2):
            pass
    except OSError:
        raise ValueError(f"未连接 OpenD：请启动并登录 moomoo OpenD，确认 API 端口为 {cfg['port']}。")
    import moomoo as mm
    firm = getattr(mm.SecurityFirm, cfg['firm'], None)
    if firm is None:
        raise ValueError('当前 SDK 不支持此券商，请检查券商设置')
    return mm, mm.OpenSecTradeContext(filter_trdmarket=mm.TrdMarket.US, host='127.0.0.1', port=cfg['port'], security_firm=firm)


@app.post('/api/accounts')
def accounts():
    ctx = None
    try:
        mm, ctx = context(settings())
        ret, frame = ctx.get_acc_list()
        if ret != mm.RET_OK:
            raise ValueError(str(frame))
        rows = [{'id': str(r['acc_id']), 'type': str(r['acc_type'])} for r in frame.to_dict('records') if str(r['trd_env']) == str(mm.TrdEnv.REAL)]
        return jsonify(accounts=rows)
    finally:
        if ctx:
            ctx.close()


def upsert(account, rows):
    now = datetime.now().isoformat(timespec='seconds')
    with db() as c:
        for r in rows:
            if not str(r.get('deal_id', '')):
                raise ValueError('成交数据缺少成交编号，未保存本批数据')
            key = f"{account}:{r['deal_id']}"
            values = [key, account] + [str(r.get(k, '')) for k in ('deal_id', 'order_id', 'code', 'stock_name', 'trd_side', 'qty', 'price', 'create_time', 'status')] + [json.dumps(r, default=str, ensure_ascii=False), now]
            c.execute('''INSERT INTO fills (id,account,deal_id,order_id,code,name,side,qty,price,time,status,raw,synced)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
              order_id=excluded.order_id,code=excluded.code,name=excluded.name,side=excluded.side,
              qty=excluded.qty,price=excluded.price,time=excluded.time,status=excluded.status,
              raw=excluded.raw,synced=excluded.synced''', values)


def sync(start, end):
    if not SYNC_LOCK.acquire(blocking=False):
        return
    STATUS.update(running=True, message='正在读取 OpenD 成交…')
    ctx = None
    try:
        cfg = settings()
        if not cfg['account']:
            raise ValueError('请先连接 OpenD 并选择实盘账户')
        mm, ctx = context(cfg)
        cursor = date.fromisoformat(start)
        finish = date.fromisoformat(end)
        count = 0
        while cursor <= finish:
            last = min(cursor + timedelta(days=29), finish)
            ret, frame = ctx.history_deal_list_query(start=f'{cursor} 00:00:00', end=f'{last} 23:59:59', trd_env=mm.TrdEnv.REAL, acc_id=int(cfg['account']))
            if ret != mm.RET_OK:
                raise ValueError(str(frame))
            rows = frame.to_dict('records')
            upsert(cfg['account'], rows)
            count += len(rows)
            STATUS['message'] = f'已读取 {count} 笔 · 至 {last}'
            cursor = last + timedelta(days=1)
            if cursor <= finish:
                time.sleep(3.2)
        STATUS.update(message=f'同步完成：读取 {count} 笔，重复成交已合并', last_sync=datetime.now().isoformat(timespec='seconds'))
    except Exception as e:
        STATUS['message'] = f'同步未完成：{e}（已读取的数据和笔记仍保留）'
    finally:
        if ctx:
            ctx.close()
        STATUS['running'] = False
        SYNC_LOCK.release()


def dates(v):
    start, end = v.get('start', ''), v.get('end', '')
    try:
        a, b = date.fromisoformat(start), date.fromisoformat(end)
    except (ValueError, TypeError):
        raise ValueError('请选择有效的开始和结束日期')
    if a > b:
        raise ValueError('开始日期不能晚于结束日期')
    return start, end


@app.post('/api/sync')
def sync_route():
    start, end = dates(request.get_json())
    if STATUS['running']:
        return jsonify(error='同步正在进行'), 409
    threading.Thread(target=sync, args=(start, end), daemon=True).start()
    return jsonify(ok=True)


def selection(v):
    start, end = dates(v)
    query = 'SELECT * FROM fills WHERE substr(time,1,10) BETWEEN ? AND ?'
    params = [start, end]
    for field in ('account', 'bias'):
        if v.get(field):
            query += f' AND {field}=?'
            params.append(v[field])
    if v.get('symbol'):
        query += ' AND instr(upper(code),?)>0'
        params.append(v['symbol'].upper().strip())
    with db() as c:
        rows = [classify(x) for x in c.execute(query + ' ORDER BY time DESC,id', params)]
        labels={r['pair_id']:dict(r) for r in c.execute('SELECT m.pair_id,m.stage,p.strategy,p.title FROM campaign_members m JOIN campaigns p ON p.id=m.campaign_id')}
    for row in rows:
        if row['pair_id'] in labels:
            meta=labels[row['pair_id']]
            row.update(strategy=meta['strategy'],strategy_label=meta['strategy'],stage=meta['stage'],campaign_title=meta['title'])
    if v.get('asset'):
        rows = [r for r in rows if r['asset'] == v['asset']]
    if v.get('strategy'):
        rows = [r for r in rows if r['asset'] == 'option' and r['strategy_label'] == v['strategy']]
    return sorted(rows, key=group_key)


def scope(v):
    dates(v)
    key = {k: v.get(k, '') for k in ('start', 'end', 'symbol', 'bias', 'account')}
    key.update({k: v[k] for k in ('asset', 'strategy') if v.get(k)})
    return json.dumps(key, sort_keys=True)


@app.get('/api/fills')
def fills():
    rows = selection(request.args)
    with db() as c:
        note = c.execute('SELECT notes FROM reviews WHERE scope=?', (scope(request.args),)).fetchone()
        accts = [x[0] for x in c.execute('SELECT DISTINCT account FROM fills')]
        strategies = [x[0] for x in c.execute("SELECT DISTINCT strategy FROM fills WHERE strategy<>'' ORDER BY strategy")]
    return jsonify(fills=rows, review=note[0] if note else '', accounts=accts, strategies=strategies)


@app.post('/api/fill')
def edit_fill():
    v = request.get_json()
    if v.get('bias', '') not in ('', '看多', '看跌', '中性'):
        raise ValueError('无效的方向标签')
    if any(len(v.get(k, '')) > 30000 for k in ('thesis', 'notes')):
        raise ValueError('单项笔记最多 30000 字')
    with db() as c:
        if 'strategy' in v:
            strategy = str(v['strategy']).strip()
            if len(strategy) > 80:
                raise ValueError('策略名称最多 80 字')
            row = c.execute('SELECT * FROM fills WHERE id=?', (v['id'],)).fetchone()
            if row is None:
                raise ValueError('找不到这笔成交')
            if row['pair_id'] and strategy!=row['strategy'] and c.execute('SELECT 1 FROM lifecycle_links WHERE open_pair=? OR close_pair=?',(row['pair_id'],row['pair_id'])).fetchone():
                raise ValueError('此组合已手动关联开平仓，请先解除手动关联再修改策略')
            if strategy and classify(row)['asset'] != 'option':
                raise ValueError('期权策略仅适用于期权成交')
            if row['pair_id']:
                c.execute('UPDATE fills SET strategy=? WHERE pair_id=?', (strategy, row['pair_id']))
            else:
                c.execute('UPDATE fills SET strategy=? WHERE id=?', (strategy, v['id']))
        result = c.execute('UPDATE fills SET thesis=?,notes=?,bias=? WHERE id=?', (v.get('thesis', ''), v.get('notes', ''), v.get('bias', ''), v['id']))
        if not result.rowcount:
            raise ValueError('找不到这笔成交')
        # Auto-link only an unambiguous, structurally compatible second leg.
        row = classify(c.execute('SELECT * FROM fills WHERE id=?', (v['id'],)).fetchone())
        candidates = pair_candidates(c, row)
        if not row['pair_id'] and is_vertical(row['strategy']) and len(candidates) == 1 and candidates[0]['compatible']:
            link_pair(c, row, candidates[0])
    return jsonify(ok=True)


def is_vertical(strategy):
    return strategy.lower().strip() in ('pds', 'cds', 'pcs', 'ccs', 'put debit spread', 'call debit spread', 'put credit spread', 'call credit spread') or strategy in ('牛市看涨价差','熊市看涨价差','牛市看跌价差','熊市看跌价差')


def pair_candidates(c, anchor):
    if anchor['asset'] != 'option' or anchor['pair_id']:
        return []
    try:
        when = datetime.fromisoformat(anchor['time'])
    except ValueError:
        return []
    output = []
    for raw in c.execute('SELECT * FROM fills WHERE account=? AND id<>?', (anchor['account'], anchor['id'])):
        r = classify(raw)
        if r['asset'] != 'option' or r['underlying'] != anchor['underlying'] or r['pair_id'] or r['code'] == anchor['code']:
            continue
        try:
            delta = abs((datetime.fromisoformat(r['time']) - when).total_seconds())
        except ValueError:
            continue
        if delta > 60:
            continue
        same_type = r['option_type'] == anchor['option_type']
        opposite = (r['side'].startswith('BUY') and anchor['side'].startswith('SELL')) or (r['side'].startswith('SELL') and anchor['side'].startswith('BUY'))
        try:
            equal_qty = float(r['qty']) == float(anchor['qty'])
        except ValueError:
            equal_qty = False
        strategy_ok = not r['strategy'] or r['strategy'] == anchor['strategy']
        expected_type = 'Put' if anchor['strategy'].lower().strip() in ('pds','pcs') or '看跌价差' in anchor['strategy'] else 'Call' if anchor['strategy'].lower().strip() in ('cds','ccs') or '看涨价差' in anchor['strategy'] else ''
        r['compatible'] = same_type and (not expected_type or r['option_type'] == expected_type) and opposite and equal_qty and r['expiry'] == anchor['expiry'] and strategy_ok
        r['seconds_apart'] = delta
        r['reason'] = '同到期、同类型、反向且数量相同' if r['compatible'] else '需核对到期日、买卖方向、数量与原策略'
        output.append(r)
    return sorted(output, key=lambda r: (not r['compatible'], r['seconds_apart'], r['id']))


def link_pair(c, anchor, other):
    if not anchor['strategy']:
        raise ValueError('请先填写策略')
    if other['strategy'] and other['strategy'] != anchor['strategy']:
        raise ValueError('候选腿已标注其他策略，请先核对并调整')
    pair_id = secrets.token_hex(6)
    c.execute('UPDATE fills SET pair_id=?,strategy=? WHERE id IN (?,?)', (pair_id, anchor['strategy'], anchor['id'], other['id']))


@app.get('/api/pair')
def pair_info():
    with db() as c:
        raw = c.execute('SELECT * FROM fills WHERE id=?', (request.args.get('id'),)).fetchone()
        if raw is None:
            raise ValueError('找不到成交')
        row = classify(raw)
        linked = [classify(x) for x in c.execute('SELECT * FROM fills WHERE pair_id=? AND id<>?', (row['pair_id'], row['id']))] if row['pair_id'] else []
        return jsonify(linked=linked, candidates=pair_candidates(c,row), pair_id=row['pair_id'])


@app.post('/api/pair')
def save_pair():
    v = request.get_json()
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        raw = c.execute('SELECT * FROM fills WHERE id=?', (v['id'],)).fetchone()
        if raw is None:
            raise ValueError('找不到成交')
        row = classify(raw)
        if v.get('unlink'):
            if row['pair_id']:
                if c.execute('SELECT 1 FROM lifecycle_links WHERE open_pair=? OR close_pair=?',(row['pair_id'],row['pair_id'])).fetchone():
                    raise ValueError('请先在开平仓关联框解除手动关联，再拆分两条腿')
                c.execute("UPDATE fills SET pair_id='' WHERE pair_id=?", (row['pair_id'],))
        else:
            other = next((r for r in pair_candidates(c,row) if r['id'] == v.get('other_id')), None)
            if other is None:
                raise ValueError('候选已变化或已关联，请刷新后重试')
            link_pair(c,row,other)
    return jsonify(ok=True)


@app.post('/api/review')
def review():
    v = request.get_json()
    if len(v.get('notes', '')) > 60000:
        raise ValueError('区间笔记最多 60000 字')
    with db() as c:
        c.execute('INSERT OR REPLACE INTO reviews VALUES (?,?)', (scope(v), v.get('notes', '')))
    return jsonify(ok=True)


@app.post('/api/recognize')
def recognize_route():
    v=request.get_json()
    ids=v.get('ids',[])
    if not isinstance(ids,list) or len(ids) not in (1,2) or len(set(ids))!=len(ids):
        raise ValueError('请拖入一条或两条不同的期权成交')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        marks=','.join('?' for _ in ids)
        legs=[dict(r) for r in c.execute(f'SELECT * FROM fills WHERE id IN ({marks})',ids)]
        if len(legs)!=len(ids):
            raise ValueError('成交不存在，请刷新列表')
        history=[dict(r) for r in c.execute("SELECT * FROM fills WHERE pair_id<>''")]
        result=recognize(legs,history,v.get('mode','auto'))
        existing={r['pair_id'] for r in legs if r['pair_id']}
        if existing:
            members={r['id'] for r in history if r['pair_id'] in existing}
            single_roundtrip=result.get('roundtrip') and all(not r['pair_id'] or len([x for x in history if x['pair_id']==r['pair_id']])==1 for r in legs)
            if (len(existing)>1 or members!=set(ids)) and not single_roundtrip:
                raise ValueError('其中一条已属于其他组合。请先在原组合解除关联，避免覆盖原复盘。')
        if v.get('save'):
            if v.get('confirmed_strategy')!=result['strategy']:
                raise ValueError('识别结果已变化，请重新确认')
            pair_id=next(iter(existing)) if existing else secrets.token_hex(6)
            if result.get('roundtrip'):
                for r in legs:
                    c.execute('UPDATE fills SET strategy=?,pair_id=? WHERE id=?',(result['strategy'],r['pair_id'] or secrets.token_hex(6),r['id']))
            else:
                c.execute(f'UPDATE fills SET strategy=?,pair_id=? WHERE id IN ({marks})',(result['strategy'],pair_id,*ids))
            result['pair_id']=pair_id
        return jsonify(result)


def strategy_cycles(v):
    selected_ids = {r['id'] for r in selection(v)}
    with db() as c:
        all_rows = [classify(r) for r in c.execute("SELECT * FROM fills")]
        reviews = {r['id']:dict(r) for r in c.execute('SELECT * FROM cycle_reviews')}
    output=[]
    for cycle in build_cycles(all_rows):
        if not any(r['id'] in selected_ids for r in cycle['fills']):
            continue
        review=reviews.get(cycle['id'], {'thesis':'','notes':'','multiplier':'1' if cycle.get('asset')=='stock' else '100','fees':''})
        cycle.update({k:review[k] for k in ('thesis','notes','multiplier','fees')})
        cycle['gross_pnl']=str((dec(cycle['gross_points'])*dec(cycle['multiplier'])).quantize(dec('.01'))) if cycle['gross_points'] is not None else None
        for name in ('closed_basis','close_proceeds'):
            cycle[name]=str((dec(cycle[name+'_points'])*dec(cycle['multiplier'])).quantize(dec('.01'))) if cycle[name+'_points'] is not None else None
        cycle['net_pnl']=str((dec(cycle['gross_pnl'])-dec(cycle['fees'])).quantize(dec('.01'))) if cycle['status']=='已平仓' and cycle['fees']!='' and cycle['gross_pnl'] is not None else None
        output.append(cycle)
    return sorted(output,key=lambda x:x['first_time'],reverse=True)


@app.get('/api/cycles')
def cycles_route():
    return jsonify(cycles=strategy_cycles(request.args))


@app.post('/api/cycle')
def cycle_save():
    v=request.get_json()
    from decimal import InvalidOperation
    try:
        multiplier=dec(v.get('multiplier','100'))
        fees=dec(v['fees']) if v.get('fees','')!='' else None
        if not multiplier.is_finite() or multiplier<=0 or multiplier>100000 or (fees is not None and (not fees.is_finite() or fees<0)):
            raise ValueError('合约乘数需为正数，费用不能为负数')
    except (InvalidOperation,TypeError):
        raise ValueError('请输入有效的合约乘数和费用')
    if any(len(v.get(k,''))>30000 for k in ('thesis','notes')):
        raise ValueError('单项笔记最多 30000 字')
    with db() as c:
        rows=[classify(r) for r in c.execute("SELECT * FROM fills")]
        if v['id'] not in {x['id'] for x in build_cycles(rows)}:
            raise ValueError('组合已改变，请刷新后再保存')
        c.execute('INSERT OR REPLACE INTO cycle_reviews VALUES (?,?,?,?,?)',(v['id'],v.get('thesis',''),v.get('notes',''),str(multiplier),str(fees) if fees is not None else ''))
    return jsonify(ok=True)


def pdf(rows, v, note, cycles=None):
    from reportlab.pdfbase.ttfonts import TTFont
    font_path = Path('C:/Windows/Fonts/simsun.ttc')
    if font_path.exists():
        pdfmetrics.registerFont(TTFont('JournalChinese', str(font_path), subfontIndex=0))
        font = 'JournalChinese'
    else:
        pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
        font = 'STSong-Light'
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=(595, 842), leftMargin=42, rightMargin=42, topMargin=42, bottomMargin=42, title='交易复盘 Summary')
    body = ParagraphStyle('body', fontName=font, fontSize=10, leading=16, wordWrap='CJK', spaceAfter=7)
    title = ParagraphStyle('title', parent=body, fontSize=23, leading=30, textColor=colors.HexColor('#143c36'), spaceAfter=15)
    heading = ParagraphStyle('heading', parent=body, fontSize=13, leading=19, spaceBefore=14, textColor=colors.HexColor('#167263'))
    def p(text, style=body):
        return Paragraph(escape(str(text)).replace('\n', '<br/>'), style)
    story = [p('交易复盘 / SUMMARY', title), p(f"{v['start']} — {v['end']} · {len(rows)} 笔成交"), p(f"筛选：标的 {v.get('symbol') or '全部'} / 方向 {v.get('bias') or '全部'} / 账户 {v.get('account') or '全部'}"), p('时间为 OpenD 原始成交时间（美股通常为美东时间）；按成交记录汇总，不计算未确认的盈亏。'), p('区间复盘', heading), p(note or '（未填写）')]
    for cycle in cycles or []:
        if cycle.get('campaign'):
            story.append(p(cycle['title'],heading))
            for stage in dict.fromkeys(r['stage'] for r in cycle['fills']):
                stage_rows=[r for r in cycle['fills'] if r['stage']==stage]
                flow=sum((dec(r['price'])*dec(r['qty'])*(-1 if r['side'].startswith('BUY') else 1) for r in stage_rows),dec(0))*dec(cycle['multiplier'])
                story.append(p(stage+' · 净现金流 USD '+str(flow.quantize(dec('.01')))))
        story += [p(cycle['strategy']+' · 完整交易复盘',heading),p(' / '.join(cycle['codes'])),p(cycle['first_time']+' — '+cycle['last_time']+' · '+cycle['status']),p('开仓 '+cycle['opened_qty']+' 组 / 已平 '+cycle['closed_qty']+' 组 / 剩余 '+cycle['remaining_qty']+' 组'),p('完整交易已实现毛盈亏（USD）：'+(cycle['gross_pnl'] if cycle['gross_pnl'] is not None else '无法确认')+'；乘数 '+cycle['multiplier']),p('净盈亏（USD）：'+(cycle['net_pnl'] if cycle['net_pnl'] is not None else '未计算（费用未填写或尚未全部平仓）')),p('统一 Thesis：'+(cycle['thesis'] or '未填写')),p('统一复盘：'+(cycle['notes'] or '未填写')),p('按完整生命周期计算，可能包含筛选日期以外成交。期权分配、行权和非标准合约需核对。')]
    rows = sorted([classify(r) for r in rows], key=group_key)
    previous_group = None
    for r in rows:
        label = group_label(r)
        if label != previous_group:
            story.append(p(label, heading))
            previous_group = label
        if r.get('pair_id'):
            story.append(p('关联组合：' + r['pair_id']))
        side = {'BUY': '买入', 'SELL': '卖出', 'SELL_SHORT': '卖空', 'BUY_BACK': '买入平空'}.get(r['side'], r['side'])
        story += [p(f"{r['code']} · {side} · {r['bias'] or '未标注观点'}", heading), p(f"{r['time']} | 数量 {r['qty']} | 成交价 {r['price']}"), p(f"账户 {r['account']} | 成交编号 {r['deal_id']} | 状态 {r['status']}"), p('Thesis：' + (r['thesis'] or '（未填写）')), p('复盘笔记：' + (r['notes'] or '（未填写）')), Spacer(1, 7)]
    if not rows:
        story.append(p('该筛选范围没有本地成交记录。'))
    def footer(canvas, document):
        canvas.setFont(font, 8)
        canvas.drawString(42, 23, 'MOOMOO JOURNAL · 本地复盘')
        canvas.drawRightString(553, 23, str(document.page))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    out.seek(0)
    return out


@app.get('/api/summary.pdf')
def summary():
    rows = selection(request.args)
    with db() as c:
        r = c.execute('SELECT notes FROM reviews WHERE scope=?', (scope(request.args),)).fetchone()
    return send_file(pdf(rows, request.args, r[0] if r else '', strategy_cycles(request.args)), mimetype='application/pdf', as_attachment=True, download_name=f"review-{request.args['start']}-{request.args['end']}.pdf")


@app.get('/api/backup')
def backup():
    with db() as c:
        data = {t: [dict(r) for r in c.execute(f'SELECT * FROM {t}')] for t in ('fills', 'reviews', 'settings','cycle_reviews','lifecycle_links','campaigns','campaign_members')}
    return send_file(io.BytesIO(json.dumps(data, ensure_ascii=False, indent=2).encode()), mimetype='application/json', as_attachment=True, download_name=f'journal-backup-{date.today()}.json')


def auto_sync():
    while True:
        time.sleep(60)
        cfg = settings()
        if cfg['auto'] and cfg['account'] and not STATUS['running']:
            today = date.today()
            sync(str(today - timedelta(days=2)), str(today + timedelta(days=1)))


init()
if __name__ == '__main__':
    threading.Thread(target=auto_sync, daemon=True).start()
    app.run(host='127.0.0.1', port=8765, debug=False, threaded=True)
