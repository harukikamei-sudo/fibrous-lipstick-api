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

最後にもう一度: **<https://tamable-fibrous-lipstick-api.hf.space/docs>** が一番手軽。
ブラウザで開いて各エンドポイントの「Try it out」を押せば、上の curl 例を入れる手間なく試せる。
