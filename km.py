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
    "LINE_CATEGORIES",
    "classify_line_category",
    "resolve_line_s",
    "LIP_PRESETS",
    "PC_SEASONS",
    "PC_LIPSTICK_TARGETS",
    "compute_pc_score",
    "compute_chroma",
]

# 仕上げタイプ → ライン散乱係数 S(各チャネル共通)のプリセット。
#
# K-M では S·t が大きいほど不透明(R→R∞)、小さいほど下地が透ける。
# 透け感の強い順 gloss < tint < velvet < matte が大小関係(固定)。
#
# ※ tint=0.4 のみ実測校正値(estimate_s_layered, コーラル juicy_lasting → S≈0.42)。
#   他 4 つは「推論値(確定の working 値)」。校正画像が揃わなかったため、tint=0.4 を
#   アンカーに 順序 gloss<tint<velvet<matte を保ち、典型的な不透明度比で設定した
#   (gloss 0.6x / velvet 2.5x / matte 5x / other は tint〜velvet 中間)。
#   淡色ではカテゴリ差が applied 色に出ることを確認済み(鮮やか色は K/S 大で
#   S にほぼ非感応)。将来 estimate_s_layered で実測できれば上書き可。
#   絶対値は t のスケールと結合する点に注意(t∈[0,1] を t_steps 分割)。
LINE_S_PRESETS = {
    "gloss":  [0.25, 0.25, 0.25],  # 艶・最も透ける(推論の暫定。校正画像が困難)
    "tint":   [0.4,  0.4,  0.4],   # ★実測校正 S≈0.42(コーラル juicy_lasting)
    "velvet": [1.0,  1.0,  1.0],   # 半不透明(暫定。要校正)
    "matte":  [2.0,  2.0,  2.0],   # 不透明・フルカバー(暫定。要校正)
    "other":  [0.6,  0.6,  0.6],   # 不明・フォールバック(tint と velvet の中間)
}

# 取りうる仕上げカテゴリ(other はフォールバック)
LINE_CATEGORIES = ("tint", "matte", "gloss", "velvet", "other")

# line_id 文字列 → カテゴリ推定のキーワード対応(先頭一致優先)。
# rom&nd のライン名(juicy_lasting, blur_fudge, glasting_water 等)は
# カテゴリ語を直接含まないので、製品知識ベースの語も入れる。
_CATEGORY_KEYWORDS = (
    ("velvet", "velvet"),
    ("juicy", "tint"),
    ("tint", "tint"),
    ("blur", "matte"),
    ("fudge", "matte"),
    ("matte", "matte"),
    ("glasting", "gloss"),
    ("dewy", "gloss"),
    ("gloss", "gloss"),
)


def classify_line_category(line_id):
    """line_id 文字列 → 仕上げカテゴリ(LINE_CATEGORIES のいずれか)。

    キーワードに一つも当たらなければ "other"。
    """
    if not line_id:
        return "other"
    low = str(line_id).lower()
    for kw, cat in _CATEGORY_KEYWORDS:
        if kw in low:
            return cat
    return "other"


def resolve_line_s(lines=None, line_id=None, line_category=None):
    """商品のライン S を解決する。優先順位:

      1. lines[line_id] が存在すればそれ(呼び出し側が明示した S)
      2. line_category が LINE_S_PRESETS にあればそのプリセット
      3. line_id から classify_line_category で推定したプリセット
      4. いずれも該当しなければ "other" のフォールバック

    Returns:
        (s: list[float] 長さ3, source: str)  source は解決経路の説明
    """
    if lines and line_id is not None and line_id in lines:
        return list(lines[line_id]), "lines"
    if line_category and line_category in LINE_S_PRESETS:
        return list(LINE_S_PRESETS[line_category]), f"category:{line_category}"
    if line_id:
        cat = classify_line_category(line_id)
        if cat != "other":
            return list(LINE_S_PRESETS[cat]), f"line_id~{cat}"
    return list(LINE_S_PRESETS["other"]), "default"


# 唇地肌の代表色プリセット(bare lip の Lab)。/recommend 等で下地として使う。
LIP_PRESETS = {
    "pale_pink":    [70.0, 16.0,  9.0],   # 淡いピンク
    "healthy_pink": [62.0, 22.0, 12.0],   # 健康的なピンク
    "reddish":      [54.0, 28.0, 14.0],   # やや赤め
    "beige":        [64.0, 13.0, 17.0],   # ベージュ寄り
    "dark":         [44.0, 21.0, 13.0],   # 暗め
}


# ============ パーソナルカラー(PC)別の理想的唇色 Lab 領域 ============
#
# 「カタログの pc_season タグでフィルタする(=答えを使う)」ではなく、論文/色彩学
# 指針から PC 別に Lab の矩形領域を定義し、シミュ結果の applied_lab がその領域
# にどれだけ近いかでランキングする。タグは答え合わせ用に別途取得・参照のみ。

PC_SEASONS = ("イエベ春", "イエベ秋", "ブルベ夏", "ブルベ冬")

# ★清濁(C* 彩度)軸を追加: 日本流 PC は「色相・明度・彩度・清濁」の 4 軸で
#   分類。清色(Clear)/濁色(Muted)の区別を C_min/C_max で表現する。
#   - 春・冬 = 清(Clear, 高彩度) → C_min を課す
#   - 夏・秋 = 濁(Muted, 低〜中彩度) → C_max を課す
#   範囲の数値も春↔秋の重なりを減らすため再調整(春は L/a を上に寄せ、
#   秋は a の下限を下げて彩度の低い領域も拾う)。
PC_LIPSTICK_TARGETS = {
    "イエベ春": {
        "L_range": (60.0, 75.0),
        "a_range": (30.0, 50.0),
        "b_range": (18.0, 35.0),
        "C_min": 35.0,                  # 清色(高彩度)
        "description": "明るく彩度高めの暖色(コーラル/ピーチ/テラコッタ、清色)",
        "sources": [
            "Color Me Beautiful (Jackson 1980): Clear warm spring",
            "日本流 4 シーズン (NPCA 等): イエベ・明・高彩・清",
            "Rees 2003 (high carotenoid → warm)",
            "Weatherall & Coombs 1992 (b* > 0 = warm undertone)",
        ],
    },
    "イエベ秋": {
        "L_range": (35.0, 50.0),
        "a_range": (15.0, 35.0),
        "b_range": (15.0, 30.0),
        "C_max": 32.0,                  # 濁色(低〜中彩度)
        "description": "暗めの暖色(ブリック/テラコッタ/ウォームブラウン、濁色)",
        "sources": [
            "Color Me Beautiful (Jackson 1980): Muted warm autumn",
            "日本流 4 シーズン: イエベ・暗・低中彩・濁",
            "Rees 2003",
        ],
    },
    "ブルベ夏": {
        "L_range": (55.0, 75.0),
        "a_range": (15.0, 35.0),
        "b_range": (-5.0, 10.0),
        "C_max": 32.0,                  # 濁色(低彩度寒色)
        "description": "明るく低彩度の寒色寄り(ローズ/モーブ/ベリー、濁色)",
        "sources": [
            "Color Me Beautiful (Jackson 1980): Muted cool summer",
            "Del Bino & Bernerd 2013 (high hemoglobin + low carotenoid → cool)",
            "Weatherall & Coombs 1992 (b* < 0 = cool undertone)",
        ],
    },
    "ブルベ冬": {
        "L_range": (30.0, 50.0),
        "a_range": (35.0, 60.0),
        "b_range": (-5.0, 15.0),
        "C_min": 35.0,                  # 清色(高彩度寒色) ※マトリクスに整合
        "description": "暗く高彩度の寒色寄り(バーガンディ/ワイン/ディープベリー、清色)",
        "sources": [
            "Color Me Beautiful (Jackson 1980): Clear cool winter",
            "日本流 4 シーズン: ブルベ・暗・高彩・清",
            "Del Bino et al. (ITA based skin tone classification)",
        ],
    },
}


def _axis_outside_distance(value, lo, hi):
    """値が [lo, hi] の外なら境界までの距離、内なら 0。"""
    if value < lo:
        return lo - value
    if value > hi:
        return value - hi
    return 0.0


def compute_chroma(lab):
    """彩度 C* = √(a² + b²)。"""
    if isinstance(lab, dict):
        a = float(lab["a"]); b = float(lab["b"])
    else:
        a = float(lab[1]); b = float(lab[2])
    return float((a * a + b * b) ** 0.5)


def compute_pc_score(applied_lab, pc_season):
    """applied_lab が PC 別 Lab 領域(L,a,b 矩形 + 清濁 C*)にどれだけ近いか。

    領域内なら 0、外なら各軸(L,a,b,C*)の超過量を二乗和で √(=4次元矩形までの
    ユークリッド距離)。小さいほど合う。

    Args:
        applied_lab: dict {L,a,b} または [L,a,b]/(L,a,b)
        pc_season: PC_LIPSTICK_TARGETS のキー("イエベ春" 等)。未知なら None を返す。
    """
    if pc_season not in PC_LIPSTICK_TARGETS:
        return None
    if isinstance(applied_lab, dict):
        L, a, b = float(applied_lab["L"]), float(applied_lab["a"]), float(applied_lab["b"])
    else:
        L, a, b = float(applied_lab[0]), float(applied_lab[1]), float(applied_lab[2])
    t = PC_LIPSTICK_TARGETS[pc_season]
    dL = _axis_outside_distance(L, *t["L_range"])
    da = _axis_outside_distance(a, *t["a_range"])
    db = _axis_outside_distance(b, *t["b_range"])
    # 清濁(C*)条件
    C = float((a * a + b * b) ** 0.5)
    dC = 0.0
    if "C_min" in t and C < t["C_min"]:
        dC = t["C_min"] - C
    elif "C_max" in t and C > t["C_max"]:
        dC = C - t["C_max"]
    return float((dL * dL + da * da + db * db + dC * dC) ** 0.5)

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
