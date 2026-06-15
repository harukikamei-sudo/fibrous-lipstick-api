"""products_with_lab.csv に x_20(20次元 pref ベクトル)列を付与する。

★ 軸定義は DB(lipstick_DB_updated.xlsx)の正式 20 軸に準拠(2026-06-02 確定)。
   DB README の「20次元の構成」と users シートの θ_pref 列順を source of truth とする。
   **x20 軸定義は AXIS_NAMES(v1.3)で確定。変更は要協議**(scene_priors / reasons の
   top_axes・product_traits・AXIS_LABELS_JA / I_dialog がこの順序と名前に依存する)。
   KAWANO_HANDOFF §Q4 の仮20軸(transparency/mature 等)は廃止。正は本ファイル。

20 軸の内訳:
  色相 (1):    hue
  発色 (3):    saturation, brightness, pigmentation
  仕上がり (5): glossy, moisture_finish, sheer, velvet, blur     ← lines シート由来
  タイプ (3):   is_tint, is_balm, is_gloss                       ← lines シート由来
  保湿 (3):    moisturizing, longlasting, transfer_resistance   ← lines シート由来
  世界観 (5):   girly, makeup_intensity, konare, sweetness, korean

  → 色ごと(products): hue, saturation, brightness, pigmentation + 世界観5 = 9 軸
  → ラインごと(lines): glossy 〜 transfer_resistance = 11 軸

すべての軸は [0, 1] に正規化(DB の値域定義に一致)。
"""

from __future__ import annotations

import csv
import math
import os
from typing import Dict, List

CATALOG_PATH = os.path.join(os.path.dirname(__file__), "products_with_lab.csv")
OUT_PATH = os.path.join(os.path.dirname(__file__), "products_with_lab.csv")


# ============ 20軸の名前(DB 正式定義・正準順序) ============
# この順序は DB users シートの θ_pref 列順(mu_pref_hue 〜 mu_pref_korean)と一致。
# x_20[0]=hue, x_20[1]=saturation, ..., x_20[19]=korean。

AXIS_NAMES: List[str] = [
    # 色相 (1)
    "hue",
    # 発色 (3)
    "saturation",
    "brightness",
    "pigmentation",
    # 仕上がり (5)  ← lines シート由来
    "glossy",
    "moisture_finish",
    "sheer",
    "velvet",
    "blur",
    # タイプ (3)  ← lines シート由来
    "is_tint",
    "is_balm",
    "is_gloss",
    # 保湿 (3)  ← lines シート由来
    "moisturizing",
    "longlasting",
    "transfer_resistance",
    # 世界観 (5)
    "girly",
    "makeup_intensity",
    "konare",
    "sweetness",
    "korean",
]
assert len(AXIS_NAMES) == 20

# 推薦理由(reasons)のフロント表示用ラベル(A2)。conciergeScript.ts と揃えること。
# Mina に伝わる平易な言葉に寄せる(形態名より質感の言葉)。
AXIS_LABELS_JA: Dict[str, str] = {
    "hue": "色み",
    "saturation": "鮮やかさ",
    "brightness": "明るさ",
    "pigmentation": "発色",
    "glossy": "ツヤ",
    "moisture_finish": "うるおい",
    "sheer": "透け感",
    "velvet": "マット感",
    "blur": "ふんわり感",
    "is_tint": "ティント",
    "is_balm": "バーム",
    "is_gloss": "グロス",
    "moisturizing": "保湿",
    "longlasting": "落ちにくさ",
    "transfer_resistance": "色移りしにくさ",
    "girly": "ガーリー",
    "makeup_intensity": "メイク感",
    "konare": "こなれ感",
    "sweetness": "甘さ",
    "korean": "韓国っぽさ",
}
assert set(AXIS_LABELS_JA) == set(AXIS_NAMES)

# lines シート由来の 11 軸(line_id でルックアップ)
LINE_AXES = [
    "glossy", "moisture_finish", "sheer", "velvet", "blur",
    "is_tint", "is_balm", "is_gloss",
    "moisturizing", "longlasting", "transfer_resistance",
]

# ============ lines シートの 11 軸値(DB lipstick_DB_updated.xlsx より、2026-06-02) ============
# 値は DB の lines シートをそのまま転記(AI仮 + anchors整合済み v1.3)。
# DB を更新したらここも更新する(将来は GAS / CSV から動的ロードに移行可)。

LINE_ATTRS: Dict[str, Dict[str, float]] = {
    #                   glossy moist  sheer velvet blur  tint  balm  gloss moistz longl transf
    "the_juicy_lasting": dict(glossy=0.7, moisture_finish=0.7, sheer=0.6, velvet=0.2, blur=0.3,
                              is_tint=1.0, is_balm=0.0, is_gloss=0.0,
                              moisturizing=0.6, longlasting=0.8, transfer_resistance=0.6),
    "dewyful":           dict(glossy=0.6, moisture_finish=0.9, sheer=0.6, velvet=0.2, blur=0.3,
                              is_tint=1.0, is_balm=0.0, is_gloss=0.0,
                              moisturizing=0.9, longlasting=0.8, transfer_resistance=0.6),
    "glasting_water":    dict(glossy=0.9, moisture_finish=0.9, sheer=0.7, velvet=0.1, blur=0.4,
                              is_tint=1.0, is_balm=0.0, is_gloss=0.0,
                              moisturizing=0.7, longlasting=0.1, transfer_resistance=0.1),
    "zero_velvet":       dict(glossy=0.8, moisture_finish=0.1, sheer=0.1, velvet=0.9, blur=0.1,
                              is_tint=1.0, is_balm=0.0, is_gloss=0.0,
                              moisturizing=0.7, longlasting=0.7, transfer_resistance=0.5),
    "blur_fudge":        dict(glossy=0.1, moisture_finish=0.3, sheer=0.1, velvet=0.1, blur=0.9,
                              is_tint=1.0, is_balm=0.0, is_gloss=0.0,
                              moisturizing=0.1, longlasting=0.9, transfer_resistance=0.9),
    "bare_mool":         dict(glossy=0.0, moisture_finish=0.2, sheer=0.5, velvet=0.2, blur=1.0,
                              is_tint=1.0, is_balm=0.0, is_gloss=0.0,
                              moisturizing=0.2, longlasting=0.9, transfer_resistance=1.0),
    "see_through_matte": dict(glossy=0.5, moisture_finish=0.5, sheer=0.5, velvet=0.4, blur=0.5,
                              is_tint=1.0, is_balm=0.0, is_gloss=0.0,
                              moisturizing=0.4, longlasting=0.7, transfer_resistance=0.6),
    "milktea_velvet":    dict(glossy=0.1, moisture_finish=0.3, sheer=0.7, velvet=0.3, blur=0.6,
                              is_tint=1.0, is_balm=0.0, is_gloss=0.0,
                              moisturizing=0.3, longlasting=0.8, transfer_resistance=0.8),
    "juicy_lasting":     dict(glossy=0.3, moisture_finish=0.4, sheer=0.9, velvet=0.8, blur=0.2,
                              is_tint=1.0, is_balm=0.0, is_gloss=0.0,
                              moisturizing=0.4, longlasting=0.9, transfer_resistance=0.8),
}

# line_id が LINE_ATTRS に無い場合のフォールバック(中庸値)
_LINE_DEFAULT = dict(glossy=0.5, moisture_finish=0.5, sheer=0.5, velvet=0.3, blur=0.4,
                     is_tint=1.0, is_balm=0.0, is_gloss=0.0,
                     moisturizing=0.5, longlasting=0.7, transfer_resistance=0.6)


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _chroma(a: float, b: float) -> float:
    return math.sqrt(a * a + b * b)


def derive_x20(row: Dict[str, str]) -> List[float]:
    """1 商品の x_20 を DB 20 軸の正準順序で生成。

    - 色相 + 発色 (hue/saturation/brightness/pigmentation): Lab から導出
    - 仕上がり/タイプ/保湿 (11軸): line_id で LINE_ATTRS をルックアップ
    - 世界観 (girly/makeup_intensity/konare/sweetness/korean): ヒューリスティック導出
    """
    try:
        L = float(row["L"])
        a = float(row["a"])
        b = float(row["b"])
    except (KeyError, ValueError, TypeError):
        return [0.0] * 20

    C = _chroma(a, b)
    line_id = (row.get("line_id") or "").strip()
    line = LINE_ATTRS.get(line_id, _LINE_DEFAULT)

    # ---- 色相・発色(products 由来、Lab から) ----
    # hue: 色相角 0-360° を 0-1 に正規化
    hue_deg = (math.degrees(math.atan2(b, a)) + 360.0) % 360.0
    hue = hue_deg / 360.0
    # saturation: C* を 0-1 に(C*=60 で飽和とみなす)
    saturation = _clip01(C / 60.0)
    # brightness: L を 0-1 に
    brightness = _clip01(L / 100.0)
    # pigmentation: 発色の高さ。C* 主体だが暗い高彩度も高発色とみなす
    pigmentation = _clip01(C / 55.0)

    # ---- 仕上がり・タイプ・保湿(lines 由来、11軸) ----
    line_vals = [line[k] for k in LINE_AXES]

    # ---- 世界観(products 由来、ヒューリスティック) ----
    warm = _clip01(max(0.0, math.cos(math.radians(hue_deg - 15.0))) * (C / 50.0))
    light = _clip01((L - 40.0) / 40.0)
    deep = _clip01((50.0 - L) / 40.0)
    sweet_hue = max(0.0, math.cos(math.radians(hue_deg - 10.0)))

    # girly: 明るめ × 暖色寄り × 中〜高彩度
    girly = _clip01(light * warm * 1.4)
    # makeup_intensity: 発色の強さ(濃く主張する色ほど高い)
    makeup_intensity = _clip01(pigmentation * (0.6 + 0.4 * (1.0 - light)))
    # konare: 中明度 × こなれ(低めの彩度 × tint 寄り)
    everyday = _clip01(max(0.0, 1.0 - abs(L - 52.5) / 15.0) *
                       max(0.0, 1.0 - abs(C - 32.5) / 17.5))
    konare = _clip01((1.0 - saturation) * everyday * (0.5 + 0.5 * line["is_tint"]))
    # sweetness: ピンク色相 × 明るめ × 彩度
    sweetness = _clip01(sweet_hue * (C / 45.0) * (0.5 + 0.5 * light))
    # korean: MLBB(tint × 暖色 × 中明度 × 中彩度)
    korean = _clip01(line["is_tint"] * warm * everyday * 1.5)

    seqenkan = [girly, makeup_intensity, konare, sweetness, korean]

    # 正準順序で連結: [hue,sat,bright,pig] + [11 line軸] + [世界観5]
    return [hue, saturation, brightness, pigmentation] + line_vals + seqenkan


X20_COL_NAMES = [f"x20_{i:02d}_{name}" for i, name in enumerate(AXIS_NAMES)]


def main(in_path: str = CATALOG_PATH, out_path: str = OUT_PATH) -> None:
    with open(in_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fields = list(reader.fieldnames or [])

    # 旧 x20_* 列(別軸定義の残骸)があれば削除して付け直す
    fields = [c for c in fields if not c.startswith("x20_")]
    for col in X20_COL_NAMES:
        fields.append(col)

    for row in rows:
        # 旧列を掃除
        for k in list(row.keys()):
            if k.startswith("x20_") and k not in X20_COL_NAMES:
                del row[k]
        x20 = derive_x20(row)
        for col, val in zip(X20_COL_NAMES, x20):
            row[col] = f"{val:.4f}"

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"✅ x_20(DB 20軸)を {len(rows)} 商品に付与: {out_path}")
    print(f"   軸順: {AXIS_NAMES[:4]} ... {AXIS_NAMES[-3:]}")


def load_x20_from_row(row: Dict[str, str]) -> List[float]:
    """app.py / recommend から使うローダー。

    CSV に x20_* 列があれば読む、無ければ derive_x20 で生成。
    旧軸定義の列が混在する場合に備え、列数が 20 に満たなければ再生成。
    """
    if all(col in row for col in X20_COL_NAMES):
        try:
            return [float(row[col]) for col in X20_COL_NAMES]
        except (ValueError, TypeError):
            pass
    return derive_x20(row)


if __name__ == "__main__":
    main()
