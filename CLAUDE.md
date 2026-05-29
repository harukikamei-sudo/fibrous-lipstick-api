# CLAUDE.md — 次回セッションへの引き継ぎ

> このファイルは Claude Code が起動時に自動で読む。プロジェクトの前後関係を
> 即座に把握できるよう簡潔にまとめてある。
>
> **新セッションは [HANDOFF.md](HANDOFF.md) を最初に読む**(直近の状態+未解決事項を集約)。
> **設計書 v1.3 の Kawanoさん 接続点(=本実装の主役)は [KAWANO_INTERFACE.md](KAWANO_INTERFACE.md)**。
> **理論・式の導出・計算過程・なぜその値か は [DESIGN.md](DESIGN.md)(ロジック設計書)** に集約。
> **API の使い方(curl 例・レスポンス例)は [API_GUIDE.md](API_GUIDE.md)**。
> **各意思決定の背景・失敗試行・採用根拠は [LOG.md](LOG.md)(開発ログ)** に時系列で残す。
> HANDOFF=最新引き継ぎ、CLAUDE=運用/進捗、KAWANO=連携IF、DESIGN=数理、API_GUIDE=エンドポイント、LOG=決定物語。

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
├── sample_lab.py      ★校正CLI: 画像の素肌/1度/2度 領域→Lab→estimate_s_layered
│                      (座標モード --substrate/--coat1/--coat2 or --gui ドラッグ選択)
├── ui_app.py          ★Streamlit UI(Lv2): 唇プリセット→/recommend→TOP5を実写唇に合成表示
│                      合成= 全画素を Lab で再着色(L比率ブレンドで質感保持+a,b置換)し
│                      α(唇マスク,羽化)で元画像と合成→顔は残し唇だけ自然に色変え。
│                      `pip install -r requirements-ui.txt && streamlit run ui_app.py`
│                      API 本体とは別依存(requirements-ui.txt)。HF には載せない(ローカル用)
├── assets/lips/       唇画像。**git 追跡しない方針**(*.png 等を gitignore。HF の binary
│                      ポリシーに抵触、UI 専用なので API 側に無くてよい)。
│                      ローカル運用: 任意の正面顔写真を `model.png` として置けば
│                      ui_app.extract_lip_mask が自動でマスクを抽出して使う。
│                      アップロードモード(UI)なら配置不要(画面ドロップで都度処理)。
│                      置かなければダミー楕円唇にフォールバック。CREDITS.txt 参照。
├── test_dark_swatch.py ダーク系維持テスト
├── sample_gas.gs      GAS サンプル (参考実装、ユーザーはこれを参考に自前で書く予定)
├── verify_batch.py    公開 API バッチ動作確認用 (CPU basic だと 50件は timeout、10件刻みなら可)
├── products.csv       入力データ (145 商品、id + image_url + line_category 列)
├── products_with_lab.csv  ★Lab 抽出済みカタログ。/recommend が起動時にロード。
│                      line_category 列付き。git 追跡(本番 HF に同梱)
│                      ※line_category は km.classify_line_category で付与(専用スクリプト無し)
├── thumbnails/        抽出色チップ可視化サムネ (gitignore)
├── images_cache/      画像 DL キャッシュ (gitignore)
├── Dockerfile         python:3.11-slim + libgl1 + 7860
├── requirements.txt
├── README.md          HF Spaces 用フロントマター付き
├── HANDOFF.md         ★★新セッション起点(直近状態・設計書ギャップ・未解決事項)
├── DESIGN.md          ★ロジック設計書(理論/式の導出/計算過程/コード対応)
├── API_GUIDE.md       ★API 使い方ガイド(全エンドポイントの curl 例+レスポンス例)
├── LOG.md             ★開発ログ(各意思決定の目的/試行/失敗/採用根拠を時系列で)
├── DEPLOY.md          push 手順
│
├── ─── 設計書 v1.3 個人化学習層(2026-05-29 追加) ───
├── models_v13.py      ★pydantic 型(UserState/Observation/PairChoice/RecommendV2…)
├── bayesian.py        ★4 θ ガウス更新(color/pref/explore/thickness)。設計書 §7
├── recommend_v2.py    ★effective_Lab 線形補間 + Part IV/VI 統合スコア(R_final)
├── pair_compare.py    ★10 ペア仮データ + 事前分布構築(§3 PC + §6 強制ペア)
├── catalog_x20.py     ★x_20(機能15+世界観5)派生計算 + CSV 付与スクリプト
├── test_bayesian.py      ベイズ更新の性質テスト(8件)
├── test_recommend_v2.py  統合スコアのテスト(7件)
├── test_v13_flow.py      E2E 統合疎通(/v13/* 4 エンドポイント)
└── KAWANO_INTERFACE.md ★Kawanoさん 向け API spec(議論ポイント7項目)
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
- `estimate_s_layered`: ★**3点フィット(本命の校正用)**。素肌+1度塗り+2度塗りの
  3 観測から、チャネル毎に **(K/S, S) を同時推定**(R∞=2度 の仮定を撤廃)。シアーな
  ティントでも筋の通った S が出る。2度=t1×coat_ratio(既定2)と仮定し least_squares で
  フィット。採用ゲート=単調(素肌→1度→2度)＋各段差ΔR≥dr_min＋残差rmse<0.02。
  フィット K/S から R∞(真のフル発色)も復元して返す。妥当域 s_valid 既定 (0.05, 5.0)。
  **⚠️ 注意**: 校正画像は「**1度塗り/2度塗り**(比≈2)」を使う。「ティッシュオフ」は
  比率不明(実測 ~1/8〜1/12)で ratio=2 だと弾かれる/値が不安定。
- `estimate_s_scalar`: 2点(full=R∞ 仮定)版の per-ch 推定から **単一スカラー S** を出す。
  採用ゲート: |R_full - R_thin| < dr_min(既定 0.03)のチャネルは除外
  (飽和=薄≈フル も 透明=素肌≈フル≈薄 も両方この片側ゲートで捌ける)。
  残ったチャネルの中央値を S とし、診断(per_channel_s/delta_r/adopted/status)も返す。
  全飽和なら status="all_saturated"(校正不能)、妥当域外なら "out_of_range" 警告。
- **S/t 規約(重要・確定)**: K-M は観測に S·t しか効かない=S と t は分離不能(ゲージ
  自由度)。よって t は **規約で固定**するしかない(データから逆算は原理的に不可)。
  採用規約: 「**1度塗り = t_light = 0.3 固定**、全校正で共通」。これで異なる画像で
  出た S が同一スケールで比較可能になる。UI は塗り重ね回数で表示(校正後に t を割当)。

**`/compute_km_table` は 2 モード(model_validator で片方のみ必須)**:
- 単品: `{lip_lab, product_lab, line_category}` … Swagger デモ/個別呼び出し向け
- バッチ: `{lip_lab, products:[{id,L,a,b,line_id?,line_category?,k_s?}], lines?}`
  … 145 商品を 1 回で計算。UI 実装の本線。lines 省略時はプリセットへフォールバック。
- レスポンス: `{mode, table:[{id, line_id, s, s_source, applied:[{t,L,a,b}]}]}`

**`LINE_S_PRESETS`(仕上げタイプ→S、km.py)**: 実測スケールに統一済み →
gloss=0.25 / **tint=0.4(★実測校正)** / velvet=1.0 / matte=2.0 / other=0.6。
旧 1〜8 は実測比 10〜20 倍過大と判明したため、tint=0.4 をアンカーに順序維持で
再スケール。**校正画像が揃わなかったため tint 以外は推論値で確定**(不透明度比
gloss 0.6x / velvet 2.5x / matte 5x、other は中間)。淡色でカテゴリ差が出ることは
確認済み。将来 estimate_s_layered で実測できれば上書き可(必須ではない)。
※ 鮮やか色(カタログ72%)は K/S が大きく t=1 で全カテゴリほぼ満色=S にほぼ非感応。
S 差が効くのは淡色・低 t。
**`classify_line_category(line_id)`**: line_id → 5 値(tint/matte/gloss/velvet/other)。
キーワード対応(juicy→tint, blur/fudge→matte, glasting/dewy→gloss, velvet→velvet)。
products.csv / products_with_lab.csv の line_category 列、resolve_line_s、/recommend
が共通で使う。bare_mool は該当語なし → other。
**`LIP_PRESETS`(km.py)**: 唇地肌の代表色 Lab 5 種
(pale_pink / healthy_pink / reddish / beige / dark)。/recommend の下地などに使う。

**`/recommend`(app.py, Phase4)**: 唇色 → 全カタログ商品の applied_lab を計算 →
スコア昇順で TOP_n。`{lip_lab, t=1.0, target_lab?, pc_season?, line_category?,
hue_min/max?, L_min/max?, top_n=5}` → `{count, catalog_size, filter_method,
pc_season, sort_target, results:[{id,name,line_category,original_lab,applied_lab,
delta_e, pc_score?, delta_e_to_lip, catalog_pc_tags}]}`。
ソートキー: `pc_season` 指定 → **pc_score**(論文ベース 4軸領域距離)、target_lab 指定
→ **ΔE2000**(applied vs target)、それ以外 → **ΔE2000**(applied vs lip = 唇に近い/自然)。
点対点の色差は ΔE76 → **CIEDE2000 へ移行済**(知覚一様、業界標準)。pc_score は
領域距離なので別物として Euclidean のまま据置。カタログは起動時に
products_with_lab.csv からロード。

**★PC(パーソナルカラー)連携 — 採用方針(2-a 論文ベース Lab 領域)**
- カタログの `pc_season` タグは**ロジックに使わない**(=「答え」を使わない)。
  **答え合わせ用に保持**(catalog_pc_tags でレスポンスに同梱、UI に小さく参考表示)。
- `km.PC_LIPSTICK_TARGETS`: 4PC × **{L,a,b 範囲 + C\*(彩度)の C_min/C_max(清濁)}**
  を論文/色彩学指針で定義。日本流PCの「色相・明度・彩度・**清濁**」4軸を再現。
  清色(春・冬)=C_min を課す、濁色(夏・秋)=C_max を課す。
  出典: **Color Me Beautiful (Jackson 1980)** 清濁理論、日本流 NPCA、Weatherall&Coombs
  1992、Rees 2003、Del Bino&Bernerd 2013、業界一般指針 coral/terracotta/rose/burgundy。
- `km.compute_chroma(lab) = √(a²+b²)` で C* を計算。
- `km.compute_pc_score(applied_lab, pc_season)`: applied が(L,a,b 矩形 ∩ C* 帯)内なら 0、
  外なら 4次元 ユークリッド距離。未知 PC は `None`。
- `/evaluate`(新)+ `evaluate_all.py`(バッチ): 「予測 TOP-N 中、カタログタグに
  expected_pc or イエベ・ブルベ問わずを含む割合」を測る妥当性メトリクス。
  **空タグ商品はバックフィル**(編集者未判定=評価対象外として分母から除外し、
  次のタグ付き商品で繰り上げて TOP_n を埋める)。MVP 合格ライン 0.70。
  清濁 C* + バックフィル後の最新測定: **全平均 0.810 (good)、20セル中19セルが good**。
  イエベ秋も平均 0.71 で good 帯に到達(0.46→0.58→0.71)。

### PC 連携の役割分担
- Kawanoさん: 写真 → 唇 Lab + PC 判定(写真ベースの判定担当)
- Haruki: 唇 Lab + PC を入力に、論文ベース推奨ロジックを構築(本実装)
- カタログ pc_season タグはあくまで「答え合わせ用」

### 6. UI 合成(`ui_app.py`、Lv2)— 詳細は DESIGN.md §6
- **`extract_lip_mask(rgb)`**: 任意顔写真から唇 α マスクを自動抽出。
  **「唇中心 y を a\*·chroma 行ピークで自動検出 → ±5%H の狭い帯だけスキャン」**方式
  (固定 bbox だと顎/鼻影を巻き込んだ反省を踏まえた根本変更)。色しきい値
  a*≥15/C*≥18/L 22-72 + **8連結 closing(3)/opening(2)** で輪郭平滑+erosion(1)+σ=1.8 羽化。
  サイドバーの「**マスク範囲 微調整**」スライダー(-2〜+2)で帯厚・横bbox・しきい値を
  同時に画像ごとに調整可。「唇マスクの輪郭を確認」(upload時 既定ON)で緑線診断。
- **`composite_lip(rgb, α, applied_lab, texture_strength)`**: 平均シフト+偏差保持の
  Lab 再着色(`L_new = L_applied + ts·(L_orig - L_mean_lip)`、a,b は applied 置換)→
  α でアルファ合成。質感の強さ ts は仕上げカテゴリで自動
  (`TEXTURE_BY_CATEGORY`: matte 0.75 / velvet 0.9 / tint 1.0 / gloss 1.5)。
- **`COAT_OPTIONS`**: 塗り厚 t を化粧用語化したラジオボタン(1度=0.3 / 2度=0.6 /
  3度=0.9 / しっかり=1.5)。規約 t1=0.3 と整合。
- **拡大モーダル**(`@st.dialog show_zoom_dialog`): TOP-N カード「🔍 拡大」で
  Before/After 並列+Lab+チップ+(PC指定時 pc_score/タグ)表示。
- **写真ソース**: アップロード(任意顔写真)/既定 model.png/ダミー楕円 の3モード。
  アップロード時は **measure_lip_lab** で唇 Lab を実測 → /recommend の lip_lab に直接渡す
  (=計算と表示の一致、option B)。
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

## ✅ PC 連携: 最終評価(2026-05-29 完了)

### 全体スコア
- 全平均一致率: **0.810 (good, ≥0.7)**
- 検証パターン: 5 唇プリセット × 4 PC = **20 セル**
- 20 セル中 **19 セルが good (≥0.7)**
- 残り 1 セルも acceptable(≥0.5)

### PC 別平均
- イエベ春: **0.82 (good)**
- イエベ秋: **0.71 (good)**
- ブルベ夏: **0.92 (excellent)**
- ブルベ冬: **0.80 (good)**

### 採用した設計原則
1. 物理シミュ(K-M モデル)で塗布後 applied_lab を計算
2. 論文ベースの PC 別 Lab 領域(Color Me Beautiful 1980、日本流 PC 4 軸分類)との
   4 軸距離スコア
3. カタログタグは**評価用のみ**(推奨ロジックには不使用)
4. 評価メトリクスはタグ欠損商品をスキップする公平な設計(バックフィル)

### Known limitations
- `healthy_pink × イエベ秋 = 0.60`(唯一の acceptable セル)
  - 原因: 明るめ唇 × 暗めシーズンの境界ケース
- カタログの「秋のみ」タグ商品が少ない
  - `n_empty_tag_skipped` で可視化済み(イエベ秋系で 5-6件のスキップ発生)
- いずれも MVP 段階の許容範囲内。深追いせず Known limitation として記録。

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
| 7.5 | S校正基盤 (estimate_s_scalar/_layered + sample_lab CLI) | ✅ 完了 (tint S≈0.4 実測、3点フィット実証) |
| 4 | /recommend(唇色→全商品applied→ΔE TOP5) + line_category + LIP_PRESETS | ✅ 完了 (catalog140件、TestClient疎通) |
| 4.5 | PC連携(論文ベース Lab領域) + /evaluate + evaluate_all.py | ✅ 完了 (全平均一致率 0.75 で MVP 70% 突破) |
| 4.6 | PC: 清濁(C*)軸 + 空タグバックフィル | ✅ 完了 (全平均 0.810、20/20 good or acceptable) |
| UI-Lv2 | Streamlit ui_app.py(実写唇に塗布シミュ合成。α羽化ブレンドで顔保持) | ✅ 完了。実写モデル(CC BY 3.0)に色を重ねてリアル表示。色しきい値で唇マスク自動抽出 |
| **v1.3-A** | **設計書 v1.3 個人化学習層: 4 θ ベイズ更新 + Part IV/VI 統合スコア** | ✅ 完了 (`bayesian.py` + `recommend_v2.py`) |
| **v1.3-B** | **強制ペア比較(色5+世界観5、仮データ)+ 事前分布構築** | ✅ 完了 (`pair_compare.py`)。ペア中身は Kawanoさん と要相談 |
| **v1.3-C** | **20次元 pref ベクトル(機能15+世界観5)の派生計算+ CSV 付与** | ✅ 完了 (`catalog_x20.py`)。軸定義は Kawanoさん と要相談 |
| **v1.3-D** | **Kawanoさん interface: `/v13/pair_compare/{init,apply}` `/v13/update_user` `/v13/recommend`** | ✅ 完了 (`app.py` + `KAWANO_INTERFACE.md`) |
| **v1.3-E** | **E2E 統合疎通(`test_v13_flow.py`)** | ✅ μ_thickness 学習で TOP-N 順位が動くことを確認 |

## v1.3 Kawanoさん interface(2026-05-29 実装)

lip API は**ステートレス計算サーバー**として実装。caller(Kawanoさん AR or 中継 GAS/BE)が
`UserState` を保持し、リクエスト毎に丸ごと送る → 計算結果と更新後 state を返す → caller が保存する。

エンドポイント:
- `GET  /v13/pair_compare/init` — 10 ペア取得
- `POST /v13/pair_compare/apply` — 選択結果 → 4 θ の事前分布
- `POST /v13/update_user` — 観測ログ(AR like/dislike + thickness)→ ベイズ更新
- `POST /v13/recommend` — UserState だけで TOP-N(km_table 内部生成)

詳細は **`KAWANO_INTERFACE.md`**。Kawanoさん からまだ何も来ていない前提のため、ペア定義・x_20軸・
データ形式・通信方式・状態の置き場所はすべて「叩き台」。同ファイル §5 に議論ポイント7項目を明記。

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
  - **カタログ色分布(調査済み)**: 140/145 で C* 中央値48, 鮮やか(C*≥40) **72%**,
    ヌード(C*<25) わずか 2%, a*中央43/hue29°=赤コーラル主体。→ **校正は淡い色**で
    取り(全chが情報を持ちSがクリーンにでるS≈hue非依存)、鮮やか色に適用が正解。
    鮮やか色は暗chが飽和=t不問でほぼフル発色なので S 精度の影響が小さい(朗報)。
    カタログ内の淡色は dewyful_16/juicy_lasting_31/dewyful_14 の3件のみ(参照用)。
  - **A(estimate_s_scalar)完了**。コーラル唇画像で検証 → dr_min=0.03 がノイズの
    R ch を正しく除外、残1chで out_of_range 警告(=校正不能を正しく検知)。鮮やか
    +光沢の画像は校正不向きと裏付け。妥当域 10-500 は仮、clean データで確定予定。
  - **案A 完了 → 3点フィットで実証**(estimate_s_layered):
    - コーラル(juicy_lasting 鮮やか)塗る前/1度/2度 → G ch採用 **S≈0.42**、R∞=
      [53.7,51.8,24.1](2度より少し濃い=真のフル色)、塗り重ねで R∞ に収束(ΔE 27→0.2)
      = **「フル塗り=商品色に寄る」成立**。
    - ヌカダミア(同line ヌード)はティッシュオフ画像で比率不明 → ratio=2 で正しく拒否。
    - **重要スケール**: 実測 tint S ≈ 0.2〜0.4。旧プリセット仮定 1〜8 は **10〜20倍過大**。
      校正後の presets は概ね 0.1〜1 オーダーになる見込み。
    - **t軸の含意(要・後決め)**: S≈0.4 だと t=1(≈3塗り)では完全発色しない。UI の「フル」は
      t=1 ではなく ~5塗り相当に割り当てる必要(規約3 のマッピングを presets 確定後に決める)。
  - **(B) 決着**: 校正画像は tint(コーラル)以外集まらず → **tint=0.4 のみ実測、他は
    推論値で確定**(LINE_S_PRESETS 参照)。gloss/velvet/matte の精緻化は任意の将来課題。
    良い「1度/2度・淡色・テカリ少(腕推奨)」画像が手に入れば sample_lab.py →
    estimate_s_layered で上書き可。探索の知見: 「全色/色味比較」投稿は単発塗り=不可、
    「1色の塗り重ね/段階別 발색/레이어링」が必要。LIPS 投稿 URL なら CC が画像自動抽出可。
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

## 画像アセット管理ポリシー(履歴書き換え事件 後)

- **assets/lips/*.{png,jpg,jpeg,webp} は git 追跡しない**(`.gitignore` 済)。
- 理由: HF Spaces の binary サイズポリシーで >1MB の PNG が push 拒否される。
  過去に CC BY 3.0 / PD の model.png をコミットしたが、HF push 不可で履歴書き換え
  (filter-branch)で完全削除。復旧用タグ `backup-before-history-rewrite` を origin
  に残してある(過去SHA 6628c3a を指す)。
- 運用:
  - **デフォルト = アップロードモード**(UI のドロップで都度処理、ファイル保存無し)
  - 固定モデルが欲しい時は `assets/lips/model.png` をローカル配置(git 追跡されない)
  - 画像が無ければ `_dummy_lip` が楕円唇を動的生成
- 将来真面目に共有するなら HF Hub Xet ストレージ経由(README 参照)。

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
