# tts-service

ローカル実行向けの Python TTS モジュールです。`sword-voice-agent` では Dify 応答を受け取り、Windows SAPI などで読み上げ、読み上げ状態を status として出します。

## Responsibility

- TTS request の重複防止。
- テキスト合成と再生。
- HTTP source と status-file source。
- `latest_tts_state.json` と runtime status file の出力。
- アプリ音量の読み書き。

TTS service は Dify 応答を生成しません。avatar 表示も担当しません。

## 初期セットアップ

```powershell
cd <workspace>\tts-service
uv sync
if (-not (Test-Path .env)) {
  Copy-Item .env.example .env
}
```

Windows SAPI を使う標準構成では追加 API key は不要です。`.env` は process manager で固定値を読みたい
場合のローカル設定ファイルです。実 token や将来 adapter 用の API key はコミットしません。

## 単発確認

```powershell
$env:PYTHONPATH = "src"
uv run python -m tts_service.apps.speak "こんにちは"
```

音声名、速度、音量を指定する場合:

```powershell
uv run python -m tts_service.apps.speak "こんにちは" --voice-name "Microsoft Haruka Desktop" --rate 0 --volume 100
```

## 通常起動: HTTP Source

`sword-voice-agent` の標準統合では HTTP source を使います。

```powershell
$env:PYTHONPATH = "src"
uv run python -m tts_service.apps.watch_sword_response `
  --source http `
  --http-host 127.0.0.1 `
  --http-port 8765 `
  --output-status-dir .cache\tts_service `
  --runtime-status-file .cache\tts_service\runtime_status.json
```

Endpoints:

| Endpoint | Purpose |
|---|---|
| `POST /api/tts` | まとまった本文を読み上げる |
| `POST /api/tts/chunk` | streaming chunk を文単位で読み上げる |
| `GET /health` | 起動確認 |
| `POST /shutdown` | watcher を停止 |
| `GET /api/volume` | アプリ音量取得 |
| `POST /api/volume` | アプリ音量更新 |

Loopback 外に bind する場合は `--shutdown-token` が必須です。

## Status File Source

`status-file` source は互換や切り分け用です。通常の統合では HTTP source を優先します。

```powershell
uv run python -m tts_service.apps.watch_sword_response `
  --source status-file `
  --status-dir <workspace>\sword-voice-agent\.cache\sword_voice_agent `
  --output-status-dir .cache\tts_service
```

## Status Output

`latest_tts_state.json` は output status dir に書かれます。

Main states:

- `idle`
- `speaking`
- `completed`
- `skipped`
- `error`

Status には本文そのものを書きません。本文ハッシュ、ID、source、エラー概要、engine、player、音量などを出します。生成 WAV には読み上げ内容が含まれる可能性があります。

## Runtime Status

`--runtime-status-file` を指定すると、PID、health URL、shutdown URL、command line、state を書きます。正常終了、Ctrl+C、`POST /shutdown` のいずれでも file は削除せず `state: "stopped"` にします。

## Security

- `.env`、API key、token、Dify payload fixture をコミットしない。
- `.cache/tts_service/events.jsonl` と生成音声はローカル機密データとして扱う。
- 対象 path は `--status-dir` で明示する。
- HTTP source を公開する場合は token とネットワーク境界を明示する。

## Tests

```powershell
$env:PYTHONPATH = "src"
uv run python -m unittest discover -s tests
```

テストは実際の音声再生を行わず、Windows SAPI も必須にしていません。
