# KAWANO_INTERFACE.md — ハルキ側 API の叩き方(提案・暫定)

> **このドキュメントは「決定事項」ではなく「叩き台」です。**
> Kawano 側の事情(SDK・状態保持・通信モデル)に合わせて、ペイロード形式・
> 通信方式・状態の置き場所はすべて差し替え可能。気になる点は遠慮なく言ってください。
>
> 最終更新: 2026-05-29 / 設計書 v1.3 準拠 / Opus 4.7 実装

---

## 0. ハルキ API の役割(ステートレス計算サーバー)

| 責務 | 担当 |
|---|---|
| 唇 Lab 取得 / PC 判定 / AR 表示 / 質感合成 | **Kawano** |
| K-M 物理計算 / ベイズ更新 / 推奨スコア計算 | **ハルキ(この API)** |
| ユーザー状態(`UserState`)の永続化 | **Kawano が選ぶ**(GAS+Spreadsheet / Firebase / 自前 BE / 何でも可) |

ハルキ API は **state を持ちません**。リクエスト毎に caller(Kawano か中継 BE)が
`UserState` を丸ごと送る → 計算結果と更新後 state を返す → caller が保存する、
という素直な流れにしてあります。

---

## 1. 全体フロー(MVP)

```
[初回診断]
1. Kawano が唇撮影 → 唇 Lab を抽出
2. Kawano が肌撮影 → PC 判定(イエベ春/秋/ブルベ夏/冬)
3. GET  /v13/pair_compare/init       → 10 ペア取得
4. ユーザーが 10 ペアを選択(強制 2 択)
5. POST /v13/pair_compare/apply      → 4 つの事前分布
6. caller が UserState を組み立てて保存

[AR 試着ループ]
7. POST /v13/recommend               → TOP-N(上位3〜5件を AR で見せる)
8. Kawano が AR スライダー UI を提供(0.0 〜 1.0 連続)
9. ユーザーが「いいね/微妙」を押す
10. POST /v13/update_user            → 観測適用 → 新 UserState
11. caller が UserState を上書き保存
12. → 7. に戻る
```

---

## 2. エンドポイント一覧

| Method | Path | 用途 |
|---|---|---|
| GET  | `/v13/pair_compare/init`  | 10 ペアを取得(初回診断) |
| POST | `/v13/pair_compare/apply` | ペア選択 → 事前分布構築 |
| POST | `/v13/update_user`        | 観測ログ → 更新後 UserState |
| POST | `/v13/recommend`          | UserState → TOP-N 推薦 |

ベース URL(本番):
```
https://tamable-fibrous-lipstick-api.hf.space
```

Swagger UI(リアルタイム仕様参照):
```
https://tamable-fibrous-lipstick-api.hf.space/docs
```

---

## 3. `UserState` の中身

すべての θ パラメータは「ガウス分布 N(μ, σ²)」として持ち回ります。

```jsonc
{
  "user_id": "mina_001",
  "lip_lab": { "L": 62.0, "a": 22.0, "b": 12.0 },
  "pc_season": "ブルベ夏",   // "イエベ春" | "ブルベ夏" | "イエベ秋" | "ブルベ冬" | null

  "theta_color": {
    "mu":  { "L": 49.8, "a": 46.0, "b": 24.3 },
    "var": { "L":  0.16, "a":  0.16, "b":  0.16 }
  },
  "theta_pref": {
    "mu":  [0.0, 0.8, ..., -0.86],  // 20 要素
    "var": [1.0, 0.96, ..., 1.0]    // 20 要素
  },
  "theta_explore":   { "mu": 0.5, "var": 0.25 },
  "theta_thickness": { "mu": 0.5, "var": 0.10 }
}
```

caller は **これを丸ごと自分のストレージに保存**して、リクエスト毎に送り返してください。
返り値で新 `UserState` が返るので、それで上書き。

---

## 4. 各エンドポイント詳細

### 4.1 `GET /v13/pair_compare/init`

レスポンス:
```jsonc
{
  "pairs": [
    {
      "pair_id": "color_01_bright_vs_deep",
      "pair_type": "color",           // "color" | "worldview"
      "left":  { "product_id": "rmd_glasting_water_05",
                 "name": "ローズ スプラッシュ",
                 "image_url": "https://...",
                 "lab":  { "L": 38.7, "a": 38.4, "b": 10.1 },
                 "x20":  [0.86, 0.79, ...] },
      "right": { "product_id": "rmd_blur_fudge_03",
                 "name": "ムスキー(MUSKY)", ... }
    },
    ...  // 計 10 ペア
  ]
}
```

**🤝 確認したいこと:** ペアの中身は俺が暫定で組んだだけ。Kawano 側で見せる
順番・本数・画像の出し方など合わせ込みたいので、希望あれば言ってください。

### 4.2 `POST /v13/pair_compare/apply`

リクエスト:
```jsonc
{
  "choices": [
    { "pair_id": "color_01_bright_vs_deep", "chose": "left"  },
    { "pair_id": "color_02_warm_vs_cool",   "chose": "right" },
    ...
  ],
  "pc_season": "ブルベ夏",   // PC が確定していれば
  "warmness": -8.0           // PC 判定の warmness 値(任意。境界判定の σ² に効く)
}
```

レスポンス: 4 つのガウス分布(`UserState` のフィールドそのまま)。
caller はこの 4 つに `user_id` / `lip_lab` / `pc_season` を足して `UserState` を完成させる。

```jsonc
{
  "theta_color":     { "mu": {...}, "var": {...} },
  "theta_pref":      { "mu": [...], "var": [...] },
  "theta_explore":   { "mu": 0.5, "var": 0.25 },
  "theta_thickness": { "mu": 0.5, "var": 0.10 },
  "n_color_obs": 5,
  "n_worldview_obs": 5
}
```

### 4.3 `POST /v13/update_user`

リクエスト:
```jsonc
{
  "user": { /* 現在の UserState 丸ごと */ },
  "observations": [
    {
      "source": "ar_view_like",          // 下記の表
      "product_id": "rmd_blur_fudge_03",
      "observed_lab": { "L": 46, "a": 42, "b": 21 },  // K-M で計算した applied_Lab
      "thickness": 0.27,                 // AR スライダー値(0.0〜1.0)
      "y": 1.0,                          // like=+1, dislike=-1
      "is_serendipity": false,           // セレンディピティ提示への反応か
      "viewed_seconds": 8.5,             // 任意
      "timestamp": "2026-05-29T11:00:00Z" // 任意
    }
  ]
}
```

`source` の取りうる値(設計書 §7.1):

| source | 主に動く θ | σ²(観測ノイズ) |
|---|---|---|
| `pair_color` | θ_color, θ_pref | 0.8 |
| `pair_worldview` | θ_pref | 0.8 |
| `dialog` | θ_pref | 1.5 |
| `behavior` | θ_color, θ_pref | 1.0 |
| `ar_view_like` | 全 θ | 1.0 |
| `ar_view_dislike` | θ_color(y=-1), θ_explore | 1.0 |

レスポンス:
```jsonc
{
  "user": { /* 更新後の UserState 丸ごと */ },
  "n_applied": {
    "theta_color": 10, "theta_pref": 0,
    "theta_thickness": 10, "theta_explore": 0
  }
}
```

### 4.4 `POST /v13/recommend`

リクエスト(最小):
```jsonc
{ "user": { /* UserState */ }, "top_n": 5 }
```

リクエスト(任意フィルタ):
```jsonc
{
  "user": { /* ... */ },
  "top_n": 5,
  "line_category": "tint",        // tint / gloss / matte / velvet / other
  "alpha": 3.0,                   // 色差感度
  "beta_max": 5.0,                // セレンディピティ最大係数
  "familiarity_weights": [4, 3, 2]
}
```

レスポンス:
```jsonc
{
  "user_id": "mina_001",
  "mu_thickness": 0.881,       // 現在の塗り厚好み中心
  "beta_used": 2.50,            // explore=0.5 → β=2.5
  "results": [
    {
      "product_id": "rmd_blur_fudge_02",
      "name": "...",
      "line_category": "matte",
      "effective_lab": { "L": 46.4, "a": 42.4, "b": 21.3 },  // ★AR に渡す Lab
      "delta_e_to_color": 2.91,
      "pref_match": 0.0,
      "f_score": -8.73,
      "familiarity": 0.080,
      "r_final": -8.93,
      "catalog_pc_tags": ["イエベ秋","ブルベ夏"]
    },
    ...
  ]
}
```

**★ AR で表示する Lab = `effective_lab`** を使ってください。
これは「ユーザーの μ_thickness(現在の塗り厚好み)で K-M 計算した塗布後 Lab」。
ユーザーが AR スライダーを動かしたら、その値を `thickness` として観測ログに送ると
学習が進んで TOP-N の `effective_lab` も追従して動きます。

---

## 5. 議論したいポイント

設計書 v1.3 を素直に実装しているが、Kawano 側との接続点で詰めたい:

1. **データの渡し方**
   - Lab を `{L,a,b}` dict にしているが、`[L,a,b]` 配列の方が楽なら変更可
   - `UserState` 丸ごと往復は重いか?(20次元 vec × 2 + Lab × 2 + スカラー × 4 ≈ 50 数値)
   - caller 側が状態保持しない選択肢が欲しい場合は、ハルキ側で SQLite を持つ拡張も可

2. **通信モデル**
   - 現状は同期 REST。Kawano が GAS なら同期で十分
   - もし Kawano AR から直接叩く構成なら CORS は `*` 解放済み

3. **ペア比較 10 問の中身**
   - 俺が仮で組んだだけ。商品の組み合わせ・提示順は Kawano 側の UX に合わせたい
   - `_PAIR_SPECS`(`pair_compare.py`)を差し替えるだけで反映できる

4. **20 次元 pref ベクトル `x_20` の軸定義**
   - 仮定義: pigmentation / vivid / transparency / glossiness / matte_finish /
     velvet_finish / moisture / durability / blur_effect / juicy_feel /
     cool_tone / warm_tone / light_color / deep_color / everyday_use /
     girly / konare / sweetness / korean / mature
   - Kawano が AR で扱いたい「印象タグ」と整合を取りたい

5. **観測ログのスキーマ**
   - 今は `source` enum で分岐。`extras: {}` フィールドを追加して将来拡張できるようにも可
   - `viewed_seconds` を観測重みに反映するか(設計書 §12.6, Phase 2 拡張)

6. **K-M テーブルの事前計算**
   - 現状 `/v13/recommend` 内部で毎回 145 × 21 を計算(MVP は十分高速)
   - 規模が増えたら caller 側でテーブルキャッシュ→`km_table` 引数で渡す方式に切り替え可

7. **ユーザー識別 / 認証**
   - 現状 `user_id` は caller が任意で発行する文字列。ハルキ側に DB なし
   - Kawano 側でアカウント機構を持つか、ハルキ側に最小限の users テーブル要るかは要相談

---

## 6. ハルキ側の実装ファイル(参考)

| ファイル | 役割 |
|---|---|
| `models_v13.py` | 全エンドポイントの pydantic 型 |
| `bayesian.py` | 4 θ のガウス更新(§7) |
| `recommend_v2.py` | effective_Lab 補間 + Part IV/VI 統合スコア |
| `pair_compare.py` | 10 ペア仮データ + 事前分布構築(§3+§6) |
| `catalog_x20.py` | x_20 列の派生計算と CSV 付与 |
| `app.py` | エンドポイント実装 |
| `test_bayesian.py` | ベイズ更新の性質テスト |
| `test_recommend_v2.py` | 統合スコアのテスト |
| `test_v13_flow.py` | 全フロー疎通テスト |

ローカル実行:
```bash
cd ~/Desktop/fibrous-lipstick-api
.venv/bin/python test_v13_flow.py   # 統合疎通
.venv/bin/uvicorn app:app --reload  # ローカル API 起動 → http://localhost:8000/docs
```
