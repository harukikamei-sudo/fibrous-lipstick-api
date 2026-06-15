# KAWANO_HANDOFF.md — Kawanoさん向けハンドオフ

> Fibrous Lipstick AR アプリのlip API × Kawanoさん 連携をスムーズに始めるための、
> **「お互い何を担当して、どこで握手するか」を1枚で見渡せる**ドキュメント。
>
> このドキュメント1つで「全体像 + 役割分担 + 接続点 + 相談したい論点」が分かる。
> 詳細な API spec は別途 [KAWANO_INTERFACE.md](KAWANO_INTERFACE.md)。

最終更新: 2026-05-29 / 設計書 v1.3 準拠

---

## 0. 一行サマリ

> **Kawanoさん は AR とユーザー UI、lip APIは色の物理計算と推薦ロジック。**
> **HTTP API 4 つで握手する。**
> **lip API 側は実装済み・本番稼働中、Kawanoさん 側はこれから。**

---

## 1. ミナさん視点のフロー(全体像)

ペルソナ「ミナ(高校1年、ブルベ夏)」がアプリを使う体験 3 ステップ:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ ① 初回診断 (約 30 秒〜2 分)                                                   │
│                                                                              │
│  📷 肌を自撮り    →  PC判定 (例: ブルベ夏)        ┐                          │
│  👄 ノーリップ唇   →  唇 Lab = (62, 22, 12)       │  ★ ぜんぶ Kawanoさん AR が担当 │
│  🎴 ペア10問選ぶ   →  「どっち好き?」を10回        ┘                          │
│                                                                              │
│  ↓ 結果をlip API に送信                                                   │
│                                                                              │
│  ☁ lip API: ベイズ事前分布を構築 → ミナ専用の UserState を返す             │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│ ② AR 試着 (1 商品あたり 10〜30 秒)                                            │
│                                                                              │
│  💄 おすすめ TOP-5 が表示される                                               │
│  📷 タップするとミナの唇に色が乗る (AR 合成)                                  │
│  🎛 「もう少し濃く」「もう少し薄く」のスライダーで好みを試す                  │
│  👍 「いいね」or 😐「微妙」を押す                                              │
│                                                                              │
│  ↓ 観測ログをlip API に送信                                                │
│                                                                              │
│  ☁ lip API: ベイズ更新 → 「ミナの好み」を学習 → 更新後の UserState を返す  │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│ ③ 体験ループ(使うほど精度上昇)                                              │
│                                                                              │
│  TOP-5 が「ミナ専用」に進化していく                                          │
│  10 観測で「ほぼ確定」レベルの確信に                                          │
│  使うほど自分のことを分かってくれるアプリ                                    │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 役割分担マップ

設計書 v1.3 §2.4 の役割分担に沿って、誰が何を作るかを明示。

```
┌───────────────────────────────┬─────────────────────────────────────────┐
│  🎨 Kawanoさん 担当(AR + UI)     │  ⚙ lip API 担当(計算サーバー、実装済)    │
├───────────────────────────────┼─────────────────────────────────────────┤
│  📷 肌撮影 → PC判定           │  K-M 物理計算(色の塗布シミュ)         │
│  📷 唇撮影 → Lab抽出          │  ベイズ更新(4 θ パラメータ)           │
│  🎴 ペア比較UI(10問の2択)    │  推奨スコア R_final 計算               │
│  💄 AR で唇に色を合成          │  effective_Lab(個人化された見え方)    │
│  🎛 塗り厚スライダー(0〜1)   │  CIEDE2000 色差                         │
│  👍 いいね/微妙 ボタン         │  PC 別事前分布                          │
│  📡 観測ログ送信(API 叩く)  │  ペア提示・選択結果からの事前分布構築    │
│  💾 UserState の保存・読込      │  商品カタログ管理(rom&nd 145商品)    │
│                                │  x_20 軸の派生計算                       │
└───────────────────────────────┴─────────────────────────────────────────┘
```

### Kawanoさん が「やらなくていい」こと
- **K-M 物理計算は不要**(lip API が `effective_Lab` を返す → それを唇に合成するだけ)
- **ΔE2000 などの色差計算は不要**(lip API 側で全部やる)
- **商品データは持たなくていい**(lip API がカタログ持ってる)
- **ペア定義は持たなくていい**(`/v13/pair_compare/init` で取れる)
- **ベイズ更新の数学は知らなくていい**(API がブラックボックスで返す)

### Kawanoさん が「やらないといけない」こと
- AR の絵作り(これが価値の中心)
- ユーザー UI(撮影誘導、ペア提示、AR スライダー、いいね/微妙)
- `UserState` の保存(GAS / Firebase / 自前 BE / なんでも可)
- lip API への HTTP リクエスト(4 種類)

---

## 3. 接続点(API 早見表)

**ベース URL**: `https://tamable-fibrous-lipstick-api.hf.space`
**Swagger UI**: `https://tamable-fibrous-lipstick-api.hf.space/docs`
**CORS**: `*` 開放(Kawanoさん AR から直接叩いて OK)

### 3.1 4 つのエンドポイント(これだけ覚えればよい)

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ① GET  /v13/pair_compare/init                                            │
│    用途: ペア10問を取得(初回診断時)                                    │
│    入力: なし                                                            │
│    出力: pairs[10] (各ペアに left/right の商品情報)                      │
├─────────────────────────────────────────────────────────────────────────┤
│ ② POST /v13/pair_compare/apply                                           │
│    用途: ペア選択結果から事前分布を構築(初回診断の最後)                │
│    入力: { choices: [{pair_id, chose}×10], pc_season, warmness? }        │
│    出力: { theta_color, theta_pref, theta_explore, theta_thickness }     │
│         → Kawanoさん は UserState に詰めて保存                                │
├─────────────────────────────────────────────────────────────────────────┤
│ ③ POST /v13/update_user                                                  │
│    用途: AR の「いいね/微妙」観測でベイズ更新(毎回叩く)                │
│    入力: { user: UserState, observations: [Observation×n] }              │
│    出力: { user: 更新後の UserState, n_applied: {...} }                  │
│         → Kawanoさん は自前ストレージを上書き                                 │
├─────────────────────────────────────────────────────────────────────────┤
│ ④ POST /v13/recommend                                                    │
│    用途: 現在の UserState で TOP-N 推薦を取得                            │
│    入力: { user: UserState, top_n: 5 }                                   │
│    出力: { results: [{product_id, name, image_url, effective_lab,        │
│                       r_final, ...}×N] }                                 │
│         → effective_lab を唇に合成、image_url を商品サムネに使う             │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.2 1 ユーザーセッションの典型的な叩き順

```
[初回]
   GET ① → 提示 → 選択 → POST ② → UserState 保存
        ↓
   POST ④ → TOP-5 取得 → AR 表示

[AR 試着で「いいね」を押すたび]
   POST ③ → UserState 更新 → 保存
        ↓
   POST ④ → 新しい TOP-5 取得 → AR 再表示
```

---

## 4. データの流れ(シーケンス図)

### 4.1 初回診断シーケンス

```
ミナ      Kawanoさん AR        lip API
 │         │                │
 ├─📷肌──→ │                │
 │         │ PC判定(local)  │
 ├─👄唇──→ │                │
 │         │ Lab抽出(local) │
 │         │                │
 │         ├──GET ①────────→│
 │         │←─pairs[10]──────│
 │         │                │
 │←─ペア提示                  │
 ├─選択×10→│                │
 │         │                │
 │         ├──POST ②───────→│
 │         │ {choices,       │
 │         │  pc_season,     │
 │         │  warmness}      │
 │         │←─4 θ 事前分布───│
 │         │                │
 │         │ UserState 組み立て、保存
 │         │                │
 │         ├──POST ④───────→│
 │         │ {user, top_n:5}│
 │         │←─TOP-5──────────│
 │         │                │
 │←─AR表示                    │
```

### 4.2 AR 試着 + 学習シーケンス

```
ミナ      Kawanoさん AR        lip API
 │         │                │
 │←─TOP-5 (effective_Lab で唇に合成)
 ├─🎛 t調整─→│                │
 │         │ Lab補間 or 再リクエスト
 ├─👍 like→│                │
 │         │                │
 │         ├──POST ③───────→│
 │         │ {user,          │
 │         │  observations:[{│
 │         │   ar_view_like, │
 │         │   product_id,   │
 │         │   observed_lab, │
 │         │   thickness,    │
 │         │   y:+1}]}       │
 │         │←─新 UserState───│
 │         │                │
 │         │ UserState 上書き保存
 │         │                │
 │         ├──POST ④───────→│
 │         │←─新 TOP-5───────│
 │         │                │
 │←─AR再表示                  │
```

---

## 5. UserState の中身(これを Kawanoさん が保存・送受信する)

```jsonc
{
  "user_id": "mina_001",         // Kawanoさん 側で発行
  "lip_lab": { "L": 62, "a": 22, "b": 12 },
  "pc_season": "ブルベ夏",

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

**サイズ感**: 約 50 数値 ≈ 1KB 程度。気にしなくていいサイズ。

---

## 6. AR で表示する Lab はこれ

`POST /v13/recommend` のレスポンスの **`results[*].effective_lab`** をそのまま使う。

これは「**ユーザーの現在の μ_thickness で K-M 物理計算した塗布後の色**」。
ユーザーがスライダーを動かしたら:
- ローカルで補間して見せる(高速だが近似)
- もしくは t を変えて再リクエスト(正確だが遅い)
どっちでもOK。

---

## 7. 議論したい 7 項目(Kawanoさん に確認したいこと)

詳細は [KAWANO_INTERFACE.md §5](KAWANO_INTERFACE.md) にあるが、要点だけ:

### Q1. データ形式(俺の仮置き → 変更可)
- Lab は `{L, a, b}` dict にしてる → `[L, a, b]` 配列の方がいい?
- UserState 丸ごと往復は重い? → 軽くしたい?

### Q2. 通信モデル
- 現状: 同期 REST + CORS 開放
- GAS 経由でも Kawanoさん AR 直叩きでも対応可
- Webhook / SSE が必要なシーン ある?

### Q3. ペア比較 10 問の中身 ⭐ 重要
- 俺が `_PAIR_SPECS`(`pair_compare.py:158`)で仮に組んでる
- 商品の組み合わせ・提示順は Kawanoさん UI のフロー次第で差し替えたい
- 提案の組み合わせを見て要望を言ってほしい

### Q4. x_20 軸定義 ⭐⭐ → ✅ **確定済み(下記「仮定義」は廃止。正は `catalog_x20.py`)**
- **正は `catalog_x20.AXIS_NAMES`(v1.3 確定・変更は要協議)**: hue / saturation /
  brightness / pigmentation / glossy / moisture_finish / sheer / velvet / blur /
  is_tint / is_balm / is_gloss / moisturizing / longlasting / transfer_resistance /
  girly / makeup_intensity / konare / sweetness / korean
- **AR の「印象タグ」はコンシェルジュ発話(reasons)に吸収**(独立タグ UI は作らない。agenda §3)。
  matte / juicy / mature 系は実装に1対1の軸が無く、当面は不要の見込み。
- ~~仮定義 20 軸(廃止): pigmentation / vivid / transparency / glossiness / matte_finish /
  velvet_finish / moisture / durability / blur_effect / juicy_feel /
  cool_tone / warm_tone / light_color / deep_color / everyday_use /
  girly / konare / sweetness / korean / mature~~

### Q5. 観測ログの拡張余地
- 今の Observation スキーマで足りない情報ある?
- `extras: {}` フィールド追加して将来拡張可能にする?
- `viewed_seconds` を観測重みに反映するか(設計書 §12.6 Phase 2)

### Q6. K-M テーブルのキャッシュ
- 現状: `/v13/recommend` 毎回内部で 145×21 計算(<100ms で十分高速)
- 規模が大きくなったら Kawanoさん 側でテーブル保持する?
- 現状のままで OK ならノータッチ

### Q7. ユーザー識別 / 認証
- 今は `user_id` は Kawanoさん が任意発行
- lip API 側に最低限の users テーブル要る?
- アカウント機構は Kawanoさん 側? OAuth?

---

## 8. 今すぐ何ができるか(Kawanoさん が試せる手順)

### 8.1 API を叩いてみる(ブラウザだけで OK)

1. Swagger UI を開く: https://tamable-fibrous-lipstick-api.hf.space/docs
2. `/v13/pair_compare/init` の **Try it out** → **Execute** → 10 ペア返ってくる
3. 同様に他のエンドポイントも試せる

### 8.2 ターミナルで個人化を体感する(lip APIの Mac で)

```bash
cd ~/Desktop/fibrous-lipstick-api
.venv/bin/python personas_cli.py
```

→ 3 ペルソナ並走シミュレータで「同じ初期 → 別 TOP-5 に分岐」が見られる。
詳細は [SIMULATOR_GUIDE.md](SIMULATOR_GUIDE.md)。

### 8.3 GUI でクリックしながら体感する

```bash
.venv/bin/streamlit run ui_v13.py
```

→ ブラウザでペア選択 → AR 試着 → ベイズ更新を画面で体験(裏で動いてる API・数式・状態も右パネルに表示)。

**サイドバーで顔写真をアップロード**すると、TOP-N の各商品が**実写の唇に合成された絵**で表示されます(設計書 Part V の Kawanoさん側 AR 表示の代用デモ)。唇マスクは自動抽出、唇 Lab も自動計測。

### 8.4 「自分の言語」で叩いてみる(JS/curl/postman など何でも)

```bash
curl -X POST https://tamable-fibrous-lipstick-api.hf.space/v13/pair_compare/apply \
  -H "Content-Type: application/json" \
  -d '{
    "choices": [
      {"pair_id":"color_01_bright_vs_deep","chose":"left"}
    ],
    "pc_season": "ブルベ夏"
  }'
```

---

## 9. 連絡フロー

### lip API 側にお願いしたいこと
- KAWANO_INTERFACE.md §5 / 本書 §7 の 7 項目に対する希望/制約を教えてほしい
- Kawanoさん AR の技術スタック(Unity? Web AR? ネイティブ?)を教えてほしい
- 撮影 UI のスペック(画像サイズ・形式)が決まったら共有してほしい

### Kawanoさん 側にお願いしたいこと(=lip APIが対応する)
- API のレスポンスに `image_url` を含めるか
- レスポンスのフィールド名を Kawanoさん が使いやすい名前に変える
- ペア定義 / x_20 軸の差し替え(俺の側で1ファイル変更で済む)
- 新エンドポイント追加(例: セレンディピティ提示専用、認証など)

---

## 10. 関連ドキュメント

- **[SIMULATOR_GUIDE.md](SIMULATOR_GUIDE.md)** — 個人化が動く証拠(CLI 取説 + 数式)
- **[KAWANO_INTERFACE.md](KAWANO_INTERFACE.md)** — API spec の技術詳細(curl 例・全フィールド説明)
- **[HANDOFF.md](HANDOFF.md)** — 全体引き継ぎ(状態・履歴)
- **[DESIGN.md](DESIGN.md)** — 元の設計理論(K-M 数式・色彩学根拠)
- **[LOG.md](LOG.md)** — 開発ログ(意思決定の理由)

---

## TL;DR(忙しい Kawanoさん 用)

```
俺が作った:                Kawanoさん が作る:
  ☁ HTTP API 4本             📷 撮影UI(肌+唇)
  🧮 K-M + ベイズ + 推薦       🎴 ペア提示UI(10問)
  📦 商品カタログ 145件       💄 AR合成 + 🎛 スライダー
  📊 検証ツール3種            👍 いいね/微妙ボタン
                              💾 UserState 保存

握手は HTTP POST/GET 4回:
  GET  /v13/pair_compare/init
  POST /v13/pair_compare/apply
  POST /v13/update_user
  POST /v13/recommend

相談事項:
  ペア10問の中身、x_20 軸定義、データ形式の微調整、認証

開始するには:
  https://tamable-fibrous-lipstick-api.hf.space/docs を開く
```
