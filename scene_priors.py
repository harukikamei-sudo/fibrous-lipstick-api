"""シーン事前分布(SCENE_MU_PREF)— θ_pref の事前構築 v14。

設計意図:
    θ_color には PC_MU_COLOR_0(pc_season → 事前)が既にあるのに、
    θ_pref は flat 事前のままだった。シーン選択(「どんなときに使いたい?」)
    1 タップで世界観系・機能系の軸に事前を入れ、ペア比較の問数を 10 → 7-8 に
    減らしても収束を維持するのが狙い(検証: personas_cli でシーン事前 + n 問
    vs flat + 10 問を比較し、同等以上になる最小 n を採用)。

数理仕様:
    - 軸 k がシーンに言及される場合:  μ_k = テーブル値, σ²_k = KAPPA · TAU2_PREF
    - 言及されない軸:                μ_k = 0,         σ²_k = TAU2_PREF (flat)
    - 複数シーン選択時:
        μ_k  = 選択シーンでの値の平均(未言及シーンは 0 として平均に含める。
               「2 シーン中 1 つしか気にしない軸」は事前が正しく薄まる)
        σ²_k = 言及シーン間で符号が一致する場合のみ KAPPA · TAU2_PREF。
               符号が衝突する場合(例: 学校 saturation<0 × 特別な日 saturation>0)
               は flat に戻す。衝突を「自信を持って中立」と誤認させないため。

軸の選定方針(コメントの根拠は手置き初版。カタログにシーンタグが入った時点で
x20 重心から再較正する):
    - hue には事前を置かない。色相の好みは PC 事前(θ_color)の担当であり、
      二重カウントを避ける。
    - brightness / saturation はシーン依存が強いので置く(校則対策の核)。
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from catalog_x20 import AXIS_NAMES
from constants import TAU2_PREF  # 一元化(constants が単一の source。循環 import 回避)

# シーン言及軸の分散縮小率。σ²_k = KAPPA · TAU2_PREF。
# 較正方針: personas_cli で「観測 7-8 問で事前を覆せるか」を確認しつつ調整。
# 強すぎる事前(観測で動かない)になっていたら上げる。
KAPPA = 0.65


# ============ シーン → μ_pref テーブル(言及軸のみ記載) ============
#
# 値域はカタログ x20 と同スケール(概ね -1 〜 +1)。
# 各行に根拠コメント必須(手置きであることを明示するため)。

SCENE_MU_PREF: Dict[str, Dict[str, float]] = {
    # --------------------------------------------------------------
    # 学校・通学: ペルソナ(15歳・地方在住)の最重要シーン。
    # 校則制約 =「塗っているとばれない」が支配的な実需。
    # --------------------------------------------------------------
    "school": {
        "sheer":               +0.8,  # 透け感 = ばれにくさの核
        "makeup_intensity":    -0.7,  # 「メイク感」が強いほどばれる
        "saturation":          -0.6,  # 高発色はばれる
        "pigmentation":        -0.5,  # 同上(顔料感)
        "blur":                +0.4,  # じゅわっと滲む = 素の血色に見える
        "moisturizing":        +0.4,  # リップケアの体で使える(言い訳が立つ)
        "is_balm":             +0.4,  # バーム形態はケア用品に見える
        "longlasting":         +0.3,  # 学校では塗り直し機会がない
        "glossy":              -0.3,  # ツヤもばれ要因(saturation より弱め)
    },
    # --------------------------------------------------------------
    # 友達と遊ぶ: トレンド共有の文脈。「かわいい」が話題になる方向。
    # --------------------------------------------------------------
    "friends": {
        "korean":              +0.6,  # 同世代のトレンド文脈そのもの
        "is_tint":             +0.5,  # ティント = じゅわ感・今っぽさ
        "glossy":              +0.4,  # うるツヤ
        "brightness":          +0.4,  # 明るめ・写真映え
        "girly":               +0.3,
        "saturation":          +0.2,  # 学校よりは出せる(弱め)
    },
    # --------------------------------------------------------------
    # デート: 「盛れている、ただしやりすぎない」。甘さ・うるおい寄り。
    # --------------------------------------------------------------
    "date": {
        "sweetness":           +0.6,
        "girly":               +0.5,
        "glossy":              +0.5,  # うるツヤは恋愛文脈の定番
        "moisture_finish":     +0.4,
        "blur":                +0.4,  # ふんわり=柔らかい印象
        "transfer_resistance": +0.3,  # 飲食でも落ちにくい(実需)
        "brightness":          +0.3,
    },
    # --------------------------------------------------------------
    # 特別な日: 発表会・式典・推し活イベント等。発色と持ちが正義。
    # --------------------------------------------------------------
    "special": {
        "saturation":          +0.6,  # ここでは発色を出してよい
        "pigmentation":        +0.5,
        "longlasting":         +0.5,  # 長時間崩れない
        "transfer_resistance": +0.4,
        "konare":              +0.3,  # 背伸び・大人っぽさの受け皿
        "glossy":              +0.3,
        "makeup_intensity":    +0.3,  # school と符号衝突 → 併選時は flat に戻る(仕様通り)
    },
}

# フロント表示用ラベル(conciergeScript.ts 側と揃えること)
SCENE_LABELS: Dict[str, str] = {
    "school":  "学校・通学",
    "friends": "友達と遊ぶ",
    "date":    "デート",
    "special": "特別な日",
}


# ============ 事前構築 ============

def build_pref_prior(scenes: List[str]) -> Tuple[List[float], List[float]]:
    """選択シーン列 → (mu[20], var[20])。

    scenes が空・未知キーのみの場合は flat (mu=0, var=TAU2_PREF) を返す。
    既存呼び出し側(pair_compare.apply_pair_choices)の flat 事前を
    この関数の返り値で置き換えるだけで配線完了。
    """
    valid = [s for s in scenes if s in SCENE_MU_PREF]
    mu: List[float] = []
    var: List[float] = []

    for axis in AXIS_NAMES:
        vals = [SCENE_MU_PREF[s].get(axis) for s in valid]
        mentioned = [v for v in vals if v is not None]

        if not valid or not mentioned:
            mu.append(0.0)
            var.append(TAU2_PREF)
            continue

        # μ: 未言及シーンを 0 として全選択シーンで平均(事前の正しい希釈)
        mu_k = sum(v if v is not None else 0.0 for v in vals) / len(valid)

        # σ²: 言及シーン間で符号が一致するときのみ縮める
        signs_consistent = all(v > 0 for v in mentioned) or all(v < 0 for v in mentioned)
        var_k = KAPPA * TAU2_PREF if signs_consistent else TAU2_PREF

        mu.append(mu_k)
        var.append(var_k)

    return mu, var


def scene_mentioned_axes(scenes: List[str]) -> set:
    """選択シーンが言及する x20 軸名の集合(I_dialog 配線用・A1)。

    recommend_v2 は「選択シーンが言及する軸のうち、商品 x20 が閾値超の軸が1つ以上」を
    familiarity の I_dialog(対話で好み明言相当)として使う。
    """
    axes: set = set()
    for s in scenes:
        if s in SCENE_MU_PREF:
            axes.update(SCENE_MU_PREF[s].keys())
    return axes
