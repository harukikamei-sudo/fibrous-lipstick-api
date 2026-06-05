"""能動学習(Active Learning)本体 — 期待情報利得 EIG による次手選択。

設計の核(設計書 §7 のガウス共役更新を前提):
    AR like は observed_lab=r を θ_color に与え、ガウス共役で更新する。
    事後分散の縮みは候補に依らず一定(precision += 1/σ²)なので、
    候補の「情報的価値」は KL の平均シフト項 (μ_N − μ_0)² から来る。
    これは ‖r − μ_color‖² に比例 = 現在の好み中心から遠い色ほど大きい。

    ただし「当たる確率」P(like|X) は遠い色ほど下がるので、
        EIG_color(X) = P(like|X) · KL(like時の事後 ‖ 事前)
    は中間距離でピークを持つ(explore/exploit のスイートスポット)。
    dislike は θ_color を更新しない(修正1)ため dislike 枝の KL は 0。

選択則:
    score(X) = (1−w)·norm(R_final) + w·norm(EIG)
    w = clamp(μ_explore, 0, 1)
    → 冒険好き(μ_explore 大)ほど EIG 重視、保守的なら R_final 重視。
    norm は候補集合内の min-max 正規化(R_final と EIG のスケール差を吸収)。

【指標が異なる近似であることの明示(重要)】
    本実装の EIG は 2 つの異なる指標を掛け合わせた近似である:
      - P(like|X) は **ΔE2000(知覚均等色差)** で「当たりやすさ」を測る
        (人間が近いと感じる色ほど like されやすい、という知覚モデル)。
      - KL(like時) は **CIE Lab 座標系での分散・平均シフト** から計算する
        (θ_color はガウスで Lab 座標を直接モデル化しているため)。
    厳密には両者を同一の計量で揃えるべきだが、MVP では「知覚で当たり確率・
    Lab座標で情報量」という実務的近似を採用する。de50 / slope は知覚モデル側の
    設計判断パラメータ。Phase 2 で ΔE2000 ベースの情報量に統一する余地がある。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Sequence

import bayesian
from models_v13 import GaussianLab, LabValue
from recommend_v2 import delta_e_2000

LN2 = math.log(2.0)

# 観測ノイズは bayesian の真値を import(自前定義してドリフトさせない)
SIGMA2_AR_LIKE = bayesian.SIGMA2_BY_SOURCE["ar_view_like"]  # = 1.0

# P(like) シグモイドの設計判断パラメータ(知覚モデル側。差し替え可)
DE50_DEFAULT = 12.0   # この ΔE2000 で like 確率 0.5(知覚的に「まあ近い」境界)
SLOPE_DEFAULT = 0.25  # シグモイドの傾き


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _kl_1d_like(mu0: float, var0: float, r: float, var_obs: float) -> float:
    """1次元ガウスに like 観測 r を1件適用したときの KL(事後 ‖ 事前)[nat]。

    事後: precision_N = 1/σ²0 + 1/σ²obs,  σ²N = 1/precision_N,
          μ_N = σ²N·(μ0/σ²0 + r/σ²obs)
    KL = 0.5·[ ln(σ²0/σ²N) + σ²N/σ²0 + (μ_N−μ0)²/σ²0 − 1 ]
    """
    prec_n = 1.0 / var0 + 1.0 / var_obs
    var_n = 1.0 / prec_n
    mu_n = var_n * (mu0 / var0 + r / var_obs)
    return 0.5 * (math.log(var0 / var_n) + var_n / var0
                  + (mu_n - mu0) ** 2 / var0 - 1.0)


def kl_color_if_liked(
    theta_color: GaussianLab, eff_lab: LabValue, sigma2_obs: float = SIGMA2_AR_LIKE
) -> float:
    """like 観測(observed_lab=eff_lab)を1件適用したときの
    KL(事後 ‖ 事前) を nat で返す(3次元独立ガウスの和)。"""
    mu0 = (theta_color.mu.L, theta_color.mu.a, theta_color.mu.b)
    var0 = (theta_color.var.L, theta_color.var.a, theta_color.var.b)
    r = (eff_lab.L, eff_lab.a, eff_lab.b)
    return sum(_kl_1d_like(mu0[j], var0[j], r[j], sigma2_obs) for j in range(3))


def p_like(
    theta_color: GaussianLab, eff_lab: LabValue,
    de50: float = DE50_DEFAULT, slope: float = SLOPE_DEFAULT,
) -> float:
    """like 確率を ΔE2000(eff_lab, μ_color)の知覚シグモイドで近似。
    ΔE が小さい(似合い中心に近い)ほど高く、de50 で 0.5。"""
    dE = delta_e_2000(eff_lab, theta_color.mu)
    return _sigmoid(slope * (de50 - dE))


@dataclass
class EIGResult:
    eig_bits: float          # 期待情報利得 [bit]
    p_like: float            # like 確率
    kl_if_liked_bits: float  # like したときの情報利得 [bit]
    delta_e: float           # μ_color までの ΔE2000


def expected_information_gain(
    theta_color: GaussianLab, eff_lab: LabValue,
    sigma2_obs: float = SIGMA2_AR_LIKE,
    de50: float = DE50_DEFAULT, slope: float = SLOPE_DEFAULT,
) -> EIGResult:
    """θ_color に関する1観測の期待情報利得。
    EIG = P(like)·KL(like時) + P(dislike)·0(修正1で dislike は色を更新しない)。"""
    kl_bits = kl_color_if_liked(theta_color, eff_lab, sigma2_obs) / LN2
    pl = p_like(theta_color, eff_lab, de50, slope)
    dE = delta_e_2000(eff_lab, theta_color.mu)
    return EIGResult(eig_bits=pl * kl_bits, p_like=pl,
                     kl_if_liked_bits=kl_bits, delta_e=dE)


@dataclass
class Candidate:
    product_id: str
    effective_lab: LabValue
    r_final: float


@dataclass
class ScoredCandidate:
    product_id: str
    r_final: float
    eig_bits: float
    p_like: float
    delta_e: float
    score: float       # 最終スコア(ブレンド後)
    r_final_norm: float
    eig_norm: float


def _minmax(values: Sequence[float]) -> List[float]:
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [0.5 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def next_best(
    candidates: Sequence[Candidate],
    theta_color: GaussianLab,
    mu_explore: float,
    sigma2_obs: float = SIGMA2_AR_LIKE,
    de50: float = DE50_DEFAULT, slope: float = SLOPE_DEFAULT,
) -> List[ScoredCandidate]:
    """候補を「R_final と EIG のブレンド」で再ランク。降順で返す。

    w = clamp(μ_explore,0,1) が EIG の重み。w=0 で純 exploit(=R_final 順)、
    w=1 で純 explore(=EIG 順)。
    """
    if not candidates:
        return []
    w = max(0.0, min(1.0, mu_explore))
    eigs = [expected_information_gain(theta_color, c.effective_lab,
                                      sigma2_obs, de50, slope) for c in candidates]
    rfin_norm = _minmax([c.r_final for c in candidates])
    eig_norm = _minmax([e.eig_bits for e in eigs])
    scored = []
    for c, e, rn, en in zip(candidates, eigs, rfin_norm, eig_norm):
        scored.append(ScoredCandidate(
            product_id=c.product_id, r_final=c.r_final, eig_bits=e.eig_bits,
            p_like=e.p_like, delta_e=e.delta_e,
            score=(1.0 - w) * rn + w * en, r_final_norm=rn, eig_norm=en,
        ))
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored
