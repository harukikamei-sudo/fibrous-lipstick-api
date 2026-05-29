"""products_with_lab.csv に x_20(20次元 pref ベクトル)列を付与する。

設計書 v1.3 §2.1: x_20 = 機能15 + 世界観5。
軸定義は MVP では Lab + line_category からの派生で自動付与する暫定版。
ユーザーが手動でタグを付ける場合は AXIS_NAMES の定義に従って CSV を
直接編集すれば派生計算をバイパスできる(差し替え容易な構造)。

すべての軸は [0, 1] にクリップして付与する。
"""

from __future__ import annotations

import csv
import math
import os
from typing import Dict, List

CATALOG_PATH = os.path.join(os.path.dirname(__file__), "products_with_lab.csv")
OUT_PATH = os.path.join(os.path.dirname(__file__), "products_with_lab.csv")


# ============ 20軸の名前(差し替え可) ============

AXIS_NAMES: List[str] = [
    # ---- 機能 15 軸 ----
    "pigmentation",      # 発色の高さ
    "vivid",             # 鮮やか
    "transparency",      # 透け感
    "glossiness",        # ツヤ
    "matte_finish",      # マット
    "velvet_finish",     # ベルベット
    "moisture",          # 保湿感
    "durability",        # 持続力
    "blur_effect",       # ぼかし
    "juicy_feel",        # ジューシー
    "cool_tone",         # 寒色寄り
    "warm_tone",         # 暖色寄り
    "light_color",       # 明るい色
    "deep_color",        # 暗色
    "everyday_use",      # デイリー向け(中明度・低〜中彩度)
    # ---- 世界観 5 軸 ----
    "girly",             # ガーリー
    "konare",            # こなれ感
    "sweetness",         # 甘さ
    "korean",            # 韓国っぽい(MLBB)
    "mature",            # 大人っぽい
]
assert len(AXIS_NAMES) == 20


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _chroma(a: float, b: float) -> float:
    return math.sqrt(a * a + b * b)


def derive_x20(row: Dict[str, str]) -> List[float]:
    """1 商品の x_20 を派生計算。"""
    try:
        L = float(row["L"])
        a = float(row["a"])
        b = float(row["b"])
    except (KeyError, ValueError, TypeError):
        return [0.0] * 20

    C = _chroma(a, b)
    cat = (row.get("line_category") or "").strip()
    line_id = (row.get("line_id") or "").lower()

    is_tint = cat == "tint"
    is_matte = cat == "matte"
    is_velvet = cat == "velvet"
    is_gloss = cat == "gloss"
    has_blur = "blur" in line_id or "fudge" in line_id
    has_juicy = "juicy" in line_id
    has_dewy = "dewy" in line_id or "glasting" in line_id

    # 機能軸
    pigmentation = _clip01(C / 60.0)            # C* 大 = 発色高い目安
    vivid = _clip01(C / 50.0)
    transparency = _clip01(0.7 * is_tint + 0.5 * is_gloss + 0.0 * (is_matte or is_velvet))
    glossiness = _clip01(1.0 * is_gloss + 0.6 * has_dewy + 0.2 * is_tint)
    matte_finish = _clip01(1.0 * is_matte + 0.6 * has_blur)
    velvet_finish = _clip01(1.0 * is_velvet)
    moisture = _clip01(0.9 * is_gloss + 0.7 * has_dewy + 0.5 * is_tint + 0.1 * is_velvet)
    durability = _clip01(0.9 * is_matte + 0.8 * is_velvet + 0.6 * is_tint + 0.2 * is_gloss)
    blur_effect = _clip01(1.0 * has_blur + 0.5 * is_matte)
    juicy_feel = _clip01(1.0 * has_juicy + 0.7 * is_gloss + 0.5 * has_dewy)
    # 色相軸: hue 角度(度)で寒色/暖色
    hue_deg = (math.degrees(math.atan2(b, a)) + 360.0) % 360.0
    # 寒色: 250-350°(青〜赤紫)、暖色: 0-50°(赤〜オレンジ)
    cool_tone = _clip01(max(0.0, math.cos(math.radians(hue_deg - 300.0)) * (C / 50.0)))
    warm_tone = _clip01(max(0.0, math.cos(math.radians(hue_deg - 15.0)) * (C / 50.0)))
    light_color = _clip01((L - 40.0) / 40.0)
    deep_color = _clip01((50.0 - L) / 40.0)
    # デイリー: 中明度(40-65)& 中彩度(20-45)
    everyday_use = _clip01(
        max(0.0, 1.0 - abs(L - 52.5) / 15.0) *
        max(0.0, 1.0 - abs(C - 32.5) / 17.5)
    )

    # 世界観軸
    # girly: 明るめ × 暖色寄り × 中〜高彩度
    girly = _clip01(light_color * warm_tone * 1.4)
    # こなれ: 中明度 × 低〜中彩度 × tint
    konare = _clip01((1.0 - vivid) * everyday_use * (0.5 + 0.5 * is_tint))
    # 甘さ: 中〜高明度 × ピンク色相(hue 0-30°)× 彩度ある
    sweet_hue = math.cos(math.radians(hue_deg - 10.0))
    sweetness = _clip01(max(0.0, sweet_hue) * (C / 45.0) * (0.5 + 0.5 * light_color))
    # 韓国 MLBB: tint × 暖色 × 中明度 × 中〜やや高彩度
    korean = _clip01(is_tint * warm_tone * everyday_use * 1.5)
    # 大人: 暗色 × 低彩度 or 深い赤
    mature = _clip01(deep_color * (1.0 - 0.5 * vivid) + 0.3 * (deep_color * warm_tone))

    return [
        pigmentation, vivid, transparency, glossiness, matte_finish,
        velvet_finish, moisture, durability, blur_effect, juicy_feel,
        cool_tone, warm_tone, light_color, deep_color, everyday_use,
        girly, konare, sweetness, korean, mature,
    ]


X20_COL_NAMES = [f"x20_{i:02d}_{name}" for i, name in enumerate(AXIS_NAMES)]


def main(in_path: str = CATALOG_PATH, out_path: str = OUT_PATH) -> None:
    with open(in_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fields = list(reader.fieldnames or [])

    for col in X20_COL_NAMES:
        if col not in fields:
            fields.append(col)

    for row in rows:
        x20 = derive_x20(row)
        for col, val in zip(X20_COL_NAMES, x20):
            row[col] = f"{val:.4f}"

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"✅ x_20 を {len(rows)} 商品に付与: {out_path}")
    print(f"   列名: {X20_COL_NAMES[:3]} ... {X20_COL_NAMES[-2:]}")


def load_x20_from_row(row: Dict[str, str]) -> List[float]:
    """app.py / recommend エンドポイントから使うローダー。

    CSV 列があれば読む、無ければ derive_x20 で派生計算する。
    """
    if all(col in row for col in X20_COL_NAMES):
        try:
            return [float(row[col]) for col in X20_COL_NAMES]
        except (ValueError, TypeError):
            pass
    return derive_x20(row)


if __name__ == "__main__":
    main()
