# Jグランツ監視ブリッジ

ChatGPT Plus から GitHub を中継して Jグランツ公開APIを利用するためのリポジトリです。

## 目的

- Jグランツの募集中案件を定期取得
- 複数キーワード検索を統合し、補助金IDで重複排除
- V2詳細APIから案件詳細を取得（添付ファイル本体のBase64は保存しない）
- 前回との差分から新規案件を抽出
- ChatGPT から GitHub コネクタ経由で `data/latest.json` / `data/latest.csv` / `data/details/` を参照
- `request.json` を変更すると任意検索またはID指定詳細取得を実行

出典: Jグランツ（jGrants）公開API / デジタル庁

公式API: https://api.jgrants-portal.go.jp/exp/v1/public/subsidies
公式ドキュメント: https://developers.digital.go.jp/documents/jgrants/api/

## 主なファイル

- `scripts/jgrants_sync.py`: API取得・差分処理
- `config/search.json`: 定期監視条件
- `request.json`: このチャットからの個別検索要求
- `data/latest.json`: 募集中案件の統合一覧
- `data/latest.csv`: Excel等で確認しやすいUTF-8 BOM付きCSV
- `data/new.json`: 前回取得時点から新しく現れた案件
- `data/details/`: V2詳細API結果（Base64添付データ除外）
- `data/query_result.json`: `request.json` の実行結果

## 注意

API一覧だけで申請可否を確定せず、公募要領等を含めて最終確認してください。
