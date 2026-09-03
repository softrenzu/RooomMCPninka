import json,re
from pathlib import Path
D=Path(__file__).resolve().parents[1]/'data'
items=[]
for n in range(1,6):
    p=D/'review_packets'/f'packet_{n}.json'
    if p.exists(): items+=json.loads(p.read_text(encoding='utf-8'))
items.sort(key=lambda x:x['seq'])

def section(s):
    s=str(s or '')
    # keep the most useful eligibility/target text, then fallback to first 1800 chars
    markers=['応募資格','補助対象者','対象企業','申込資格','対象事業','補助対象事業','概要','目的・概要']
    chunks=[]
    for m in markers:
        i=s.find(m)
        if i>=0: chunks.append(s[i:i+2200])
    out=' '.join(chunks[:2]) if chunks else s[:2200]
    return re.sub(r'\s+',' ',out).strip()[:3500]
md=['# 43件 公募要領・API詳細の応募条件要約','']
for x in items:
    md += [f"## {x['seq']}. {x['title']}",f"- 締切: {x['deadline']}",f"- 地域: {x['area']}",f"- 上限: {x['max_yen']}",f"- 業種: {x.get('industry','')}",f"- 従業員: {x.get('employees','')}",f"- 応募条件抜粋: {section(x.get('api_detail',''))}",'']
(D/'review_facts_43.md').write_text('\n'.join(md),encoding='utf-8')
