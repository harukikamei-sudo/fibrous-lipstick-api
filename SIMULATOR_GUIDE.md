# SIMULATOR_GUIDE.md — 3 ペルソナ並走シミュレータ完全ガイド

> 設計書 v1.3 の個人化学習層が本当に動くかを、対話的に検証するための CLI シミュレータ
> `personas_cli.py` の取扱説明 + 裏で動いてる数式 + 設計の背景を 1 つにまとめたドキュメント。

最終更新: 2026-05-29

---

## 目次

- [1. このシミュレータは何か](#1-このシミュレータは何か)
- [2. 起動と終了](#2-起動と終了)
- [3. コマンド全リファレンス](#3-コマンド全リファレンス)
- [4. 3 ペルソナの定義](#4-3-ペルソナの定義)
- [5. 用語集(これだけ覚えれば全部読める)](#5-用語集これだけ覚えれば全部読める)
- [6. 裏で動いてる数式(全部)](#6-裏で動いてる数式全部)
- [7. CLI 出力の読み方](#7-cli-出力の読み方)
- [8. 検証ハイポセシス H1〜H5](#8-検証ハイポセシス-h1h5)
- [9. 設計書 v1.3 ↔ 実装の対応表](#9-設計書-v13--実装の対応表)
- [10. 既知の限界](#10-既知の限界)
- [11. トラブルシュート](#11-トラブルシュート)

---

## 1. このシミュレータは何か

**目的:** 設計書 v1.3 の「個人化学習」が本当に成立しているかを、3 人の仮想ペルソナを並走させて検証する。

**何が見える:**
- 同じ事前分布から始めた 3 人が、観測を重ねるごとに違う TOP-N に分岐する様子
- ベイズ更新の数式に現在の値を代入した計算過程
- 設計書の式と実装の出力が一致しているかの ✓ チェック
- 「確信」が形成される様子(σ² の縮小)

**何が見えないか:**
- AR の見た目(色の合成は Streamlit `ui_v13.py` の方で確認)
- 商品画像(CLI なので)
- 実際の Kawano AR 側の動き(これから作る部分)

---

## 2. 起動と終了

### 起動
```bash
cd ~/Desktop/fibrous-lipstick-api
.venv/bin/python personas_cli.py
```

起動すると凡例 + 3 ペルソナの紹介 + コマンド一覧 + 初期状態の表 + 初期 TOP-3 が表示される。

### 終了
```
(personas) ▸ q
```
または Ctrl+C / Ctrl+D。

---

## 3. コマンド全リファレンス

| コマンド | 引数 | 動作 |
|---|---|---|
| `step` | `[<回数>]` | 3 人全員にそれぞれ AR like 観測を 1 件流す。回数指定で複数件まとめて。観測のたびに `μ_thickness` がどう動いたか + 解釈ラベル(💧/💋/❤️‍🔥)を表示 |
| `top` | `[<件数>]` | 各ペルソナの TOP-N を 3 人横並び表示(省略=3、最大10) |
| `state` | なし | 4 θ パラメータの現状(μ・σ²・進捗バー・確信度ラベル)を表示 |
| `formula` | なし | 直近の更新で動いたベイズ式に現在値を代入した計算過程 + 実装出力と一致するかの ✓ |
| `diff` | なし | 初期 TOP-5 と現在 TOP-5 の差分(何件入れ替わったか) |
| `obs` | なし | 各ペルソナの観測履歴(最新10件) |
| `reset` | なし | 3 人とも初期状態に戻す |
| `help` | なし | コマンド一覧再表示 |
| `quit` / `q` | なし | 終了 |

### 引数表記の凡例
- `< >` は必須引数、`[ ]` は省略可能
- 半角整数を渡す(`step 5` は OK、`step 五` や `step5` はエラー)

### コマンドの推奨叩き順(初回)
```
(personas) ▸ step 5       ← 観測5件流す(進化のドラマ)
(personas) ▸ state        ← 3人の脳内パラメータを比較
(personas) ▸ formula      ← 数式と実装の一致を確認
(personas) ▸ diff         ← TOP-5 がどれだけ入れ替わったか
(personas) ▸ step 10      ← さらに10件流して「ほぼ確定」状態に
(personas) ▸ top 5        ← 横並び TOP-5 を最終比較
```

---

## 4. 3 ペルソナの定義

すべて **ブルベ夏 + 同じペア選択(全 left)** で初期化される。違いは「どんな商品にいいねするか」だけ。

### 🌸 ミナ(高1・濃いめ暖色 韓国っぽい派)
- **target_thickness**: 0.9(濃いめ)
- **like する商品の条件**:
  - `line_category == "tint"`
  - `x20_18_korean > 0.3`(韓国っぽい軸が高い)
  - `x20_11_warm_tone > 0.5`(暖色軸が高い)
- **代表 like 商品**: ベアーグレープ、マルドピーチ、ポメロスキン、ヌカダミア…
- **設計書 §1.1 のペルソナ「ミナ」と対応**

### 🌿 アヤ(OL・薄めヌード ナチュラル派)
- **target_thickness**: 0.2(薄め)
- **like する商品の条件**:
  - `line_category in ("gloss", "tint")`
  - `x20_02_transparency > 0.4`(透明感軸が高い)
  - `x20_12_light_color > 0.4`(明るい色軸が高い)
- **代表 like 商品**: ポメロスキン、ベアアプリコット、パパイヤジャム、ピーチピーチミー…

### 💎 ユウキ(大学生・マット深色 マチュア派)
- **target_thickness**: 0.95(超濃いめ)
- **like する商品の条件**:
  - `line_category in ("matte", "velvet")`
  - `x20_13_deep_color > 0.3`(暗色軸が高い)
  - `x20_19_mature > 0.2`(マチュア軸が高い)
- **代表 like 商品**: ペルシレッド、ディープソウル、フィズ、アンシャーリー…

### ペルソナを変えたい場合
`personas_cli.py:88-122` の `PERSONAS` リストを書き換えるだけ。`product_filter` のラムダ式を変えれば「もしミナが寒色派だったら?」みたいな仮想シナリオも作れる。

---

## 5. 用語集(これだけ覚えれば全部読める)

### θ(シータ) — ベイズ更新する 4 つの個人パラメータ
| 記号 | 次元 | 意味 |
|---|---|---|
| **θ_color** | Lab 3次元 | 似合う色の中心(L, a, b) |
| **θ_pref** | 20次元 | 好みベクトル(機能15 + 世界観5) |
| **θ_thickness** | スカラー1次元 | 塗り方好み(0=極薄 〜 1=濃ベタ) |
| **θ_explore** | スカラー1次元 | 新しい発見への興味度(0=保守 〜 1=冒険) |

### μ(ミュー) — ベイズ事後の中心値
「アプリが思ってる現在のベスト推定値」。観測で動く。

### σ²(シグマ二乗) — 事後分散
「アプリの確信度」。観測で縮む。**小さい = 確信あり、大きい = まだ不確実**。

### effective_Lab
ユーザーの `μ_thickness` で K-M 物理計算した「**塗布後の見え方**」の Lab。
ミナ(μ=0.88)とアヤ(μ=0.21)では同じ商品でも違う `effective_Lab` になる。

### R_final(最終推奨スコア)
$$R_{final}(c, user) = f(c, user) - \beta(\mu_{explore}) \cdot familiarity(c, user)$$

ここで $f(c, user) = -\alpha \cdot \Delta E_{2000}(\text{eff\_Lab}, \mu_{color}) + \mu_{pref} \cdot c.x_{20}$。
大きいほど上位。

### CIEDE2000 (ΔE2000)
業界標準の知覚均等色差。「人間がどれだけ違う色だと感じるか」を 0(同じ)〜 100(対極)で表す。
ΔE < 1: 知覚不能、1〜3: 訓練すれば分かる、3〜10: 普通に違う、>10: 全然違う。

### x_20(20次元 pref ベクトル)
各商品が「どんな印象か」を 20 軸で数値化したもの。
全 145 商品の x_20 は `products_with_lab.csv` の `x20_00_*` 〜 `x20_19_*` 列。
派生計算ロジックは `catalog_x20.py:derive_x20()`。

---

## 6. 裏で動いてる数式(全部)

すべて設計書 v1.3 と完全一致。実装は `bayesian.py` / `recommend_v2.py`。

### 6.1 PC 別事前分布(設計書 §3.2 / §3.3)

PC season から `μ_color_0` を選ぶ:

| シーズン | μ_color_0 (L, a, b) |
|---|---|
| イエベ春 | (55, 45, 30) |
| イエベ秋 | (40, 40, 25) |
| ブルベ夏 | (55, 35, 5) |
| ブルベ冬 | (40, 50, 15) |

σ²_color_0 はシグモイドで「PC 判定の境界付近」では大きくする:
$$\sigma^2_{color,0} = \sigma^2_{base} \cdot \left(1 + \gamma \cdot \text{sigmoid}\left(-\frac{|w - \theta| - \delta}{s}\right)\right)$$

定数: σ²_base=100, γ=2, δ=5, s=2。`pair_compare._sigma2_color_0`。

### 6.2 ベイズ更新(設計書 §7)

すべての θ を「対角共分散ガウス」として、観測でガウス共役更新する。

#### 6.2.1 θ_color(L成分の例、a/b も同じ式)— §7.2

$$\sigma^2_{N} = \frac{1}{\frac{1}{\sigma^2_{0}} + \sum_k \frac{y_k^2}{\sigma^2_{k,obs}}}$$

$$\mu_{N} = \sigma^2_{N} \cdot \left( \frac{\mu_{0}}{\sigma^2_{0}} + \sum_k \frac{y_k \cdot Lab_{k,j}}{\sigma^2_{k,obs}} \right)$$

- $y_k$ = 観測の符号(like=+1, dislike=-1)
- $Lab_{k,j}$ = 観測の j 次元の値
- $\sigma^2_{k,obs}$ = 観測ソース別ノイズ(下表)

実装: `bayesian.update_theta_color`

#### 6.2.2 θ_pref(20次元)— §7.3

$$\sigma^2_{N,j} = \frac{1}{\frac{1}{\tau^2_{pref}} + \sum_k \frac{x_{k,j}^2}{\sigma^2_{k,obs}}}$$

$$\mu_{N,j} = \sigma^2_{N,j} \cdot \left( \frac{\mu_{0,j}}{\tau^2_{pref}} + \sum_k \frac{x_{k,j} \cdot y_k}{\sigma^2_{k,obs}} \right)$$

- τ²_pref = 1.0(設計書 §11)
- $x_{k,j}$ = 観測 k の商品の x_20[j]

実装: `bayesian.update_theta_pref`

#### 6.2.3 θ_thickness(スカラー1次元)— §7.5

$$\sigma^2_{N} = \frac{1}{\frac{1}{\sigma^2_{0}} + \frac{N}{\sigma^2_{obs,thickness}}}$$

$$\mu_{N} = \sigma^2_{N} \cdot \left( \frac{\mu_{0}}{\sigma^2_{0}} + \sum_k \frac{t_k}{\sigma^2_{obs,thickness}} \right)$$

- μ_0 = 0.5, σ²_0 = 0.1(事前、中立)
- σ²_obs_thickness = 0.05
- 結果は [0, 1] にクリップ

実装: `bayesian.update_theta_thickness`

#### 6.2.4 θ_explore — §7.4

同じガウス共役の形式。観測値は like なら r=1.0, dislike なら r=0.0。
σ²_obs_explore = 0.25。実装: `bayesian.update_theta_explore`

#### 6.2.5 観測ノイズ表(設計書 §7.1)

| source | σ²_obs |
|---|---|
| `pair_color` | 0.8 |
| `pair_worldview` | 0.8 |
| `dialog` | 1.5 |
| `behavior` | 1.0 |
| `ar_view_like` | 1.0 |
| `ar_view_dislike` | 1.0 |

### 6.3 effective_Lab(設計書 §5.4)

21 段階の K-M 計算済み Lab テーブルから μ_thickness で線形補間:

```
t_lower = floor(μ_thickness × 20)        # 0..20
t_upper = min(t_lower + 1, 20)
w = (μ_thickness × 20) - t_lower
Lab = (1 - w) × applied[t_lower] + w × applied[t_upper]
```

実装: `recommend_v2.effective_lab`

### 6.4 推奨スコア(設計書 §8 / §10)

$$f(c, user) = -\alpha \cdot \Delta E_{2000}(\text{eff\_Lab}, \mu_{color}) + \mu_{pref} \cdot c.x_{20}$$

$$\text{familiarity}(c, user) = w_1 \cdot I_{\text{dialog}} + w_2 \cdot \cos(\mu_{pref}, c.x_{20}) + w_3 \cdot \frac{1}{1 + \Delta E_{2000}}$$

$$\beta(\mu_{explore}) = \beta_{max} \cdot \mu_{explore}$$

$$R_{final}(c, user) = f(c, user) - \beta \cdot \text{familiarity}(c, user)$$

定数: α=3.0, β_max=5.0, w=(4, 3, 2)。実装: `recommend_v2.recommend_v2`

### 6.5 K-M(Kubelka-Munk)物理計算(設計書 §5.1)

各チャネル(L, a, b)独立で:

$$\frac{K}{S} = \frac{(1 - R_\infty)^2}{2 R_\infty}, \quad a = 1 + \frac{K}{S}, \quad b = \sqrt{a^2 - 1}$$

$$R(t) = \frac{1 - R_{lip}(a - b \coth(bSt))}{(a - R_{lip}) + b \coth(bSt)}$$

- R_lip = sRGB_to_reflectance(唇 Lab)
- R∞ = sRGB_to_reflectance(商品 Lab マスストーン)
- S = ライン代表値(`km.LINE_S_PRESETS`、tint=0.4 のみ実測、他は推論値)

実装: `km.py:km_reflectance` / `km.py:compute_applied_lab`

---

## 7. CLI 出力の読み方

### 7.1 視覚バー
```
🌸 ミナ    0.8810  ■■■■■■■■■■■■■■■■■■□□
```
20 マスで μ_thickness の位置を視覚化。`■` が多いほど濃いめ志向。

### 7.2 確信度ラベル
σ²_thickness が σ²_0(=0.1)からどれだけ縮んだかで判定:

| 状態 | σ²_thickness の範囲 |
|---|---|
| 確信なし | ≥ 0.090 |
| 少し動き始めた | 0.050 〜 0.090 |
| 方向性が見えてきた | 0.020 〜 0.050 |
| かなり確信 | 0.005 〜 0.020 |
| **ほぼ確定** | < 0.005 |

### 7.3 解釈絵文字(μ_thickness)

| μ_thickness | ラベル |
|---|---|
| < 0.30 | 薄めが好き 💧 |
| 0.30〜0.45 | やや薄め寄り |
| 0.45〜0.55 | 中立(まだ未知) |
| 0.55〜0.70 | やや濃いめ寄り |
| 0.70〜0.85 | 濃いめが好き 💋 |
| ≥ 0.85 | ガッツリ濃いめ ❤️‍🔥 |

### 7.4 観測ラウンドのナラティブ
```
── 観測ラウンド #1 ──
  🌸 ミナ: 👍 ベアーグレープ (tint, t=0.9)
     μ_thickness: 0.500 ↑ 0.767   (濃いめが好き 💋)
```
- `👍 ベアーグレープ` = 何にいいねしたか
- `t=0.9` = 塗り厚スライダーの位置
- `0.500 ↑ 0.767` = 観測前→観測後の μ_thickness 変化
- `↑` `↓` `→` で動いた向き
- カッコ内は解釈ラベル

### 7.5 TOP-N 表示
```
#1 ジュジュブ
     [tint] eff L52a43b23
     R=-7.30 ΔE=1.5
```
- `#1` = ランキング
- `ジュジュブ` = 商品名
- `[tint]` = 仕上げカテゴリ
- `eff L52a43b23` = effective_Lab(ユーザー視点での塗布後の色)
- `R=-7.30` = R_final スコア(大きいほど上位)
- `ΔE=1.5` = effective_Lab と μ_color の色差(小さいほど似合う)

### 7.6 `formula` の ✓ マーク
```
σ²_N = 1 / (1/0.02000 + 1/0.05) = 0.01429
       implementation: 0.01429  ✓
```
左辺は「設計書の式に値を代入した計算」、右辺は「実装の出力」。
これが ✓(一致)なら、実装が数式通り動いてる証拠。

---

## 8. 検証ハイポセシス H1〜H5

`personalization_demo.py` で自動検証する 5 つの仮説。

### H1 個人化が成立する
**主張:** 同じ事前 + 違う観測 → 違う TOP-N

**検証方法:** 3 ペルソナの 10 観測後 TOP-5 を比較、重複が 5 未満なら成立。

**結果:** ✅ ミナ∩ユウキ=0, アヤ∩ユウキ=0(完全分離)

### H2 観測蓄積で σ² が縮む
**主張:** ベイズ更新が正しく働けば、観測数 N に応じて σ² が単調縮小

**検証方法:** 0観測→10観測で σ²_thickness の変化を見る

**結果:** ✅ 0.10 → 0.005 (20倍縮小)

### H3 θ_thickness が観測の方向に動く
**主張:** ミナ(t=0.9 like) → μ_thickness ↑, アヤ(t=0.2 like) → μ_thickness ↓

**検証方法:** 観測後の μ_thickness が target_thickness 方向に寄ったか

**結果:** ✅ ミナ 0.88, アヤ 0.21, ユウキ 0.93(全員ターゲット方向)

### H4 TOP-1 の特性がペルソナ志向と整合
**主張:** ミナ→tint warm、アヤ→明るい透明感、ユウキ→暗い matte/velvet

**検証方法:** 10観測後の TOP-1 商品の line_category / Lab / x_20 を確認

**結果:** ✅ ミナ→ジュジュブ(tint, warm=1.00), アヤ→ピーチダウン(L=55), ユウキ→ペッパーチェリー(velvet, L=40)

### H5 同じ商品でも μ_thickness で effective_Lab が変わる
**主張:** μ_thickness が異なれば、同じ商品の見え方が違う(個人化の核心)

**検証方法:** 共通商品の effective_Lab を比較

**結果:** ✅ the_juicy_lasting_05 の effective_Lab がミナ(L=51.8) vs アヤ(L=56.0)

---

## 9. 設計書 v1.3 ↔ 実装の対応表

| 設計書 § | 内容 | 実装ファイル / 関数 |
|---|---|---|
| §3.2 | PC 別 μ_color_0 | `pair_compare.PC_MU_COLOR_0` |
| §3.3 | σ²_color_0 シグモイド | `pair_compare._sigma2_color_0` |
| §5.1 | K-M 反射率式 | `km.km_reflectance` |
| §5.4 | 21段線形補間 | `recommend_v2.effective_lab` |
| §6 | 強制ペア比較 10問 | `pair_compare.PAIR_BANK` |
| §7.1 | 観測ノイズ表 | `bayesian.SIGMA2_BY_SOURCE` |
| §7.2 | θ_color 更新 | `bayesian.update_theta_color` |
| §7.3 | θ_pref 更新 | `bayesian.update_theta_pref` |
| §7.4 | θ_explore 更新 | `bayesian.update_theta_explore` |
| §7.5 | θ_thickness 更新 | `bayesian.update_theta_thickness` |
| §8 | f = -α·ΔE + μ_pref·x_20 | `recommend_v2.f_score` |
| §10.1 | familiarity | `recommend_v2.familiarity` |
| §11 | 全ハイパーパラ | 各モジュールで設計書値を使用 |

設計書未指定の判断(6 箇所):
1. ΔE_inv の関数形 → `1/(1+ΔE)`
2. β(μ_explore) の関数形 → `β_max · μ_explore`
3. μ_thickness のクリップ → `max(0, min(1, μ))`
4. dislike の y → `-1.0`
5. ペア未選択側の扱い → `y=-1` 観測として扱う
6. PC threshold → `0`

詳細は LOG.md エポック10。

---

## 10. 既知の限界

### 10.1 TOP-1 精度に「ニアミス」がある
アヤ(薄めヌード派)の TOP-1 が matte 系商品になるなど、ペルソナ志向と完全一致しないケースがある。

**原因:** x_20 軸が荒い派生計算で、Kawano UI と未合意。

**対策:** Kawano と x_20 軸を詰める(KAWANO_INTERFACE.md §5 第4項)。

### 10.2 ペア定義が仮データ
`_PAIR_SPECS`(`pair_compare.py:158`)は俺が組んだだけ。Kawano UI のフロー次第で差し替え必要。

### 10.3 設計書 §7.5 の収束表との数値乖離
設計書本文の表(N=1→σ²=0.094)は σ²_obs を別値で計算した近似値で、数式 `σ²_N = 1/(1/σ²_0 + N/σ²_obs)` から計算される値(N=1→σ²=0.0333)とは異なる。実装は数式を採用。

### 10.4 シミュレータでは applied_Lab が線形近似
`personas_cli.py` 内では K-M でなく単純な線形補間で観測 Lab を作っている。これは「観測の方向性」を見るには十分だが、本番の `/v13/update_user` は厳密な K-M 結果(`effective_Lab`)で叩く想定。

---

## 11. トラブルシュート

### `.venv/bin/python: no such file or directory`
→ プロジェクトディレクトリにいない。`cd ~/Desktop/fibrous-lipstick-api` してから叩く。

### `step abc` → エラー
→ `step` の引数は半角整数。`step 5` のように指定。

### `step5` → 不明なコマンド
→ コマンドと引数の間は半角スペース。`step 5` と分けて。

### 表示が文字化け / 絵文字が四角になる
→ ターミナルが Unicode 対応してない。macOS 標準 Terminal.app か iTerm2 推奨。

### ANSI カラーが効かない / 制御コードがそのまま見える
→ `TERM` 環境変数が `dumb` などになってる可能性。`echo $TERM` で `xterm-256color` 系か確認。

### `🌸 ミナ: 候補商品なし`
→ ペルソナの product_filter にマッチする商品がカタログに無い。`personas_cli.py:88-122` の条件を緩める。

### 起動時に長時間止まる
→ FastAPI の `TestClient` がカタログ ロード + ペアを生成中。10 秒程度なら正常。
それ以上待つなら `print(...)` を追加してデバッグ。

### 観測しても μ_thickness が動かない
→ サーバー側で `n_applied.theta_thickness == 0` の可能性。観測の `source` が `ar_view_like` で、`thickness` フィールドが入ってるか確認。

---

## 関連ドキュメント

- [HANDOFF.md](HANDOFF.md) — 全体の引き継ぎ
- [CLAUDE.md](CLAUDE.md) — プロジェクト概要
- [DESIGN.md](DESIGN.md) — 元の設計理論
- [KAWANO_INTERFACE.md](KAWANO_INTERFACE.md) — API spec(技術詳細)
- [KAWANO_HANDOFF.md](KAWANO_HANDOFF.md) — Kawano と相談用(役割分担)
- [LOG.md](LOG.md) — 開発ログ(エポック10 が v1.3 個人化層)
