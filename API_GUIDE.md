# Fibrous Lipstick API — 使い方ガイド

口紅推薦システム公開APIの**実用マニュアル**。各エンドポイントの**目的・curl例・レスポンス例・注意点**を1ファイルにまとめてある。

- **本番URL**: `https://tamable-fibrous-lipstick-api.hf.space`
- **Swagger UI (Try it out あり)**: <https://tamable-fibrous-lipstick-api.hf.space/docs>
- 理論・式の詳細は [DESIGN.md](DESIGN.md)、進捗/方針は [CLAUDE.md](CLAUDE.md) 参照。

---

## クイックスタート(まず動かす)

```bash
# 1) サービスが生きてるか
curl https://tamable-fibrous-lipstick-api.hf.space/health
#=> {"status":"ok"}

# 2) 唇色から TOP5 を推薦
curl -X POST https://tamable-fibrous-lipstick-api.hf.space/recommend \
  -H "Content-Type: application/json" \
  -d '{"lip_lab":{"L":62,"a":22,"b":12},"top_n":5}'

# 3) パーソナルカラー込みで推薦(イエベ春)
curl -X POST https://tamable-fibrous-lipstick-api.hf.space/recommend \
  -H "Content-Type: application/json" \
  -d '{"lip_lab":{"L":62,"a":22,"b":12},"pc_season":"イエベ春","top_n":5}'
```

ブラウザでぽちぽち試したい時は **Swagger UI** が一番ラク → `/docs` を開いて、エンドポイント展開 → 「Try it out」→ Execute。

---

## エンドポイント一覧

| Method | Path | 一言 |
|---|---|---|
| GET | `/` | サービス情報・エンドポイント一覧・カタログ件数 |
| GET | `/health` | 死活確認 |
| POST | [`/extract_lab`](#post-extract_lab) | スウォッチ画像URL → 商品 Lab |
| POST | [`/extract_lab_batch`](#post-extract_lab_batch) | 画像URL を最大50件まとめて Lab 化 |
| POST | [`/estimate_s`](#post-estimate_s) | フル発色+薄付きの2点から散乱係数 S を逆推定 |
| POST | [`/compute_km_table`](#post-compute_km_table) | 唇×商品×厚み 21段の塗布後 Lab テーブル |
| POST | [`/recommend`](#post-recommend) ★ | 唇色(+PC) → 全カタログから TOP-N 推薦 |
| POST | [`/evaluate`](#post-evaluate) ★ | PC 連携の妥当性メトリクス(予測 vs サイトタグ一致率) |

★= 一般用途のメインエンドポイント。

---

### GET `/`

サービスの基本情報。

```bash
curl https://tamable-fibrous-lipstick-api.hf.space/
```

```json
{
  "service": "Fibrous Lipstick API",
  "version": "0.1.0",
  "endpoints": ["/extract_lab","/extract_lab_batch","/estimate_s",
                "/compute_km_table","/recommend","/evaluate"],
  "catalog_size": 140
}
```

### GET `/health`
```bash
curl https://tamable-fibrous-lipstick-api.hf.space/health
#=> {"status":"ok"}
```

---

## POST `/extract_lab`

**用途**: 1枚のスウォッチ画像URLから商品の代表色 Lab を取得。

**入力**: `{ "image_url": "https://..." }`(http/https の直リンク。10MB上限)

**curl 例**:
```bash
curl -X POST https://tamable-fibrous-lipstick-api.hf.space/extract_lab \
  -H "Content-Type: application/json" \
  -d '{"image_url":"https://cloudflare.lipscosme.com/image/8cf22155add736274c1c1226-1740115256.png"}'
```

**レスポンス例**:
```json
{
  "status": "auto_high",
  "lab": {"L": 61.71, "a": 31.28, "b": 31.08},
  "notes": "sat=0.55, hue=15°, size=0.20, edge=0.04, ..."
}
```

- `status`: `auto_high`(自動採用OK) / `auto_low`(目視推奨) / `excluded`(失敗)
- `notes`: 抽出に使った特徴量(色相・サイズ・エッジ等)
- 詳細: [DESIGN.md §1](DESIGN.md)

**注意**:
- URL は **直リンク**(.png/.jpg 等)。HTMLページURLは不可。
- 内部IP(loopback/private)は SSRF 対策で拒否。

---

## POST `/extract_lab_batch`

**用途**: 複数画像をまとめて Lab 化。最大50件。

**入力**:
```json
{"products":[
  {"id":"x1","image_url":"https://..."},
  {"id":"x2","image_url":"https://..."}
]}
```

**curl 例**:
```bash
curl -X POST https://tamable-fibrous-lipstick-api.hf.space/extract_lab_batch \
  -H "Content-Type: application/json" \
  -d '{"products":[{"id":"a","image_url":"https://cloudflare.lipscosme.com/image/8cf22155add736274c1c1226-1740115256.png"}]}'
```

**レスポンス例**:
```json
{"results":[{"id":"a","status":"auto_high","lab":{"L":61.7,"a":31.3,"b":31.1},"notes":"..."}]}
```

51件以上送ると 422、各商品の失敗は `excluded` で個別返却(全体は失敗しない)。

---

## POST `/estimate_s`

**用途**: 同じラインの2点観測(フル発色+薄付き)から、ライン共通の散乱係数 `S` を逆推定する**校正用**エンドポイント。普通の UI からは叩かない。

**入力**:
```json
{
  "full_lab":  {"L": 37.0, "a": 36.0, "b": 21.0},   // 商品フル発色 = R∞
  "light_lab": {"L": 50.0, "a": 22.0, "b": 16.0},   // t=t_light での薄付き観測
  "t_light": 0.3,                                   // 規約: 1度塗り = 0.3
  "substrate_lab": null                             // 省略時=白基板
}
```

**curl 例**:
```bash
curl -X POST https://tamable-fibrous-lipstick-api.hf.space/estimate_s \
  -H "Content-Type: application/json" \
  -d '{"full_lab":{"L":37,"a":36,"b":21},"light_lab":{"L":50,"a":22,"b":16},"t_light":0.3}'
```

**レスポンス例**:
```json
{"s":[2.54, 0.35, 0.34], "k_s":[0.89, 10.23, 12.00]}
```

`s` はチャネル毎(R,G,B 帯)の散乱係数、`k_s` は商品 K/S 比。
理論詳細: [DESIGN.md §3](DESIGN.md)。

**注意**: シアーな色は暗チャネルが飽和して S が出ない。**校正は淡い色推奨**。

---

## POST `/compute_km_table`

**用途**: 唇×商品×厚み 21段階の「塗布後 Lab」テーブルを K-M モデルで計算。**2モード**:
- **単品モード**: 1商品×t=0..1 を21段で
- **バッチモード**: 複数商品(最大50件)×t=0..1 を21段で

### 単品モード
```bash
curl -X POST https://tamable-fibrous-lipstick-api.hf.space/compute_km_table \
  -H "Content-Type: application/json" \
  -d '{
    "lip_lab": {"L":60,"a":15,"b":10},
    "product_lab": {"L":37,"a":36,"b":21},
    "line_category": "tint"
  }'
```

レスポンス: `{ "mode":"single", "table":[{"id":"product","line_id":null,"s":[2.0,2.0,2.0],"s_source":"category:tint","applied":[{"t":0.0,...},{"t":0.05,...},...]}] }`

`applied` の中身が **t=0..1 を21段(またはt_stepsで指定した分割数)で「塗布後Lab」がずらっと並ぶ**。各 t は塗り重ね量に対応(0=素肌、1=しっかり塗り)。

### バッチモード
```bash
curl -X POST https://tamable-fibrous-lipstick-api.hf.space/compute_km_table \
  -H "Content-Type: application/json" \
  -d '{
    "lip_lab":{"L":60,"a":18,"b":12},
    "products":[
      {"id":"p1","line_id":"L1","L":33.4,"a":35.6,"b":21.9},
      {"id":"p2","line_id":"L2","L":44.0,"a":44.5,"b":26.6}
    ],
    "lines":{"L1":[2,2,2],"L2":[8,8,8]},
    "t_steps":5
  }'
```

- `line_category` 指定時はプリセット S が使われる(`gloss=0.25 / tint=0.4 / velvet=1.0 / matte=2.0 / other=0.6`)
- バッチで `lines` 省略可: `line_id` キーワード or `line_category` から自動推定
- 同一リクエストで単品/バッチを併用不可(422)

**line_category の値**: `tint / matte / gloss / velvet / other` 以外は 422。
**プリセット詳細**: [DESIGN.md §4.1](DESIGN.md)。

---

## POST `/recommend` ★

**用途**: 唇色(+任意でPC・目標色・絞り込み)を渡すと、**全カタログ140商品**で塗布後Labを計算し、スコア昇順で TOP-N 返す。**メインのエンドポイント**。

**入力スキーマ(全フィールド任意は ?)**:
```json
{
  "lip_lab": {"L":62,"a":22,"b":12},     // 必須:唇の Lab(下地)
  "t": 1.0,                                // ? 塗り厚 (既定 1.0)
  "target_lab": null,                      // ? 目標色 (指定時はそれに近い順)
  "pc_season": null,                       // ? "イエベ春"|"イエベ秋"|"ブルベ夏"|"ブルベ冬"
  "line_category": null,                   // ? "tint"|"matte"|"gloss"|"velvet"|"other"
  "hue_min": null, "hue_max": null,        // ? applied の色相絞り込み(0-360)
  "L_min":   null, "L_max":   null,        // ? applied の明度絞り込み
  "top_n": 5
}
```

**ソートキーの自動切替**:
| 指定 | filter_method | スコア(=delta_e) |
|---|---|---|
| `pc_season` あり | `pc_season_target_region` | PC Lab 領域からの距離(pc_score) |
| `target_lab` あり | `delta_e_to_target` | applied と target の **ΔE2000(CIEDE2000)** |
| 何も指定なし | `delta_e_to_lip` | applied と lip の **ΔE2000**(=自然/唇寄り) |

※ ΔE2000(CIEDE2000) は明度/彩度/色相を非線形に重み付けた知覚一様な色差(化粧品/印刷の業界標準)。
旧 ΔE76(単純ユークリッド)から移行済み。`pc_score` は領域距離なのでユークリッドのまま据置。

### 例1: 唇に近い順(最も自然)
```bash
curl -X POST https://tamable-fibrous-lipstick-api.hf.space/recommend \
  -H "Content-Type: application/json" \
  -d '{"lip_lab":{"L":62,"a":22,"b":12},"top_n":5}'
```

### 例2: パーソナルカラーで推薦
```bash
curl -X POST https://tamable-fibrous-lipstick-api.hf.space/recommend \
  -H "Content-Type: application/json" \
  -d '{"lip_lab":{"L":62,"a":22,"b":12},"pc_season":"ブルベ夏","top_n":5}'
```

### 例3: 目標色狙い+仕上げ絞り込み
```bash
curl -X POST https://tamable-fibrous-lipstick-api.hf.space/recommend \
  -H "Content-Type: application/json" \
  -d '{"lip_lab":{"L":62,"a":22,"b":12},
       "target_lab":{"L":50,"a":45,"b":25},
       "line_category":"matte",
       "top_n":3}'
```

**レスポンス例**(PC指定時):
```json
{
  "count": 140,
  "catalog_size": 140,
  "filter_method": "pc_season_target_region",
  "pc_season": "ブルベ夏",
  "sort_target": {"L":65.0,"a":30.0,"b":2.5},
  "results": [
    {
      "id": "rmd_the_juicy_lasting_23",
      "name": "ピーチピーチミー",
      "line_category": "tint",
      "original_lab": {"L":67.87,"a":47.65,"b":12.4},
      "applied_lab":  {"L":62.32,"a":30.64,"b":6.01},
      "applied_chroma": 31.22,            // 彩度 C*=√(a²+b²)。清濁判定軸
      "delta_e": 0.0,                     // ソート主スコア(ここではpc_score)
      "pc_score": 0.0,                    // PC領域(L,a,b,C*)からの4次元距離(0=領域内)
      "delta_e_to_lip": 10.52,            // 参考:唇との距離
      "catalog_pc_tags": ["ブルベ夏","イエベ春"]  // サイト編集者のタグ(参考)
    },
    ...
  ]
}
```

**重要**: `catalog_pc_tags` はサイト編集者が付けたタグ。**推奨ロジックには使ってない**(答え合わせ用に同梱)。

**フィルタ組み合わせ**:
```bash
# 色相 350-30°(赤系) かつ 明度50以上 のグロスだけ
curl -X POST https://tamable-fibrous-lipstick-api.hf.space/recommend \
  -H "Content-Type: application/json" \
  -d '{"lip_lab":{"L":62,"a":22,"b":12},
       "line_category":"gloss","hue_min":350,"hue_max":30,"L_min":50,"top_n":3}'
```

---

## POST `/evaluate` ★

**用途**: PC連携の**妥当性メトリクス**。指定唇色 + 想定PCで `/recommend` を内部実行し、TOP-N の `catalog_pc_tags` に `expected_pc` または `"イエベ・ブルベ問わず"` がどれだけ含まれるかを測る。

「論文ベース予測 vs サイト編集者の人手タグ」**一致率**で評価。MVP合格ライン = 0.70。

**入力**:
```json
{
  "lip_lab": {"L":62,"a":22,"b":12},
  "expected_pc": "イエベ春",      // 必須
  "t": 1.0,
  "top_n": 10
}
```

**curl 例**:
```bash
curl -X POST https://tamable-fibrous-lipstick-api.hf.space/evaluate \
  -H "Content-Type: application/json" \
  -d '{"lip_lab":{"L":62,"a":22,"b":12},"expected_pc":"ブルベ夏","top_n":10}'
```

**レスポンス例**:
```json
{
  "expected_pc": "ブルベ夏",
  "top_n": 10,                       // 実評価できた件数(タグ付きで埋めたTOP_n)
  "matched_count": 10,
  "match_rate": 1.0,
  "interpretation": "good",          // "good"(>=0.7) | "acceptable"(>=0.5) | "poor"
  "n_empty_tag_skipped": 0,          // 埋めるために飛ばした空タグ件数
  "details": [
    {"id":"...","name":"...","line_category":"...",
     "applied_lab":{...},"applied_chroma":31.22,"pc_score":0.0,
     "catalog_pc_tags":["ブルベ夏","イエベ春"],
     "match": true},
    ...
  ]
}
```

**現状の妥当性**(清濁 C* 軸 + 空タグ バックフィル版・ローカル実測):
| 唇プリセット | イエベ春 | イエベ秋 | ブルベ夏 | ブルベ冬 |
|---|---|---|---|---|
| pale_pink | 0.90 | 0.70 | 0.90 | 0.80 |
| healthy_pink | 0.90 | 0.60 | 0.90 | 0.80 |
| reddish | 0.80 | 0.70 | 0.90 | 0.80 |
| beige | 0.80 | 0.70 | 0.90 | 0.80 |
| dark | 0.70 | 0.80 | 1.00 | 0.80 |
| **全平均** | | | | **0.810 (good)** |

**20セル中19セルが good (≥0.7)**。イエベ秋も平均 0.71 で good 帯に到達。
空タグ商品は分母から除外(`n_empty_tag_skipped` で透明性確保)。

---

## バッチ評価スクリプト `evaluate_all.py`

5唇プリセット × 4PC の20組合せを一発で評価する CLI。

```bash
# ローカルで API テストクライアント経由(自動)
.venv/bin/python evaluate_all.py

# 公開API を叩く
.venv/bin/python evaluate_all.py --api https://tamable-fibrous-lipstick-api.hf.space

# top_n を変える
.venv/bin/python evaluate_all.py --top-n 20
```

出力(末尾):
```
全平均 一致率 = 0.750  (good (>=0.7))
```

---

## Streamlit UI(ローカル)

ブラウザでビジュアルに試したい場合:

```bash
cd ~/Desktop/fibrous-lipstick-api
.venv/bin/pip install -r requirements-ui.txt   # 初回のみ
.venv/bin/streamlit run ui_app.py
```

→ ブラウザで <http://localhost:8501> を開く。
- 顔写真をアップロード or 既定モデル選択
- 塗り重ね・PC・カテゴリで絞り込み
- TOP-N が顔写真に塗布合成された状態で並ぶ
- 「🔍 拡大」で Before/After 比較モーダル

詳細: [DESIGN.md §6](DESIGN.md)。

---

## 共通の注意事項

- すべて **POST** メソッド、`Content-Type: application/json`
- **CORS は全許可**(MVP)、ブラウザから直叩き可
- レート制限なし(HF Spaces CPU basic、長時間ジョブだと timeout 可能性)
- バッチ系のサイズ上限 = **50件**
- 画像取得は **10MB 上限**、http(s) のみ、SSRF 対策で内部IP拒否
- 入力JSON のフィールド型違反は **422 Unprocessable Entity** で返る(Swagger UI が分かりやすく表示)
- `line_category` / `pc_season` の許容値は固定文字列のみ。それ以外は 422。

---

## トラブルシューティング

| 症状 | 原因と対処 |
|---|---|
| 422 で `pc_season` 蹴られる | 値が `イエベ春/イエベ秋/ブルベ夏/ブルベ冬` のいずれかか確認(全角) |
| 422 で `line_category` 蹴られる | `tint/matte/gloss/velvet/other` のいずれか |
| 画像 URL で 400 | http(s) 直リンクか? HTMLページではダメ |
| 画像 URL で 413 | 10MB 超過 |
| /recommend で空配列 | フィルタが厳しすぎる可能性。`hue_min/max`, `L_min/max` を緩める |
| /evaluate で poor | カタログタグ未付与の商品多めの可能性。`details` を確認 |
| HF Space 起動が遅い | コールドスタートで初回 30秒程度かかることあり |

---

# v1.3 個人化学習層 API (`/v13/*`)

> 設計書 v1.3 に基づく個人化推薦の 4 エンドポイント。詳細仕様は
> [KAWANO_INTERFACE.md](KAWANO_INTERFACE.md) / [KAWANO_HANDOFF.md](KAWANO_HANDOFF.md) も参照。

## 0. v1.3 API の流れ

```
[初回診断]
  ① GET  /v13/pair_compare/init     → 10 ペア取得
  ② POST /v13/pair_compare/apply    → 4 θ の事前分布
  caller は ① の選択を ② に送る、返ってきた θ で UserState を組み立てて保存

[AR 試着ループ]
  ③ POST /v13/recommend             → TOP-N(effective_Lab を AR で表示)
  ④ POST /v13/update_user           → 観測ログでベイズ更新
  ③ → ④ → ③ → ④ を繰り返す
```

---

## v1.3-① GET /v13/pair_compare/init

10 ペア(色5 + 世界観5)を取得。初回診断で UI に表示する。

```bash
curl https://tamable-fibrous-lipstick-api.hf.space/v13/pair_compare/init | jq
```

レスポンス例(抜粋):
```json
{
  "pairs": [
    {
      "pair_id": "color_01_bright_vs_deep",
      "pair_type": "color",
      "left": {
        "product_id": "rmd_glasting_water_05",
        "name": "ローズ スプラッシュ",
        "image_url": "https://cloudflare.lipscosme.com/image/...",
        "lab": {"L": 38.7, "a": 38.4, "b": 10.1},
        "x20": [0.86, 0.79, 0.50, ...]
      },
      "right": { "product_id": "rmd_blur_fudge_03", ... }
    }
  ]
}
```

---

## v1.3-② POST /v13/pair_compare/apply

10 ペアの選択結果から 4 θ の事前分布を構築する。

```bash
curl -X POST https://tamable-fibrous-lipstick-api.hf.space/v13/pair_compare/apply \
  -H "Content-Type: application/json" \
  -d '{
    "choices": [
      {"pair_id": "color_01_bright_vs_deep", "chose": "left"},
      {"pair_id": "color_02_warm_vs_cool",   "chose": "right"},
      {"pair_id": "color_03_vivid_vs_nude",  "chose": "left"},
      {"pair_id": "color_04_pink_vs_coral",  "chose": "left"},
      {"pair_id": "color_05_rose_vs_red",    "chose": "left"},
      {"pair_id": "wv_06_girly_vs_mature",   "chose": "left"},
      {"pair_id": "wv_07_korean_vs_konare",  "chose": "left"},
      {"pair_id": "wv_08_juicy_vs_matte",    "chose": "left"},
      {"pair_id": "wv_09_sweet_vs_classy",   "chose": "left"},
      {"pair_id": "wv_10_daily_vs_statement","chose": "left"}
    ],
    "pc_season": "ブルベ夏",
    "warmness": -8.0
  }' | jq
```

レスポンス:
```json
{
  "theta_color":     { "mu": {"L":49.8,"a":46.0,"b":24.3},
                       "var":{"L":0.16,"a":0.16,"b":0.16} },
  "theta_pref":      { "mu": [0.0, 0.8, ..., -0.86],
                       "var": [1.0, 0.96, ..., 1.0] },
  "theta_explore":   { "mu": 0.5, "var": 0.25 },
  "theta_thickness": { "mu": 0.5, "var": 0.10 },
  "n_color_obs": 5,
  "n_worldview_obs": 5
}
```

→ caller はこの 4 つに `user_id` / `lip_lab` / `pc_season` を足して UserState を組む。

---

## v1.3-③ POST /v13/recommend

UserState 1つで TOP-N。`km_table` は API 内部で生成するので caller は持つ必要なし。

```bash
curl -X POST https://tamable-fibrous-lipstick-api.hf.space/v13/recommend \
  -H "Content-Type: application/json" \
  -d '{
    "user": {
      "user_id": "mina_001",
      "lip_lab": {"L":62, "a":22, "b":12},
      "pc_season": "ブルベ夏",
      "theta_color": {
        "mu":  {"L":49.8, "a":46.0, "b":24.3},
        "var": {"L":0.16, "a":0.16, "b":0.16}
      },
      "theta_pref": {
        "mu":  [0.0, 0.8, 0.0, 0.0, -0.86, 0.0, 0.0, 0.0, -0.86, 0.0,
                0.0, 0.0, 0.0, 0.0, 0.0, 0.66, 0.05, 0.10, 0.20, 0.0],
        "var": [1.0, 0.96, 1.0, 1.0, 0.96, 1.0, 1.0, 1.0, 0.96, 1.0,
                1.0, 1.0, 1.0, 1.0, 1.0, 0.95, 1.0, 1.0, 1.0, 1.0]
      },
      "theta_explore":   {"mu": 0.5, "var": 0.25},
      "theta_thickness": {"mu": 0.5, "var": 0.10}
    },
    "top_n": 5
  }' | jq
```

レスポンス(抜粋):
```json
{
  "user_id": "mina_001",
  "mu_thickness": 0.5,
  "beta_used": 2.5,
  "results": [
    {
      "product_id": "rmd_glasting_water_01",
      "name": "コーラル ミスト",
      "line_category": "gloss",
      "image_url": "https://cloudflare.lipscosme.com/image/...",
      "effective_lab": {"L": 48.1, "a": 45.8, "b": 25.0},
      "delta_e_to_color": 1.71,
      "pref_match": 0.0,
      "f_score": -5.13,
      "familiarity": 1.10,
      "r_final": -7.89,
      "catalog_pc_tags": ["イエベ秋", "ブルベ夏"]
    }
  ]
}
```

★ `results[*].effective_lab` を AR で唇に合成して表示。

### オプション
- `top_n`: 1〜50(既定 5)
- `line_category`: tint / gloss / matte / velvet / other で絞り込み
- `alpha`: 色差感度(既定 3.0)
- `beta_max`: セレンディピティ最大係数(既定 5.0)
- `familiarity_weights`: [w1, w2, w3](既定 [4, 3, 2])

### `reasons`(推薦理由・A2)

各 `results[*]` に推薦理由の構造化データ `reasons` が付く(**文章化はフロントの責務**。
API は数値・ラベル・来歴のみ返す)。読まない既存クライアントは無視できる(後方互換)。

```json
"reasons": {
  "color_percentile": 0.92,   // 色の似合い順位率(1=プール内で最も似合う)
  "pref_percentile": 0.78,    // 好み一致の順位率(1=最も好みに一致)
  "scene_match": false,       // シーン選択軸への合致(A1 配線後に有効。現状 false 固定)
  "top_axes": [               // 好み起点:正寄与かつ確信のある軸(最大2)
    {"axis": "sheer", "label": "透け感", "contribution": 0.41, "evidence": []}
  ],
  "product_traits": [         // 商品起点:値が突出した軸(is_系除く・top_axes と重複除く、最大2)
    {"axis": "blur", "label": "ふんわり感"}
  ]
}
```

- **percentile はパーセンタイル方式**(候補プール内の順位率・絶対閾値なし=`is_serendipity` と
  同じ自己校正の哲学)。スコア計算(`r_final`)には一切影響しない派生指標。
- **top_axes** は `μ_pref[k]·x20[k] > 0` かつ `theta_pref.var[k] ≤ RHO·TAU2_PREF`(RHO=0.5、
  「確信のある軸」)のみ。is_系バイナリ軸とその連続プロキシ(is_gloss↔glossy 等)が拮抗する
  場合は連続軸を優先表示(表示規則のみ・スコア無影響)。※ RHO はフロント発話トリガーと同値共有。
- **evidence**(その軸の事後分散を最も縮めた観測の pair_id・最大2件)は、ペア比較適用時に
  `UserState.pref_evidence`(軸名→pair_id 列)として構築され、reasons がそれを充填する。
  精度寄与 `x²/σ²` の大きいペアを記録(更新式は不変)。`pref_evidence` が無ければ空配列。
- 順位の同点は商品ID昇順で安定化済み(同一入力 → 同一 TOP-N=決定性)。

### `candidate_count` / `catalog_size`(絞り込みカウンタ・A2-fix)

レスポンス直下に**残候補数**を返す(診断UIの「◯色 → … → 5色」表示用)。

- `catalog_size`: 候補プール(`km_table`)の総数。「◯色から」の起点。
- `candidate_count`: **competitive set 方式**=現時点の事後で全候補をスコアリングし、
  「TOP-N 最下位スコアから `margin·(1位−N位)` 以内にいる候補の数」(margin=0.15)。
  事後が尖るほどスコアが分離して**減る**(絞り込みの進行)。退化(全同値)時は TOP-N 件数。
  **表示専用の派生指標で TOP-N 選定・スコアには不使用**。
  ※ 当初設計の「R_final>中央値の個数」は中央値分割が常に≈N/2で減らないため破棄・置換。
  /v14(逐次ペア比較)の start / next でも同じ指標を返す予定(A3)。

---

## v1.3-④ POST /v13/update_user

AR の「いいね/微妙」観測でベイズ更新。返り値の UserState で caller の保存を上書き。

```bash
curl -X POST https://tamable-fibrous-lipstick-api.hf.space/v13/update_user \
  -H "Content-Type: application/json" \
  -d '{
    "user": { /* 現在の UserState */ },
    "observations": [{
      "source": "ar_view_like",
      "product_id": "rmd_blur_fudge_03",
      "observed_lab": {"L": 46.4, "a": 42.4, "b": 21.3},
      "thickness": 0.27,
      "y": 1.0,
      "viewed_seconds": 8.5
    }]
  }' | jq
```

### Observation の source(設計書 §7.1)
| source | σ²_obs | 主に動く θ |
|---|---|---|
| `pair_color` | 0.8 | θ_color + θ_pref |
| `pair_worldview` | 0.8 | θ_pref |
| `dialog` | 1.5 | θ_pref |
| `behavior` | 1.0 | θ_color + θ_pref |
| `ar_view_like` | 1.0 | 全 θ(thickness 含む) |
| `ar_view_dislike` | 1.0 | θ_color(y=-1), θ_explore |

### Observation のフィールド
- `source`: 上表のいずれか(必須)
- `product_id`: 観測対象商品(任意)
- `observed_lab`: θ_color 更新用。AR なら effective_lab をそのまま入れる
- `observed_x20`: θ_pref 更新用。ペア/対話で使う
- `thickness`: θ_thickness 更新用(AR like のみ)。0.0〜1.0
- `is_serendipity`: セレンディピティ提示への反応(θ_explore 更新トリガ)
- `y`: like=+1, dislike=-1
- `viewed_seconds`: 滞在時間(Phase 2 拡張で観測重み付けに利用)

レスポンス:
```json
{
  "user": { /* 更新後の UserState 丸ごと */ },
  "n_applied": {
    "theta_color": 1, "theta_pref": 0,
    "theta_thickness": 1, "theta_explore": 0
  }
}
```

---

## v14 追加エンドポイント(2026-06 / `feat/v14`)

### POST `/v14/pair_compare/start` — 逐次ペア比較の開始

シーン+PC 事前で初期化し、**最大 EIG の first_pair** を返す。各ペアの left/right に
`effective_lab`(唇に塗った想定 Lab)が付くのが v13 との差。セッションはクライアント往復方式。

```bash
curl -sX POST https://tamable-fibrous-lipstick-api.hf.space/v14/pair_compare/start \
  -H 'Content-Type: application/json' \
  -d '{"lip_lab":{"L":62,"a":22,"b":12},"scenes":["school","friends"],"pc_season":"ブルベ夏"}'
# → {session, n_pairs_total:8, first_pair:{pair_id,pair_type,left/right:{...,effective_lab}}, candidate_count, catalog_size}
```

### POST `/v14/pair_compare/next` — 選択 → 更新 → 次のペア

選択を観測としてベイズ更新し、残問あれば次の最大 EIG ペアを返す。**固定 N=8 問で `done:true`**。

```bash
curl -sX POST .../v14/pair_compare/next \
  -d '{"session":<前レスポンスの session>,"pair_id":"color_01_bright_vs_deep","chose":"left"}'
# → {session, done, next_pair|null, theta_snapshot:{pref_mu,pref_var,top_shrunk_axis}, candidate_count}
```
- `theta_snapshot`: 中間実況用(コンシェルジュが「透け感が好きみたいだね」)。同一ペアは二度出さない。

### GET `/v13/popular` — みんなの定番(ユーザー非依存)

```bash
# 基本(ランキングのみ)
curl -s 'https://tamable-fibrous-lipstick-api.hf.space/v13/popular?top_n=5'
# → {catalog_size, method, results:[{product_id,name,line_category,image_url,lab,representativeness,effective_lab:null}]}

# 本人の唇に重ねるプレビュー用: lip_lab(+塗り厚 mu_thickness)を渡すと各定番に effective_lab が付く
curl -s '.../v13/popular?top_n=5&lip_l=62&lip_a=22&lip_b=12&mu_thickness=0.5'
# → results[*].effective_lab:{L,a,b}(K-M 塗布後 Lab)。★これを唇に合成すれば定番も顔プレビューできる
```
- MVP は売上/レビューが無いため **カタログ代表性(中央 Lab=median centroid への近さ)で代用**(本番は売上に差替)。決定的。
- **`lip_l/lip_a/lip_b`(任意・3つ揃った時のみ有効)+ `mu_thickness`(既定 0.5)**: 渡すと TOP-N 各定番に
  `km.compute_applied_lab` の **`effective_lab`(本人の唇に塗った塗布後 Lab)** を付与。未指定なら `effective_lab:null`。
  **ランキング(順序)はユーザー非依存で不変**(effective_lab は付加情報のみで並べ替えに不使用)。

### `Observation.extras`(F4-fix・任意)

`/v13/update_user` の観測に `extras:{action,kept,decided}` 等を付与可。**ベイズ更新には未使用**=Phase 2 のデータ収集用。
`source_pair_id` も観測の来歴(reasons の evidence)用に追加済み。

### POST `/v14/concierge_speech` — コンシェルジュ(妖精)の発話生成

発話生成をバックエンドに一本化(RN/Next の二重実装回避・6/29 方針)。既存の reasons(A2)/
theta_snapshot(A3・session 内)を**日本語文面に変換するだけ**。フロントは返った文面を吹き出しに出すだけ。

```bash
# explore(ペア比較中の中間実況): session をそのまま渡す(spoken_axes=実況済み軸の状態が相乗り)
curl -sX POST .../v14/concierge_speech \
  -d '{"phase":"explore","session":<pair_compare/next が返した session>,"step":"pair_compare"}'
# → {speech:{type:"axis_realization"|"step_intro", text}, session:<spoken_axes 追記版・次ターンへ持ち回る>}

# recommend(推薦理由の口語化)
curl -sX POST .../v14/concierge_speech \
  -d '{"phase":"recommend","reasons":<recommend の results[].reasons>,"is_serendipity":false}'
# → {speech:{type:"reason_hybrid"|"reason_user"|"reason_product"|"serendipity_offer"|"step_intro", text}}

# decide(確認/終端)
curl -sX POST .../v14/concierge_speech -d '{"phase":"decide","is_final":true}'
# → {speech:{type:"decision_final", text}}
```

- **状態管理**: 中間実況の重複防止・予算(最大3回)は `session.spoken_axes` に相乗り(caller は session を往復するだけ・中身を知らなくてよい)。spoken_axes が要るのは explore のみ。
- **軸実況は μ_pref>0(好意方向)のみ**・確信(var ≤ RHO·TAU2)した軸を1つ。否定方向は黙る(Phase 2)。
- 文面は **Haruki 作成の確定版**(上品なホテルのコンシェルジュ風・ですます・絵文字 ✨👍👀・対象 Mina)。名前は `{name}` を「名前+さん」に解決、無ければ「あなた」(現状 name フィールド無=実質「あなた」)。ロジック・文面は `conciergeScript.ts` と同一(TS≡API 全枠パリティテスト有)。

#### 【将来拡張・未実装】双方向チャット相談機能 `POST /v14/concierge_chat`(Phase 2+)

現行 `/v14/concierge_speech` は **一方通行・テンプレ**(状態 → 定型文、LLM 不使用)。将来ユーザーが自由入力で
相談できる **双方向チャット**(例:「学校でもバレない?」「これ落ちにくい?」にその場で答える)を足す場合は、
**別エンドポイント `/v14/concierge_chat` を新設**し、speech 系統とは **別系統で共存**させる想定
(speech=導線上の決め打ち発話 / chat=自由対話)。返答種別は将来 `ConciergeSpeechType` に `chat_reply` を足す想定
(models_v13.py にコメントで予約済み)。**前提**: LLM 必須 / フロントにチャット UI 必須 / 「LLM 不使用」の MTG 合意の
見直しが必要 → 詳細は [LOG.md](LOG.md) 「将来像」。※現時点は**未実装・拡張余地の明示のみ**。

> v14 の全フィールド定義は [KAWANO_INTERFACE.md](KAWANO_INTERFACE.md) §4.6/§4.7、最新 OpenAPI は `openapi.json`(CI 再生成済み)。

---

## v1.3 トラブルシューティング

| 症状 | 原因 / 対処 |
|---|---|
| 422 で `theta_pref` 蹴られる | `mu` と `var` は **20要素必須** |
| 422 で `theta_color.var` 蹴られる | `var` のすべての成分は **>0**(0 不可) |
| 422 で `observations` 空 | 観測リストは1件以上必須(最大100件) |
| `theta_thickness` が動かない | source が `ar_view_like` で、`thickness` フィールドがあるか確認 |
| TOP-1 が直感とズレる | x_20 軸が荒い(Kawanoさんと詰める前提) |
| `image_url` が null | products.csv にURL未登録の商品。CATALOG_BY_ID で確認 |

---

最後にもう一度: **<https://tamable-fibrous-lipstick-api.hf.space/docs>** が一番手軽。
ブラウザで開いて各エンドポイントの「Try it out」を押せば、上の curl 例を入れる手間なく試せる。
