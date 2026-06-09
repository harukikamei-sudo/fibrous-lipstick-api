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
- 実際の Kawanoさん AR 側の動き(これから作る部分)

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
| `plot` | `[<観測数>]` | N 観測を逐次適用してベイズ更新を**統計的に可視化** → `bayes_report.png` 出力(省略=15)。詳細は §3.5 |
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
(personas) ▸ plot 15      ← ベイズ更新を統計的に可視化(図2枚 + レポート)
(personas) ▸ top 5        ← 横並び TOP-5 を最終比較
```

### `plot` が出す 2 枚の図(§3.5)

`plot [N]` は API を使わず `bayesian`/`pair_compare` を直接呼び、各ペルソナに N 観測を
逐次適用して **2 枚の PNG** を出力する:

**`bayes_report.png`(統計ビュー、2×3)** — N を固定した断面:
- (A) θ_thickness 事前→事後のガウス密度(狙い値=点線)
- (B) σ²_thickness 逐次収縮 + 解析解 — **3本が重なる=分散はデータ非依存**
- (C) μ_thickness 逐次収束(狙い値へ漸近)
- (D) θ_color 95%信用楕円(a–b 平面、半径 √χ²(2,0.95)·σ)
- (E) σ²_L 逐次収縮(log軸)
- (F) ゼロ知識デザイン事前(§3.2 PC中心 σ²=100)からの情報利得 KL[bit] 積み上げ棒

**`bayes_convergence.png`(収束速度、2×2)** — N をスイープした比較:
- (G) 95%CI 幅 vs N(共通)+ 閾値到達 N*(幅0.2 → N*≈19)
- (H) |μ−target| 収束(log、~1/N)+ ε到達 N* マーカー
- (I) 地形図: |μ_N−target| を (N, target) で等高線 + ペルソナ重畳
- (J) N* 比較棒: μ収束 N*≈3–4 vs CI確信 N*≈19

> **洞察:** 「**方向(μ)はすぐ掴めるが、確信(CI幅)を締めるには桁違いの観測が要る**」。
> σ² はデータ非依存(件数だけで決まる)なので CI の N* は全ペルソナ共通、μ の N* は
> prior-target gap が大きいほど遅い。

**`bayes_eig.png`(能動学習 EIG、2×2)** — `/v13/recommend` の `rerank` の中身:
- (K) EIG 分解: P(like)↓ × KL↑ = EIG(**中間距離 ΔE≈14 でピーク**=スイートスポット)
- (L) 事前確信度 σ²₀ 別 EIG(既に確信が強いほど1観測で学べる量が小さい)
- (M) explore_weight スイープ → 選ばれる top1 の ΔE が単調増加(exploit→explore)
- (N) 候補散布(ΔE × EIG): w=0 は最近傍(exploit)、w=1 は EIG 最大(explore)を選ぶ

> **洞察(EIG):** 近すぎる色は「もう知ってる=学びが薄い」、遠すぎる色は「当たらない
> (P(like)→0)」。その積 EIG が中間でピーク = 能動学習が選ぶ「次の1本」。w=θ_explore.mu
> で配合が決まり、冒険好きほど遠い色を提案する。

> **注意:** この Mac は matplotlib の**初回 import に 30〜85 秒**かかる(macOS の dylib
> 検証)。`plot` が固まって見えても落ちていない。バックグラウンド実行ではなく REPL 内
> (前景)で叩くこと。生成後は `open bayes_report.png bayes_convergence.png bayes_eig.png`。

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

> **⚠️ 但し書き(拘束量へのガウス近似):** θ_thickness は物理的に **[0, 1] に拘束**された
> 量だが、事後を**非拘束ガウス** N(μ, σ²) で近似している。μ は [0,1] にクリップするが
> **分散側は素のガウスのまま**なので、μ が 0/1 に近く σ が大きいと確率質量が
> [0,1] の外に十数%漏れる(`plot` の図1パネル A で Mina/Yuki の事後が t=1.0 を
> はみ出すのはこのため)。MVP では実害は小さいが、厳密には **truncated normal** か
> **logit 変換空間での更新**にするのが筋。Phase 2 の改善候補。

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

## 6.6 MVP 設計上の割り切り(確定事項)

MVP クローズにあたり、以下 2 点は「割り切り」を**確定の設計判断**として明記する。
どちらも実装はこのまま(コード変更なし)、較正・精緻化は将来フェーズの課題とする。

### 割り切り1:θ_thickness の観測ソース(設計書 Part V「③」)

AR の塗り厚スライダ(`intensity`、初期値 **0.7**)の値を、**そのまま θ_thickness の
観測**として採用する。

- これは「**プレビュー用の操作**(見え方を確認するためにスライダを動かす)」と
  「**好みの塗り厚の申告**(この厚みが好き)」を**同一視する割り切り**である。
- **MVP では (a) 現状維持を採用**する。観測ノイズの緩和(σ²_obs_thickness の調整)や、
  「プレビュー操作」と「好み申告」を UI で分離することは将来課題とする。
- 理由:**その厚みで ❤️ した = その厚みを許容する信号**として妥当、と解釈する。
  スライダ値そのものを観測 `t_k` として §6.2.3 のガウス更新に投入する。

> 関連:θ_thickness は [0,1] 拘束だが非拘束ガウスで近似している(§6.2.3 の但し書き)。
> これも MVP の割り切りで、truncated normal / logit 空間化は将来課題。

### 割り切り2:P(like) の de50 / slope は仮値(較正未実施)

能動学習の like 確率モデル
$$P(\text{like}) = \mathrm{sigmoid}\big(\text{slope} \cdot (\text{de50} - \Delta E_{2000})\big)$$
の **de50 = 12.0 / slope = 0.25 は経験的な仮値**であり、**被験者データに基づく較正は
未実施**である(`active_learning.DE50_DEFAULT` / `SLOPE_DEFAULT`)。

- 較正の道筋:**AR の ❤️/✕ ログ(観測時の ΔE と like/dislike 結果)をロジスティック
  回帰すれば de50/slope は較正可能**。能動学習(EIG)が中間〜遠方の ΔE を意図的に
  試させる(§3.5 図3 のスイートスポット)ため、較正に必要な ΔE 範囲のデータ収集と
  相性が良い。**本格較正は Phase 3 パイロット待ち**。
- それまでは EIG のスイートスポット位置(ΔE≈14 前後)は仮値依存である点に留意。
  ランキングは R_final とのブレンド(`rerank`)なので、仮値でも exploit 側が下支えする。

### 割り切り3:事前 θ_color の分散較正(ペア比較の観測ノイズ)

**EIG が最大化するもの ≠ 真値への近さ。** EIG は KL(事後‖事前) の期待値=「信念の
移動量(θ_color を速く学ぶ)」を最大化する acquisition であり、真の好みへの距離
(リグレット)最小化とは別目的。EIG は現在の μ から中間距離の「よく動く」色を選ぶが
真値方向とは限らない。さらに dislike は θ_color を更新しない仕様(割り切り済み)のため、
EIG が選ぶ P(like) 低めの候補は有効更新(like)が出にくく、純粋な真値収束では
一様ランダム + like フィルタ(実質「真値領域への棄却サンプリング」)に最終値で劣りうる
(能動学習で既知の現象)。

**真因は acquisition でなく事前 θ_color の過信だった。** 旧実装ではペア比較10問
(色5問)適用後に θ_color が σ²≈0.16(**SD≈0.40 Lab**)まで縮み、商品間隔(ΔE 数十)に
対して過信。これが Thompson を exploit に退化させ EIG の情報評価も歪めていた。

**較正:ペア比較(色)の観測ノイズ σ²_obs を上げて事前を SD≈2.0 Lab に緩める。**
「ペア比較は10問しかなく質問設計も暫定 → 強くは信じない」という設計思想をそのまま
モデル化する方法を採用した(`bayesian.SIGMA2_BY_SOURCE["pair_color"]` を逆算値 ≈20.83 に)。
色ペア5問適用後に σ²_N≈4.0(SD≈2.0)となる:
$$\sigma^2_N = \frac{1}{1/100 + 5/\sigma^2_{obs}} = 4.0 \;\Rightarrow\; \sigma^2_{obs} = \frac{5}{1/4 - 1/100} \approx 20.83$$
較正後、探索系が本来の働きを取り戻し、in silico(仮説ズレ中・400 seed 平均)で
**EIG は製品で使える戦略(exploit/EIG/Thompson)の中で最良、かつ試着7回以内なら
ランダムにも勝つ**ことを確認した。EIG は σ² に対し山なりの最適点を持ち(SD≈2 最良、
SD≈10 では逆に悪化=スイートスポットが真値を通り越す)、Thompson は σ² を広げるほど
単調改善する、という非対称も観察された。

**スコープ(重要):** 較正したのは **`pair_color`(→θ_color)のみ**。
`pair_worldview`(→θ_pref、事前 τ²=1.0 でそもそも過信なし)と `ar_view_like`(AR 学習)は
**変更しない**。事前だけ緩め、AR で試着を重ねれば σ² は従来どおり 2.0 以下へ縮む
(=事前は緩いが学習は効く)。不変条件 `σ²_N = 1/(1/σ²_0 + N/σ²_obs)` は
`test_bayesian.test_pair_prior_color_sd_calibrated` で**式として**検証している
(マジックナンバー固定ではない)。

### 割り切り4:色 ΔE の3用途マップ(「色を3回数えてないか」への回答)

同じ量 **ΔE2000(effective_Lab, μ_color)**(似合う色の中心からの色差)が、システム内の
**3か所**で使われている。これは重複カウントではなく、**3つの異なる役割の分担**である。

| 使用箇所 | 式(色項) | 符号/効果 | 役割 |
|---|---|---|---|
| `recommend_v2.f_score` | −α·ΔE(α=3) | ΔE 大で減点(線形) | **当てる**:似合う色を上位に(exploit) |
| `recommend_v2.familiarity`(w3項) | w3·1/(1+ΔE)(w3=2)を `R_final` で −β 倍 | 近い色ほど「馴染み」→ β でペナルティ | **あえて外す**:冒険度 β で似合いすぎを減点 |
| `active_learning.p_like` | sigmoid(slope·(de50−ΔE)) | 近い色ほど like 確率高 | **学ぶ**:EIG の「当たる確率」項 |

`familiarity` は色(上記 w3 項)と**世界観**(w2·cos(μ_pref, x20)、w2=3)の両方を使う
重み付き和(w1 対話=4 / w2 世界観=3 / w3 色=2)。世界観の重みが色より大きいので、
セレンディピティ(意外さ)は**「色は似合うが世界観が新鮮」型に寄る**設計判断
(色だけ外すと"似合わない色"に近づくが、世界観で外せば"似合う色のまま新鮮"を作れる)。

**これは重複でなく役割分担。ただし注意点:** `R_final = f − β·familiarity` の中で、
色 ΔE が **+α(f項)と −β·w3(familiarity項)で部分的に相殺**する(冒険度 β が大きいほど
色 exploit が弱まる=冒険好きには似合い一辺倒をやめて少し外す、という意図どおりの挙動)。
**ただし α と β·w3 の比次第では、冒険好きで色 exploit が過度に相殺され「色を無視して
世界観だけで選ぶ→似合わない色を出す」事故になりうる**(ランダムが製品化不可なのと同じ穴)。

現定数(α=3, w3=2, β_max=5)では**相殺は ΔE≈0〜2 の近傍に局所化**し、最冒険(β=5)でも
色 exploit は支配的(純色寄与 g(ΔE)=−αΔE−β·w3/(1+ΔE) は ΔE≈1 で最大の −8、ΔE=10 で −31、
ΔE=40 で −120 と大きく変動)。実測でも μ_explore=1 で「世界観完璧一致だが色が遠い(ΔE≈33)」
候補は R=−110 で「色ピッタリだが世界観普通」候補 R=−10 に負ける = **色は無視されない**。
回帰防止に `test_recommend_v2.test_explore_does_not_ignore_color` で固定。
**α:β·w3 の比は Phase 3 で実データ較正時に要監視**(似合わない色を出さない範囲を保つ)。

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

**原因:** x_20 軸が荒い派生計算で、Kawanoさん UI と未合意。

**対策:** Kawanoさん と x_20 軸を詰める(KAWANO_INTERFACE.md §5 第4項)。

### 10.2 ペア定義が仮データ
`_PAIR_SPECS`(`pair_compare.py:158`)は俺が組んだだけ。Kawanoさん UI のフロー次第で差し替え必要。

### 10.3 設計書 §7.5 の収束表との数値乖離
設計書本文の表(N=1→σ²=0.094)は σ²_obs を別値で計算した近似値で、数式 `σ²_N = 1/(1/σ²_0 + N/σ²_obs)` から計算される値(N=1→σ²=0.0333)とは異なる。実装は数式を採用。

### 10.4 シミュレータでは applied_Lab が線形近似
`personas_cli.py` 内では K-M でなく単純な線形補間で観測 Lab を作っている。これは「観測の方向性」を見るには十分だが、本番の `/v13/update_user` は厳密な K-M 結果(`effective_Lab`)で叩く想定。

### 10.5 MVP 設計上の割り切り(確定事項)
θ_thickness の観測ソース(スライダ値=好み申告の同一視)、P(like) の de50/slope が
仮値(較正未実施)、そして**事前 θ_color の分散較正(EIG≠真値近さ/真因は事前過信/
ペア比較 σ²_obs を上げて SD≈2.0 に較正)**は、**確定の割り切り**として §6.6 にまとめた
(割り切り1〜3)。較正の道筋・in silico 検証結果も同節に記載。

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
- [API_GUIDE.md](API_GUIDE.md) — `/v13/*` 含む全エンドポイントの curl 例
- [KAWANO_INTERFACE.md](KAWANO_INTERFACE.md) — API spec(技術詳細・議論ポイント)
- [KAWANO_HANDOFF.md](KAWANO_HANDOFF.md) — Kawanoさんと相談用(役割分担・フロー図)
- [LOG.md](LOG.md) — 開発ログ(エポック10 が v1.3、エポック11 が今回の磨き)

## 別の触り方(任意)

CLI 以外にも 2 つの検証手段が用意されている:

- **`personalization_demo.py`** — 一発実行型(CI でも回る、スモークテスト用)
- **`ui_v13.py`** — Streamlit ブラウザ UI、ペア比較 + AR 試着ループを GUI で
  操作。サイドバーから顔写真をアップロードすると、TOP-N に **実写唇合成**(K-M
  effective_Lab を実際の唇に適用した絵)が表示される。

詳細は KAWANO_HANDOFF.md §8 を参照。
