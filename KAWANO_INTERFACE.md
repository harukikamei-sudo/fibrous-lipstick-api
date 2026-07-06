# KAWANO_INTERFACE.md — lip API 側 API の叩き方(提案・暫定)

> **このドキュメントは「決定事項」ではなく「叩き台」です。**
> Kawanoさん 側の事情(SDK・状態保持・通信モデル)に合わせて、ペイロード形式・
> 通信方式・状態の置き場所はすべて差し替え可能。気になる点は遠慮なく言ってください。
>
> 最終更新: 2026-07-06 / 設計書 v1.3 + v14(逐次ペア・reasons・concierge・popular effective_lab)準拠

---

## 0. lip API の役割(ステートレス計算サーバー)

| 責務 | 担当 |
|---|---|
| 唇 Lab 取得 / PC 判定 / AR 表示 / 質感合成 | **Kawanoさん** |
| K-M 物理計算 / ベイズ更新 / 推奨スコア計算 | **lip API(この API)** |
| ユーザー状態(`UserState`)の永続化 | **Kawanoさん が選ぶ**(GAS+Spreadsheet / Firebase / 自前 BE / 何でも可) |

lip API は **state を持ちません**。リクエスト毎に caller(Kawanoさん か中継 BE)が
`UserState` を丸ごと送る → 計算結果と更新後 state を返す → caller が保存する、
という素直な流れにしてあります。

---

## 1. 全体フロー(MVP)

```
[初回診断]
1. Kawanoさん が唇撮影 → 唇 Lab を抽出
2. Kawanoさん が肌撮影 → PC 判定(イエベ春/秋/ブルベ夏/冬)
3. GET  /v13/pair_compare/init       → 10 ペア取得
4. ユーザーが 10 ペアを選択(強制 2 択)
5. POST /v13/pair_compare/apply      → 4 つの事前分布
6. caller が UserState を組み立てて保存

[AR 試着ループ]
7. POST /v13/recommend               → TOP-N(上位3〜5件を AR で見せる)
8. Kawanoさん が AR スライダー UI を提供(0.0 〜 1.0 連続)
9. ユーザーが「いいね/微妙」を押す
10. POST /v13/update_user            → 観測適用 → 新 UserState
11. caller が UserState を上書き保存
12. → 7. に戻る
```

---

## 2. エンドポイント一覧

| Method | Path | 用途 |
|---|---|---|
| POST | `/v14/pair_compare/start` | **【現行フロント採用】** 逐次ペア比較の開始(最大EIGペア + effective_lab)。§4.6 |
| POST | `/v14/pair_compare/next`  | **【現行フロント採用】** 選択→更新→次の最大EIGペア(固定 N=8 問)。§4.6 |
| POST | `/v14/concierge_speech`   | コンシェルジュ発話生成(explore/recommend/decide)。§4.8 |
| GET  | `/v13/popular`            | ユーザー非依存「みんなの定番」(代表性ランキング + 任意 effective_lab)。§4.7 |
| POST | `/v13/recommend`          | UserState → TOP-N 推薦(`rerank:true` で EIG 能動学習) |
| POST | `/v13/update_user`        | 観測ログ → 更新後 UserState |
| GET  | `/v13/pair_compare/init`  | 【旧・一括】10 ペアを取得(v14 逐次に置換済。API は後方互換で残置) |
| POST | `/v13/pair_compare/apply` | 【旧・一括】ペア選択 → 事前分布構築(同上) |

> **現行フロント(color-capture `feat/v14-recommend`)は v14 逐次ペア(`/v14/pair_compare/{start,next}`)を採用**。
> v13 の一括 `init`/`apply` は API に残っているが未使用。詳細は §4.6。

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

**🤝 確認したいこと:** ペアの中身は俺が暫定で組んだだけ。Kawanoさん 側で見せる
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
      "image_url": "https://cloudflare.lipscosme.com/image/...",  // ★商品サムネ
      "effective_lab": { "L": 46.4, "a": 42.4, "b": 21.3 },  // ★AR に渡す Lab
      "delta_e_to_color": 2.91,
      "pref_match": 0.0,
      "f_score": -8.73,
      "familiarity": 0.080,
      "r_final": -8.93,
      "catalog_pc_tags": ["イエベ秋","ブルベ夏"],
      "is_serendipity": true
    },
    ...
  ]
}
```

**★ AR で表示する Lab = `effective_lab`** を使ってください。
これは「ユーザーの μ_thickness(現在の塗り厚好み)で K-M 計算した塗布後 Lab」。
ユーザーが AR スライダーを動かしたら、その値を `thickness` として観測ログに送ると
学習が進んで TOP-N の `effective_lab` も追従して動きます。

**★ 商品サムネは `image_url`** をそのまま `<img src>` に渡せばOK(lipscosme の CDN URL)。

**★ `is_serendipity: true` の商品は「冒険枠」**(似合い圏から少し外れた未知の提案)。
UI で「いつもと違う冒険」等のバッジを付けて見せてください。そして **この商品への
like/dislike を送るときは観測の `is_serendipity` も `true` にする**と、探索性
(θ_explore)が学習されます(冒険提案に当たる人/外す人を区別)。判定基準は API 側で
「返却 TOP-N 内で ΔE が中央値超 かつ familiarity が中央値未満」と定義(§7.4 配線)。

### 4.5 能動学習(EIG)— `/v13/recommend` の `rerank` オプション

**新エンドポイントは無い。** `/v13/recommend` に `rerank:true` を足すだけで、
「似合う順(exploit)」から「次に試着させると一番学べる順(explore 混合)」に切り替わる。
R_final(似合い)と EIG(期待情報利得)をブレンドし、探索性 `θ_explore` で配合を変える。

リクエスト:
```jsonc
{
  "user": { /* UserState */ },
  "top_n": 5,
  "rerank": true,            // ← これだけで能動選択。既定 false は従来と完全同一
  "explore_weight": 0.5      // 任意。0=似合い重視, 1=冒険重視。
                             // 省略時は user.theta_explore.mu が自動で効く
}
```

レスポンス(rerank 時のみ各 result に eig_bits / p_like / score が付く):
```jsonc
{
  "user_id": "mina_001",
  "mu_thickness": 0.88,
  "beta_used": 2.5,
  "reranked_by_eig": true,
  "used_explore_weight": 0.5,   // 実際に使った w(指定値 or θ_explore.mu)
  "results": [
    {
      "product_id": "rmd_blur_fudge_07",
      "effective_lab": { "L": 44, "a": 40, "b": 18 },
      "image_url": "https://...",
      "r_final": -9.1,        // 似合い(exploit)指標
      "delta_e_to_color": 11.8,
      "eig_bits": 6.6,        // 期待情報利得(explore)指標 [bit](rerank時のみ)
      "p_like": 0.46,         // like 確率(ΔE2000 知覚シグモイド、rerank時のみ)
      "score": 0.78,          // (1−w)·norm(R_final)+w·norm(EIG)(rerank時のみ)
      ...
    }
  ]
}
```

**★ フロントは recommend 呼び出しに `rerank:true` を足すだけで能動選択になる。**
`explore_weight` 省略時は θ_explore 事後平均が自動で効く(冒険好き→遠い色、保守的→近い色)。
既定(`rerank` 無し)は並び・出力とも従来と完全に同一なので、既存の呼び出しは無変更で OK。

> 注: EIG は「P(like) は ΔE2000(知覚)で、KL は Lab座標の情報量で」測る異指標の近似。
> EIG は中間距離の色でピーク(近すぎ=学びが薄い、遠すぎ=当たらない)。

### 4.6 v14 逐次ペア比較 — `/v14/pair_compare/start` / `next`(A3)

ペア比較を「固定10問一括」から「**逐次・最大EIG選択・固定 N=8 問**」に変更した新系。
**v13 系は完全温存**(Kawanoさんの既存実装は無改修で動く)。v14 を使う場合のみ移行。

```
POST /v14/pair_compare/start
  in : { lip_lab, scenes?, pc_season?, warmness?, mu_thickness?=0.5 }
  out: { session, n_pairs_total(=8), first_pair: PairV14, candidate_count, catalog_size }

POST /v14/pair_compare/next
  in : { session, pair_id, chose:"left"|"right" }
  out: { session, done, next_pair?: PairV14, theta_snapshot, candidate_count }
```

- **session はクライアント往復方式**(`{ user: UserState, asked_pair_ids: [...] }`)。サーバ側に
  セッションを持たない(v13 の UserState 往復と同じ思想)。毎回 out の session をそのまま次の in に渡す。
- **`PairV14` は left/right に `effective_lab` を含む**(`lip_lab + μ_thickness` の K-M 塗布後 Lab)。
  フロントはこれで**本人の唇画像を再着色**して比較(パッケージ画像をやめ、観測とモデル仮定を整合)。
  そのため start で **`lip_lab` を渡す必要がある**(ここが v13 との接続差・MTG §5-1)。
- **逐次選択**: 各 next で選択を観測としてベイズ更新 → 残問あれば次の最大EIGペアを返す。
  同一ペアは二度出さない。EIG 最大選択は同点 pair_id 昇順で決定的。
- **EIG_pair** = Σ_c P(c)·KL(事後‖事前)(期待KL形・ガウス閉形式)。P(c) は Bradley-Terry
  `σ(β_BT·(fit差))`、β_BT=0.25(`active_learning.SLOPE_DEFAULT` 流用)。更新ノイズは v13 と同じ
  ペア σ²。詳細は `pair_eig.py`。動的打ち切りはしない(進捗バーの終端を見せる=UX確定仕様)。
- **`theta_snapshot`**(中間実況用): `theta_pref` の現在 mu/var + 直前で σ² が最も縮んだ軸名。
  コンシェルジュ(F3)が「透け感が好きみたいだね」と実況するのに使う。
- **`candidate_count`**(絞り込みカウンタ): その時点の事後での残候補数(competitive set・§ A2-fix)。
- N_PAIRS は既定 8(`app.N_PAIRS_V14`)。**A4 検証で 8 を確定**(scene+7 で flat+10 と hit 同等、+8 で σ²・世界観カバレッジに余裕)。

---

### 4.7 A3 以降に増えた差分(2026-06 追記。§4.1〜4.5 は A3 時点ベースのため、ここで補完)

既存は後方互換のまま、以下を追加済み:

- **`/v13/recommend` レスポンス**:
  - `results[].reasons`: 推薦理由。`top_axes`(軸名・日本語ラベル・寄与・来歴 `evidence`)+ `product_traits` +
    `color_percentile` / `pref_percentile` + `scene_match`。**文章化はフロント**(コンシェルジュ)が担当。
  - `results[].is_serendipity`: 冒険枠(遠い×未知)フラグ。
  - `candidate_count` / `catalog_size`: 絞り込みカウンタ用(R_final 中央値超えの実候補数 / プール総数)。
- **`UserState.scenes`**(A1): シーン選択(`school` / `friends` / `date` / `special`)。事前分布 + reasons の
  `scene_match` に使用。空配列なら従来挙動。
- **`Observation.extras`**(F4-fix): `{action, kept, decided}` 等の任意メタ。**ベイズ更新には未使用**
  (Phase 2 のデータ収集として保持するのみ)。`source_pair_id` も観測の来歴用に追加済み。
- **`GET /v13/popular?top_n=N`**: ユーザー非依存の「みんなの定番」。MVP は売上/レビューが無いため
  **カタログ代表性**(中央 Lab=median centroid への近さ)で代用。レスポンス `{catalog_size, method, results[]}`、
  `results[]` は `{product_id, name, line_category, image_url, lab, representativeness, effective_lab}`。決定的。
  - **任意 `lip_l/lip_a/lip_b`(3つ揃った時のみ)+ `mu_thickness`(既定 0.5)**: 渡すと各定番に
    `effective_lab`(本人の唇に塗った K-M 塗布後 Lab)が付く。未指定なら `effective_lab:null`。
    **ランキングはユーザー非依存で不変**(effective_lab は付加情報のみ)。定番も唇に合成して顔プレビューできる。

> ✅ **`openapi.json` は再生成済み**(/v14 全エンドポイント + `/v13/popular` の lip 引数 + `PopularItem.effective_lab`
> 反映済み)。CI(`test.yml` の a4 ジョブ)が `app.openapi()` を dump してアーティファクトに出力 →
> リポジトリの `openapi.json` に反映済み。型生成(`gen:api-types`)はこの最新版から可能。

### 4.8 `POST /v14/concierge_speech` — コンシェルジュ(妖精)の発話生成

発話生成を**バックエンドに一本化**(RN=Kawano さん / Next の二重実装回避)。既存の reasons(§4.7)/
theta_snapshot(§4.6・session 内)を**日本語文面に変換するだけ**の薄い層。フロントは返った `speech.text` を吹き出しに出すだけ。

- **リクエスト** `{phase, session?, step?, reasons?, is_serendipity?, scenes?, is_final?}`:
  - `phase="explore"`(ペア比較中の中間実況): `session` をそのまま渡す(`spoken_axes`=実況済み軸が相乗り)。`step` は step_intro 用。
  - `phase="recommend"`(推薦理由の口語化): `reasons`(recommend の `results[].reasons`)+ `is_serendipity`。
  - `phase="decide"`(確認/終端): `is_final`。
- **レスポンス** `{speech:{type, text} | null, session?}`:
  - `type` は `step_intro` / `axis_realization` / `reason_user` / `reason_product` / `reason_hybrid` / `serendipity_offer` / `decision_confirm` / `decision_final`。
  - explore では **`spoken_axes` 追記版の `session`** が返る(次ターンへ持ち回る)。caller は中身を知らず往復するだけ。
- **状態管理**: 中間実況の重複防止・予算(最大3回)は `session.spoken_axes` に相乗り(§4.6 の session をそのまま使う)。
- 軸実況は **μ_pref>0(好意方向)** かつ確信した軸を1つだけ。否定方向は黙る(Phase 2)。
- **来歴の一言化**: reason 発話は `evidence`(pair_id 列)を生で出さず、`_PAIR_LABELS`(pair_id → 「甘い vs クラシー」等)に変換。
- 文面は Haruki 作成の暫定確定版(上品なコンシェルジュ風)。**3パターン最終文面は Kawano さんと協議予定**。

---

## 5. 議論したいポイント

設計書 v1.3 を素直に実装しているが、Kawanoさん 側との接続点で詰めたい:

1. **データの渡し方**
   - Lab を `{L,a,b}` dict にしているが、`[L,a,b]` 配列の方が楽なら変更可
   - `UserState` 丸ごと往復は重いか?(20次元 vec × 2 + Lab × 2 + スカラー × 4 ≈ 50 数値)
   - caller 側が状態保持しない選択肢が欲しい場合は、lip API 側で SQLite を持つ拡張も可

2. **通信モデル**
   - 現状は同期 REST。Kawanoさん が GAS なら同期で十分
   - もし Kawanoさん AR から直接叩く構成なら CORS は `*` 解放済み

3. **ペア比較 10 問の中身**
   - 俺が仮で組んだだけ。商品の組み合わせ・提示順は Kawanoさん 側の UX に合わせたい
   - `_PAIR_SPECS`(`pair_compare.py`)を差し替えるだけで反映できる

4. **20 次元 pref ベクトル `x_20` の軸定義** — ✅ **確定済み(要協議で変更)**
   - **x20 軸定義は `catalog_x20.AXIS_NAMES`(v1.3)で確定。変更は要協議**
     (scene_priors / reasons の top_axes・product_traits / I_dialog がこの順序・名前に依存)。
   - 確定 20 軸: hue / saturation / brightness / pigmentation / glossy / moisture_finish /
     sheer / velvet / blur / is_tint / is_balm / is_gloss / moisturizing / longlasting /
     transfer_resistance / girly / makeup_intensity / konare / sweetness / korean
   - ↓の旧「仮定義」(transparency / mature 等)は**廃止**。正は `catalog_x20.py`。
   - 仮定義(廃止): pigmentation / vivid / transparency / glossiness / matte_finish /
     velvet_finish / moisture / durability / blur_effect / juicy_feel /
     cool_tone / warm_tone / light_color / deep_color / everyday_use /
     girly / konare / sweetness / korean / mature

5. **観測ログのスキーマ**
   - 今は `source` enum で分岐。`extras: {}` フィールドを追加して将来拡張できるようにも可
   - `viewed_seconds` を観測重みに反映するか(設計書 §12.6, Phase 2 拡張)

6. **K-M テーブルの事前計算**
   - 現状 `/v13/recommend` 内部で毎回 145 × 21 を計算(MVP は十分高速)
   - 規模が増えたら caller 側でテーブルキャッシュ→`km_table` 引数で渡す方式に切り替え可

7. **ユーザー識別 / 認証**
   - 現状 `user_id` は caller が任意で発行する文字列。lip API 側に DB なし
   - Kawanoさん 側でアカウント機構を持つか、lip API 側に最小限の users テーブル要るかは要相談

---

## 6. lip API 側の実装ファイル(参考)

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
