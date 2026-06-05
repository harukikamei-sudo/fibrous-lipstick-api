"""設計書 v1.3 §7 ベイズ更新。

すべての θ を独立対角ガウス(diagonal covariance)として扱う。
これは設計書の式に一致しており、計算負荷が軽く、解釈もしやすい。

数学的根拠(ガウス共役更新の y_k 重み付き拡張):
    観測モデル: r_k ~ N(y_k · θ_j, σ²_k_obs) を各次元 j 独立に仮定
    事前: θ_j ~ N(μ_0, σ²_0)
    事後:
        σ²_N = 1 / ( 1/σ²_0 + Σ_k y_k² / σ²_k_obs )
        μ_N = σ²_N · ( μ_0/σ²_0 + Σ_k (y_k · r_k) / σ²_k_obs )

設計書 §7.2/§7.3 の式を厳密にこの形で実装している。
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from models_v13 import (
    GaussianLab,
    GaussianScalar,
    GaussianVec20,
    LabValue,
    Observation,
    ObservationSource,
    UserState,
)


# ============ 観測ノイズ(設計書 §7.1 / §11) ============

SIGMA2_BY_SOURCE: Dict[ObservationSource, float] = {
    "pc_diagnosis": 100.0,         # PC は事前 σ²_color_0 として別経路で扱うため通常は使わない
    "pair_color": 0.8,             # 強制ペア比較(色)
    "pair_worldview": 0.8,         # 強制ペア比較(世界観)
    "dialog": 1.5,                 # 対話確認
    "behavior": 1.0,               # 行動データ
    "ar_view_like": 1.0,           # AR いいね
    "ar_view_dislike": 1.0,        # AR 微妙
}

SIGMA2_OBS_THICKNESS = 0.05        # §7.5
SIGMA2_OBS_EXPLORE = 0.25          # §7.4 補足: 仮値(τ²_explore と同スケール)


# ============ ヘルパ ============

def _sigma2(src: ObservationSource) -> float:
    return SIGMA2_BY_SOURCE[src]


def _lab_to_tuple(lab: LabValue) -> Tuple[float, float, float]:
    return (lab.L, lab.a, lab.b)


# ============ θ_color: Lab 3次元 ============

def update_theta_color(
    prior: GaussianLab,
    observations: Sequence[Observation],
) -> Tuple[GaussianLab, int]:
    """θ_color の事後分布を計算(各次元独立)。

    対象観測: observed_lab を持つ「肯定的」観測(pair_color の選択側 / behavior /
    ar_view_like)。**ar_view_dislike は除外する**。

    理由(重要): dislike の observed_lab を平均更新に通すと、嫌った色の方向へ
    μ_color が引き寄せられ(y=-1 で r を負方向に加算)、さらに分散も縮んで
    「偽の確信」が生まれる。dislike は θ_color を肯定的に動かす根拠にならない
    (反発させたいなら別の repulsive モデルが必要だが本 MVP の範囲外)。
    θ_thickness が ar_view_like のみ拾う設計と思想を揃える。

    不変条件: 除外後に残る observed_lab 観測は構成上すべて y=+1。
      - pair_color: 選択側のみ observed_lab を持ち y=+1(非選択側は observed_x20 のみ)
      - behavior / ar_view_like: y=+1(肯定観測)
    よって観測モデル Lab_k,j ~ N(μ_j, σ²_src) として y を畳む。
    """
    relevant = [o for o in observations
                if o.observed_lab is not None and o.source != "ar_view_dislike"]
    if not relevant:
        return prior, 0

    prior_mu = _lab_to_tuple(prior.mu)
    prior_var = _lab_to_tuple(prior.var)

    new_mu = [0.0, 0.0, 0.0]
    new_var = [0.0, 0.0, 0.0]

    for j in range(3):
        precision = 1.0 / prior_var[j]
        weighted_sum = prior_mu[j] / prior_var[j]
        for o in relevant:
            sigma2 = _sigma2(o.source)
            r = _lab_to_tuple(o.observed_lab)[j]
            # 残るのは y=+1 の肯定観測のみ(上記の不変条件)
            precision += 1.0 / sigma2
            weighted_sum += r / sigma2
        var_j = 1.0 / precision
        new_var[j] = var_j
        new_mu[j] = var_j * weighted_sum

    return (
        GaussianLab(
            mu=LabValue(L=new_mu[0], a=new_mu[1], b=new_mu[2]),
            var=LabValue(L=new_var[0], a=new_var[1], b=new_var[2]),
        ),
        len(relevant),
    )


# ============ θ_pref: 20次元 ============

def update_theta_pref(
    prior: GaussianVec20,
    observations: Sequence[Observation],
) -> Tuple[GaussianVec20, int]:
    """θ_pref の事後分布(対角共分散近似)。

    対象観測: observed_x20 を持つもの。
    観測モデル: y_k ~ N(μ · x_k, σ²_src) を各次元独立に近似:
        各次元 j: σ²_j_N = 1/(1/σ²_j_0 + Σ x_k,j²/σ²)
                 μ_j_N = σ²_j_N (μ_j_0/σ²_j_0 + Σ x_k,j·y_k/σ²)
    """
    relevant = [o for o in observations if o.observed_x20 is not None]
    if not relevant:
        return prior, 0

    new_mu: List[float] = [0.0] * 20
    new_var: List[float] = [0.0] * 20

    for j in range(20):
        precision = 1.0 / prior.var[j]
        weighted_sum = prior.mu[j] / prior.var[j]
        for o in relevant:
            sigma2 = _sigma2(o.source)
            x_j = o.observed_x20[j]
            y = o.y
            precision += (x_j * x_j) / sigma2
            weighted_sum += (x_j * y) / sigma2
        var_j = 1.0 / precision
        new_var[j] = var_j
        new_mu[j] = var_j * weighted_sum

    return GaussianVec20(mu=new_mu, var=new_var), len(relevant)


# ============ θ_thickness: スカラー ============

def update_theta_thickness(
    prior: GaussianScalar,
    observations: Sequence[Observation],
) -> Tuple[GaussianScalar, int]:
    """θ_thickness の事後(設計書 §7.5)。

    対象観測: thickness を持つ ar_view_like のみ(設計書既定で dislike は除外)。
    観測モデル: t_k ~ N(μ, σ²_obs_thickness)
    """
    relevant = [
        o for o in observations
        if o.thickness is not None and o.source == "ar_view_like"
    ]
    if not relevant:
        return prior, 0

    precision = 1.0 / prior.var
    weighted_sum = prior.mu / prior.var
    for o in relevant:
        precision += 1.0 / SIGMA2_OBS_THICKNESS
        weighted_sum += o.thickness / SIGMA2_OBS_THICKNESS
    var_n = 1.0 / precision
    mu_n = var_n * weighted_sum

    # μ_thickness は [0,1] に物理的に拘束(クリップ)
    mu_n = max(0.0, min(1.0, mu_n))
    return GaussianScalar(mu=mu_n, var=var_n), len(relevant)


# ============ θ_explore: スカラー ============

def update_theta_explore(
    prior: GaussianScalar,
    observations: Sequence[Observation],
) -> Tuple[GaussianScalar, int]:
    """θ_explore の事後(設計書 §7.4)。

    対象観測: is_serendipity=True の ar_view_like / ar_view_dislike。
    観測モデル: 反応 r_k ~ N(μ, σ²_obs_explore)
        like  → r_k = 1.0(探索的提示が刺さった)
        dislike → r_k = 0.0(探索的提示が外した)
    """
    relevant = [
        o for o in observations
        if o.is_serendipity and o.source in ("ar_view_like", "ar_view_dislike")
    ]
    if not relevant:
        return prior, 0

    precision = 1.0 / prior.var
    weighted_sum = prior.mu / prior.var
    for o in relevant:
        r = 1.0 if o.source == "ar_view_like" else 0.0
        precision += 1.0 / SIGMA2_OBS_EXPLORE
        weighted_sum += r / SIGMA2_OBS_EXPLORE
    var_n = 1.0 / precision
    mu_n = var_n * weighted_sum
    mu_n = max(0.0, min(1.0, mu_n))
    return GaussianScalar(mu=mu_n, var=var_n), len(relevant)


# ============ 統合: 全 θ をバッチ更新 ============

def apply_observations(
    user: UserState,
    observations: Sequence[Observation],
) -> Tuple[UserState, Dict[str, int]]:
    """user の 4 パラメータすべてを観測リストでバッチ更新。"""
    color_post, n_color = update_theta_color(user.theta_color, observations)
    pref_post, n_pref = update_theta_pref(user.theta_pref, observations)
    thick_post, n_thick = update_theta_thickness(user.theta_thickness, observations)
    explore_post, n_explore = update_theta_explore(user.theta_explore, observations)

    new_user = UserState(
        user_id=user.user_id,
        lip_lab=user.lip_lab,
        pc_season=user.pc_season,
        theta_color=color_post,
        theta_pref=pref_post,
        theta_explore=explore_post,
        theta_thickness=thick_post,
    )
    n_applied = {
        "theta_color": n_color,
        "theta_pref": n_pref,
        "theta_thickness": n_thick,
        "theta_explore": n_explore,
    }
    return new_user, n_applied
