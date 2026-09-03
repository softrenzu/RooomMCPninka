import csv
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'
SRC=DATA/'eligibility.csv'
OUT=DATA/'eligibility_refined.csv'
OUTMD=DATA/'eligibility_refined.md'
SUM=DATA/'eligibility_refined_summary.json'
JST=ZoneInfo('Asia/Tokyo')

KNOWN=[
 (r'ゼロエミッション推進に向けた事業転換支援事業.*製品開発', '申請対応中'),
 (r'小規模事業者持続化補助金', '申請済'),
 (r'TOKYO戦略的イノベーション', '申請対応中'),
 (r'AI.*データ.*知財|データ知財取得支援', '準備中'),
 (r'インバウンド対応力強化', '申請対応中'),
 (r'観光関連事業者.*環境対策促進', '差戻し対応中'),
 (r'課題解決型製品.*サービス.*販路拡大', '申請済'),
]

DIRECT=[
 r'AI|人工知能|生成AI|DX|デジタル|ICT|IT導入|情報通信|ソフトウェア|システム|データ活用|サイバー',
 r'宿泊|旅館|ホテル|観光|インバウンド|民泊',
 r'不動産|空き家',
 r'知財|特許|商標|意匠',
 r'省エネ|再エネ|太陽光|蓄電池|脱炭素|ゼロエミッション|省CO2',
]
GENERIC_SME=r'中小企業|小規模事業者|スタートアップ|創業'
GENERIC_PURPOSE=r'販路|新事業|事業転換|生産性|人材|設備|知財|デジタル|省エネ|脱炭素|事業継続|防災|海外展開|成長|経営'

UNRELATED=[
 (r'水素|アンモニア', '水素・燃料分野の専門事業'),
 (r'内航|外航|船舶|海運|造船|港湾', '船舶・海運分野'),
 (r'鉄道|タクシー|バス事業者|航空|空港', '特定運輸分野'),
 (r'宇宙|ロケット|衛星', '宇宙分野'),
 (r'半導体|蓄電池等の製品の持続可能性|電池材料', '専門製造・材料分野'),
 (r'原子力|核燃料', '原子力分野'),
 (r'医療|病院|診療所|医薬|介護|福祉|保育|学校法人', '医療・福祉・教育分野'),
 (r'農業|農林|畜産|酪農|水産|漁業|林業|森林', '農林水産分野'),
 (r'酒類|酒造|醸造|清酒|焼酎', '酒類分野'),
 (r'鉱業|鉱山|採石', '鉱業分野'),
]

rows=[]
with SRC.open(encoding='utf-8-sig',newline='') as f:
    for r in csv.DictReader(f): rows.append(r)

for r in rows:
    title=r['補助金_公募名']
    original=r['判定']
    status='新規'
    for pat,st in KNOWN:
        if re.search(pat,title,re.I): status=st; break

    if original=='×':
        refined='×'; reason=r['判定理由']; status='対象外'
    else:
        hit_unrelated=None
        for pat,label in UNRELATED:
            if re.search(pat,title,re.I): hit_unrelated=label; break
        direct=any(re.search(p,title,re.I) for p in DIRECT)
        generic=bool(re.search(GENERIC_SME,title,re.I) and re.search(GENERIC_PURPOSE,title,re.I))
        # 専門技術R&Dは、ROOOMTECHの直接事業テーマに一致しない限り対象外とする
        specialist_rd=bool(re.search(r'研究開発|技術開発|実証|量産化|標準化',title,re.I))
        if hit_unrelated:
            refined='×'; reason=f'ROOOMTECHの確認済み事業領域外（{hit_unrelated}）'; status='対象外'
        elif direct or generic:
            # 研究開発でもAI/宿泊/観光/省エネ等の直接テーマなら候補に残す
            refined='○'; reason='ROOOMTECHの事業領域と直接一致。公募要領の応募資格を最終確認して申請準備'
            if status=='新規': status='申請候補'
        elif specialist_rd:
            refined='×'; reason='専門技術の研究開発・実証公募で、ROOOMTECHの確認済み事業領域との直接一致がない'; status='対象外'
        else:
            refined='△'; reason='地域・法人条件だけでは判断不能。対象者・対象経費・事業内容を公募要領で個別確認'
            if status=='新規': status='要確認'
    r['最終一次判定']=refined
    r['現在状況']=status
    r['精査理由']=reason

fields=['No','最終一次判定','現在状況','締切','残日数','補助金_公募名','対象地域','従業員条件','上限額円','精査理由','JグランツID','URL']
with OUT.open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)

def esc(v): return str(v or '').replace('|','｜').replace('\n',' ')
md=['# Jグランツ382件 ROOOMTECH申請可否 精査表','',f"生成日時: {datetime.now(JST).strftime('%Y-%m-%d %H:%M JST')}",'','○=申請候補、△=公募要領の個別確認が必要、×=現時点で申請対象外。','','|No|判定|状況|締切|公募名|地域|上限額円|理由|ID|','|---:|:---:|---|---|---|---|---:|---|---|']
for r in rows:
    md.append(f"|{r['No']}|{r['最終一次判定']}|{esc(r['現在状況'])}|{esc(r['締切'])}|{esc(r['補助金_公募名'])}|{esc(r['対象地域'])}|{esc(r['上限額円'])}|{esc(r['精査理由'])}|{esc(r['JグランツID'])}|")
OUTMD.write_text('\n'.join(md)+'\n',encoding='utf-8')
counts={k:sum(1 for r in rows if r['最終一次判定']==k) for k in ['○','△','×']}
status_counts={}
for r in rows: status_counts[r['現在状況']]=status_counts.get(r['現在状況'],0)+1
urgent=[{k:r[k] for k in fields if k in r} for r in rows if r['最終一次判定']!='×' and r['締切'] <= '2026-09-10 23:59']
SUM.write_text(json.dumps({'count':len(rows),'counts':counts,'status_counts':status_counts,'urgent_through_2026_09_10':urgent},ensure_ascii=False,indent=2),encoding='utf-8')
print({'count':len(rows),'counts':counts,'status_counts':status_counts})
