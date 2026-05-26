"""ダーク系スウォッチが BLACK_THRESHOLD 引き上げで誤って除外されないかの単体テスト。

extract_lab() を直接呼んで、以下が引き続き赤系として auto 通過することを確認する:
  - rmd_milktea_velvet_09: L≈11 のダーク赤(現行 auto)
  - rmd_zero_velvet_01: L≈44 の典型例(現行 auto)
  - rmd_glasting_water_09: パープル容器のみ(現行 excluded、維持確認)

images_cache から直接画像を読み込む(API 経由ではない)。
"""

import os
import sys
from PIL import Image

from extract_lab import extract_lab, IMAGE_DIR

CASES = [
    # (product_id, expected_status_prefix, lab_check)
    #   expected_status_prefix: "auto" (auto_high/auto_low どちらでも auto* なら可) or "excluded"
    #   lab_check: (L_min, L_max, a_min, a_max) or None
    ("rmd_milktea_velvet_09", "auto",     (5, 20, 10, 30)),   # ダーク赤
    ("rmd_zero_velvet_01",    "auto",     (35, 55, 35, 55)),  # 典型例
    ("rmd_glasting_water_09", "excluded", None),              # パープル容器のみ
]


def main():
    fails = []
    for pid, expected, lab_check in CASES:
        path = os.path.join(IMAGE_DIR, f"{pid}.png")
        if not os.path.exists(path):
            fails.append(f"{pid}: 画像キャッシュなし ({path})")
            continue

        img = Image.open(path).convert("RGB")
        res = extract_lab(img)
        status = res["status"]
        L, a, b = res.get("L"), res.get("a"), res.get("b")
        spread = res.get("spread")

        if expected == "auto" and status != "auto":
            fails.append(f"{pid}: expected auto, got {status} ({res['notes']})")
            continue
        if expected == "excluded" and status != "excluded":
            fails.append(f"{pid}: expected excluded, got {status} ({res['notes']})")
            continue

        if lab_check is not None and L is not None:
            L_min, L_max, a_min, a_max = lab_check
            if not (L_min <= L <= L_max):
                fails.append(f"{pid}: L={L:.2f} not in [{L_min},{L_max}]")
            if not (a_min <= a <= a_max):
                fails.append(f"{pid}: a={a:.2f} not in [{a_min},{a_max}]")

        spread_str = f"{spread:.3f}" if spread is not None else "-"
        L_str = f"{L:.2f}" if L is not None else "-"
        a_str = f"{a:.2f}" if a is not None else "-"
        b_str = f"{b:.2f}" if b is not None else "-"
        print(
            f"  {pid:<28} status={status:<10} L={L_str:>6} a={a_str:>6} b={b_str:>6} "
            f"spread={spread_str}"
        )

    print()
    if fails:
        print(f"FAIL ({len(fails)}):")
        for f in fails:
            print(f"  - {f}")
        sys.exit(1)
    print(f"PASS: {len(CASES)} cases")


if __name__ == "__main__":
    main()
