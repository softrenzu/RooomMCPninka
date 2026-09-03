import csv, json, re
from pathlib import Path

DATA=Path(__file__).resolve().parents[1]/'data'
SRC=DATA/'eligibility_refined.csv'
OUT=DATA/'eligible_45_history.md'
OUTCSV=DATA/'eligible_45_history.csv'

# 過去ログで確認済みの状態。名称ゆれを正規表現で吸収。
HISTORY=[
 (r'ゼロエミッション推進に向けた事業転換支援事業.*製品開発', '差戻し・再申請対応中', '新規申請不要'),
 (r'ゼロエミ.*製品.*サービス.*販路拡大', '申請済・差戻し対応中', '新規申請不要'),
 (r'課題解決型.*販路拡大', '申請中/申請済履歴あり', '新規申請不要'),
 (r'観光関連事業者.*環境対策促進', '申請済・差戻し対応中', '新規申請不要'),
 (r'インバウンド対応力強化', '申請済・差戻し対応中（事業②〜④継続）', '新規申請不要'),
 (r'観光.*ICT|ICT利活用.*観光', '申請中・差戻し対応中', '新規申請不要'),
 (r'AI.*データ.*知財|データ知財', '申請書類作成済・準備中', '新規申請不要'),
 (r'TOKYO戦略的イノベーション', '事前エントリー済・本申請状況要確認', '重複申請前に状況確認'),
 (r'小規模事業者持続化補助金', '申請済・結果待ち', '新規申請不要'),
 (r'中小企業新事業進出|新事業進出補助金', '申請済履歴あり', '新規申請不要'),
 (r'賃貸住宅.*断熱.*再エネ', '申請準備中・省エネ診断/見積進行', '新規申請不要'),
 (r'観光関連事業者.*DX|デジタル化レベルアップ', '検討・準備中', '継続案件'),
]

rows=[]
with SRC.open(encoding='utf-8-sig', newline='') as f:
    for r in csv.DictReader(f):
        if r['最終一次判定']!='○':
            continue
        title=r['補助金_公募名']
        hist='過去ログ該当なし'
        action='新規申請候補'
        for pat,status,next_action in HISTORY:
            if re.search(pat,title,re.I):
                hist=status; action=next_action; break
        rows.append({
            'No':len(rows)+1,
            '元No':r['No'],
            '締切':r['締切'],
            '公募名':title,
            '地域':r['対象地域'],
            '上限額円':r['上限額円'],
            '過去ログ状況':hist,
            '今回の扱い':action,
            'JグランツID':r['JグランツID'],
        })

fields=['No','元No','締切','公募名','地域','上限額円','過去ログ状況','今回の扱い','JグランツID']
with OUTCSV.open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)

def esc(v): return str(v or '').replace('|','｜').replace('\n',' ')
md=['# Jグランツ ○45件 × 過去ログ照合','',f'件数: {len(rows)}','', '|No|締切|公募名|地域|上限額|過去ログ状況|今回の扱い|ID|','|---:|---|---|---|---:|---|---|---|']
for r in rows:
    md.append(f"|{r['No']}|{esc(r['締切'])}|{esc(r['公募名'])}|{esc(r['地域'])}|{esc(r['上限額円'])}|{esc(r['過去ログ状況'])}|{esc(r['今回の扱い'])}|{esc(r['JグランツID'])}|")
OUT.write_text('\n'.join(md)+'\n',encoding='utf-8')
print(json.dumps({'count':len(rows),'history_hits':sum(1 for r in rows if r['過去ログ状況']!='過去ログ該当なし')},ensure_ascii=False))
