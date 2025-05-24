# Life is Beautiful Podcast Generator

「Life is Beautiful」メルマガからポッドキャストを自動生成するアプリケーションです。

## 機能

- メルマガのマークダウンファイルをアップロード
- マークダウンをh2の見出しで分割
- Gemini 2.5 Pro AIを使用してポッドキャスト台本を生成
- Gemini 2.5 Pro TTSを使用して音声を生成
- 生成された音声ファイルを連結して一つのポッドキャストを作成

## 技術スタック

- バックエンド: FastAPI (Python)
- フロントエンド: HTML, JavaScript
- AI: Google Gemini 2.5 Pro, Gemini 2.5 Pro TTS
- 音声処理: pydub
- パッケージ管理: uv
- コード品質: ruff (linter & formatter)

## セットアップ

### 前提条件

- Python 3.8以上
- Gemini API キー
- uv (パッケージマネージャー)

### インストール

1. リポジトリをクローン:

```bash
git clone https://github.com/Tomodo1773/life-is-beautiful-podcast.git
cd life-is-beautiful-podcast
```

2. 依存関係をインストール:

```bash
uv pip install -e ".[dev]"
```

3. pre-commitフックをインストール:

```bash
pre-commit install
```

4. 環境変数を設定:

`.env`ファイルを作成し、以下の内容を追加:

```
GEMINI_API_KEY=your_gemini_api_key
```

### 実行

```bash
uvicorn app.main:app --reload
```

アプリケーションは http://localhost:8000 で実行されます。

## 使い方

1. ブラウザで http://localhost:8000 にアクセス
2. マークダウンファイルをアップロード
3. 「ポッドキャストを生成」ボタンをクリック
4. 処理が完了したら、生成されたポッドキャストをダウンロード

## API エンドポイント

- `POST /api/generate-podcast`: マークダウンファイルからポッドキャストを生成
- `GET /api/podcast-status/{job_id}`: ポッドキャスト生成ジョブのステータスを取得
- `GET /api/download-podcast/{job_id}`: 生成されたポッドキャストをダウンロード

## 処理の流れ

1. マークダウンファイルを読み込み
2. h2見出しでチャンクに分割（最初のチャンクはSTART、最後のチャンクはEND、その他は連番）
3. 各チャンクに対して:
   - Gemini 2.5 Proで台本を生成
   - Gemini 2.5 Pro TTSで音声を生成
4. 生成された音声ファイルを連結
5. 最終的なポッドキャストファイルを提供

## ライセンス

MIT
