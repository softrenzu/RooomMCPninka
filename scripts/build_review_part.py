import base64,csv,io,json,os,re,time
from pathlib import Path
import requests
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/'data'; SRC=DATA/'eligible_45_history.csv'; OUT=DATA/'review_packets'; OUT.mkdir(parents=True,exist_ok=True)
API='https://api.jgrants-portal.go.jp/exp/v2/public/subsidies/id/{}'
PART=int(os.environ.get('PART','1')); SIZE=9; START=(PART-1)*SIZE; END=START+SIZE
KEYS=['補助対象者','申請者','応募者','対象者','補助対象事業','対象事業','補助対象経費','対象経費','要件','資格','共同','コンソーシアム','中小企業','小規模','事業所','所在地','所有','賃借','実績','従業員','資本金','宿泊','観光','建築','空き家','太陽光','蓄電池','商店街','船舶','データセンター','商標','意匠','特許']

def clean(s): return re.sub(r'\s+',' ',re.sub(r'<[^>]+>',' ',str(s or ''))).strip()
def pdftext(raw):
    try: return '\n'.join((p.extract_text() or '') for p in PdfReader(io.BytesIO(raw)))
    except Exception: return ''
def docs(d):
    out=[]
    for field in ['application_guidelines','outline_of_grant','application_form']:
        v=d.get(field); vals=v if isinstance(v,list) else ([v] if v else [])
        for x in vals:
            if not isinstance(x,dict): continue
            name=x.get('name',''); txt=''; b=x.get('data','')
            if b:
                try:
                    raw=base64.b64decode(b)
                    if name.lower().endswith('.pdf') or raw[:4]==b'%PDF': txt=pdftext(raw)
                except Exception: pass
            out.append((field,name,txt))
    return out
def snippets(text):
    t=re.sub(r'[ \t]+',' ',text.replace('\r','')); hits=[]; seen=set()
    for k in KEYS:
        for m in re.finditer(re.escape(k),t,re.I):
            a=max(0,m.start()-500); b=min(len(t),m.end()+1100); s=re.sub(r'\s+',' ',t[a:b]).strip()
            sig=s[:180]
            if len(s)>100 and sig not in seen:
                seen.add(sig); hits.append(s)
            if len(hits)>=32:return hits
    return hits
rows=[]
with SRC.open(encoding='utf-8-sig',newline='') as f:
    rows=[r for r in csv.DictReader(f) if r['今回の扱い']=='新規申請候補']
sel=rows[START:END]; packets=[]
for j,r in enumerate(sel,START+1):
    sid=r['JグランツID']; resp=requests.get(API.format(sid),timeout=40,headers={'User-Agent':'RooomMCPninka/1.3'}); resp.raise_for_status(); arr=resp.json().get('result') or []; d=arr[0] if arr else {}
    ds=docs(d); full='\n'.join(x[2] for x in ds if x[2]); packets.append({'seq':j,'id':sid,'title':r['公募名'],'deadline':r['締切'],'area':r['地域'],'max_yen':r['上限額円'],'api_detail':clean(d.get('detail')),'catch':clean(d.get('subsidy_catch_phrase')),'industry':d.get('industry'),'employees':d.get('target_number_of_employees'),'use_purpose':d.get('use_purpose'),'docs':[{'field':a,'name':b,'text_length':len(c)} for a,b,c in ds],'guideline_text_length':len(full),'snippets':snippets(full)})
    print(PART,j,sid,len(full),flush=True); time.sleep(.14)
(OUT/f'packet_{PART}.json').write_text(json.dumps(packets,ensure_ascii=False,indent=2),encoding='utf-8')
