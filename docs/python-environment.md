# Python環境とエディタの設定

依存パッケージはリポジトリ直下の `.venv` で管理する。環境を新しく作る場合は、`.python-version` のPythonを用意して以下を実行する。

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

`pyrefly.toml` はリポジトリ全体のPythonファイルに適用され、`.venv/bin/python` から依存パッケージを探す。診断は未設定時と同じ `basic` を使用する。`missing-import` は型チェッカーによるimport解決の診断であり、フォーマットの問題ではない。

VS Code / Cursorでこのリポジトリをフォルダとして開くと、`.vscode/settings.json` が既定のPython環境を指定する。既に別のPythonを選択している場合は、コマンドパレットの `Python: Select Interpreter` でこのリポジトリの `.venv/bin/python` を選ぶ。診断が更新されなければ `Developer: Reload Window` を実行する。親フォルダから複数のリポジトリを開いている場合は、このリポジトリをワークスペースのフォルダとして追加するとフォルダ単位の設定が適用される。

Pyrefly CLIを利用できる環境では、リポジトリ直下で `pyrefly check` を実行して全体を確認できる。

参考: [Pyrefly設定](https://pyrefly.org/en/docs/configuration/)、[エディタ設定](https://pyrefly.org/en/docs/IDE/)
