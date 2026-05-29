# HANDOFF.md — 新セッションへの引き継ぎ

> 新しい Claude (Cursor / Claude Code) セッションで作業を継続するための起点。
> **このファイルを最初に読んでから、リンク先 docs を参照する**。

最終更新: 2026-05-29 (Opus 4.7 / 1M context)
最新 commit (origin & hf 同期済み): `e8ccb26` (fix(ui): smooth mask contour ...)

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
| ③ | **[DESIGN.md](DESIGN.md)** | 理論・式の導出・計算過程・なぜその値か |
| ④ | **[LOG.md](LOG.md)** | 各意思決定の目的・試行・失敗・採用根拠(時系列) |
| ⑤ | **[API_GUIDE.md](API_GUIDE.md)** | エンドポイント使い方(curl 例・レスポンス例) |

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

## 5. **直近の重大な発見 — 設計書 v1.3 とのギャップ**

ユーザーから設計書 PDF を共有された (2026-05-29 14:10) 。
v1.3 の正式構造は以下の 6 Part:

```
Part I    PC診断              → θ_color 事前分布(経路A)
Part I'   唇Lab取得 [新規]    → Kawano撮影
Part I''  K-Mバッチ生成 [新規]→ user_product_lab_table 146×21
Part II   強制ペア比較(10問)  → 事前分布(経路B、ミナ向け中核)
Part III  統合ベイズ更新      → 4パラメータ学習
Part IV   推奨スコア統合式    → f = -α·ΔE2000(eff_Lab, μ_color) + μ_pref·c.x_20
Part V    AR試着 [拡張]       → Kawano AR + スライダー + いいね/微妙
Part VI   セレンディピティ    → R_final = f - β(μ_explore)·familiarity
```

**ユーザーごとに ベイズ更新される4パラメータ**:
- `θ_color` (Lab 3次元、似合う色の中心)
- `θ_pref` (20次元、機能15 + 世界観5)
- `θ_explore` (1次元、探索性)
- `θ_thickness` (1次元、塗り厚好み)

**役割分担(設計書)**:
- ハルキ: K-M計算・推奨計算 (**設計書では GAS で実装**)
- Kawano: AR表示・質感合成・スライダーUI・いいね/微妙UI・観測ログ送信

### 現状実装との乖離 5 点

1. **個人化学習が無い** — Bayesian update 未実装、全ユーザーに同じ推薦
2. **強制ペア比較が無い** — ミナの事前分布構築の中核(経路B)が無い
3. **20次元 pref ベクトルが無い** — `μ_pref·c.x_20` 項が推薦スコアから落ちてる
4. **PC連携実装方針が違う** — 設計書は事前分布、実装はハード距離マッチング
5. **GAS vs Python** — 設計書は GAS+Spreadsheet、実装は FastAPI+Python (Kawano 連携 interface 接続未確認)

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

## 6. **次セッション開始時の最初のユーザー入力(待ち状態)**

最後の私(Opus 4.7)の発言で、4つの選択肢を提示した:

> どの方向で進めるかで次の動きが変わります。どうしたいですか？

- **A. 現状で Mina さん向けデモ実施**: PC × 唇色 × 物理計算の静的版で見せる。
  個人化進化体験は無いが見栄え・物理は強い
- **B. 設計書の残り(Part II/III/IV完全/VI)を実装**: 個人化学習込みの完全 MVP。1〜2 週間
- **C. GAS への移植 + Kawano 連携**: 設計書の役割分担に完全準拠。中規模工数
- **D. ハイブリッド**: 現状の Python API は維持して**ベイズ更新と observations 収集だけ追加** →
  「ミナの好み学習」を Python 側で実現、Kawano AR は将来連携

→ **ユーザーの返答待ち**。新セッションの最初に「どれで進めるか」を聞くか、
ユーザーから方針が来たらそれに従う。

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

# ローカル UI 起動
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
