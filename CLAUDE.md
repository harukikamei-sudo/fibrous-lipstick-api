# CLAUDE.md — 次回セッションへの引き継ぎ

> このファイルは Claude Code が起動時に自動で読む。プロジェクトの前後関係を
> 即座に把握できるよう簡潔にまとめてある。

## プロジェクト概要

**Fibrous Lipstick API** — 口紅推奨ロジック MVP の Python 処理を FastAPI 化したもの。
商品スウォッチ画像 URL を投げると K-means + 形状特徴ベースで色を抽出し、
CIE Lab を返す公開 API。

最終ゴール: 「あなたの唇にこの口紅を塗ったらこう見える」をユーザー × 商品 × 厚み 21 段階で
事前計算して推薦するシステム。**今回作ったのはその第 1 段(商品の色を取り込む層)**。

## デプロイ先

| 用途 | URL |
|---|---|
| 公開 API | <https://tamable-fibrous-lipstick-api.hf.space> |
| Swagger UI | <https://tamable-fibrous-lipstick-api.hf.space/docs> |
| HF Space 管理 | <https://huggingface.co/spaces/Tamable/fibrous-lipstick-api> |
| GitHub | <https://github.com/harukikamei-sudo/fibrous-lipstick-api> |
| ローカル | `~/Desktop/fibrous-lipstick-api/` |

git remote: `origin` = GitHub (HTTPS), `hf` = HF Spaces (HTTPS)
ローカル git config: `harukikbb8-max <harukikbb8@gmail.com>` (個人 GitHub)
HF アカウント: `Tamable` (組織アカウント)

## ファイル構成

```
fibrous-lipstick-api/
├── app.py             FastAPI 本体。SSRF/DoS 対策、CORS、Literal 型
├── extract_lab.py     画像 → Lab 抽出ロジック (CLI 兼 API ライブラリ)、classify_status
├── lab_utils.py       色空間変換 (RGB↔Lab、Lab↔反射率、HSV)
├── km.py              ★K-M 本実装。有限層反射率 + K/S 算出 + applied_lab + table
├── estimate_s.py      ★ライン S 逆推定 (brentq でチャネル毎に数値求解)
├── test_lab_utils.py  Lab↔反射率往復テスト (ΔE<1)
├── test_km.py         ★K-M 性質テスト (t=0で唇/t大で発色/S往復/table)
├── sample_lab.py      ★校正CLI: 画像の薄/濃/素肌 領域→Lab→estimate_s で S 算出
│                      (座標モード --thin/--full/--substrate or --gui ドラッグ選択)
├── test_dark_swatch.py ダーク系維持テスト
├── sample_gas.gs      GAS サンプル (参考実装、ユーザーはこれを参考に自前で書く予定)
├── verify_batch.py    公開 API バッチ動作確認用 (CPU basic だと 50件は timeout、10件刻みなら可)
├── products.csv       入力データ (145 商品、id + image_url 等)
├── products_with_lab.csv  CLI 実行結果 (gitignore対象だが手元には残る)
├── thumbnails/        抽出色チップ可視化サムネ (gitignore)
├── images_cache/      画像 DL キャッシュ (gitignore)
├── Dockerfile         python:3.11-slim + libgl1 + 7860
├── requirements.txt
├── README.md          HF Spaces 用フロントマター付き
└── DEPLOY.md          push 手順
```

## 重要な設計判断

### 1. 色抽出ロジック (extract_lab.py)
**パラメータ (固定、いじらない方が無難)**:
```
EDGE_DENSITY_MAX = 0.10
MAX_CLUSTER_RATIO_MIN = 0.25
SATURATION_MIN = 0.25         ← Phase 1+ で 0.15 → 0.25 に引き上げ済み
PACKAGE_SIZE_RATIO_MAX = 0.15
BG_ADJACENCY_NEIGHBORHOOD = 3  ← scipy.binary_dilation で 3px 隣接判定
CONTAINER_ASPECT_MIN = 1.5     ← 縦長判定 (実際は機能弱)
CONTAINER_PENALTY = 0.3
AUTO_HIGH_EDGE_MAX = 0.05
AUTO_HIGH_SIZE_MIN = 0.30
AUTO_HIGH_ADJ_MIN = 0.10
N_CLUSTERS = 6
WHITE_THRESHOLD = 230
BLACK_THRESHOLD = 60          ← Phase 1+ で 25 → 60 に引き上げ済み
MIN_CENTER_VALUE = 30         ← 黒系クラスタ除外用
```

**スコア式**: `sat × size_ratio × (1 + bg_adj) × container_penalty`

### 2. status 3 段階分類 (`classify_status` in extract_lab.py)
- `auto_high`: edge<0.05 AND size>0.30 AND (adj>0.10 OR 非容器形状)
- `auto_low`: 上記以外の auto (目視レビュー推奨)
- `excluded`: 抽出失敗 / 容器のみ画像
- **CLI/API 共通の固定閾値**(中央値計算なし、Phase 1+++ で統一)

### 3. セキュリティ (app.py)
- SSRF: `_validate_url` で http(s) 以外 + loopback/private/link-local/multicast/reserved IP 拒否
- DoS: `_fetch_image` で stream + 10MB 上限、超過で 413 打ち切り
- batch: `max_length=50`、超えると 422
- CORS: 全許可 (MVP)

### 4. Lab ↔ 反射率変換 (lab_utils.py)
**linear sRGB を反射率近似**として使う (D65)。
sRGB ガンマ補正は可逆なので Lab→反射率→Lab の ΔE は 0.000(浮動小数精度)。
K-M 計算ではこの各チャネル値を波長帯反射率として扱う想定。

### 5. K-M モデル (km.py / estimate_s.py) ★今回実装
**有限層 Kubelka-Munk 式**(下地反射率 R_g の上に厚み t の顔料層):
```
K/S = (1 - R∞)² / (2 R∞)              # フル発色 = R∞ から商品固有の K/S
a = 1 + K/S,  b = √(a²-1)
R  = [1 - R_g(a - b·coth(bSt))] / [(a - R_g) + b·coth(bSt)]
```
- St→0 で R→R_g(膜なし=下地), St→∞ で R→R∞=a-b(無限厚)。間は単調。
- チャネル = linear sRGB の R/G/B 帯反射率。S はライン共通、K/S は商品ごと。
- `km.km_reflectance` が forward 本体。`compute_applied_lab` は唇 Lab を R_g に。
- `compute_km_table`: products × lines(省略可) × t_steps。商品ごとの S は
  `resolve_line_s` の優先順位で解決 → **lines[line_id] > line_category プリセット
  > line_id キーワード推定(velvet 等) > "other" default**。
- `estimate_s`: full(R∞)+light の 2 点から S をチャネル毎に brentq 求解。
  薄付き観測時の下地は `substrate_lab`(省略時 白基板 R_g≈1)。

**`/compute_km_table` は 2 モード(model_validator で片方のみ必須)**:
- 単品: `{lip_lab, product_lab, line_category}` … Swagger デモ/個別呼び出し向け
- バッチ: `{lip_lab, products:[{id,L,a,b,line_id?,line_category?,k_s?}], lines?}`
  … 145 商品を 1 回で計算。UI 実装の本線。lines 省略時はプリセットへフォールバック。
- レスポンス: `{mode, table:[{id, line_id, s, s_source, applied:[{t,L,a,b}]}]}`

**`LINE_S_PRESETS`(仕上げタイプ→S、km.py)**: gloss=1 < tint=2 < velvet=4 < matte=8。
透け感が強いほど S 小。**絶対値は t∈[0,1] スケールと結合**しており、S を大きく
(例 matte=200)すると t=0.05 で即飽和し 21 段階が階段関数に潰れるので O(1〜10) に。
暫定値で、薄付きスウォッチが集まれば estimate_s で実測 S に置換予定。
- **物理的限界(重要)**: K/S が大きい暗・高彩度チャネルは薄付きでも完全不透明
  (R が R∞ に張り付く)になり、S が観測色に反映されず逆算不能。これは情報損失
  でありバグではない。test_km.py は「自己整合性(全ch)＋感度chのS復元」で検証。
  → 実運用で S を正しく取るには **薄付きスウォッチをかなり薄く(小 t_light)** 撮る必要あり。

## 既知の問題点

### 誤抽出が直っていない 3 商品
| id | 現状 status | L | 期待 | 原因 |
|---|---|---:|---|---|
| rmd_juicy_lasting_17 | auto_high | 14.58 | L≈30 | 容器(暗赤ボトル)を採用。スウォッチと容器が同系色で sat×size×adj では分離不可 |
| rmd_the_juicy_lasting_16 | auto_low | 17.42 | L≈40 | 同上 |
| rmd_the_juicy_lasting_28 | auto_low | 71.18 | L≈70 | (Phase 1+ で SATURATION_MIN 0.25 引き上げで L=84→71 改善、ほぼ OK だが完璧ではない) |

**根本対策の候補(未着手)**:
- 連結成分解析で容器の縦長形状を確実に検出 (現状の bbox ベースは点在画素のせいで is_container=False になりがち)
- 中央領域のみサンプリング
- ユーザー手動 QA で auto_low を仕分け

### the_juicy_lasting ライン
29 件中 auto_high はわずか 1 件 (3.4%)。容器画像構成のため自動分類が困難。
**運用上は auto_low ベースの目視 QA 前提**で進めるのが現実的。

## 進捗フェーズ

| Phase | 内容 | 状態 |
|---|---|---|
| 1 | 黒背景バグ修正 + 容器/淡色対策 (bg_adjacency, container) | ✅ 完了 |
| 2 | lab_utils.py 切り出し + Lab↔反射率テスト | ✅ 完了 (CSV md5 一致) |
| 3 | FastAPI 化 (app.py + estimate_s/km 雛形) | ✅ 完了 |
| 4 | Docker + requirements + README + .gitignore | ✅ 完了 |
| 5 | git init + GitHub push + HF Spaces push | ✅ 完了 (公開済み) |
| security | SSRF/DoS/Batch上限/CORS/Literal 型 | ✅ 完了 |
| refactor | classify_status を CLI/API で一本化 | ✅ 完了 |
| 6 | GAS sample_gas.gs | ✅ 参考実装あり、ユーザーが自前で書く予定 |
| 7 | K-M 本実装 (km/estimate_s + /estimate_s,/compute_km_table の501解除) | ✅ 完了 (TestClient で疎通確認、全テスト通過) |

## 次回の進め方 / TODO

### A. K-M モデルの本実装 ✅ 完了
- `estimate_s` / `compute_applied_lab` / `compute_km_table` 実装済み
- `/estimate_s` `/compute_km_table` の 501 解除済み(pydantic スキーマ付き)
- **S 校正の段取り(決定済み・出費回避方針)**:
  - 口紅を買わず、**無料のスウォッチ画像**から light_lab/substrate を拾う方針。
    画像源は lipscosme の pattern ページ(全145件 URL あり)や Google 画像検索。
    宣材(特にマット"blur"系)は加工が強く計測不向き → ユーザー投稿の腕スウォッチ推奨。
  - 校正ツール `sample_lab.py` 実装済み。画像の薄/濃/素肌領域を座標 or GUI で指定
    → Lab 抽出 → estimate_s で S。合成画像(既知 S=2.5)で復元検証済み。
  - **必要な画像**: 「薄づき + 素肌が同じ写真に写った」スウォッチ。各仕上げ
    (gloss/tint/velvet/matte)で淡い色 1 枚ずつあれば 4 プリセット校正可能。
  - S/t スケール不定性のため t_light は規約固定(0.3)。得るのは相対 S。
  - **次アクション**: ユーザーが各仕上げの良いスウォッチ画像を数枚用意 → sample_lab.py
    に投げて S 算出 → km.py の LINE_S_PRESETS を実測値で更新。
- その他候補: compute_km_table 出力を CSV/JSON 保存するバッチ CLI。

### B. データ層の追い込み (余力があれば)
- 誤抽出 3 件の連結成分ベース判定追加
- the_juicy_lasting ラインの画像差し替え or 別ロジック

### C. GAS 連携
- ユーザーが自分で GAS コードを書く予定。困ったときは sample_gas.gs を参考にしてもらう
- スプレッドシート構成が決まったら sample_gas.gs の COLS を実環境に合わせる

### D. 運用周り
- HF Space のレート制限・ログ監視 (現状無し)
- products.csv の更新フロー (新商品追加時)
- auto_low の QA UI (Streamlit でサムネ並べる等)

## トリビア・注意

- HF アクセストークン: 現在は Tamable アカウントの `lips2`(write)が稼働中。
  git credential(osxkeychain)に保存済みなので `git push hf main` はそのまま通る。
  ※ 旧 `lips` は revoke 済み。`hf auth login --force` は対話 token 入力が必要で、
  CC セッションの `!` 経由だと getpass が echo 制御できず Aborted になる →
  **実 Terminal で `cd ~/Desktop/fibrous-lipstick-api && .venv/bin/hf auth login --force`** を実行すること。
- 公開 API は **無認証**。悪用が増えたら HF Space を private 化する選択肢あり
- `huggingface-cli` は deprecated、新 CLI は `hf` コマンド (`pip install huggingface_hub`)
- macOS Python 3.13 (system) は SSL 証明書問題あり。venv の `requests` を使えば OK
- `git push hf main` で HF Space が自動再ビルド (30秒〜数分)

## デプロイ更新フロー

```bash
cd ~/Desktop/fibrous-lipstick-api
source .venv/bin/activate
# (変更を加える)
git add <files>
git commit -m "..."
git push origin main   # GitHub
git push hf main       # HF Spaces (自動再ビルド)
```
