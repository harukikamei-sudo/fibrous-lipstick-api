---
title: Fibrous Lipstick API
emoji: 💄
colorFrom: pink
colorTo: red
sdk: docker
app_port: 7860
pinned: false
license: mit
---

# Fibrous Lipstick API

口紅推奨ロジック MVP の Python 処理を集約した FastAPI サーバー。

## エンドポイント

- `POST /extract_lab` — 商品画像 URL から Lab を抽出
- `POST /extract_lab_batch` — 一括処理
- `POST /estimate_s` — ライン散乱係数推定(未実装、501)
- `POST /compute_km_table` — K-M バッチ計算(未実装、501)
- `GET /health` — ヘルスチェック

詳細は `/docs` の Swagger UI 参照。

## ローカル実行

```bash
pip install -r requirements.txt
uvicorn app:app --reload
```

`http://localhost:8000/docs` にアクセスして Swagger UI から各エンドポイントを試せる。

## CLI バッチ(API を経由せず手元で実行)

```bash
python extract_lab.py
```

カレントディレクトリの `products.csv` (`id`, `image_url` 列を含む)を読み、
`products_with_lab.csv` / `excluded_list.csv` / `thumbnails/{id}.png` を出力する。

## モジュール構成

| ファイル | 役割 |
|---|---|
| `app.py` | FastAPI アプリ |
| `extract_lab.py` | 画像 → Lab 抽出ロジック(CLI と API で共通) |
| `lab_utils.py` | 色空間変換(RGB ↔ Lab、Lab ↔ 反射率、HSV) |
| `estimate_s.py` | ライン S 逆推定(雛形) |
| `km.py` | K-M モデル計算(雛形) |

## デプロイ(Hugging Face Spaces / GitHub)

初回 push の例:

```bash
git remote add origin https://github.com/USER/fibrous-lipstick-api.git
git remote add hf https://huggingface.co/spaces/USER/fibrous-lipstick-api
git push origin main
git push hf main
```

HF Spaces 側は `sdk: docker` を指定しているので、push されると Dockerfile を読んでビルドされる。
