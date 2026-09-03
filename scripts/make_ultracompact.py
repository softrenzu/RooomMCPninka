import json,re,csv
from pathlib import Path
D=Path(__file__).resolve().parents[1]/'data'
items=[]
for n in range(1,6): items += json.loads((D/'review_packets'/f'packet_{n}.json').read_text(encoding='utf-8'))
items.sort(key=lambda x:x['seq'])

def span(s, words, n=700):
 s=str(s or '')
 for w in words:
  i=s.find(w)
  if i>=0:return re.sub(r'\s+',' ',s[i:i+n]).strip()
 return re.sub(r'\s+',' ',s[:n]).strip()
rows=[]
for x in items:
 d=x.get('api_detail','')
 rows.append({'seq':x['seq'],'締切':x['deadline'],'タイトル':x['title'],'地域':x['area'],'上限':x['max_yen'],'業種':x.get('industry',''),'従業員':x.get('employees',''),'応募資格':span(d,['応募資格','補助対象者','対象企業','申込資格','交付申請ができる者'],850),'対象事業':span(d,['補助対象事業','対象事業','事業内容','目的・概要'],650)})
with (D/'review_ultracompact.csv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
