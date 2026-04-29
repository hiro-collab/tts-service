# tts_service

`tts_service` は、ローカル実行向けの Python 製 TTS モジュールです。
`sword-voice-agent` が出力する Dify 応答を読み上げる用途を最初の連携先にしていますが、core は汎用にしてあり、別の入力元や TTS エンジンにも差し替えられる構成です。

## 設計

小さな Ports and Adapters 構成です。

- `tts_service/core`: リクエスト型、重複防止、合成と再生のパイプライン
- `tts_service/ports`: source、synthesizer、player、status sink の抽象
- `tts_service/adapters`: ファイル監視、HTTP 入力、Windows SAPI、VOICEVOX 境界、ローカル再生、JSON 状態出力
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

合成も再生もせず、状態遷移だけを確認する場合:

```powershell
python -m tts_service.apps.speak_text --text "こんにちは" --engine noop --player noop
```

Windows SAPI の音声、速度、音量を指定する場合:

```powershell
python -m tts_service.apps.speak_text --text "こんにちは" --voice-name "Microsoft Haruka Desktop" --rate 0 --volume 100
```

`--volume` は Windows SAPI に渡す合成側の音量です。OS のシステム音量とは別に、tts_service 側だけのアプリ音量を掛ける場合は `--app-volume` を使います。値は `0.0` から `1.0` です。

```powershell
python -m tts_service.apps.speak_text --text "こんにちは" --app-volume 0.5
```

watcher 起動中に利用システム側から音量を変えたい場合は、`app_volume.json` を更新します。既定の場所は `--output-status-dir` 配下です。

```powershell
python -m tts_service.apps.set_volume 0.35 --output-status-dir .cache\tts_service
```

`set_volume` は既定で短い確認音を鳴らします。実際の TTS と同じ app volume ゲインを通すので、変更後のおおよその音量を確認できます。自動テストや無音で更新したい場合は `--no-preview` を付けます。

```powershell
python -m tts_service.apps.set_volume 0.35 --output-status-dir .cache\tts_service --no-preview
```

直接書く場合は次の形式です。

```json
{
  "app_volume": 0.35
}
```

watcher 起動中に `app_volume.json` が変更された場合は、読み上げリクエストがなくても `latest_tts_state.json` を `idle` 状態で更新します。

日本語が不自然に読まれる場合は、まず日本語音声を明示してください。既定音声が英語の場合、`こんにちは` のような日本語テキストは英語音声の発音規則で読まれてしまいます。

Windows SAPI が「音声がインストールされていない」系のエラーを返す場合は、現在のユーザーで利用可能な Windows 音声をインストールしてから再実行してください。MVP では、空の WAV ファイルを成功扱いせずエラーにします。

利用可能な Windows SAPI 音声を確認する場合:

```powershell
python -m tts_service.apps.list_voices
python -m tts_service.apps.list_voices --json
```

watcher 側からも確認できます。

```powershell
python -m tts_service.apps.watch_sword_response --list-voices
python -m tts_service.apps.watch_sword_response --list-voices --json
```

## sword-voice-agent の応答を監視する

```powershell
python -m tts_service.apps.watch_sword_response `
  --source status-file `
  --status-dir <sword_voice_agent_root>\.cache\sword_voice_agent `
  --output-status-dir .cache\tts_service
```

watcher は、明示指定された `--status-dir` の `latest_dify_response.json` だけを読みます。広範囲のディレクトリを勝手にスキャンしません。
起動時には、監視対象、出力 status dir、TTS engine、player、voice name、app volume、poll interval を標準出力に表示します。

起動前に設定とパスだけ確認する場合:

```powershell
python -m tts_service.apps.watch_sword_response `
  --status-dir <sword_voice_agent_root>\.cache\sword_voice_agent `
  --output-status-dir .cache\tts_service `
  --dry-run
```

統合側から JSON でヘルスチェックする場合:

```powershell
python -m tts_service.apps.watch_sword_response `
  --status-dir <sword_voice_agent_root>\.cache\sword_voice_agent `
  --output-status-dir .cache\tts_service `
  --health-json
```

音声エンジンに依存せず、ファイル監視、重複防止、状態出力だけ確認する場合:

```powershell
python -m tts_service.apps.watch_sword_response `
  --status-dir <sword_voice_agent_root>\.cache\sword_voice_agent `
  --output-status-dir .cache\tts_service `
  --app-volume 0.7 `
  --engine noop `
  --player noop
```

想定する payload 例:

```json
{
  "message_id": "msg-123",
  "conversation_id": "conv-456",
  "answer": "こんにちは"
}
```

`{"payload": {"answer": "..."}}` や `{"response": {"answer": "..."}}` のようなネスト形式も受け付けます。

`sword-voice-agent` の handoff payload では、読み上げ本文は `response.text`、`message_id` は `response.message_id`、`conversation_id` は `response.conversation_id` から取得します。`turn_id` は top-level または `request.context.turn_id` から取得し、status に出します。

```json
{
  "type": "dify_handoff_result",
  "request": {
    "text": "今日はいい天気ですね",
    "context": {
      "turn_id": "turn-1"
    }
  },
  "response": {
    "type": "agent_response",
    "text": "はい、今日はいい天気ですね。",
    "conversation_id": "conv-1",
    "message_id": "msg-1"
  },
  "skipped": false,
  "turn_id": "turn-1"
}
```

`skipped: true` の payload は読み上げ対象外です。

## HTTP 入力 source

`latest_dify_response.json` の polling を避けたい場合は、HTTP source を起動します。

```powershell
python -m tts_service.apps.watch_sword_response `
  --source http `
  --http-host 127.0.0.1 `
  --http-port 8765 `
  --output-status-dir .cache\tts_service `
  --runtime-status-file .cache\tts_service\runtime_status.json
```

HTTP source は指定 port が使用中の場合、自動で別 port へ退避せずにエラー終了します。統合側が期待する port と実際の listen port がずれないようにするためです。

全文を渡す場合:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8765/api/tts `
  -ContentType 'application/json' `
  -Body '{"text":"こんにちは","message_id":"msg-1","turn_id":"turn-1"}'
```

LLM streaming の delta を先行 TTS したい場合は、句点、改行、または `--http-chunk-max-chars` に達した時点で request に分割されます。最後の残りは `final: true` で flush します。

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8765/api/tts/chunk `
  -ContentType 'application/json' `
  -Body '{"delta":"こんにちは。続き","message_id":"msg-1","turn_id":"turn-1"}'

Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8765/api/tts/chunk `
  -ContentType 'application/json' `
  -Body '{"delta":"です","message_id":"msg-1","turn_id":"turn-1","final":true}'
```

HTTP source はローカル実行前提です。`--http-host 0.0.0.0` など loopback 以外に bind する場合は `--shutdown-token` が必須です。`POST /shutdown` では `Authorization: Bearer ...` または `X-Sword-Agent-Token` で token を渡します。

ヘルスチェック:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8765/health
```

`/health` は `ok`、`module`、`pid`、`uptime_s`、`host`、`port` に加えて、`volume_endpoint`、`queued`、`phase` を返します。

協調停止:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/shutdown
```

`POST /shutdown` は即時 kill ではなく、HTTP server loop を止め、watcher 側で再生停止、source close、status 更新を行って終了します。停止後は `latest_tts_state.json` に `service: "stopped"` を書きます。

HTTP source 起動中は app volume もHTTPで取得・変更できます。

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8765/api/volume

Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8765/api/volume `
  -ContentType 'application/json' `
  -Body '{"app_volume":0.35}'
```

`POST /api/volume` は `app_volume.json` を更新します。ファイルを直接書き換えた場合と同じく、watcher は次のループで status に反映します。

## Runtime Status File

長時間起動する watcher は、`--runtime-status-file` を指定すると PID と停止方法を書き出します。

```powershell
python -m tts_service.apps.watch_sword_response `
  --source http `
  --http-port 8765 `
  --output-status-dir .cache\tts_service `
  --runtime-status-file .cache\tts_service\runtime_status.json
```

例:

```json
{
  "module": "tts_service",
  "state": "running",
  "pid": 12345,
  "parent_pid": 12000,
  "started_at": "2026-04-29T00:00:00+00:00",
  "stopped_at": null,
  "host": "127.0.0.1",
  "port": 8765,
  "health_url": "http://127.0.0.1:8765/health",
  "shutdown_url": "http://127.0.0.1:8765/shutdown",
  "shutdown_command": null,
  "command_line": ["python", "-m", "tts_service.apps.watch_sword_response", "..."]
}
```

正常終了、Ctrl+C、`POST /shutdown` のいずれでも runtime status file は削除せず、`state: "stopped"` と `stopped_at` に更新します。`--shutdown-token` の値は `command_line` 上で `<redacted>` に置き換えます。

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
watcher 起動中は `service: "running"`、Ctrl+C 終了時は `service: "stopped"` を書きます。watcher 由来の状態には `watching`、`engine`、`player`、`voice_name`、`poll_interval`、`app_volume`、`app_volume_file`、`volume`、`rate` も含まれます。

`events.jsonl` には状態遷移に加えて、低遅延化の比較用に次の計測イベントを書きます。各イベントは `wall_time` と `monotonic_time` / `perf_counter`、`turn_id`、`request_id`、`message_id`、`conversation_id`、`source`、本文の `text_hash`、`app_volume`、`app_volume_file`、`volume`、`rate` を持ち、本文そのものは書きません。

- `tts_request`
- `tts_first_audio`
- `play_start`
- `play_done`
- `tts_error`

例:

```json
{
  "phase": "speaking",
  "service": "running",
  "request_id": "...",
  "message_id": "msg-1",
  "conversation_id": "conv-1",
  "turn_id": "turn-1",
  "source": "sword_status_store",
  "watching": ".cache/sword_voice_agent/latest_dify_response.json",
  "engine": "windows-sapi",
  "player": "speaker",
  "app_volume": 0.7,
  "app_volume_file": ".cache/tts_service/app_volume.json",
  "volume": 100,
  "rate": 0
}
```

## 再生キュー方針

MVP は単一の同期 worker です。読み上げ中の音声はキャンセルしません。音声再生中は watcher がブロックされ、再生後に現在の `latest_dify_response.json` を読みます。

`latest_dify_response.json` 方式では、長い読み上げ中に複数回更新された場合、途中の応答は最新ファイルの内容に畳まれる可能性があります。

HTTP source は受信スレッドで request を queue に積むため、file polling を使わずに TTS worker へ渡せます。`/api/tts/chunk` を使うと、全文完了を待たずに文単位 chunk を request 化できます。

現時点の worker は単一同期処理です。再生中に次の音声を並列合成する overlap worker は次段の実装対象です。

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
