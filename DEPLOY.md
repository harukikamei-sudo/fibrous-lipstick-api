# デプロイ手順

GitHub public リポジトリと Hugging Face Spaces (Docker SDK) の両方に push する想定。
ローカルコミットは作成済み (`git log` で確認可)。以降は haruki が手動でやる部分。

## 0. 事前準備

- GitHub アカウント
- Hugging Face アカウント (GitHub アカウントでログイン可)

**認証はすでに通っている。追加のログインは不要。** HF の write token は git credential
(osxkeychain) に保存済みで、`git push hf ...` はそのまま通る。

`huggingface-cli login` は**書かない**。このコマンドは廃止済みで、新しい CLI は `hf`。
そもそもこの手順では不要である。

認証まわりで疑わしいときは、まず次で切り分ける。

```bash
git ls-remote hf     # ref が返れば認証は通っている
```

`git fetch hf` が `fatal: expected 'acknowledgments'` で落ちるのは**認証エラーではない**
(理由は「以降の更新」を参照)。

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
```

**HF への push は通常の push ではない。**「以降の更新」の orphan push 手順を使う。
新規作成の初回も同じ手順でよい (履歴を送らないので、初回かどうかで変わらない)。

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

**GitHub と HF で push の仕方が違う。`git push hf main` は必ず失敗する。**

```bash
git add <変更ファイル>
git commit -m "..."
git push origin main          # GitHub は通常の push
```

HF へは **orphan 単一コミットを force push** する。

```bash
export GIT_INDEX_FILE=$(mktemp)
git read-tree origin/main
git ls-tree -r --name-only origin/main | grep '[.]png$' \
  | while read -r f; do git rm --cached -q "$f"; done
TREE=$(git write-tree)
unset GIT_INDEX_FILE

ORPHAN=$(git commit-tree "$TREE" \
  -m "deploy: <変更の要約>(main $(git rev-parse --short origin/main) のツリー − 図PNG)")

git push hf "$ORPHAN:main" --force
```

### なぜ通常の push ではだめか

HF は **1MB 超のバイナリを履歴ごと拒否**する。`git rm` した新しいコミットを積んでも、
過去の blob が履歴に残っていて pre-receive で弾かれる。**orphan にして履歴ごと捨てる**のが要点。

その結果、HF 側は履歴を持たない単一コミットになっている。GitHub の履歴とは共通の祖先が
ゼロなので、次のようになる。

| コマンド | 結果 | 意味 |
| --- | --- | --- |
| `git push hf main` | `! [rejected] main -> main (fetch first)` | 相手に知らない commit がある |
| `git fetch hf` | `fatal: expected 'acknowledgments'` | **認証エラーではない。** 共通祖先ゼロの相手とのネゴシエーションが失敗しているだけ |
| `git ls-remote hf` | ref が返る | 認証は通っている |

**HF から fetch する必要はない。** 履歴を引き継がない運用なので、常に上書きする。

### デプロイ後

HF Spaces は push されると自動で再ビルドする (数分)。

```bash
curl https://tamable-fibrous-lipstick-api.hf.space/health
# → {"status":"ok"}
```

**起動に10秒以上かかる。** `extract_lab` の起動時先読みが入っているため。`cpu-basic` では
macOS の実測 13.6 秒よりさらに延びる可能性がある。起動しない場合はまずこれを疑う。
