# デプロイ手順

GitHub public リポジトリと Hugging Face Spaces (Docker SDK) の両方に push する想定。
ローカルコミットは作成済み (`git log` で確認可)。以降は haruki が手動でやる部分。

## 0. 事前準備

- GitHub アカウント
- Hugging Face アカウント (GitHub アカウントでログイン可)
- Git に Hugging Face の credential ヘルパーが有効になっていること

```bash
# HF のトークン認証 (初回のみ)
pip install huggingface_hub
huggingface-cli login        # write 権限のトークンを貼る
```

## 1. GitHub にリポジトリを作る

1. <https://github.com/new>
2. リポジトリ名: `fibrous-lipstick-api`
3. **Public**
4. README / .gitignore / license は **追加しない** (空リポで作る、push 時に競合させない)
5. Create

## 2. Hugging Face Spaces を作る

1. <https://huggingface.co/new-space>
2. Space 名: `fibrous-lipstick-api`
3. **License**: MIT
4. **SDK**: **Docker** (← 重要、Streamlit/Gradio ではない)
5. Hardware: CPU basic (無料枠)
6. Create

## 3. リモート登録 + push

`USER` を実際のユーザー名に置き換える。

```bash
cd ~/Desktop/fibrous-lipstick-api

# リモートを 2 つ登録
git remote add origin https://github.com/USER/fibrous-lipstick-api.git
git remote add hf     https://huggingface.co/spaces/USER/fibrous-lipstick-api

# まず GitHub
git push -u origin main

# 続いて Hugging Face Spaces
git push -u hf main
```

push 後、HF Spaces 側で Dockerfile が読まれて自動ビルドが始まる (数分かかる)。
ビルドログは Space の `Logs` タブで確認できる。

## 4. デプロイ後の確認

`USER` を実際の HF ユーザー名に置き換える。

```bash
# ヘルスチェック
curl https://USER-fibrous-lipstick-api.hf.space/health
# → {"status":"ok"}

# 単発抽出 (ムスキー画像)
curl -X POST https://USER-fibrous-lipstick-api.hf.space/extract_lab \
  -H "Content-Type: application/json" \
  -d '{"image_url":"https://cloudflare.lipscosme.com/image/1146e2669f8f25c9f3298df7-1687245280.png"}'

# Swagger UI
open https://USER-fibrous-lipstick-api.hf.space/docs
```

## 以降の更新

```bash
git add <変更ファイル>
git commit -m "..."
git push origin main
git push hf main
```

HF Spaces は push されると自動で再ビルドする。
