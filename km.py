"""Kubelka-Munk(K-M)モデルによる重ね塗り後 Lab の計算。

唇地肌(下地)の上に、商品固有の K/S 比を持つ顔料層を厚み t で塗ったときの
反射率を **有限層 K-M 式** で求め、Lab に戻す。

理論
----
無限厚での反射率 R∞ から商品固有の吸収/散乱比を得る::

    K/S = (1 - R∞)^2 / (2 R∞)

下地反射率 R_g の上に厚み t の層を重ねたときの反射率(有限層解, Kubelka 1948)::

    a = 1 + K/S
    b = sqrt(a^2 - 1)
    R = [1 - R_g (a - b·coth(bSt))] / [(a - R_g) + b·coth(bSt)]

性質:
  - St → 0  で R → R_g   (膜が無ければ下地そのもの)
  - St → ∞ で R → R∞ = a - b (背景に依存しない無限厚反射率)
  - その間 R は St に対して単調

各「チャネル」は linear sRGB 近似の R/G/B 帯域反射率(lab_utils 参照)。
S(散乱係数)はライン共通、K/S は商品ごとに異なる、という設計。

依存: numpy
"""

import numpy as np

from lab_utils import lab_to_reflectance, reflectance_to_lab


__all__ = [
    "ks_from_lab",
    "km_reflectance",
    "compute_applied_lab",
    "compute_km_table",
    "LINE_S_PRESETS",
    "resolve_line_s",
]

# 仕上げタイプ → ライン散乱係数 S(各チャネル共通)のプリセット。
#
# K-M では S·t が大きいほど不透明(R→R∞)、小さいほど下地が透ける。
# よって 透け感の強い順 gloss < tint < velvet < matte で S を大きくする
# (大小関係はこの順で固定)。
#
# ※ 絶対値は t のスケールと結合している点に注意。本実装は t∈[0,1] を
#   t_steps 分割するので、S は O(1〜10) でないと t=0.05 付近で即飽和し
#   21 段階が階段関数に潰れる(matte=200 等は不可)。下記は t∈[0,1] で
#   滑らかなグラデーションになる暫定スケール。薄付きスウォッチが集まれば
#   estimate_s で実測 S に置き換える。
LINE_S_PRESETS = {
    "gloss":  [1.0, 1.0, 1.0],   # 艶・透け感 最大(最も下地が透ける)
    "tint":   [2.0, 2.0, 2.0],   # 染めつき・シアー
    "velvet": [4.0, 4.0, 4.0],   # 半不透明・ソフトマット
    "matte":  [8.0, 8.0, 8.0],   # 不透明・フルカバー
    "other":  [3.0, 3.0, 3.0],   # 不明・その他のフォールバック
}

# line_id 文字列からカテゴリを推定する際に探すキーワード(優先順)
_LINE_ID_KEYWORDS = ("matte", "velvet", "gloss", "tint")


def resolve_line_s(lines=None, line_id=None, line_category=None):
    """商品のライン S を解決する。優先順位:

      1. lines[line_id] が存在すればそれ(呼び出し側が明示した S)
      2. line_category が LINE_S_PRESETS にあればそのプリセット
      3. line_id 内にカテゴリ語(velvet 等)があれば推定プリセット
      4. いずれも該当しなければ "other" のフォールバック

    Returns:
        (s: list[float] 長さ3, source: str)  source は解決経路の説明
    """
    if lines and line_id is not None and line_id in lines:
        return list(lines[line_id]), "lines"
    if line_category and line_category in LINE_S_PRESETS:
        return list(LINE_S_PRESETS[line_category]), f"category:{line_category}"
    if line_id:
        low = str(line_id).lower()
        for cat in _LINE_ID_KEYWORDS:
            if cat in low:
                return list(LINE_S_PRESETS[cat]), f"line_id~{cat}"
    return list(LINE_S_PRESETS["other"]), "default"

# 反射率を (EPS, 1-EPS) に収めて 0/1 での発散を避ける
EPS = 1e-6
# coth(x) は x→0 で発散。下地に張り付く極小膜は別処理するので下限でクリップ
_COTH_MIN = 1e-9
# tanh が飽和して coth≈1 になる領域。これ以上は頭打ちにして overflow を避ける
_COTH_SAT = 50.0


# ============ K/S(商品固有) ============

def _ks_from_reflectance(r_inf):
    """無限厚反射率 R∞(各チャネル 0〜1)→ K/S 比(各チャネル)。"""
    r = np.clip(np.asarray(r_inf, dtype=float), EPS, 1.0 - EPS)
    return (1.0 - r) ** 2 / (2.0 * r)


def ks_from_lab(full_lab):
    """フル発色 Lab → 商品 K/S 比(np.array shape (3,))。

    フル発色を「無限厚で観測した色 R∞」とみなして K/S を逆算する。
    """
    return _ks_from_reflectance(lab_to_reflectance(full_lab))


# ============ 有限層 K-M 反射率(forward) ============

def km_reflectance(ks, s, t, r_g):
    """有限層 K-M 反射率 R(各チャネル shape (3,)、0〜1)。

    Args:
        ks:  商品 K/S 比(shape (3,))
        s:   ライン散乱係数 S(shape (3,))
        t:   厚み(スカラ、0〜1 を想定するが上限は問わない)
        r_g: 下地反射率(shape (3,)、0〜1)
    """
    ks = np.asarray(ks, dtype=float)
    r_g = np.clip(np.asarray(r_g, dtype=float), EPS, 1.0 - EPS)
    st = np.asarray(s, dtype=float) * float(t)

    a = 1.0 + ks
    b = np.sqrt(np.maximum(a * a - 1.0, 0.0))

    bst = np.clip(b * st, _COTH_MIN, _COTH_SAT)
    coth = 1.0 / np.tanh(bst)

    num = 1.0 - r_g * (a - b * coth)
    den = (a - r_g) + b * coth
    return np.clip(num / den, 0.0, 1.0)


# ============ 重ね塗り後 Lab ============

def compute_applied_lab(lip_lab, product_k_s, line_s, t):
    """K-M 式で重ね塗り後の Lab を計算。

    Args:
        lip_lab:     唇地肌の Lab(shape (3,)) → 下地反射率 R_g
        product_k_s: 商品の K/S 比(shape (3,))
        line_s:      ライン散乱係数 S(shape (3,))
        t:           厚み(0〜1)

    Returns:
        applied_lab: 重ね塗り後の Lab(np.array shape (3,))
    """
    r_g = lab_to_reflectance(lip_lab)
    r = km_reflectance(product_k_s, line_s, t, r_g)
    return reflectance_to_lab(r)


# ============ バッチ: ユーザー × 商品 × 厚み テーブル ============

def compute_km_table(lip_lab, products, lines=None, t_steps=21):
    """user_product_lab_table を生成。

    Args:
        lip_lab: 唇地肌の Lab(shape (3,))
        products: 商品リスト。各要素は dict で下記を含む:
            - "k_s": K/S 比(shape (3,))。あれば優先
            - "L","a","b": フル発色 Lab(k_s が無ければここから算出)
          S 解決のため "line_id" / "line_category" を任意で持つ。
        lines: {line_id: S(shape (3,))} の dict。省略(None)可。
               商品の S は resolve_line_s の優先順位
               (lines > line_category プリセット > line_id 推定 > default)
               で解決され、lines に無くてもフォールバックする。
        t_steps: 厚み段階数(デフォルト 21 → t = 0.0, 0.05, …, 1.0)

    Returns:
        list[dict]: 各商品につき
            {"id", "line_id", "s", "s_source",
             "applied": [{"t", "L", "a", "b"}, …]}
    """
    lip_lab = np.asarray(lip_lab, dtype=float)
    ts = np.linspace(0.0, 1.0, int(t_steps))

    table = []
    for p in products:
        if "k_s" in p and p["k_s"] is not None:
            ks = np.asarray(p["k_s"], dtype=float)
        else:
            full_lab = np.array([p["L"], p["a"], p["b"]], dtype=float)
            ks = ks_from_lab(full_lab)

        line_key = p.get("line_id") or p.get("line")
        s_list, source = resolve_line_s(
            lines=lines, line_id=line_key, line_category=p.get("line_category")
        )
        s = np.asarray(s_list, dtype=float)

        applied = []
        for t in ts:
            lab = compute_applied_lab(lip_lab, ks, s, float(t))
            applied.append({
                "t": round(float(t), 4),
                "L": round(float(lab[0]), 2),
                "a": round(float(lab[1]), 2),
                "b": round(float(lab[2]), 2),
            })

        table.append({
            "id": p.get("id"),
            "line_id": line_key,
            "s": [round(float(v), 4) for v in s_list],
            "s_source": source,
            "applied": applied,
        })

    return table
