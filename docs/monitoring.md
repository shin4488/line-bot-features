# Sentryエラー監視

このリポジトリはLINE Bot用のSentryプロジェクトに送信します。別アプリの
`financial-statement` 用DSNは使いません。DSNや管理用トークンはコミットしません。

## 環境とIssueの分離

- `SENTRY_DSN`: LINE BotプロジェクトのDSN。未設定なら監視を無効化します。
  既存設定との移行用に `SENTRY_DNS` も読みます。両方あれば `SENTRY_DSN` が優先です。
- `SENTRY_ENVIRONMENT`: 本番は `production`、検証は `staging`。
  Render上で未指定なら、このリポジトリでは `production`。ローカルは `development`。
- `release`: 通常 `line-bot-features@<RENDER_GIT_COMMIT>`。Render以外では
  `SENTRY_RELEASE` で明示できます。指定がなければ末尾は `local` です。
- `repository` タグと、既定のグルーピングにリポジトリ名・環境を加えたfingerprintで、
  同じ例外でも本番と検証のIssueを分けます。一方のResolveは他方に影響しません。

`.env` は自動では読みません。RenderのEnvironmentで設定してください。
`SENTRY_AUTH_TOKEN` はIssueの調査・Resolveに使うローカル管理用で、アプリには不要です。

## 収集するもの

- Flaskの未処理例外（LINE返信失敗を含む）、起動時の設定・import失敗。
- メッセージ処理で捕まえてエラー返信に変換した例外。
- Places・Vision・翻訳APIのHTTP失敗、HTTP 200内のAPIエラー、不正な応答、設定不足。
- HTTPの接続・読み取りにはそれぞれ3.05秒・10秒のタイムアウトを指定。
  タイムアウトと不正なJSONはメッセージ処理の例外として検知します。

検索0件、OCR文字なし、署名不正、未対応イベントは監視エラーにしません。
障害時の返信は固定メッセージにして、翻訳やDBの再呼び出しによる二次障害を避けます。

例外の種類・ファイル名・関数・行番号と固定分類だけを送ります。例外本文は
`[Filtered]` とし、リクエスト本文・画像・位置情報・LINEユーザーID・認証情報・
URL/クエリ・ローカル変数・任意のextra/contextを除去します。HTTPやDBのbreadcrumbも
送信しません。原因調査にはスタックとAPI名・失敗種別・HTTPステータスを使います。
トレース・プロファイル・ログ・自動セッション統計の収集は無効、エラーは全件が送信対象です。

## 実行環境と依存関係

Renderは `.python-version` のPython 3.12.14を使用します。
従来の `runtime.txt` だけでは古いサービスの既定値3.7.10が使われるため、明示しました。
Renderに `PYTHON_VERSION` が設定されていればそちらが優先なので、3.12.14に合わせるか
削除して `.python-version` を使ってください。

`requirements.in` が直接依存、`requirements.txt` が推移依存も含む固定バージョンです。
Flask、Firebase Admin、Requests、Gunicornを更新し、旧Firebase/Googleライブラリや
Sentry/urllib3間の依存関係の不整合を解消しています。LINE SDKは既存APIを維持します。

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m py_compile gunicorn.conf.py const/env.py main.py monitoring.py line/service.py store/service.py ocr/service.py util/util.py
```

依存更新時は、新しい仮想環境で `requirements.in` をインストールしてから
`.venv/bin/python -m pip freeze > requirements.txt` で再生成し、上記の確認を実行します。
テストは合成データ・模擬API/DB・メモリ内Sentry送信先を使い、実サービスに送信しません。
起動確認は生成した一時鍵とローカルエミュレータ指定で実ライブラリを初期化します。

## マージ後の確認順序

1. 検証サービスに `SENTRY_DSN` と `SENTRY_ENVIRONMENT=staging` を設定し、
   検証用PRを先にマージ。Renderで最新コミット・Pythonの版・ビルド・Liveを確認。
2. 検証サービスの同じ環境で `python -m scripts.sentry_smoke` を明示実行。
   LINE送信やDB更新はせず、合成エラー `MonitoringSmokeTest` を1件送ります。
   出力されたevent IDだけでは受信成功ではありません。Sentry側で受信と
   environment/release/repository、個人情報がないことを確認してください。
3. 送信先を確認した検証用LINEアカウントでテキスト返信・店舗検索・OCR・設定保存を確認。
   ローカルのテストだけでは実APIや実データの互換性を検証したことにはなりません。
4. 本番サービスに `SENTRY_DSN` と `SENTRY_ENVIRONMENT=production` を設定し、
   本番PRをマージして同様に確認。本番と検証が別Issueになることも確認。
5. SentryのIssue Alertで新規エラー・再発を通知するルールと通知先を確認。
   定期的にAIで全ログを読む運用は不要です。

Issueは修正コミットのデプロイと該当動作の再確認後にResolveします。
「しばらくイベントがない」だけではResolveしません。環境とreleaseを必ず確認します。
監視設定不正はアプリ起動を止めず固定の警告を出すため、DSN設定後の受信確認が必要です。

参考: [Sentry Flask](https://docs.sentry.io/platforms/python/integrations/flask/)、
[SDK設定](https://docs.sentry.io/platforms/python/configuration/options/)、
[グルーピング](https://docs.sentry.io/platforms/python/usage/sdk-fingerprinting/)、
[Render Python設定](https://render.com/docs/python-version)。

## ローカルでの追加検証

`unittest`は55件です。通常返信、画像・音声・動画・スタンプ、設定メニュー・保存、
検索範囲全5段階、API/DBの障害、不正な応答、空・長文、複数イベント、設定不足、
例外チェーン・並行処理時のSentryデータを確認します。

`tests/test_gunicorn.py` は実際のGunicornとSentry SDKのHTTP送信を使います。
送信先はlocalhostの模擬受信サーバーだけです。実際の送信バイト列から個人情報が
消えていること、正常時にセッション統計などを送らないこと、Sentryが503でも
Webhook処理が続くこと、ワーカータイムアウトの通知と再起動を検証します。
ローカルでポートを開ける実行環境が必要です。テスト専用ルートは
`tests/gunicorn_fixture.py` のみにあり、`main:app`には追加されません。

追加検証で次を再現し、修正しました。

- 店舗の任意項目（営業時間・評価・icon）の欠損で検索全体が失敗する。
- 長い翻訳結果で店舗カードの本文上限を超える。
- OCRの空文字や翻訳APIの空文字から、空のLINE返信を作ってしまう。
- Sentry SDKがエラー以外のセッション統計を自動送信する。
- このMacでGunicornのワーカー再起動がループする。不要な制御サーバーを
  `gunicorn.conf.py` で無効化すると解消したため、その設定を追加。
- 保存された検索範囲が無視される。設定メニューの定義からメートルに変換して適用。
- LINEのチャネルシークレット・アクセストークンが空でも初期チェックを通る。空・空白は起動時に拒否。

実APIの認証・利用上限・データ・LINE画面表示、Sentry本体の受信/グルーピング/通知、
Renderでのデプロイや実負荷は、このローカル試験では保証しません。
LINE返信が失敗するとHTTP 500でそのバッチの処理を中断する既存動作もテストで確認
しています。後続イベントの再処理や、LINE側の再配信に対する重複防止は未実装です。
OSによる強制終了・OOMもローカル試験の対象外です。

APIの境界条件は [LINEの文字数仕様](https://developers.line.biz/en/docs/messaging-api/text-character-count/)
と [Placesの応答定義](https://developers.google.com/maps/documentation/places/web-service/legacy/search-nearby)
を参照しています。
