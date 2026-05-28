# DESIGN.md — Fibrous Lipstick ロジック設計書

> 口紅推薦システムの**理論・式の導出・計算過程・実装対応**をまとめた技術文書。
> 次回セッション/他メンバーがゼロから追えることを目的とする。
> 運用・進捗・申し送りは [CLAUDE.md](CLAUDE.md) 側。ここは「なぜその式・その値か」。

最終ゴール: **「あなたの唇にこの口紅を塗ったらこう見える」** をユーザー×商品×厚みで
事前計算し推薦する。本文書は色取り込み → 塗布シミュ → 推薦 → 可視化の全ロジックを扱う。

---

## 0. 記号表

| 記号 | 意味 | 範囲/型 |
|---|---|---|
| `R` | 反射率(チャネル毎) | 0〜1 |
| `R∞` | 無限厚(完全発色)反射率 | 0〜1 |
| `R_g` | 下地(基板/唇地肌)反射率 | 0〜1 |
| `K` | 吸収係数 / `S` 散乱係数 | ≥0 |
| `K/S` | 吸収散乱比(商品固有) | ≥0 |
| `t` | 塗膜の厚み(無次元、規約で固定) | ≥0 |
| `a` `b`(KM式内) | `a=1+K/S`, `b=√(a²-1)` | — |
| `L*,a*,b*` | CIE Lab | — |
| `ΔE` | CIE76 色差 | ≥0 |
| 「チャネル」 | linear sRGB の R/G/B 帯域 | 3 |

> 注意: KM 式の `a,b` と Lab の `a*,b*` は別物。文脈で区別する。

データフロー:
```
商品スウォッチ画像 ──extract_lab──▶ 商品フル発色 Lab (R∞)
                                       │ ks_from_lab
唇地肌 Lab (LIP_PRESETS) ─────────────┤ K/S(商品)
仕上げタイプ ──LINE_S_PRESETS──▶ S(ライン)  │
                                       ▼ km_reflectance / compute_applied_lab
                            塗布後 Lab ──ΔE──▶ /recommend TOP-N ──▶ UI(実写唇に合成)
薄付きスウォッチ(任意) ──estimate_s_layered──▶ 実測 S(校正)
```

---

## 1. 色空間と反射率近似 (`lab_utils.py`)

K-M は波長毎の反射率を要するが、本MVPでは **linear sRGB の R/G/B 各値を
「その帯域の反射率近似」** として扱う(D65)。

- sRGB(ガンマ) ↔ linear sRGB は標準の区分関数で可逆:
  - `c ≤ 0.04045: c/12.92` / それ以外 `((c+0.055)/1.055)^2.4`(→linear)
- `lab_to_reflectance(Lab)` = Lab →(skimage)→ sRGB → linear sRGB(=反射率)
- `reflectance_to_lab` はその逆。

**性質**: ガンマ変換は可逆なので Lab→反射率→Lab の往復 ΔE ≒ 0(浮動小数精度)。
`test_lab_utils.py` で ΔE<1 を担保。

---

## 2. Kubelka-Munk 理論 (`km.py`)

### 2.1 無限厚と K/S
無限厚(完全不透明)で観測した反射率 `R∞` から商品固有の吸収散乱比:

```
K/S = (1 - R∞)² / (2 R∞)         … (式1)  [_ks_from_reflectance]
```

`a = 1 + K/S`, `b = √(a²-1)` と置くと **`R∞ = a - b`**。
(証明: `(a-b)(a+b) = a²-b² = a²-(a²-1) = 1` ⇒ `a+b = 1/R∞`, `a-b = R∞`。)

実装 `ks_from_lab(full_lab)` = `_ks_from_reflectance(lab_to_reflectance(full_lab))`。
**フル発色 Lab を R∞ とみなす**のが基本(ただし §5.4 でこの仮定の限界に触れる)。

### 2.2 有限層(厚み t)の反射率
下地 `R_g` の上に厚み `t` の顔料層を重ねたときの反射率(Kubelka 1948 の有限層解):

```
        1 - R_g·(a - b·coth(b·S·t))
R  =  ────────────────────────────────     … (式2)  [km_reflectance]
          (a - R_g) + b·coth(b·S·t)
```

**極限と単調性**(t→塗り量):
- `S·t → 0`  ⇒ `coth→∞` ⇒ `R → R_g`(膜なし=下地そのもの)
- `S·t → ∞` ⇒ `coth→1` ⇒ `R → R∞ = a-b`(背景に依存しない無限厚)
  (代入: 分子`1-R_g(a-b)=1-R_g R∞`、分母`(a-R_g)+b=1/R∞-R_g`、比=`R∞`)
- 間は `S·t` に対して単調 ⇒ 後述の逆推定で解が一意。

**数値処理**: `coth(x)=1/tanh(x)` は `x→0` で発散するので
`b·S·t` を `[1e-9, 50]` にクリップ(50超は `coth≈1` で飽和扱い)。`R` は `[0,1]` クリップ。
反射率は `[EPS,1-EPS]`=`[1e-6, 1-1e-6]` に収め 0/1 発散を回避。

### 2.3 重ね塗り後 Lab
```
compute_applied_lab(lip_lab, product_k_s, line_s, t):
    R_g = lab_to_reflectance(lip_lab)          # 唇地肌が下地
    R   = km_reflectance(product_k_s, line_s, t, R_g)
    return reflectance_to_lab(R)
```
唇(地肌)+ 商品 K/S + ライン S + 厚み t → 塗布後 Lab。

### 2.4 バッチ・テーブル
`compute_km_table(lip_lab, products, lines, t_steps=21)`:
各商品×t(0..1 を t_steps 分割)で applied_lab を出す。商品ごとの S は
`resolve_line_s` で **lines[line_id] > line_category プリセット > line_id 推定 > other**
の優先順位で解決。出力に `s` と `s_source`(解決経路)を含める。

**S の設計**: `S` は**ライン共通**(仕上げタイプで決まる散乱)、`K/S` は**商品ごと**(色)。

---

## 3. ライン散乱係数 S の逆推定 (`estimate_s.py`)

### 3.1 識別性の定理(最重要)
**式2で S と t は必ず積 `S·t` の形でしか現れない**(coth の中だけ)。
⇒ 1 枚の薄付き観測から決まるのは **`S·t` という1つの量だけ**。
⇒ **S と t は原理的に分離不能(ゲージ自由度)**。データからは取り出せない。

**帰結(規約)**: t は規約で固定するしかない。本プロジェクトの採用規約:
- **「1度塗り = `t1` = 0.3」を全校正で共通**に使う。
- これで異なる画像/商品で得た S が**同一スケールで比較可能**になる(目的)。
- UI は塗り重ね回数で表現(校正後に t を割当)。2度塗り = `t1 × coat_ratio`(既定2)。

「t をデータから逆算する」案は **不成立**(2未知 S,t に対し実質パラメータ1個 `S·t` で退化)。

### 3.2 2点法 `estimate_s`(full=R∞ 仮定)
入力: フル発色(=R∞)Lab、薄付き Lab、`t_light`、下地 `substrate_lab`(省略時 白基板)。
- `K/S` は full から(式1)。
- 残る未知 `S` を、有限層式 `R(S; K/S, R_g, t_light) = R_obs` から
  **チャネル毎に `brentq` で数値求解**。`R` は単調なのでブラケット `[0, S_hi]` を
  倍々で広げて符号反転を捕捉 → brentq。
- 実装の注意: `_solve_s_channel` では `lo/hi/target` を**必ずスカラー化**して計算する
  (`r_g` を (1,) 配列のまま比較に使うと target が配列化し brentq が壊れる ← 実バグ修正済)。

### 3.3 単一スカラー化 `estimate_s_scalar`(校正用の頑健版)
S は本来「散乱は色相にほぼ非依存=1スカラー」が物理前提。チャネル毎の推定の
ばらつきは**暗・高彩度チャネルの飽和 artifact**。そこで情報の無いチャネルを捨て中央値を採る。

**採用ゲート(両方満たす ch のみ)**:
1. `|R_full - R_thin| ≥ dr_min`(既定 0.03)
   - 飽和(薄≈フル)も透明(素肌≈フル≈薄)も**両方この片側ゲートで除外**できる
     (どちらも S の情報を持たない)。閾値 0.03 の根拠: 実コーラル画像でノイズの
     R チャネル(ΔR≈0.021)を弾き、有意な G/B(≈0.03)を残せる値。
2. 物理整合(単調): `R_thin` が `R_substrate` と `R_full` の間(±0.01)。照明ムラで
   薄付きが素肌より明るい等の非物理 ch を除外。

採用 ch の `S` の**中央値**を単一スカラーとする。全除外なら `status="all_saturated"`、
妥当域 `s_valid` 外なら `"out_of_range"` 警告。

### 3.4 3点フィット `estimate_s_layered`(本命の校正法)
「2度塗り=R∞」を**仮定しない**。シアーなティント(何度塗っても不透明にならない)でも
正しい S が出るよう、**素肌 + 1度 + 2度の3観測**から K/S と S を同時推定する。

- 未知(チャネル毎): `K/S` と `u1 = S·t1`。
- 観測: `R1 = R(u1)`, `R2 = R(coat_ratio·u1)`(2度 = `t1×coat_ratio`, 既定 2)。
  ⇒ 2 式 2 未知 → `scipy.optimize.least_squares` でフィット。`R(·)` は
  `km_reflectance(ks, S=u, t=1, R_g)`(S·t=u をスカラーで評価)。
- `S = u1 / t1`。フィット `K/S` から `R∞ = a-b` を復元(=真のフル発色色)。
- **採用ゲート**: 単調(素肌→1度→2度) ∧ 各段差 `ΔR ≥ dr_min` ∧ フィット残差 `rmse < 0.02`。
  採用 ch の `S` の中央値を単一スカラーに。`s_valid` 既定 (0.05, 5.0)。
- **校正画像の要件**: 「1度塗り/2度塗り(厚み比≈2)」。**ティッシュオフは不可**
  (比率不明=実測 ~1/8〜1/12、ratio=2 だとフィット破綻して正しく弾かれる)。

**検証(test_km.py)**: 合成データで `K/S` と `S` を完全復元、塗り重ねで R∞ に収束
(ΔE→0)、非単調 ch 除外。実データ: コーラル juicy_lasting → S≈0.42、フル塗りで
商品色に収束を確認。

---

## 4. プリセットと分類 (`km.py`)

### 4.1 `LINE_S_PRESETS`(仕上げタイプ→S)とスケール根拠
```
gloss=0.25 / tint=0.4(★実測) / velvet=1.0 / matte=2.0 / other=0.6
```
- **tint=0.4 のみ実測**(estimate_s_layered, コーラル juicy_lasting → S≈0.42 を丸め)。
- 旧仮定 1〜8 は**実測比 10〜20 倍過大**と判明 ⇒ tint=0.4 をアンカーに、不透明度の
  順序 `gloss<tint<velvet<matte` を保って再スケール(gloss 0.6x / velvet 2.5x / matte 5x)。
- gloss は良い校正画像が入手困難(鏡面反射+鮮やか)なため**推論で 0.25 固定**。
  velvet/matte も校正画像が揃わず**推論値で確定**(将来 estimate_s_layered で上書き可)。
- **絶対値は t スケールと結合**: S を大きく(例 matte=200)すると t=0.05 で即飽和し
  t∈[0,1] の 21 段が階段関数に潰れる ⇒ O(0.1〜2) に保つ。
- **鮮やか色の非感応性**: K/S が大きい色は t=1 で全カテゴリほぼ満色 ⇒ S 差は出ない。
  S 差が効くのは**淡色・低 t**(淡色商品で applied 色がカテゴリ毎に分かれることを確認)。

### 4.2 `classify_line_category(line_id)`
line_id 文字列 → 5値(tint/matte/gloss/velvet/other)。rom&nd 名はカテゴリ語を直接
含まないので製品知識キーワードで対応: juicy→tint, blur/fudge→matte,
glasting/dewy→gloss, velvet→velvet。該当無し(bare_mool 等)→ other。
products.csv / products_with_lab.csv の `line_category` 列、resolve_line_s、
/recommend が共通利用(単一情報源)。

### 4.3 `LIP_PRESETS`(唇地肌の代表 Lab)
pale_pink / healthy_pink / reddish / beige / dark の 5 色。/recommend の下地、
UI の選択肢に使う。

---

## 5. /recommend エンドポイント (`app.py`)

唇色 → 全カタログ商品の塗布後色 → 目標色との ΔE で並べ替え TOP-N。

```
入力: lip_lab, t(=1.0), target_lab?(省略時=lip_lab=最も自然/唇寄り),
      line_category?, hue_min/max?, L_min/max?, top_n(=5)
処理: 各商品 p について
        ks = ks_from_lab(p.lab)
        S  = resolve_line_s(line_id, line_category)
        applied = compute_applied_lab(lip_lab, ks, S, t)
        applied の hue/L でフィルタ
        ΔE = ‖applied - target‖   (CIE76)
      ΔE 昇順 TOP_n
出力: {count, sort_target, results:[{id,name,line_category,original_lab,applied_lab,delta_e}]}
```
- カタログは起動時に `products_with_lab.csv` からロード(status=excluded と Lab 欠損は除外)。
  本番 HF に同梱するため同 CSV を git 追跡化。
- `ΔE(CIE76) = √(ΔL*² + Δa*² + Δb*²)`。
- 既定の並べ替え目標 = lip_lab ⇒ **applied が唇に近い=最も自然/シアー**な順。
  target_lab 指定でその色狙い。

---

## 6. UI Lv2 — 実写唇への塗布合成 (`ui_app.py`)

「色チップ」では口紅感が出ないため、**実写の唇に塗布後の色を合成**してビジュアル化。

### 6.1 唇マスク抽出(自動)
顔ランドマーク(mediapipe)は Python 3.13 で不可 ⇒ **色しきい値法**:
Lab で `a* > 25 ∧ chroma > 30 ∧ 中央域` → 最大連結成分 → 穴埋め(ハイライト等)→
クロージング → **ガウス羽化して α(0-1)** に。`assets/lips/model.png`(RGBA, α=唇マスク)。

### 6.2 合成数理 `composite_lip(rgb, alpha, applied_lab, l_blend=0.5)`
全画素を Lab に変換し**再着色**:
```
L' = (1 - l_blend)·L + l_blend·L_applied   (元の陰影/質感を残す。既定 50:50)
a' = a_applied ,  b' = b_applied            (色味は塗布後に置換)
```
再着色 RGB を `rec`、元画像を `base`、唇マスク α で**アルファ合成**:
```
out = α·rec + (1-α)·base
```
⇒ 顔・周辺は元のまま、唇だけ色変え。α が羽化済みなので**縁が自然に馴染む**。

### 6.3 画像のロードと差し替え
`load_lip_image(preset)` 優先順位: `lip_<preset>.png`(個別) > `model.png`(共用) >
ダミー(楕円描画フォールバック)。**塗布色は a,b を上書きするので、写真の元の唇色は
無関係**(写真は形/質感/陰影を担当) ⇒ 実写 1 枚で全プリセット/全商品に使える。
将来 Kawano さんデータは `load_lip_image` の内部だけ差し替え(インターフェース固定)。

### 6.4 素材と権利
`model.png` = Wikimedia Commons **"Mouth.jpg"(Public Domain)**。素の唇(化粧無し)を選定し、
唇周辺をクロップ+2x LANCZOS 拡大、α=色しきい値で唇マスク自動抽出+羽化。実測 Lab ≈ (54, 24, -4)
=自然な下地。PD のため帰属義務は無いが `CREDITS.txt` と UI で出所を明示。

### 6.5 計算と表示の一致(オプション B 採用)
`measure_lip_lab(rgb, alpha)` で唇マスクのコア(α≥0.7)から **代表 Lab を中央値で算出**し、
それを /recommend の `lip_lab`(K-M 下地 R_g)として使う ⇒ **「表示している唇のLab」と
「計算上の下地」が一致**。写真が無い時のみダミー+プリセット Lab にフォールバック。
(過去経緯: 当初は写真=キャンバス/プリセット=下地で不一致 → 一致のため B を採用 →
最初の model は CC BY 3.0 で唇が既に口紅塗布済み(L≈44, a≈48)だったので、素の唇 PD に差替)。

---

## 6.6 パーソナルカラー(PC)連携 — 論文ベース Lab 領域マッチング

### 方針(採用 / 不採用)
- **不採用**: カタログの `pc_season` タグでフィルタする(=「答え」を直接利用する)。
- **採用(2-a)**: PC 別に「**理想的な唇色 Lab 領域**」を論文/色彩学指針で定義し、
  シミュ結果 `applied_lab` が領域からどれだけ離れているかでランク付け。
  カタログタグは「答え合わせ用」として保持し、推奨ロジックには使わない。

### `km.PC_LIPSTICK_TARGETS`(km.py)
4 PC × {L_range, a_range, b_range, description, sources} の辞書。例(イエベ春):

| PC | L | a* | b* | 想定色 |
|---|---|---|---|---|
| イエベ春 | 55–75 | 25–50 | 15–35 | コーラル/ピーチ/テラコッタ |
| イエベ秋 | 35–55 | 20–40 | 15–30 | ブリック/テラコッタ/ウォームブラウン |
| ブルベ夏 | 55–75 | 20–40 | -5–10 | ローズ/モーブ/ベリー |
| ブルベ冬 | 30–50 | 35–60 | -5–15 | バーガンディ/ワイン/ディープベリー |

**論文/指針 出典**:
- Weatherall & Coombs 1992(b* 軸でのアンダートーン分類)
- Rees 2003(高カロテノイド → ウォーム)
- Del Bino & Bernerd 2013(高ヘモグロビン+低カロテノイド → クール)
- Del Bino et al.(ITA based skin tone classification)
- 業界一般指針: 春=コーラル / 秋=テラコッタ / 夏=ローズ / 冬=バーガンディ

### `km.compute_pc_score(applied_lab, pc_season)`
矩形領域からのユークリッド距離。領域内なら 0:
```
d_L = max(0, L_min-L, L-L_max)
d_a = max(0, a_min-a, a-a_max)
d_b = max(0, b_min-b, b-b_max)
pc_score = √(d_L² + d_a² + d_b²)
```
**小さいほど PC に合う**。

### /recommend の組み込み
リクエストに `pc_season?` を追加。指定時:
1. `sort_target = PC 領域の中心`(参考表示用)
2. 全商品の applied_lab を計算 → `pc_score` を出す
3. **pc_score 昇順で並べる**(同点は連続)
4. レスポンス各項目に `pc_score / delta_e_to_lip / catalog_pc_tags`(参考)を含める
未指定時は従来通り `delta_e_to_target` または `delta_e_to_lip`。

### `/evaluate` + `evaluate_all.py`(妥当性測定)
「論文ベース予測の TOP-N」と「カタログ `pc_season` タグ」の一致率:
```
matched = TOP-N 中、catalog_pc_tags に expected_pc または "イエベ・ブルベ問わず"
          を含む件数
match_rate = matched / N
interpretation: ≥0.7 good / ≥0.5 acceptable / <0.5 poor
```
**MVP 合格ライン = 0.70。初回バッチ(5唇プリセット × 4PC = 20組) 全平均 0.750(good)**。
イエベ秋のみ 0.40〜0.50 で要チューニング(L 領域が春と被る)。

### 役割分担
- **Kawano**: 写真 → 唇 Lab + PC 判定(撮影/分類担当)
- **Haruki**: 唇 Lab + PC を入力に、論文ベース推奨ロジックを構築(本実装)
- カタログ `pc_season` タグはあくまで「答え合わせ用」

---

## 7. 校正の実証結果と知見

| 項目 | 結果 |
|---|---|
| tint(コーラル juicy_lasting) | S ≈ 0.42、塗り重ねで R∞ に収束(ΔE 27→0.2) |
| 実測 S スケール | 0.2〜0.4 オーダー。旧仮定 1〜8 は 10〜20 倍過大 |
| カタログ色分布(140件) | C* 中央値48、鮮やか(C*≥40)72% / ヌード(C*<25)2%、赤コーラル主体 |
| 鮮やか色 | K/S 大 → 薄付きでも暗 ch 飽和 → S 非感応(校正不能/精度寄与小) |
| 校正向き | 淡色・テカリ少・1度/2度・素肌あり(腕スウォッチ推奨) |

**含意**: 校正は淡色で行い鮮やか色に適用(S は色相非依存が前提)。鮮やか色は
そもそも S の精度が効かないので問題にならない。

---

## 8. 既知の限界・将来課題

- **S/t ゲージ**: 絶対 S は t1 規約依存。t∈[0,1] と S 実測値の整合上、UI の「フル塗り」を
  t=1 ではなく数塗り相当に割り当てる**塗り重ね→t マッピング(規約3)**の確定が未了。
- **velvet/matte/gloss は推論値**(tint のみ実測)。良い 1度/2度 画像が来れば上書き。
- **mediapipe 不可**(Py3.13) → 唇マスクは色しきい値依存。赤くない唇/別構図では
  閾値調整が要る(将来 face landmark or 手動マスク併用)。
- **推薦は ΔE のみ**。似合い度(パーソナルカラー、明度コントラスト等)の評価軸は未実装。
- linear sRGB を反射率近似とする MVP 近似(厳密な分光反射率ではない)。

---

## 9. 主要式まとめ(早見)

```
K/S   = (1-R∞)² / (2R∞)                                   フル発色→吸収散乱比
a,b   = 1+K/S , √(a²-1)        R∞ = a-b                    無限厚反射率
R(t)  = [1 - R_g(a - b·coth(bSt))] / [(a-R_g) + b·coth(bSt)]  有限層反射率
        St→0 ⇒ R→R_g ,  St→∞ ⇒ R→R∞                       極限
S·t のみ可観測 ⇒ t は規約固定(1度塗り=t1=0.3)               識別性
estimate_s_layered: (K/S,u1) を R1=R(u1),R2=R(2u1) からfit  S=u1/t1
applied: L'=(1-λ)L+λL_app, a'=a_app, b'=b_app             UI 再着色
out = α·rec + (1-α)·base                                  α 合成
ΔE  = √(ΔL*²+Δa*²+Δb*²)                                   CIE76 色差
```

## 10. コード対応表

| 概念 | 実装 |
|---|---|
| Lab↔反射率 | `lab_utils.lab_to_reflectance / reflectance_to_lab` |
| K/S(式1) | `km._ks_from_reflectance` / `km.ks_from_lab` |
| 有限層 R(式2) | `km.km_reflectance` |
| 塗布後 Lab | `km.compute_applied_lab` / `km.compute_km_table` |
| S 2点法 | `estimate_s.estimate_s`(+ `_solve_s_channel`, brentq) |
| S 単一スカラー | `estimate_s.estimate_s_scalar` |
| S 3点フィット | `estimate_s.estimate_s_layered`(least_squares) |
| プリセット/分類 | `km.LINE_S_PRESETS / classify_line_category / resolve_line_s / LIP_PRESETS` |
| 推薦 | `app.recommend_endpoint`(+ `_load_catalog`) |
| 校正CLI | `sample_lab.py`(領域→Lab→estimate_s_layered) |
| UI 合成 | `ui_app.composite_lip / load_lip_image` |
| テスト | `test_km.py`(性質1〜8) / `test_lab_utils.py` / `test_dark_swatch.py` |
