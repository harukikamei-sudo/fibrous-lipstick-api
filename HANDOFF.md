# HANDOFF.md — 新セッションへの引き継ぎ

> 新しい Claude (Cursor / Claude Code) セッションで作業を継続するための起点。
> **このファイルを最初に読んでから、リンク先 docs を参照する**。

最終更新: 2026-07-10 — **Kawano AR 版が届き、フロントを fibrous-lipstick-ui に統合(PR #1)**

## 2026-07-10 セッション(Kawano AR 版 → フロント統合)★最新

**Kawano さんから AR 本実装版が届いた**: 新リポ **`YK-0204/fibrous-lipstick-ui`**(WRITE 権限あり)。
リアルタイム動画 AR 試着(WebGL シェーダー、合成数式は recolorLips と同一)+ ❤️/✕ ベイズ学習ループ + KEYROOM デザイン。
詳細評価は LOG エポック 18。

**統合(人間承認済み)**: **Kawano 版を土台**に color-capture feat/v14-recommend の追加分を移植 →
`feat/v14-merge` ブランチ、CI(tsc)green、**PR #1**: <https://github.com/YK-0204/fibrous-lipstick-ui/pull/1>
- 移植: SceneStep / 静止画顔プレビュー(recolorLips・一覧比較用。AR とは併用=役割分担)/ /v13/popular(定番も顔に重ねる)/ PC ✓一致 / tsc CI
- 見送り: shortlist(keep/decide)フロー(AR ❤️/✕ が観測を担う。extras 追加は Kawano さんと後日協議)、Concierge コンポーネント(インライン吹き出しで同等)
- **⚠️ env**: 本番 Space に `/v14/*`・`/v13/popular` は無い(404)→ フロントの `.env.local` は **v14 プレビュー Space**(`…-api-v14.hf.space`)に向ける。API main マージ後に戻す

**フロントの主戦場は fibrous-lipstick-ui に移行**。color-capture(feat/v14-recommend)は参照用として残置。

**Kawano 報告②「絞り込みカウンタが 5→6 に増える」対応済み(2026-07-10)**: バグでなく competitive set の
定義上の挙動(生値は 5→10 まで暴れることをライブ実測)。/v14 の `candidate_count` を**表示ラチェット化**
(min(過去最小, 生値)=単調非増加保証、floor は `session.cc_floor` 相乗り、生値は `candidate_count_raw` 併載)。
副発見の **spoken_axes 落ちバグ**(/next が session 再構築で毎回 [] に)も修正。テスト6件・CI green・
プレビュー Space 再デプロイ・ライブ3パターン検証済み。詳細 LOG エポック18。

**人間/Kawano 待ち**: ① PR #1 のレビュー&マージ(Kawano さん)② ブラウザ通し確認(Haruki・.env を v14 プレビュー Space に)
③ AR 観測への extras{action,kept,decided} 追加の要否 ④ コンシェルジュ文面3パターン ⑤ API feat/v14 → main マージ計画

---

## 2026-07-04〜06 セッション(F3 API 化 / 顔プレビュー / プレビュー環境)

**前提**: ブランチは前セッションと同じ(API=`feat/v14` / フロント=`feat/v14-recommend`=YK-0204/color-capture)。
**API 変更のたびに v14 プレビュー Space を再デプロイ**(下記)。全 CI green。

**実装済(全 CI green)**:
- **F3 コンシェルジュ発話を API 化**: フロント `conciergeScript.ts`(TS)→ `POST /v14/concierge_speech`(`concierge_speech.py`)へ移植。
  RN(Kawano)/Next の二重実装を回避。3フェーズ(explore/recommend/decide)。**中間実況の重複防止・予算(最大3)は
  `session.spoken_axes` に相乗り**(caller は session を往復するだけ・option b 承認)。**TS≡API 全枠パリティテスト**(13件)。
- **コンシェルジュ生 pair_id 漏れ修正**: 「さっき**wv_09_sweet_vs_classy**。だからこれ」→ `_PAIR_LABELS` で
  「さっき「甘い vs クラシー」で選んだのが効いてる」に。未知値は軸ラベルにフォールバック。TS/API 両方。
- **顔全体プレビューに統一**: 唇クロップ断片 → **顔写真全体 + 唇だけ再着色**(ペア比較・推薦・定番すべて)。
  `SampleResult.face`(顔画像~720px + 唇ポリゴン)+ `renderFaceLipPreview`(ポリゴンからマスク再構築 → recolorLips 流用)。
  lipDetection 無変更(既に顔座標系の mask/polygon を返していた)。face 無ければクロップに fallback(後方互換)。
- **写真アップロード対応**: カメラ不使用でも写真選択 → 1280px ダウンスケール → 同じ detectLips 経路。
- **唇プレビュー自然化(recolorLips)**: マスク縁フェザリング(box blur 羽化α)+ 不透明度 `LIP_OPACITY=0.85` +
  L 偏差保持。定数化(`LIP_TEXTURE_STRENGTH/OPACITY/FEATHER_RADIUS`)。
- **パーソナルカラー表示**: RecommendStep に `pc_season` + カード `catalog_pc_tags` +「✓一致」。
- **みんなの定番も顔プレビュー**: `GET /v13/popular` に任意 `lip_l/lip_a/lip_b(+mu_thickness)` を追加 →
  各定番に `effective_lab`(K-M 塗布後 Lab)を付与、定番も顔に重ねる。**ランキングは不変**。test 18件。
- **recommend「計算中」固定バグ修正**: 取得 effect の `finally` を無条件 `setLoading(false)` に + 導入発話 concierge を fire-and-forget。

**プレビュー環境(本番非汚染)**: feat/v14 を **別 HF Space** `Tamable/fibrous-lipstick-api-v14`
(`https://tamable-fibrous-lipstick-api-v14.hf.space`)にデプロイ。本番 Space(main)・main ブランチ・本番 Vercel env は無変更。
- **デプロイ手順(API 変更のたびに実施)**: HF は >1MB PNG を履歴ごと拒否 → **orphan 単一コミット(feat/v14 ツリー − 全図PNG・履歴なし)**を
  `git push hf-v14 <orphan>:main --force`。`git rm` の新コミットは過去 blob が履歴に残り弾かれる → orphan で履歴を捨てるのが要点。
- フロントは `color-capture/.env.production` の `NEXT_PUBLIC_LIP_API_URL` を上記 Space に向ける(**★ main マージ前に必ず削除**)。

**人間/Kawano 待ち(このセッション時点)**: ① F3 コンシェルジュ **文面3パターン**(現行は Haruki 確定の暫定版)
② Vercel プレビュー deploy(`npx vercel` or dashboard・env は .env.production で自動)③ 実 PAIR_BANK 再設計 ④ Phase2 実ユーザー再検証。

---

## 2026-06-15〜29 セッション(v14 推薦体験改修)

**ブランチ**: API=`feat/v14`(origin harukikamei-sudo・main より 39 先行 / main は不変)、
フロント=`feat/v14-recommend`(別 repo **YK-0204/color-capture**・`~/Desktop/color-capture/`)。

**実装済(全 CI green)**:
- API: シーン事前分布(A1)/ 推薦理由 reasons(A2)/ 絞り込みカウンタ candidate_count(A2-fix)/
  逐次ペア比較 `/v14/pair_compare/{start,next}`(A3・最大EIG・effective_lab)/ 全体ランキング `/v13/popular` /
  `Observation.extras`(F4-fix・ベイズ更新不使用)。テスト: v13_endpoints 17 + v14_flow + scene_priors 等。
- フロント: SceneStep(F1)/ recolorLips 純関数(F2)/ PairCompareStep v14化+唇プレビュー(F2本体)/
  Concierge 器+選択ロジック(F3・文面は Kawano 3パターン待ち)/ RecommendStep 購入フロー shortlist(F4-fix)。
  color-capture に CI(`ci.yml`・tsc --noEmit)追加。

**C/D 確定(人間承認・LOG エポック16)**: N_PAIRS=8 / KAPPA=0.65 / β_BT=0.25 / x20=20軸。
中核成果=**scene+7 で flat+10 と hit 同等(問数3問削減)**。

**collapse 調査の決着**: 似た合成ペルソナ(mina/aya)で TOP5 が同一化する現象を発見 →
diag/pairsep/v1/v2/reasons の系列で「**色も好みも本質的に同一=人工的 edge、アルゴリズム欠陥でない**」と確定。
**戦略(A)採用**(色では分けない・差別化は reasons+shortlist・色ペア据え置き)。(B)=実ユーザーで Phase2 再検証。
協議資料: `KAWANO_V14_REVIEW.md` + `KAWANO_PAIRS_NOTE.md` + 図 `scripts/figures/kawano_*.png`。

**運用メモ(重要)**: このマシンの sandbox は **skimage import / app import / tsc / npm が Gatekeeper でハング**。
→ 検証は CI 経由(`test.yml` の workflow_dispatch `a4` ジョブ + color-capture `ci.yml`)。`openapi.json` も
CI で再生成済み(`a4` ジョブ内で `app.openapi()` dump、6/15版の陳腐化解消)。詳細は [[feedback_macos_gatekeeper_ci]]。

**人間/Kawano 待ち**: ① 色5ペア据え置き追認 ② F3 コンシェルジュ3パターン文面 ③ フロント `gen:api-types`
再実行(新 openapi.json で)④(将来)PAIR_BANK 明度軸 / Phase2 実ユーザー検証。

---

## 2026-06-05〜09 セッション(個人化層ハードニング + ピッチ図)

詳細は [LOG.md](LOG.md) エポック 13・14。要点:

- **ベイズ更新の3欠陥を修正**(LOG エポック13):
  1. dislike が θ_color を壊していた → `update_theta_color` から ar_view_dislike を除外
  2. θ_explore が未更新だった → `recommend_v2._flag_serendipity`(TOP-N 中央値分割)で配線
  3. 能動学習(EIG)を**新エンドポイントでなく** `/v13/recommend` の `rerank`/`explore_weight`
     パラメータで統合(rerank=False は従来挙動を完全維持=後方互換)
- **事前 θ_color の過信を較正**: pair_color の σ²_obs を ≈20.83 に上げ SD≈0.40→2.0
  (`bayesian.SIGMA2_BY_SOURCE["pair_color"]`)。式として回帰テスト化。
- **色 ΔE の3用途マップ**を SIMULATOR_GUIDE §割り切り4 に明記 + 回帰テスト
  `test_explore_does_not_ignore_color`(冒険好きでも色を無視しない)。
- **ピッチ用 in-silico 図**(`docs/figures/`、生成は `scripts/figures/*.py` + ルート
  `plot_explore_vs_fit.py`)を本番コード経由で作成。⚠️ **重要な正直な発見**: 旧スライドの
  「能動学習が最速(7回以内 random にも勝つ)」は本番 ΔE2000 では**不成立**(random が真値収束では
  終始最良。EIG は KL=信念移動の最大化で真値最小化とは別目的)。→ 図は「現行 exploit vs
  能動学習 EIG」+ 体験軸(似合わない色を出す率は random が突出)+ **2軸トレードオフ総括図**で
  「現行=学ばない / random=似合わない / 能動学習=両立」を示す構成に。詳細 LOG エポック14。
- 図(PNG)は **GitHub(origin)のみ**。HF Spaces はバイナリ push を拒否(Xet 必須)、かつ
  HF Space=API はこれらに非依存で機能的に最新。

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
