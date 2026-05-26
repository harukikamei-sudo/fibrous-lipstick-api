"""lab_utils.py の単体テスト。

主目的: Lab → 反射率 → Lab の往復誤差が ΔE(CIE76) < 1 で通ること。
副: HSV 系関数の境界条件、RGB ↔ Lab の往復精度。
"""

import sys
import numpy as np

from lab_utils import (
    rgb_to_lab, lab_to_rgb,
    lab_to_reflectance, reflectance_to_lab,
    compute_saturation, compute_hue_deg, is_red_hue,
)


def deltaE_76(lab1, lab2):
    lab1 = np.asarray(lab1, dtype=float)
    lab2 = np.asarray(lab2, dtype=float)
    return float(np.sqrt(np.sum((lab1 - lab2) ** 2)))


# Lab → 反射率 → Lab 往復対象(口紅レンジ + 端値)
ROUND_TRIP_LAB_CASES = [
    # 実データから採取した代表値(products_with_lab.csv より)
    (33.40, 35.58, 21.86),  # rmd_blur_fudge_03 (ムスキー)
    (44.04, 44.46, 26.61),  # rmd_zero_velvet_01
    (13.82, 24.35, 12.46),  # rmd_milktea_velvet_09 (ダーク)
    (69.28, 42.21, 23.96),  # rmd_bare_mool_01
    (71.18, 39.31,  6.41),  # rmd_the_juicy_lasting_28 (淡)
    # 端値
    (50.0,  0.0,  0.0),     # 中明度の灰
    (95.0,  0.0,  0.0),     # 明色
    (10.0,  0.0,  0.0),     # 暗色
    (50.0, 60.0,  0.0),     # 強赤a
]


def test_lab_reflectance_round_trip():
    print("Lab → 反射率 → Lab 往復誤差(ΔE):")
    fails = []
    for L, a, b in ROUND_TRIP_LAB_CASES:
        lab_in = np.array([L, a, b])
        refl = lab_to_reflectance(lab_in)
        lab_out = reflectance_to_lab(refl)
        dE = deltaE_76(lab_in, lab_out)
        ok = dE < 1.0
        mark = "OK" if ok else "NG"
        print(f"  [{mark}] Lab=({L:>6.2f},{a:>6.2f},{b:>6.2f}) → "
              f"Lab=({lab_out[0]:>6.2f},{lab_out[1]:>6.2f},{lab_out[2]:>6.2f}) "
              f"ΔE={dE:.3f}  reflectance={refl.round(3).tolist()}")
        if not ok:
            fails.append((L, a, b, dE))
    return fails


def test_rgb_lab_round_trip():
    print("\nRGB → Lab → RGB 往復(参考、クランプ込み):")
    cases = [(76, 9, 27), (200, 100, 110), (255, 255, 255), (0, 0, 0), (128, 128, 128)]
    fails = []
    for r, g, b in cases:
        rgb_in = np.array([r, g, b])
        lab = rgb_to_lab(rgb_in)
        rgb_out = lab_to_rgb(lab)
        diff = float(np.max(np.abs(rgb_in - rgb_out)))
        ok = diff < 1.0
        mark = "OK" if ok else "NG"
        print(f"  [{mark}] RGB=({r:>3},{g:>3},{b:>3}) → "
              f"Lab=({lab[0]:>6.2f},{lab[1]:>6.2f},{lab[2]:>6.2f}) → "
              f"RGB=({rgb_out[0]:>6.2f},{rgb_out[1]:>6.2f},{rgb_out[2]:>6.2f}) "
              f"|Δ|max={diff:.3f}")
        if not ok:
            fails.append((r, g, b, diff))
    return fails


def test_hsv_functions():
    print("\nHSV 系の動作確認:")
    fails = []
    # compute_saturation: 純赤 sat=1, 灰 sat=0
    cases = [
        ((255, 0, 0), 1.0, 0.0),      # 純赤
        ((128, 128, 128), 0.0, 0.0),  # 灰(hue 不定 → 0)
        ((0, 255, 0), 1.0, 120.0),    # 純緑
        ((0, 0, 255), 1.0, 240.0),    # 純青
        ((255, 255, 0), 1.0, 60.0),   # 黄
    ]
    for rgb, exp_sat, exp_hue in cases:
        sat = compute_saturation(np.array(rgb))
        hue = compute_hue_deg(np.array(rgb))
        ok_sat = abs(sat - exp_sat) < 0.01
        ok_hue = abs(hue - exp_hue) < 1.0
        ok = ok_sat and ok_hue
        mark = "OK" if ok else "NG"
        print(f"  [{mark}] RGB={rgb}: sat={sat:.2f} (exp {exp_sat:.2f}), hue={hue:.1f} (exp {exp_hue:.1f})")
        if not ok:
            fails.append((rgb, sat, hue))

    # is_red_hue 境界
    boundary = [(0, True), (60, True), (61, False), (180, False), (299, False), (300, True), (360, True)]
    for h, exp in boundary:
        got = is_red_hue(h)
        ok = got == exp
        mark = "OK" if ok else "NG"
        print(f"  [{mark}] is_red_hue({h}) = {got} (exp {exp})")
        if not ok:
            fails.append(("is_red_hue", h, got))
    return fails


def main():
    all_fails = []
    all_fails += test_lab_reflectance_round_trip()
    all_fails += test_rgb_lab_round_trip()
    all_fails += test_hsv_functions()

    print()
    if all_fails:
        print(f"FAIL ({len(all_fails)} 件):")
        for f in all_fails:
            print(f"  - {f}")
        sys.exit(1)
    print("PASS: 全テスト通過")


if __name__ == "__main__":
    main()
