# HANDOFF.md — 新セッションへの引き継ぎ

> 新しい Claude (Cursor / Claude Code) セッションで作業を継続するための起点。
> **このファイルを最初に読んでから、リンク先 docs を参照する**。

最終更新: 2026-06-02 (Opus 4.7 / 1M context) — **DB 連携 + Kawano AR フロント疎通確認**
全テスト: 32 件合格(bayesian 8, recommend_v2 7, v13_endpoints 11, v13_flow E2E 6)
CI: GitHub Actions で Python 3.11/3.12 を自動回転

## 2026-06-02 セッションの追加(DB 連携)

Kawano さんから AR フロント `color-capture`(Next.js + MediaPipe)を受領、本番 API と
全4エンドポイント疎通確認済み。DB は `lipstick_DB_updated.xlsx`(Spreadsheet+GAS 方針)で確定。

- **x_20 を DB の20軸定義に統一**(`catalog_x20.py`): hue/saturation/brightness/pigmentation
  + lines由来11軸(glossy〜transfer_resistance)+ 世界観5(girly/makeup_intensity/konare/
  sweetness/korean)。DB の users θ_pref 列順が source of truth
- **`DB_V13_COLUMNS.md`**: DB に追加すべき v1.3 列の手順(users に lip_L/a/b・mu_thickness・
  sigma2_thickness、observations に thickness・observed_lab_*・y・viewed_seconds)
- **`gas_webapp.gs`**: GAS Web App。?action=load/save/observe で users/observations 読み書き。
  lip API の UserState と 1:1 対応。Kawano の userStateStore.ts を差し替えるだけで繋がる
- **`sync_db_products.py` → `db_products_filled.csv`**: DB products シートに貼る Lab+9軸 CSV(140件)

### ✅ DB 構築 完了(2026-06-02、最新ファイル `~/Downloads/lpis_DB.xlsx`)
- users に5列追加済(BF-BJ: lip_L/a/b, mu_thickness, sigma2_thickness)
- observations に6列追加済(thickness, observed_lab_L/a/b, y, viewed_seconds)
- products に Lab 流し込み済(140行すべて Lab 入り)
- GAS デプロイ済 → `TEST_saveAndLoad` で users への save/load 成功確認
  (lip_lab/theta_thickness/20次元θ_pref が正しく往復)
- ⚠️ 軽微: 一部列名に余分な空白/記号(`'lip_L '`, `'viewed_seconds │'`等)。
  GAS は列番号で読み書きするので動作影響なし。気になれば Sheets で掃除(任意)

### 残タスク
1. (任意)`TEST_observe` 実行で observations 書き込みも目視確認
2. (任意)zero_velvet_02 削除(aspect=4.76, container=True=パッケージ色)
3. **GAS Web App URL を取得 → 外部 curl 疎通テスト**(エディタ内 TEST は通過済、
   残るは外部HTTPアクセス確認のみ)
4. **DB の件を Kawano に共有**(Friday のタイミング。まだ未連絡)
5. Kawano: userStateStore.ts を localStorage → GAS版(?action=load/save/observe)に差し替え

---

---

## 1. プロジェクト一行紹介

**Fibrous Lipstick API** — 高校1年生「ミナ」向けの口紅推奨システム MVP。
rom&nd 1ブランド145商品を対象に、唇の Lab + 商品 + 厚みから K-M モデルで
「塗ったらこう見える」を計算し、パーソナルカラー込みで推薦する。
本番 API は HF Spaces に稼働中: <https://tamable-fibrous-lipstick-api.hf.space/docs>

---

## 2. 重要ドキュメント (役割分担)

新セッションは下記4点を**読む順番**で参照:

| 順 | ファイル | 役割 |
|---|---|---|
| ① | **HANDOFF.md (このファイル)** | 直近の状態・未解決事項・新セッション起点 |
| ② | **[CLAUDE.md](CLAUDE.md)** | 運用・進捗・申し送り |
| ③ | **[KAWANO_INTERFACE.md](KAWANO_INTERFACE.md)** | ★v1.3 個人化学習層の Kawanoさん interface(議論ポイント付き) |
| ④ | **[DESIGN.md](DESIGN.md)** | 理論・式の導出・計算過程・なぜその値か |
| ⑤ | **[LOG.md](LOG.md)** | 各意思決定の目的・試行・失敗・採用根拠(時系列) |
| ⑥ | **[API_GUIDE.md](API_GUIDE.md)** | エンドポイント使い方(curl 例・レスポンス例) |

> **設計書 PDF** (`/Users/Friday/Downloads/口紅推奨ロジック設計書_VN1_3 (1).pdf`)
> は v1.3、**現状の実装と乖離あり**(§5 参照)。

---

## 3. 現状のシステム到達点

| 項目 | 状態 |
|---|---|
| K-M モデル本体 (km.py) | ✅ |
| `/recommend` エンドポイント | ✅ 公開稼働 |
| **PC連携(論文ベースLab領域+清濁C\*軸+空タグバックフィル)** | ✅ **全平均一致率 0.810 (good)** |
| `/evaluate` メトリクス | ✅ |
| S 校正基盤 (estimate_s_layered) | ✅ (tint=0.42 のみ実測、他は推論値で確定) |
| 色差: CIEDE2000 移行 | ✅ |
| Streamlit UI Lv2 (実写顔合成) | ✅ |
| 唇マスク自動抽出 (`extract_lip_mask`) | ✅ a*·chroma 行ピークで縦中心自動検出 + 8連結 morpho 平滑化 |
| ファイルアップロード + マスク微調整スライダー | ✅ |
| 拡大モーダル (Before/After) | ✅ |
| 画像アセット git 除外方針 | ✅ (HF binary policy で履歴書き換え対応済み) |
| 全テスト (test_km.py 性質1〜8) | ✅ pass |
| **設計書 v1.3 個人化学習層 (本セッション追加)** | ✅ |
| ├ 4 θ ベイズ更新 (color/pref/explore/thickness) | ✅ `bayesian.py` + test 8件 |
| ├ effective_Lab 線形補間 + Part IV/VI 統合スコア | ✅ `recommend_v2.py` + test 7件 |
| ├ 強制ペア比較 10問(色5 + 世界観5、仮データ) | ✅ `pair_compare.py` |
| ├ 20次元 pref ベクトル(機能15 + 世界観5、派生計算) | ✅ `catalog_x20.py` + CSV 列付与済 |
| ├ Kawanoさん interface 4 エンドポイント | ✅ `/v13/pair_compare/init,apply` `/v13/update_user` `/v13/recommend` |
| ├ エンドポイント単体テスト | ✅ `test_v13_endpoints.py` 11件(正常+エラー) |
| ├ E2E 統合疎通テスト | ✅ `test_v13_flow.py`(μ_thickness 学習で TOP 順位変動を確認) |
| ├ `image_url` をレスポンスに含める | ✅ Kawanoさん AR がそのまま商品サムネ表示可 |
| ├ Streamlit 実写唇合成統合 | ✅ `ui_v13.py` で顔写真→マスク抽出→TOP-N に effective_Lab で合成表示 |
| ├ 個人化検証ツール 3 種 | ✅ `personalization_demo.py` / `personas_cli.py` / `ui_v13.py` |
| └ GitHub Actions CI | ✅ push/PR で Python 3.11/3.12 × 6テスト自動実行 |

最新の git 状態:
```
e8ccb26 fix(ui): smooth mask contour with 8-connected morphology
bfc94c0 fix(ui): auto-detect lip vertical center
1d5e1e2 feat: switch /recommend point-to-point ΔE from CIE76 to CIEDE2000
3c0498b feat(/evaluate): backfill empty-tag products
dcf000f feat: add C* axis to PC_LIPSTICK_TARGETS
```
復旧アンカー: `backup-before-history-rewrite` タグが origin に保全

---

## 4. ファイル構成 (主要)

```
fibrous-lipstick-api/
├── km.py                K-M モデル + LINE_S_PRESETS + PC_LIPSTICK_TARGETS + LIP_PRESETS
├── estimate_s.py        S 逆推定 (2点法/単一スカラー/3点フィット)
├── app.py               FastAPI: /recommend /evaluate /compute_km_table /extract_lab ...
├── ui_app.py            Streamlit UI Lv2 (実写合成、マスク自動抽出、PC選択)
├── evaluate_all.py      PC連携バッチ評価 (5唇 × 4PC = 20組)
├── sample_lab.py        校正用CLI (画像→Lab→S推定)
├── products_with_lab.csv  カタログ140件 (Lab + line_category + pc_season)
├── lab_utils.py         色変換ユーティリティ
├── test_km.py           ユニットテスト
└── assets/lips/         唇画像 (gitignore、ローカル限定)
```

---

## 5. ~~設計書 v1.3 ギャップ~~ **大部分解決済(2026-05-29)**

本セッション(Opus 4.7)で個人化学習層の主要4ギャップを実装。

| 旧ギャップ | 状態 |
|---|---|
| 1. 個人化学習が無い | ✅ `bayesian.py` で 4 θ ガウス更新 実装 |
| 2. 強制ペア比較が無い | ✅ `pair_compare.py` で 10 ペア仮データ + 事前分布構築 |
| 3. 20次元 pref ベクトルが無い | ✅ `catalog_x20.py` で派生計算、CSV 付与済 |
| 4. PC連携実装方針が違う | ⚠️ 既存ハード距離マッチングは維持(MVP の高精度実装、0.81 達成)。Bayesian 事前分布側の経路も新規実装で並走 |
| 5. GAS vs Python | 🤝 ステートレス Python API として実装。永続化先(GAS/Firebase/他)は Kawanoさん 次第 |

詳細は `KAWANO_INTERFACE.md` 参照。以下、旧ドキュメント原文を残置:

---

### 旧: 設計書 v1.3 とのギャップ(参考)

ユーザーから設計書 PDF を共有された (2026-05-29 14:10) 。
v1.3 の正式構造は以下の 6 Part:

```
Part I    PC診断              → θ_color 事前分布(経路A)
Part I'   唇Lab取得 [新規]    → Kawanoさん撮影
Part I''  K-Mバッチ生成 [新規]→ user_product_lab_table 146×21
Part II   強制ペア比較(10問)  → 事前分布(経路B、ミナ向け中核)
Part III  統合ベイズ更新      → 4パラメータ学習
Part IV   推奨スコア統合式    → f = -α·ΔE2000(eff_Lab, μ_color) + μ_pref·c.x_20
Part V    AR試着 [拡張]       → Kawanoさん AR + スライダー + いいね/微妙
Part VI   セレンディピティ    → R_final = f - β(μ_explore)·familiarity
```

**ユーザーごとに ベイズ更新される4パラメータ**:
- `θ_color` (Lab 3次元、似合う色の中心)
- `θ_pref` (20次元、機能15 + 世界観5)
- `θ_explore` (1次元、探索性)
- `θ_thickness` (1次元、塗り厚好み)

**役割分担(設計書)**:
- lip API: K-M計算・推奨計算 (**設計書では GAS で実装**)
- Kawanoさん: AR表示・質感合成・スライダーUI・いいね/微妙UI・観測ログ送信

### 現状実装との乖離 5 点

1. **個人化学習が無い** — Bayesian update 未実装、全ユーザーに同じ推薦
2. **強制ペア比較が無い** — ミナの事前分布構築の中核(経路B)が無い
3. **20次元 pref ベクトルが無い** — `μ_pref·c.x_20` 項が推薦スコアから落ちてる
4. **PC連携実装方針が違う** — 設計書は事前分布、実装はハード距離マッチング
5. **GAS vs Python** — 設計書は GAS+Spreadsheet、実装は FastAPI+Python (Kawanoさん 連携 interface 接続未確認)

### Part 対応表

| Part | 実装状態 |
|---|---|
| Part I (PC診断) | ⚠️ ハード距離マッチング(設計書はベイズ事前分布) |
| Part I' (唇Lab) | ✅ measure_lip_lab で同等 |
| Part I'' (K-M) | ⚠️ compute_km_table はあるが**テーブル保存なし**(都度計算) |
| Part II (ペア比較) | ❌ 未実装 |
| Part III (ベイズ更新) | ❌ 未実装 |
| Part IV (統合スコア) | ⚠️ ΔE/pc_score のみ、μ_pref·c.x_20 項なし |
| Part V (AR試着) | ✅ Streamlit Lv2 で代替実装 |
| Part VI (セレンディピティ) | ❌ familiarity 関数なし |

---

## 6. **次セッション開始時の状態**

ユーザー方針(2026-05-29 回答済):
> 「唇Lab・AR・PC判定は Kawanoさん がやるから、それを俺が受け取ってシミュできるようにして」
> 「Kawanoさん からはまだ何も来てない前提で、連携しやすいように作る」

→ 設計書 v1.3 の役割分担に従い、**lip API はステートレス計算サーバー**として実装完了。
   Kawanoさん からの interface 確定待ち(`KAWANO_INTERFACE.md` §5 に議論ポイント7項目)。

### 待ち状態(Kawanoさん との合意事項)

| # | 議論ポイント | デフォルト実装 |
|---|---|---|
| 1 | データ形式(Lab dict vs array、UserState 往復のサイズ) | dict 形式、丸ごと往復 |
| 2 | 通信モデル(同期 REST、CORS) | 同期 REST、CORS=`*` |
| 3 | ペア比較10問の中身(商品の組み合わせ・提示順) | 俺が仮で組んだ `_PAIR_SPECS` |
| 4 | x_20 軸の20軸定義(機能15+世界観5) | 派生計算による暫定軸 |
| 5 | 観測ログの拡張余地(`extras`, `viewed_seconds`) | `extras` 無し、`viewed_seconds` 任意 |
| 6 | K-M テーブルの事前計算 vs 都度計算 | 都度計算(MVP は十分高速) |
| 7 | 認証 / users 永続化(lip API 側 or Kawanoさん 側) | lip API 側 DB なし(caller が保持) |

### 直近のオプション

- **a. このまま Kawanoさん に「叩き台 ready」と連絡** → 1〜7 を相談しながら詰める
- **b. ミナさん向けデモを Streamlit Lv2 のまま実施** → 個人化学習を組み込んだ UI に拡張
- **c. 既存 `/recommend` (ハード距離マッチング、0.81 達成) を本番継続、`/v13/*` は実験ライン**
- **d. Streamlit UI を v1.3 ベイズ更新ループに対応させる**(AR スライダー + いいね/微妙)

---

## 7. 公開URL / コマンド早見表

```bash
# 本番 API
curl https://tamable-fibrous-lipstick-api.hf.space/health

# 推薦 (PC込み)
curl -X POST https://tamable-fibrous-lipstick-api.hf.space/recommend \
  -H "Content-Type: application/json" \
  -d '{"lip_lab":{"L":62,"a":22,"b":12},"pc_season":"ブルベ夏","top_n":5}'

# 妥当性評価
curl -X POST https://tamable-fibrous-lipstick-api.hf.space/evaluate \
  -H "Content-Type: application/json" \
  -d '{"lip_lab":{"L":62,"a":22,"b":12},"expected_pc":"ブルベ夏","top_n":10}'

# 公開 Swagger UI
# https://tamable-fibrous-lipstick-api.hf.space/docs

# ★試着デモ(口紅を顔写真に合成)は HF Spaces に公開済(2026-06-04)
# → https://tamable-fibrous-lipstick-tryon.hf.space  (ブラウザで開くだけ。ローカル起動不要)
#   ソース: hf_streamlit_space/(独立 HF Space リポジトリ)
#   更新: bash hf_streamlit_space/sync_demo.sh

# ローカルで動かしたい場合のみ(macOS の初回ライブラリ検証で起動が遅いことあり)
cd ~/Desktop/fibrous-lipstick-api
.venv/bin/streamlit run ui_app.py
# → http://localhost:8501

# バッチ評価(本番API版)
PYTHONPATH=. .venv/bin/python evaluate_all.py --api https://tamable-fibrous-lipstick-api.hf.space

# テスト
.venv/bin/python test_km.py
```

---

## 8. デプロイ更新フロー

```bash
cd ~/Desktop/fibrous-lipstick-api
source .venv/bin/activate
# (変更を加える)
git add <files>
git commit -m "..."
git push origin main      # GitHub
git push hf main          # HF Spaces (自動再ビルド 30秒〜数分)
```

注意:
- `assets/lips/*.{png,jpg,webp}` は git 追跡しない方針 (HF binary policy)
- HF アクセストークン `lips2` (write) が osxkeychain に保存済み
- 履歴書き換えが必要な場合は `backup-before-history-rewrite` タグから復旧可

---

## 9. 既知の限界(Known Limitations)

- イエベ秋 acceptable セルが 1 つ (`healthy_pink × イエベ秋 = 0.60`) — 境界ケース、深追いせず
- マスク輪郭にピクセル単位のギザギザが残る — mediapipe py3.13 未対応のため色しきい値法の宿命
- カタログ pc_season タグ未付与 11/145 (約8%) — バックフィルで対応済
- gloss/velvet/matte の S は推論値(tint=0.42 のみ実測アンカー)
- **個人化学習(ベイズ更新)・ペア比較・対話 UI・観測ログ収集が未実装(§5 設計書ギャップ)**

---

## 10. 新セッションへのオープナー例

新しい Cursor/Claude Code セッションに**最初のメッセージとして貼る**ためのテンプレ:

```
このプロジェクトの状態を把握したい。
HANDOFF.md → CLAUDE.md → DESIGN.md → LOG.md → API_GUIDE.md の順で読んで、
特に HANDOFF.md §5 (設計書 v1.3 とのギャップ) と §6 (待ち状態の4選択肢) を
理解した上で、次に何をすべきか提案してほしい。
```

これで新セッションが既存 docs を読んで状況をキャッチアップし、
次の一手を提案してくれるはず。
