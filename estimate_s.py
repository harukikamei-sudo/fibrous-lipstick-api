"""ライン散乱係数 S の逆推定。

同一ラインの 2 点観測:
  - フル発色 Lab (full_lab)  … 無限厚 R∞ とみなして K/S を決める
  - 薄付き Lab   (light_lab) … 厚み t_light での観測反射率

から、ライン共通の散乱係数 S を **チャネル毎に数値求解** する。

K/S は full_lab から決まる(km.ks_from_lab)。残る未知は S だけなので、
有限層 K-M 順モデル km.km_reflectance(ks, S, t_light, R_g) = R_obs を
S について解けばよい。R は S に対し単調なので brentq で安定に解ける。

薄付き観測時の下地反射率 R_g は引数 substrate_lab で与える。省略時は
「白基板スウォッチ(R_g≈1)」を仮定する(口紅サンプルの一般的な提示形態)。

依存: numpy, scipy
"""

import numpy as np
from scipy.optimize import brentq

from lab_utils import lab_to_reflectance
import km


__all__ = ["estimate_s"]

# S の探索上限。S·t_light が大きいと R は R∞ に張り付くので、この辺で頭打ち
_S_MAX = 1.0e4


def _solve_s_channel(ks, r_obs, t, r_g, r_inf):
    """1 チャネル分の S を解く。到達不能域はクランプして境界 S を返す。"""
    lo, hi = (r_inf, r_g) if r_g >= r_inf else (r_g, r_inf)
    if (hi - lo) < km.EPS:
        # フル発色と下地がほぼ同色 → S は不定。散乱なしとして 0 を返す
        return 0.0

    # 観測値を到達域 (r_g 〜 r_inf) の内側にクランプ
    target = min(max(r_obs, lo + km.EPS), hi - km.EPS)

    def f(s):
        return float(km.km_reflectance(ks, s, t, r_g)[0]) - target

    # f(0) = r_g - target。S を倍々に広げて符号反転(=解の挟み込み)を探す
    f0 = f(0.0)
    s_hi = 1.0
    for _ in range(60):
        if f0 * f(s_hi) <= 0.0:
            break
        s_hi *= 2.0
        if s_hi >= _S_MAX:
            s_hi = _S_MAX
            break
    else:
        return s_hi

    if f0 * f(s_hi) > 0.0:
        # 挟み込めなかった(target が r_inf 側に張り付く)→ 上限 S
        return s_hi

    return float(brentq(f, 0.0, s_hi, maxiter=100, xtol=1e-6))


def estimate_s(full_lab, light_lab, t_light=0.3, substrate_lab=None):
    """ライン散乱係数 S を逆推定する。

    Args:
        full_lab:      フル発色の Lab(shape (3,))
        light_lab:     t=t_light で観測した薄付き Lab(shape (3,))
        t_light:       薄付きの厚み t(デフォルト 0.3)
        substrate_lab: 薄付き観測時の下地 Lab(shape (3,))。
                       None なら白基板(反射率≈1)を仮定。

    Returns:
        S: ライン散乱係数(各チャネル独立、np.array shape (3,))
    """
    r_inf = lab_to_reflectance(full_lab)
    r_obs = lab_to_reflectance(light_lab)
    ks = km.ks_from_lab(full_lab)

    if substrate_lab is None:
        r_g = np.full(3, 1.0 - km.EPS)
    else:
        r_g = np.clip(lab_to_reflectance(substrate_lab), km.EPS, 1.0 - km.EPS)

    s = np.empty(3, dtype=float)
    for ch in range(3):
        # km_reflectance は配列前提なので 1 要素ベクトルとして渡す
        ks_ch = np.array([ks[ch]])
        rg_ch = np.array([r_g[ch]])
        s[ch] = _solve_s_channel(
            ks_ch, float(r_obs[ch]), float(t_light), rg_ch, float(r_inf[ch])
        )
    return s
