import base64, csv, io, json, re, time
from pathlib import Path
import requests
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'
SRC=DATA/'eligible_45_history.csv'
OUTDIR=DATA/'review_packets'
OUTDIR.mkdir(parents=True,exist_ok=True)
API='https://api.jgrants-portal.go.jp/exp/v2/public/subsidies/id/{}'
KEYS=['補助対象者','申請者','応募者','対象者','補助対象事業','対象事業','補助対象経費','対象経費','要件','資格','共同','コンソーシアム','中小企業','小規模','事業所','所在地','所有','賃借','実績','従業員','資本金','宿泊','観光','建築','空き家','太陽光','蓄電池','商店街','船','データセンター','商標','意匠','特許']

def clean(s):
    s=re.sub(r'<[^>]+>',' ',str(s or ''))
    return re.sub(r'\s+',' ',s).strip()

def extract_pdf(b):
    try:
        r=PdfReader(io.BytesIO(b))
        return '\n'.join((p.extract_text() or '') for p in r.pages)
    except Exception:
        return ''

def docs_from(obj):
    out=[]
    for field in ['application_guidelines','outline_of_grant','application_form']:
        v=obj.get(field)
        if not v: continue
        vals=v if isinstance(v,list) else [v]
        for x in vals:
            if not isinstance(x,dict): continue
            name=x.get('name','')
            data=x.get('data','')
            txt=''
            if data:
                try:
                    raw=base64.b64decode(data)
                    if name.lower().endswith('.pdf') or raw[:4]==b'%PDF':
                        txt=extract_pdf(raw)
                    elif name.lower().endswith(('.txt','.csv')):
                        txt=raw.decode('utf-8','ignore')
                except Exception:
                    pass
            out.append({'field':field,'name':name,'text':txt})
    return out

def snippets(text):
    text=re.sub(r'\r','',text)
    compact=re.sub(r'[ \t]+',' ',text)
    hits=[]
    for k in KEYS:
        for m in re.finditer(re.escape(k),compact,re.I):
            a=max(0,m.start()-420); b=min(len(compact),m.end()+850)
            sn=re.sub(r'\s+',' ',compact[a:b]).strip()
            if len(sn)>80 and sn not in hits: hits.append(sn)
            if len(hits)>=24: return hits
    return hits

rows=[]
with SRC.open(encoding='utf-8-sig',newline='') as f:
    for r in csv.DictReader(f):
        if r['今回の扱い']=='新規申請候補': rows.append(r)

packets=[]
for i,r in enumerate(rows,1):
    sid=r['JグランツID']
    resp=requests.get(API.format(sid),timeout=30,headers={'User-Agent':'RooomMCPninka/1.2'})
    resp.raise_for_status()
    arr=resp.json().get('result') or []
    d=arr[0] if arr else {}
    docs=docs_from(d)
    full='\n'.join(x['text'] for x in docs if x['text'])
    packet={
      'seq':i,'id':sid,'title':r['公募名'],'deadline':r['締切'],'area':r['地域'],'max_yen':r['上限額円'],
      'api_detail':clean(d.get('detail')),'catch':clean(d.get('subsidy_catch_phrase')),
      'industry':d.get('industry'),'employees':d.get('target_number_of_employees'),'use_purpose':d.get('use_purpose'),
      'docs':[{'field':x['field'],'name':x['name'],'text_length':len(x['text'])} for x in docs],
      'guideline_text_length':len(full),'snippets':snippets(full),
    }
    packets.append(packet)
    print(i,sid,len(full),len(packet['snippets']),flush=True)
    time.sleep(0.14)

# split into manageable files
for start in range(0,len(packets),9):
    part=packets[start:start+9]
    n=start//9+1
    (OUTDIR/f'packet_{n}.json').write_text(json.dumps(part,ensure_ascii=False,indent=2),encoding='utf-8')
(DATA/'review_packets_summary.json').write_text(json.dumps({'count':len(packets),'parts':(len(packets)+8)//9},ensure_ascii=False,indent=2),encoding='utf-8')
