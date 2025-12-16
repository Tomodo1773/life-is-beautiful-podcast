# Life is Beautiful Podcast Generator

「Life is Beautiful」メルマガからポッドキャストを自動生成するアプリケーションです。

![アプリ画面サンプル](images/demo.png)

## 機能

- メルマガのマークダウンファイルをアップロード
- メルマガの分割方法：
  - 「今週のざっくばらん」はh2ごとに分割
  - 「私の目に止まった記事」はリンク＋コメントのセットごとに分割
  - その他のセクションはそのまま
- Gemini 2.5 Pro AIでポッドキャスト台本を生成
- Gemini 2.5 Pro TTSで音声を生成
- 生成された音声ファイルを連結して1つのポッドキャストを作成

## 技術スタック

- バックエンド: FastAPI (Python)
- フロントエンド: HTML, JavaScript
- AI: Google Gemini 2.5 Pro, Gemini 2.5 Pro TTS
- 音声処理: pydub
- パッケージ管理: uv
- コード品質: ruff (linter & formatter)

## セットアップ

### 前提条件

- Python 3.12以上
- Gemini APIキー
- uv (パッケージマネージャー)

### インストール

1. リポジトリをクローン：

```bash
git clone https://github.com/Tomodo1773/life-is-beautiful-podcast.git
cd life-is-beautiful-podcast
```

1. 依存関係をインストール：

```bash
uv sync
```

1. pre-commitフックをインストール：

```bash
pre-commit install
```

1. 環境変数を設定：

.envファイルを作成し、以下を追加してください：

```env
GEMINI_API_KEY=your_gemini_api_key
```

必要に応じて、並行数/リトライも環境変数で調整できます（デフォルトは `SCRIPT_CONCURRENCY=20`, `TTS_CONCURRENCY=5`）：

```env
# 台本生成（Gemini）同時実行数
SCRIPT_CONCURRENCY=20

# TTS同時実行数
TTS_CONCURRENCY=5

# 429/5xx 等のリトライ回数と待ち時間上限（指数バックオフ）
GEMINI_MAX_RETRIES=8
GEMINI_RETRY_MAX_SECONDS=60
```

### 実行

```bash
uvicorn app.main:app --reload
```

アプリケーションは http://localhost:8000 で実行されます。

## 使い方

1. ブラウザで http://localhost:8000 にアクセス
1. メルマガのマークダウンファイルをアップロード（必ずmarkdown形式でアップロードしてください。Obsidian等で変換可能です）
1. 「ポッドキャストを生成」ボタンをクリック
1. 処理が完了したら、生成されたポッドキャストをダウンロード

## API エンドポイント

- `POST /api/generate-podcast`: マークダウンファイルからポッドキャストを生成
- `GET /api/podcast-status/{job_id}`: ポッドキャスト生成ジョブのステータスを取得
- `GET /api/download-podcast/{job_id}`: 生成されたポッドキャストをダウンロード

## メルマガ分割の流れ

1. マークダウンファイルを読み込み
1. 「今週のざっくばらん」はh2ごと、「私の目に止まった記事」はリンク＋コメントごと、その他はそのまま分割
1. 各チャンクごとに：
   - Gemini 2.5 Flashで台本を生成
   - Gemini 2.5 Flash TTSで音声を生成
1. 生成された音声ファイルを連結
1. 最終的なポッドキャストファイルを提供

## ライセンス

MIT
