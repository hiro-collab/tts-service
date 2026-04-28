# tts_service

`tts_service` は、ローカル実行向けの Python 製 TTS モジュールです。
`sword-voice-agent` が出力する Dify 応答を読み上げる用途を最初の連携先にしていますが、core は汎用にしてあり、別の入力元や TTS エンジンにも差し替えられる構成です。

## 設計

小さな Ports and Adapters 構成です。

- `tts_service/core`: リクエスト型、重複防止、合成と再生のパイプライン
- `tts_service/ports`: source、synthesizer、player、status sink の抽象
- `tts_service/adapters`: ファイル監視、Windows SAPI、VOICEVOX 境界、ローカル再生、JSON 状態出力
- `tts_service/apps`: CLI エントリポイント

MVP の処理は同期パイプラインです。

1. `TtsRequest` を検出する
2. すでに読み上げ済みならスキップする
3. テキストを WAV に合成する
4. スピーカーで再生、または音声ファイルとして出力する
5. 状態とイベントを書き出す

core は Windows SAPI、VOICEVOX、OpenAI、Dify、ローカルファイル監視に依存しません。これらは adapter として差し替えます。

## TTS エンジン

MVP の標準エンジンは、PowerShell 経由で Windows `System.Speech` を使う `windows-sapi` です。

- API キー不要
- Python パッケージの追加依存なし
- Windows にインストール済みの音声を利用
- Windows 専用

`pyttsx3` は Python 依存を増やす一方で、最終的には各 OS の音声エンジンに依存するため MVP では採用していません。OpenAI TTS と VOICEVOX は adapter 境界を用意してあり、core を変えずに追加できます。

## インストール

リポジトリルートで実行します。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

現時点の MVP は、Windows 上の Python と PowerShell 以外に必須の実行時依存はありません。

## テキストを読み上げる

```powershell
python -m tts_service.apps.speak_text --text "こんにちは"
```

標準入力から読む場合:

```powershell
"こんにちは" | python -m tts_service.apps.speak_text
```

スピーカー再生ではなく、生成した音声ファイルを保存する場合:

```powershell
python -m tts_service.apps.speak_text --text "こんにちは" --player file --output-audio-dir .cache/tts_service/out
```

Windows SAPI の音声、速度、音量を指定する場合:

```powershell
python -m tts_service.apps.speak_text --text "こんにちは" --voice-name "Microsoft Haruka Desktop" --rate 0 --volume 100
```

日本語が不自然に読まれる場合は、まず日本語音声を明示してください。既定音声が英語の場合、`こんにちは` のような日本語テキストは英語音声の発音規則で読まれてしまいます。

Windows SAPI が「音声がインストールされていない」系のエラーを返す場合は、現在のユーザーで利用可能な Windows 音声をインストールしてから再実行してください。MVP では、空の WAV ファイルを成功扱いせずエラーにします。

## sword-voice-agent の応答を監視する

```powershell
python -m tts_service.apps.watch_sword_response `
  --status-dir <sword_voice_agent_root>\.cache\sword_voice_agent `
  --output-status-dir .cache\tts_service
```

watcher は、明示指定された `--status-dir` の `latest_dify_response.json` だけを読みます。広範囲のディレクトリを勝手にスキャンしません。

想定する payload 例:

```json
{
  "message_id": "msg-123",
  "conversation_id": "conv-456",
  "answer": "こんにちは"
}
```

`{"payload": {"answer": "..."}}` や `{"response": {"answer": "..."}}` のようなネスト形式も受け付けます。

## 重複防止

watcher は、処理済みリクエストの識別子を次のファイルに保存します。

```text
.cache/tts_service/seen_requests.json
```

読み上げ済み判定のキーは次の順で決めます。

1. `message_id`
2. `conversation_id + answer hash`
3. answer hash

Dify 応答本文そのものは、重複防止ファイルには書きません。

## 状態出力

状態 adapter は次のファイルを書きます。

```text
.cache/tts_service/latest_tts_state.json
.cache/tts_service/events.jsonl
```

状態は次のいずれかです。

- `idle`: プロセスは起動中で、読み上げ中のリクエストはない
- `speaking`: 合成または再生中
- `completed`: 直近のリクエストが完了
- `skipped`: 直近のリクエストは読み上げ済みのためスキップ
- `error`: 合成または再生に失敗

状態 JSON には ID、source、本文ハッシュ、エラー内容を書きます。Dify 応答本文や API キーは意図的に含めません。

## 再生キュー方針

MVP は単一の同期 worker です。読み上げ中の音声はキャンセルしません。音声再生中は watcher がブロックされ、再生後に現在の `latest_dify_response.json` を読みます。

`latest_dify_response.json` 方式では、長い読み上げ中に複数回更新された場合、途中の応答は最新ファイルの内容に畳まれる可能性があります。

メッセージ単位で厳密にキューイングしたい場合は、`events.jsonl`、HTTP、WebSocket、UDP、MQTT などの source adapter を追加してください。core pipeline と dedupe store はそのまま再利用できます。

## セキュリティと運用上の注意

- 認証や通信路の保護を追加するまでは、ローカル実行前提で扱ってください。
- `.env`、API キー、アクセストークン、実際の Dify payload fixture をコミットしないでください。
- `.cache/tts_service/events.jsonl` と生成音声は、Dify の活動内容を推測できるローカル機密データとして扱ってください。
- 状態ファイルと重複防止ファイルには応答本文を書かない設計ですが、生成 WAV には読み上げ内容が含まれる可能性があります。
- watcher の対象パスは必ず `--status-dir` で明示してください。

## テスト

```powershell
python -m unittest discover -s tests
```

テストは実際の音声再生を行わず、Windows SAPI も必須にしていません。
