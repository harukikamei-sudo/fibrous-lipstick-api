# DB_V13_COLUMNS.md — DB に v1.3 対応列を追加する手順

> `lipstick_DB_updated.xlsx` は設計書 v1.0〜v1.2 世代の構造で、v1.3 で追加された
> **θ_thickness(塗り厚)と唇 Lab、AR 観測**を保存する列が無い。
> この手順で列を追加すると、lip API の v1.3 UserState / Observation と完全対応する。

最終更新: 2026-06-02

---

## 0. なぜ追加が必要か

| v1.3 で必要なもの | 現状の DB | 対応 |
|---|---|---|
| 唇 Lab(K-M 計算の下地) | users に skin_Lab はあるが lip_Lab が無い | **users に lip_L/a/b を追加** |
| θ_thickness(塗り厚好み) | users に列が無い | **users に mu_thickness / sigma2_thickness を追加** |
| AR 観測(thickness, observed_lab, y) | observations は pair/dialog/behavior 用のみ | **observations に列を追加** |

> 注: skin_Lab(肌)は PC 診断用、lip_Lab(唇)は K-M 計算用。役割が違うので両方必要。

---

## 1. users シートに追加する列(現状 BE=57列目まで)

末尾(BF 列目以降)に以下 5 列を追加する:

| 列 | 列名 | 意味 | 初期値 |
|---|---|---|---|
| BF (58) | `lip_L` | 唇 Lab の L(K-M 下地) | 撮影で取得 |
| BG (59) | `lip_a` | 唇 Lab の a | 撮影で取得 |
| BH (60) | `lip_b` | 唇 Lab の b | 撮影で取得 |
| BI (61) | `mu_thickness` | θ_thickness 事後平均(0=薄 1=濃) | **0.5** |
| BJ (62) | `sigma2_thickness` | θ_thickness 事後分散 | **0.1** |

ヘッダーグループ(1行目)は `θ_thickness [v1.3]` のように付けると見やすい。

### 既存の skin_Lab との関係
- `skin_L/a/b`(E/F/G 列、既存)= PC 診断用の肌色。**そのまま残す**。
- `lip_L/a/b`(新規)= K-M 計算の下地。AR で唇を撮影して取得。

---

## 2. observations シートに追加する列(現状 K=11列目まで)

末尾(L 列目以降)に以下 6 列を追加する:

| 列 | 列名 | 意味 | 使う source |
|---|---|---|---|
| L (12) | `thickness` | AR スライダー値(0〜1) | ar_view_like |
| M (13) | `observed_lab_L` | 観測 Lab の L(K-M 結果) | ar_view_* |
| N (14) | `observed_lab_a` | 観測 Lab の a | ar_view_* |
| O (15) | `observed_lab_b` | 観測 Lab の b | ar_view_* |
| P (16) | `y` | 観測の符号(like=+1 / dislike=-1) | ar_view_* |
| Q (17) | `viewed_seconds` | 滞在時間(Phase 2 重み付け用) | ar_view_* |

### source 列(D 列)に追加される値
既存: `pair_color` / `pair_worldview` / `dialog` / `behavior`
**追加**: `ar_view_like` / `ar_view_dislike`

---

## 3. x_20(θ_pref 20軸)は変更不要 ✅

DB の users シートの θ_pref 20 列(mu_pref_hue 〜 mu_pref_korean)は **そのまま正式定義**として採用済み。
lip API 側を DB に合わせて `catalog_x20.py` を更新済み(2026-06-02)。

DB の 20 軸正準順序(= lip API の x_20 順序):
```
1.  hue                  ← products(Lab由来)
2.  saturation           ← products(Lab由来)
3.  brightness           ← products(Lab由来)
4.  pigmentation         ← products(Lab由来)
5.  glossy               ← lines
6.  moisture_finish      ← lines
7.  sheer                ← lines
8.  velvet               ← lines
9.  blur                 ← lines
10. is_tint              ← lines
11. is_balm              ← lines
12. is_gloss             ← lines
13. moisturizing         ← lines
14. longlasting          ← lines
15. transfer_resistance  ← lines
16. girly                ← products(世界観)
17. makeup_intensity     ← products(世界観)
18. konare               ← products(世界観)
19. sweetness            ← products(世界観)
20. korean               ← products(世界観)
```

---

## 4. products シートの Lab を埋める

現状 products シートは Lab(K/L/M 列)が空。lip API 側の `products_with_lab.csv` に
145 商品の Lab 抽出済みなので、これを DB に流し込む。

→ `sync_db_products.py`(別途用意)で CSV → DB products の L/a/b + 派生 x_20 列を一括反映。

> 注: products シートの個別 x_20 列(hue/saturation/brightness/pigmentation/
> girly/makeup_intensity/konare/sweetness/korean)も空。これらは Lab から
> 導出できる(lip API の `catalog_x20.derive_x20` と同じロジック)。

---

## 5. 追加後の users 行イメージ(v1.3 完全対応)

```
user_id | created_at | ... | skin_L/a/b | warmness | pc_season |
  mu_color_L/a/b | sigma2_color_L/a/b |
  mu_pref_hue ... mu_pref_korean (20) | sigma2_pref_* (20) |
  mu_explore | sigma2_explore |
  ★lip_L | ★lip_a | ★lip_b | ★mu_thickness | ★sigma2_thickness
```

これで lip API の `UserState` と 1:1 対応する:
- `lip_lab` = lip_L/a/b
- `theta_color` = mu_color_* + sigma2_color_*
- `theta_pref` = mu_pref_* + sigma2_pref_*(20軸)
- `theta_explore` = mu_explore + sigma2_explore
- `theta_thickness` = mu_thickness + sigma2_thickness

---

## 6. 作業順序

1. ☐ users シートに 5 列追加(lip_L/a/b, mu_thickness, sigma2_thickness)
2. ☐ observations シートに 6 列追加(thickness, observed_lab_L/a/b, y, viewed_seconds)
3. ☐ products シートに Lab を流し込み(`sync_db_products.py`)
4. ☐ GAS Web App で users/observations を読み書き(`gas_webapp.gs`)
5. ☐ Kawano の `userStateStore.ts` を localStorage → GAS 版に差し替え

1〜2 は Friday が手で列追加。3〜4 は lip API 側で用意。5 は Kawano 側。
