# Sentryエラー監視

このリポジトリはLINE Bot用のSentryプロジェクトに送信します。別アプリの `financial-statement` 用DSNは使いません。DSNや管理用トークンはコミットしません。

## 環境とIssueの分離

- `SENTRY_DSN`: LINE BotプロジェクトのDSN。未設定なら監視を無効化します。既存設定との移行用に `SENTRY_DNS` も読みます。両方あれば `SENTRY_DSN` が優先です。
- `SENTRY_ENVIRONMENT`: 本番は `production`、検証は `staging`。Render上で未指定なら、このリポジトリでは `production`。ローカルは `development`。
- `release`: `SENTRY_RELEASE` があればその値、なければ `line-bot-features@<RENDER_GIT_COMMIT>`。`RENDER_GIT_COMMIT` がない環境では末尾が `local` になります。
- `repository` タグと、既定のグルーピングにリポジトリ名・環境を加えたfingerprint（[Sentryのグルーピング](https://docs.sentry.io/platforms/python/usage/sdk-fingerprinting/)）で、同じ例外でも本番と検証のIssueを分けます。一方のResolveは他方に影響しません。

`SENTRY_DSN` と `SENTRY_ENVIRONMENT` は、RenderのEnvironmentで設定してください。`RENDER_GIT_COMMIT` はRenderが設定します（[Renderの既定の環境変数](https://render.com/docs/environment-variables)）。`SENTRY_RELEASE` を設定するとコミットが変わってもreleaseが変わらないため、通常は設定しません。`SENTRY_AUTH_TOKEN` はIssueの調査・Resolveに使うローカル管理用で、アプリには不要です。

## 送るものと送らないもの

| 区分 | 送る | 送らない |
| --- | --- | --- |
| エラー | Flaskの未処理例外（LINEへの返信の失敗を含む。[SentryのFlask連携](https://docs.sentry.io/platforms/python/integrations/flask/)で収集）、起動時の設定・importの失敗、メッセージ処理で捕まえてエラー返信に変えた例外、Places・Vision・翻訳APIのHTTPの失敗・HTTP 200の中のAPIエラー・不正な応答・設定不足 | 検索結果が0件、画像に文字がない、署名が不正、未対応のイベント |
| エラーの内容 | 例外の種類・ファイル名・関数名・行番号、固定の分類（起動・メッセージ処理の別、API名、失敗の種類、HTTPステータス）、environment・release・`repository` タグ | 例外のメッセージ（`[Filtered]` に置き換える）、リクエスト本文、画像、位置情報、LINEのユーザーID、認証情報、URL・クエリ、ローカル変数、任意のextra・context、HTTPやDBのbreadcrumb |
| エラー以外 | なし | トレース、プロファイル、ログ、自動のセッション統計 |

エラーは全件を送ります（[SDKの設定項目](https://docs.sentry.io/platforms/python/configuration/options/)）。原因の調査には、スタックとAPI名・失敗の種類・HTTPステータスを使います。

Places・Vision・翻訳APIの呼び出しには、接続3.05秒・読み取り10秒のタイムアウトを指定しています。タイムアウトと不正なJSONは、メッセージ処理の例外として送ります。LINE Messaging APIの呼び出しのタイムアウトは、line-bot-sdkの既定値（5秒）です。メッセージ処理で例外が起きたときの返信は固定のメッセージにして、翻訳APIやDBを再び呼ぶことによる二次障害を避けます。

## 実行環境と依存関係

Renderは `.python-version` に書いたバージョンのPythonを使います（[RenderのPythonバージョン設定](https://render.com/docs/python-version)）。`runtime.txt` だけでは古いサービスの既定値3.7.10が使われたため、`.python-version` で指定しています。Renderに `PYTHON_VERSION` が設定されていればそちらが優先なので、`PYTHON_VERSION` を `.python-version` と同じ値にするか削除してください。

`requirements.in` が直接依存、`requirements.txt` が推移依存も含む固定バージョンです。line-bot-sdkは3系ですが、コードは3.0で非推奨になった旧API（`linebot` の `LineBotApi`・`WebhookHandler`・`linebot.models`）を使っています。

依存更新時は、新しい仮想環境で `requirements.in` をインストールしてから `.venv/bin/python -m pip freeze > requirements.txt` で再生成します。その後、`requirements.txt` から新しい仮想環境を作り、[CI](../.github/workflows/test.yml)と同じく `pip check`・`py_compile`・テストを実行します。起動確認のテストは、生成した一時鍵とローカルエミュレータ指定で実ライブラリを初期化します。

## マージ後の確認順序

1. 検証サービス（[line-bot-features-test](https://github.com/shin4488/line-bot-features-test) をデプロイするRenderのサービス）に `SENTRY_DSN` と `SENTRY_ENVIRONMENT=staging` を設定し、line-bot-features-testで同じ変更をしたPRを先にマージ。Renderで最新コミット・Pythonの版・ビルド・Liveを確認。
2. 検証サービスの同じ環境で `python -m scripts.sentry_smoke` を明示実行。LINE送信やDB更新はせず、合成エラー `MonitoringSmokeTest` を1件送ります。出力されたevent IDだけでは受信成功ではありません。Sentry側で受信とenvironment/release/repository、個人情報がないことを確認してください。
3. 送信先を確認した検証用LINEアカウントでテキスト返信・店舗検索・OCR・設定保存を確認。ローカルのテストだけでは実APIや実データの互換性を検証したことにはなりません。
4. 本番サービスに `SENTRY_DSN` と `SENTRY_ENVIRONMENT=production` を設定し、このリポジトリのPRをマージして同様に確認。本番と検証が別Issueになることも確認。
5. SentryのIssue Alertで新規エラー・再発を通知するルールと通知先を確認。定期的にAIで全ログを読む運用は不要です。

Issueは修正コミットのデプロイと該当動作の再確認後にResolveします。「しばらくイベントがない」だけではResolveしません。環境とreleaseを必ず確認します。Sentryの設定が不正でもアプリは起動を続け、固定の警告をログに出すだけなので、DSNを設定した後はSentryで受信を確かめてください。

## ローカルでの追加検証

`unittest` では、外部サービスをフェイクに置き換えて、次のことを確かめます。

| 対象 | 確かめる内容 |
| --- | --- |
| 返信 | テキスト・位置情報・画像・動画・音声・スタンプ・設定のボタンへの返信とメニュー、返信文の翻訳 |
| 設定 | 言語と検索範囲のすべての選択肢の保存、保存済みのほかの設定が残ること、保存した検索範囲での店舗検索 |
| 障害 | API・Firestoreの失敗、タイムアウト、不正な応答、設定不足、壊れたWebhook、LINEへの返信の失敗、1回のWebhookに複数のイベントがある場合 |
| 文字数 | 空の文字・長い文字と、LINEの文字数の上限 |
| Sentry | 送るデータから個人情報を除くこと、例外の連鎖や並行処理での分類、起動時の失敗 |

`tests/test_gunicorn.py` は実際のGunicornとSentry SDKのHTTP送信を使います。送信先はlocalhostの模擬受信サーバーだけです。実際の送信バイト列から個人情報が消えていること、正常時にセッション統計などを送らないこと、Sentryが503でもWebhook処理が続くこと、ワーカータイムアウトの通知と再起動を検証します。ローカルでポートを開ける実行環境が必要です。テスト専用ルートは `tests/gunicorn_fixture.py` のみにあり、`main:app` には追加されません。

テストでは、過去に再現した次の不具合が再発しないことも確認します。

- 店舗の任意項目（営業時間・評価・icon）の欠損で検索全体が失敗する。
- 長い翻訳結果で店舗カードの本文上限を超える。
- OCRの空文字や翻訳APIの空文字から、空のLINE返信を作ってしまう。
- Sentry SDKがエラー以外のセッション統計を自動送信する。
- macOSでGunicornのワーカー再起動がループする。使わない制御サーバーを `gunicorn.conf.py` で無効化して防いでいます。
- 保存された検索範囲が無視される。設定メニューの定義からメートルに変換して適用します。
- LINEのチャネルシークレット・アクセストークンが空でも初期チェックを通る。空・空白は起動時に拒否します。

ローカルのテストでは、次のことは確かめていません。

- 実際のAPIの認証・利用上限・データと、LINEの画面での表示
- Sentry本体での受信・グルーピング・通知
- Renderでのデプロイ、実際の負荷、OSによる強制終了やメモリ不足

LINEへの返信が失敗すると、HTTP 500を返し、同じWebhookの残りのイベントは処理しません。この動作はテストで確かめています。残りのイベントの再処理や、LINEの再配信に対する重複の防止は実装していません。

APIの境界条件は [LINEの文字数仕様](https://developers.line.biz/en/docs/messaging-api/text-character-count/) と [Placesの応答定義](https://developers.google.com/maps/documentation/places/web-service/legacy/search-nearby) を参照しています。
