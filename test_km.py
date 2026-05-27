"""km.py / estimate_s.py の単体テスト。

検証する物理的性質:
  1. 境界: t=0 で重ね塗り後 Lab ≒ 唇地肌(膜が無い)
  2. 飽和: t を大きくすると重ね塗り後の色 → 商品フル発色(R∞)
  3. 単調: t 増加で L が単調に下地→発色へ向かう
  4. S 往復: 既知 S で順計算した薄付き Lab から estimate_s が S を復元
  5. テーブル: compute_km_table の構造と端点
"""

import sys
import numpy as np

from lab_utils import lab_to_reflectance, reflectance_to_lab
import km
from estimate_s import estimate_s, estimate_s_scalar


def deltaE_76(lab1, lab2):
    lab1 = np.asarray(lab1, dtype=float)
    lab2 = np.asarray(lab2, dtype=float)
    return float(np.sqrt(np.sum((lab1 - lab2) ** 2)))


# 代表的な唇地肌と商品フル発色(products_with_lab.csv レンジ)
LIP_LAB = np.array([60.0, 18.0, 12.0])      # 標準的な唇
PRODUCTS = [
    (np.array([33.40, 35.58, 21.86]), "rmd_blur_fudge_03 ムスキー"),
    (np.array([44.04, 44.46, 26.61]), "rmd_zero_velvet_01"),
    (np.array([13.82, 24.35, 12.46]), "rmd_milktea_velvet_09 ダーク"),
    (np.array([69.28, 42.21, 23.96]), "rmd_bare_mool_01 明発色"),
]

# 妥当なライン散乱係数(チャネル毎)。実推定前の仮値
LINE_S = np.array([8.0, 8.0, 8.0])


def test_t0_is_lip():
    print("性質1: t=0 → 唇地肌に一致")
    fails = []
    for full_lab, name in PRODUCTS:
        ks = km.ks_from_lab(full_lab)
        applied = km.compute_applied_lab(LIP_LAB, ks, LINE_S, 0.0)
        dE = deltaE_76(applied, LIP_LAB)
        ok = dE < 1.0
        mark = "OK" if ok else "NG"
        print(f"  [{mark}] {name:32s} t=0 ΔE(lip)={dE:.3f}")
        if not ok:
            fails.append((name, dE))
    return fails


def test_large_t_is_full():
    print("\n性質2: t→大 → フル発色(R∞)に収束")
    fails = []
    for full_lab, name in PRODUCTS:
        ks = km.ks_from_lab(full_lab)
        applied = km.compute_applied_lab(LIP_LAB, ks, LINE_S, 1.0)
        # full_lab を反射率→Labに通した値(往復誤差を吸収した基準)と比較
        full_ref = reflectance_to_lab(lab_to_reflectance(full_lab))
        dE = deltaE_76(applied, full_ref)
        ok = dE < 5.0  # t=1, S=8 だと完全飽和には僅差
        mark = "OK" if ok else "NG"
        print(f"  [{mark}] {name:32s} t=1 ΔE(full)={dE:.3f}  "
              f"applied=({applied[0]:.1f},{applied[1]:.1f},{applied[2]:.1f})")
        if not ok:
            fails.append((name, dE))
    return fails


def test_monotonic_L():
    print("\n性質3: t 増加で L が下地→発色へ単調")
    fails = []
    ts = np.linspace(0.0, 1.0, 21)
    for full_lab, name in PRODUCTS:
        ks = km.ks_from_lab(full_lab)
        Ls = [km.compute_applied_lab(LIP_LAB, ks, LINE_S, float(t))[0] for t in ts]
        diffs = np.diff(Ls)
        # 全商品ダーク方向(下地 L=60 より暗い)なので L は単調減少のはず
        target_dir = -1 if full_lab[0] < LIP_LAB[0] else 1
        signs = np.sign(diffs)
        ok = np.all((signs == target_dir) | (np.abs(diffs) < 1e-6))
        mark = "OK" if ok else "NG"
        print(f"  [{mark}] {name:32s} L: {Ls[0]:.1f} → {Ls[-1]:.1f} "
              f"(dir {'↓' if target_dir < 0 else '↑'})")
        if not ok:
            fails.append((name, "non-monotonic"))
    return fails


def test_estimate_s_round_trip():
    """S 往復。

    重要な物理的限界: K/S が大きい(暗く彩度の高い)チャネルでは、薄付きでも
    層が完全不透明になり R が R∞ に張り付く。すると S の値が観測色に反映され
    ず逆算不能(どんな大きい S でも同じ色)。これは情報損失でありバグではない。

    そこで:
      (1) 自己整合性 … 復元 S を順モデルに戻すと薄付き Lab を再現(全チャネル)
      (2) S 値の復元 … 飽和していない感度のあるチャネルのみ真値と一致を要求
    """
    print("\n性質4: S 往復(自己整合性 + 感度チャネルの S 復元)")
    fails = []
    t_light = 0.3
    # 感度のあるチャネルが少なくとも 1 つ生じるよう、軽めの S を使う
    true_s = np.array([2.0, 2.0, 2.0])
    r_g_white = np.full(3, 1.0 - km.EPS)
    sensitive_seen = 0

    for full_lab, name in PRODUCTS:
        ks = km.ks_from_lab(full_lab)
        r_inf = km.km_reflectance(ks, true_s, 1e6, r_g_white)  # ≈ R∞
        r_light = km.km_reflectance(ks, true_s, t_light, r_g_white)
        light_lab = reflectance_to_lab(r_light)

        s_est = estimate_s(full_lab, light_lab, t_light=t_light)

        # (1) 自己整合性: 復元 S → 薄付き反射率 → Lab が入力に一致
        r_back = km.km_reflectance(ks, s_est, t_light, r_g_white)
        lab_back = reflectance_to_lab(r_back)
        dE = deltaE_76(lab_back, light_lab)
        ok_consist = dE < 1.0

        # (2) 感度チャネル(基板にも発色にも張り付いていない)で S 復元
        frac = (r_g_white - r_light) / (r_g_white - r_inf + 1e-12)
        sensitive = (frac > 0.05) & (frac < 0.9)
        sensitive_seen += int(sensitive.sum())
        if sensitive.any():
            rel_err = np.abs(s_est[sensitive] - true_s[sensitive]) / true_s[sensitive]
            ok_recover = np.all(rel_err < 0.05)
            rerr_str = f"{rel_err.max()*100:.1f}%"
        else:
            ok_recover = True
            rerr_str = "—(全飽和)"

        ok = ok_consist and ok_recover
        mark = "OK" if ok else "NG"
        print(f"  [{mark}] {name:32s} S_est={s_est.round(2).tolist()} "
              f"自己整合ΔE={dE:.3f} 感度ch={sensitive.tolist()} S誤差={rerr_str}")
        if not ok:
            fails.append((name, s_est.tolist(), dE))

    if sensitive_seen == 0:
        print("  [NG] 感度のあるチャネルが 1 つも無い(テスト設計が無意味)")
        fails.append("no sensitive channel")
    return fails


def test_compute_km_table():
    print("\n性質5: compute_km_table の構造")
    fails = []
    products = [
        {"id": "p1", "line_id": "lineA",
         "L": 33.40, "a": 35.58, "b": 21.86},
        {"id": "p2", "line_id": "lineA",
         "L": 44.04, "a": 44.46, "b": 26.61},
    ]
    lines = {"lineA": LINE_S.tolist()}
    table = km.compute_km_table(LIP_LAB, products, lines, t_steps=21)

    ok_len = len(table) == 2
    ok_steps = all(len(row["applied"]) == 21 for row in table)
    # 各商品 t=0 は唇、t=1 は発色寄り
    row0 = table[0]["applied"]
    ok_t0 = abs(row0[0]["t"] - 0.0) < 1e-9 and abs(row0[-1]["t"] - 1.0) < 1e-9
    dE_lip = deltaE_76([row0[0]["L"], row0[0]["a"], row0[0]["b"]], LIP_LAB)
    ok_lip = dE_lip < 1.0
    # lines 指定が S と s_source に反映される
    ok_s = table[0]["s"] == LINE_S.tolist() and table[0]["s_source"] == "lines"

    for label, ok in [("len=2", ok_len), ("steps=21", ok_steps),
                      ("t端点", ok_t0), ("t0=lip", ok_lip),
                      ("s/s_source=lines", ok_s)]:
        mark = "OK" if ok else "NG"
        print(f"  [{mark}] {label}")
        if not ok:
            fails.append(label)
    return fails


def test_resolve_line_s():
    """S 解決の優先順位とプリセットのフォールバック。"""
    print("\n性質6: resolve_line_s の優先順位とフォールバック")
    fails = []
    lines = {"lineA": [9.0, 9.0, 9.0]}
    cases = [
        # (lines, line_id, line_category, 期待S, 期待source先頭)
        (lines, "lineA", "matte", [9.0, 9.0, 9.0], "lines"),       # lines 最優先
        (None, "lineA", "matte", km.LINE_S_PRESETS["matte"], "category"),  # category
        (None, "zero_velvet_01", None, km.LINE_S_PRESETS["velvet"], "line_id~velvet"),  # 推定
        (None, "unknown_xyz", None, km.LINE_S_PRESETS["other"], "default"),  # default
    ]
    for ln, lid, lcat, exp_s, exp_src in cases:
        s, src = km.resolve_line_s(lines=ln, line_id=lid, line_category=lcat)
        ok = s == exp_s and src.startswith(exp_src)
        mark = "OK" if ok else "NG"
        print(f"  [{mark}] id={lid} cat={lcat} → S={s} source={src}")
        if not ok:
            fails.append((lid, lcat, s, src))

    # プリセットの大小関係: gloss < tint < velvet < matte(透け→隠蔽)
    order = ["gloss", "tint", "velvet", "matte"]
    s_vals = [km.LINE_S_PRESETS[c][0] for c in order]
    ok_order = all(s_vals[i] < s_vals[i + 1] for i in range(len(s_vals) - 1))
    mark = "OK" if ok_order else "NG"
    print(f"  [{mark}] プリセット S 単調増加 {dict(zip(order, s_vals))}")
    if not ok_order:
        fails.append("preset order")
    return fails


def test_estimate_s_scalar():
    """単一スカラー化(plan A): 飽和ch除外 + median + 診断。"""
    print("\n性質7: estimate_s_scalar(飽和ch除外→単一S)")
    fails = []
    white = np.array([96.0, 0.0, 0.0])
    r_g = km.km_reflectance(np.zeros(3), np.zeros(3), 0.0, lab_to_reflectance(white))

    def forward_thin(full_lab, S, t):
        ks = km.ks_from_lab(full_lab)
        r = km.km_reflectance(ks, np.full(3, S), t, lab_to_reflectance(white))
        return reflectance_to_lab(r)

    # (1) 中明度タウプ(全ch 情報あり) → 3ch採用 & S 復元
    full_light = np.array([55.0, 10.0, 8.0])
    thin = forward_thin(full_light, 50.0, 0.01)
    r = estimate_s_scalar(full_light, thin, t_light=0.01, substrate_lab=white,
                          dr_min=0.03, s_valid=(1, 1000))
    ok = r["n_adopted"] == 3 and abs(r["s"] - 50.0) / 50.0 < 0.1
    print(f"  [{'OK' if ok else 'NG'}] 全ch情報: 採用{r['n_adopted']}/3 S={r['s']} "
          f"(true 50) ΔR={r['delta_r']}")
    if not ok: fails.append(("全ch", r))

    # (2) 鮮やか赤 + 大きな S: 暗ch飽和 → 一部除外, S は出る
    full_vivid = np.array([45.0, 55.0, 25.0])
    thin = forward_thin(full_vivid, 80.0, 0.02)
    r = estimate_s_scalar(full_vivid, thin, t_light=0.02, substrate_lab=white,
                          dr_min=0.03, s_valid=(1, 1000))
    ok = 1 <= r["n_adopted"] < 3 and r["s"] is not None
    print(f"  [{'OK' if ok else 'NG'}] 鮮やか: 採用{r['n_adopted']}/3 S={r['s']} "
          f"採用ch={r['adopted']} ΔR={r['delta_r']}")
    if not ok: fails.append(("鮮やか一部除外", r))

    # (3) 全飽和(薄=フル) → 校正不能
    r = estimate_s_scalar(full_vivid, full_vivid, t_light=0.3, substrate_lab=white,
                          dr_min=0.03)
    ok = r["s"] is None and r["status"] == "all_saturated"
    print(f"  [{'OK' if ok else 'NG'}] 薄=フル: status={r['status']} s={r['s']}")
    if not ok: fails.append(("全飽和", r))

    # (4) 妥当域外の警告フラグ
    thin = forward_thin(full_light, 50.0, 0.01)
    r = estimate_s_scalar(full_light, thin, t_light=0.01, substrate_lab=white,
                          dr_min=0.03, s_valid=(100, 500))  # 50 は域外
    ok = r["status"] == "out_of_range" and r["s"] is not None
    print(f"  [{'OK' if ok else 'NG'}] 妥当域外: status={r['status']} S={r['s']}")
    if not ok: fails.append(("妥当域外", r))

    return fails


def main():
    all_fails = []
    all_fails += test_t0_is_lip()
    all_fails += test_large_t_is_full()
    all_fails += test_monotonic_L()
    all_fails += test_estimate_s_round_trip()
    all_fails += test_compute_km_table()
    all_fails += test_resolve_line_s()
    all_fails += test_estimate_s_scalar()

    print()
    if all_fails:
        print(f"FAIL ({len(all_fails)} 件):")
        for f in all_fails:
            print(f"  - {f}")
        sys.exit(1)
    print("PASS: 全テスト通過")


if __name__ == "__main__":
    main()
