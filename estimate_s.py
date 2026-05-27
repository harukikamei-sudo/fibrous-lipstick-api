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
from scipy.optimize import brentq, least_squares

from lab_utils import lab_to_reflectance, reflectance_to_lab
import km


__all__ = ["estimate_s", "estimate_s_scalar", "estimate_s_layered"]

# S の探索上限。S·t_light が大きいと R は R∞ に張り付くので、この辺で頭打ち
_S_MAX = 1.0e4


def _solve_s_channel(ks, r_obs, t, r_g, r_inf):
    """1 チャネル分の S を解く。到達不能域はクランプして境界 S を返す。

    ks/r_g は km_reflectance に渡すため (1,) 配列のまま受けるが、ブラケット計算
    (lo/hi/target)は必ずスカラーで行う(配列が混ざると target が配列化し brentq が
    壊れる)。
    """
    r_g_s = float(np.ravel(r_g)[0])
    lo, hi = (r_inf, r_g_s) if r_g_s >= r_inf else (r_g_s, r_inf)
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


def estimate_s_scalar(full_lab, light_lab, t_light=0.3, substrate_lab=None,
                      dr_min=0.03, s_valid=(10.0, 500.0)):
    """飽和チャネルを除外して、単一スカラーのライン S を頑健に推定する。

    S は本来「散乱は色相にほぼ依存しない=1スカラー」が物理前提。チャネル毎の
    推定がばらつくのは暗・高彩度チャネルの飽和による artifact なので、情報の
    無いチャネルを捨てて残りの中央値を採る。

    チャネル採用ゲート(両方を満たす ch のみ採用):
      1. |R_full - R_thin| >= dr_min: 飽和(薄≈フル)も透明(素肌≈フル≈薄)も
         この片側ゲートで除外できる(どちらも S の情報を持たない)。
      2. 物理整合: R_thin が R_substrate と R_full の間にある(±tol)。照明ムラ等で
         薄付きが素肌より明るい/フルより濃いといった非物理 ch を弾く。

    Args:
        full_lab/light_lab/t_light/substrate_lab: estimate_s と同じ。
            t_light は規約で固定する量(データから逆算は原理的に不可。S·t しか
            観測に効かないため)。
        dr_min: チャネル採用の反射率差しきい値(既定 0.03)。
        s_valid: 物性的に妥当とみなす S の範囲(min, max)。外れたら警告。

    Returns:
        dict: {
            "s": float|None,          # 採用チャネルの中央値。校正不能なら None
            "per_channel_s": [3 floats],
            "delta_r": [3 floats],     # |R_full - R_thin|
            "adopted": [3 bools],
            "n_adopted": int,
            "t_light", "dr_min": 入力エコー,
            "status": "ok"|"out_of_range"|"all_saturated",
            "note": str,
        }
    """
    r_inf = np.asarray(lab_to_reflectance(full_lab), dtype=float)
    r_obs = np.asarray(lab_to_reflectance(light_lab), dtype=float)
    if substrate_lab is not None:
        r_sub = np.asarray(lab_to_reflectance(substrate_lab), dtype=float)
    else:
        r_sub = np.full(3, 1.0 - km.EPS)
    s_all = estimate_s(full_lab, light_lab, t_light=t_light,
                       substrate_lab=substrate_lab)

    dr = np.abs(r_inf - r_obs)
    # 物理整合: 薄付きが 素肌〜フル の間(±tol)にあるか
    _tol = 0.01
    lo = np.minimum(r_sub, r_inf) - _tol
    hi = np.maximum(r_sub, r_inf) + _tol
    monotonic = (r_obs >= lo) & (r_obs <= hi)
    adopted = (dr >= dr_min) & monotonic

    result = {
        "per_channel_s": [round(float(v), 3) for v in s_all],
        "delta_r": [round(float(v), 4) for v in dr],
        "monotonic": [bool(x) for x in monotonic],
        "adopted": [bool(x) for x in adopted],
        "n_adopted": int(adopted.sum()),
        "t_light": t_light,
        "dr_min": dr_min,
    }

    if not adopted.any():
        result.update(
            s=None, status="all_saturated",
            note="採用ch ゼロ(飽和 ΔR<dr_min または 非物理)。校正不能 → "
                 "より淡い色 / 照明の揃った画像で取り直す",
        )
        return result

    s_scalar = float(np.median(s_all[adopted]))
    status, note = "ok", f"{int(adopted.sum())}/3 ch 採用 → median S"
    if not (s_valid[0] <= s_scalar <= s_valid[1]):
        status = "out_of_range"
        note += f"（S={s_scalar:.1f} が妥当域{list(s_valid)}外、要確認）"
    result.update(s=round(s_scalar, 3), status=status, note=note)
    return result


# ============ 3 点フィット(素肌+1度+2度 → K/S と S を同時推定) ============
#
# 「2度塗り=R∞(完全不透明)」を仮定せず、素肌(下地)と 2 つの厚みの観測から
# チャネル毎に (K/S, u1=S·t1) を least_squares でフィットする。シアーなティント
# (何度塗っても不透明にならない)でも、真の K/S と S が分離して求まる。
#
# 識別性: K-M は S·t しか効かないので、1度塗りの厚み t1 は規約で固定する
# (既定 0.3)。2度塗りは t2 = coat_ratio·t1(既定 2 倍)と仮定。これで
# チャネル毎に 2 観測・2 未知(K/S, u1)となり解ける。S = u1 / t1。

def _R_of_u(ks, u, r_g):
    """K-M 反射率を S·t = u(スカラー)として 1 チャネル分だけ返す。"""
    return float(km.km_reflectance(np.array([ks], dtype=float), float(u),
                                   1.0, np.array([r_g], dtype=float))[0])


def _fit_channel_layered(r_sub, r1, r2, coat_ratio):
    """1 チャネル: (K/S, u1) を 2 観測 R1=R(u1), R2=R(coat_ratio·u1) からフィット。

    Returns: (ks, u1, rmse)
    """
    # 初期値: K/S は 2度 を R∞ とみなした近似、u1 は 1
    ks0 = float(km._ks_from_reflectance(np.array([r2]))[0])

    def resid(theta):
        ks, u1 = theta
        return [_R_of_u(ks, u1, r_sub) - r1,
                _R_of_u(ks, coat_ratio * u1, r_sub) - r2]

    res = least_squares(resid, x0=[max(ks0, 1e-3), 1.0],
                        bounds=([1e-4, 1e-4], [1e3, 1e3]), max_nfev=3000)
    rmse = float(np.sqrt(np.mean(np.square(res.fun))))
    return float(res.x[0]), float(res.x[1]), rmse


def estimate_s_layered(substrate_lab, coat1_lab, coat2_lab, t1=0.3,
                       coat_ratio=2.0, dr_min=0.03, rmse_max=0.02,
                       s_valid=(0.05, 5.0)):
    """素肌 + 1度塗り + 2度塗り の 3 点から、ライン S(単一スカラー)を推定する。

    R∞ 仮定なしでチャネル毎に (K/S, u1=S·t1) をフィット。採用ゲートを通った
    チャネルの S=u1/t1 の中央値を単一スカラー S とする。フィット由来の K/S から
    各チャネルの真の R∞(=a-b)も復元して「フル発色色」として返す。

    Args:
        substrate_lab/coat1_lab/coat2_lab: 素肌 / 1度 / 2度 の Lab(shape (3,))
        t1: 1度塗りの厚み(規約固定値, 既定 0.3)
        coat_ratio: 2度塗りの厚み倍率(既定 2.0)
        dr_min: 各塗り段階の反射率差しきい値(既定 0.03)
        rmse_max: フィット残差(反射率)の上限。超えたら不採用(既定 0.02)
        s_valid: 妥当な S の範囲(min, max)。外れたら out_of_range 警告。

    Returns: dict {
        "s": float|None, "per_channel_s","per_channel_ks","rmse": [3 floats],
        "adopted":[3 bools], "n_adopted":int,
        "rinf_lab":[L,a,b],   # フィット K/S から復元したフル発色(R∞)
        "t1","coat_ratio","dr_min": echo,
        "status": "ok"|"out_of_range"|"insufficient", "note": str,
    }
    """
    r_sub = np.asarray(lab_to_reflectance(substrate_lab), dtype=float)
    r1 = np.asarray(lab_to_reflectance(coat1_lab), dtype=float)
    r2 = np.asarray(lab_to_reflectance(coat2_lab), dtype=float)

    ks_ch, u1_ch, s_ch, rmse_ch, adopted = [], [], [], [], []
    for c in range(3):
        ks, u1, rmse = _fit_channel_layered(float(r_sub[c]), float(r1[c]),
                                            float(r2[c]), coat_ratio)
        ks_ch.append(ks); u1_ch.append(u1); s_ch.append(u1 / t1); rmse_ch.append(rmse)
        # ゲート: 単調(素肌→1度→2度) & 各段階が情報あり & フィット良好
        lo, hi = sorted((r_sub[c], r2[c]))
        mono = (lo - 0.01) <= r1[c] <= (hi + 0.01)
        informative = abs(r2[c] - r1[c]) >= dr_min and abs(r1[c] - r_sub[c]) >= dr_min
        adopted.append(bool(mono and informative and rmse < rmse_max))

    adopted = np.array(adopted)
    s_arr = np.array(s_ch)

    # フィット K/S から R∞(=a-b)を全ch復元 → フル発色色
    a = 1.0 + np.array(ks_ch)
    b = np.sqrt(np.maximum(a * a - 1.0, 0.0))
    rinf = np.clip(a - b, 0.0, 1.0)
    rinf_lab = reflectance_to_lab(rinf)

    result = {
        "per_channel_s": [round(float(v), 4) for v in s_arr],
        "per_channel_ks": [round(float(v), 4) for v in ks_ch],
        "rmse": [round(float(v), 4) for v in rmse_ch],
        "adopted": [bool(x) for x in adopted],
        "n_adopted": int(adopted.sum()),
        "rinf_lab": [round(float(v), 2) for v in rinf_lab],
        "t1": t1, "coat_ratio": coat_ratio, "dr_min": dr_min,
    }

    if not adopted.any():
        result.update(s=None, status="insufficient",
                      note="採用ch ゼロ(非単調/情報不足/フィット不良)。"
                           "淡い色・照明の揃った塗り重ね画像で取り直す")
        return result

    s_scalar = float(np.median(s_arr[adopted]))
    status, note = "ok", f"{int(adopted.sum())}/3 ch 採用 → median S"
    if not (s_valid[0] <= s_scalar <= s_valid[1]):
        status = "out_of_range"
        note += f"（S={s_scalar:.2f} が妥当域{list(s_valid)}外、要確認）"
    result.update(s=round(s_scalar, 4), status=status, note=note)
    return result
