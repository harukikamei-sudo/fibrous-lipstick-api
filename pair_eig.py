"""v14 逐次ペア比較の期待情報利得(EIG_pair)と最大EIGペア選択(A3)。

設計(確定済み・確認待ち事項は実装で固定):
  EIG_pair(p) = Σ_{c∈{左,右}} P(c) · KL( q_c(θ) ‖ q(θ) )   [bit]
    - q_c は「選択 c を観測として1件更新した事後」。bayesian.apply_observations を
      そのまま使う(= 実際の更新経路と完全一致)。ガウス共役なので閉形式・サンプリング不要。
    - KL は θ_color(3次元)+ θ_pref(20次元)のガウス KL の和(_kl_gauss)。
      期待 Σ_c P(c)·KL は相互情報量 I(choice;θ)= H(prior)−E[H(posterior)] に厳密一致。
    - 選択確率 P(c) は Bradley-Terry: P(左)=σ(β_BT·(fit_左−fit_右))。
      fit = 色ペア: −ΔE2000(eff_lab, μ_color) / 世界観ペア: μ_pref·x20。
      β_BT = active_learning.SLOPE_DEFAULT(=0.25)を流用(新定数を作らない)。
      ※ de50 はペアでは2側の差で相殺し消える。
    - 観測ノイズ σ²_obs は実更新と同じ pair の値(bayesian.SIGMA2_BY_SOURCE: 色≈20.83 /
      世界観0.8)を apply_observations 経由で使う。
    - ラプラスは使わない(案1): 更新=厳密ガウス共役、選択確率=事後平均で1点プラグイン。

v14 は観測とモデル仮定の整合のため、色ペアの観測 Lab に **effective_lab**
(lip_lab + μ_thickness の K-M 塗布後)を使う(v13 の .lab マスストーンではなく)。
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import active_learning as al
import bayesian
from catalog_x20 import AXIS_NAMES
from models_v13 import (
    KMTableRow,
    LabValue,
    Observation,
    PairItem,
    PairQuestion,
    PairV14,
    PairV14Side,
    ThetaSnapshot,
    UserState,
)
from recommend_v2 import delta_e_2000, effective_lab

LN2 = math.log(2.0)
BETA_BT = al.SLOPE_DEFAULT  # = 0.25。fit 差 → 選択確率のロジスティック温度(流用)


def _kl_gauss(m1: float, v1: float, m0: float, v0: float) -> float:
    """KL( N(m1,v1) ‖ N(m0,v0) ) [nat]。post=1, prior=0。"""
    return 0.5 * (math.log(v0 / v1) + (v1 + (m1 - m0) ** 2) / v0 - 1.0)


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _eff_lab(side: PairItem, row_by_id: Dict[str, KMTableRow], mu_thickness: float) -> LabValue:
    """ペア片側の effective_lab(lip + μ_thickness の K-M)。row が無ければ .lab で代替。"""
    row = row_by_id.get(side.product_id)
    if row is None:
        return side.lab
    return effective_lab(row, mu_thickness)


def pair_v14(
    pair: PairQuestion, row_by_id: Dict[str, KMTableRow], mu_thickness: float
) -> PairV14:
    """PAIR_BANK の PairQuestion → effective_lab 付き PairV14。"""
    def _side(s: PairItem) -> PairV14Side:
        return PairV14Side(
            product_id=s.product_id, name=s.name, image_url=s.image_url,
            lab=s.lab, x20=s.x20, effective_lab=_eff_lab(s, row_by_id, mu_thickness),
        )
    return PairV14(pair_id=pair.pair_id, pair_type=pair.pair_type,
                   left=_side(pair.left), right=_side(pair.right))


def _observations_for_choice(
    pair: PairQuestion, chose: str,
    row_by_id: Dict[str, KMTableRow], mu_thickness: float,
) -> List[Observation]:
    """選択結果 → 観測列(v14: 色ペアの observed_lab は effective_lab)。

    apply_pair_choices と同型(chosen y=+1 / rejected y=−1、source_pair_id 付与)。
    """
    chosen = pair.left if chose == "left" else pair.right
    rejected = pair.right if chose == "left" else pair.left
    src = "pair_color" if pair.pair_type == "color" else "pair_worldview"
    obs: List[Observation] = []
    if pair.pair_type == "color":
        obs.append(Observation(
            source=src, product_id=chosen.product_id, source_pair_id=pair.pair_id,
            observed_lab=_eff_lab(chosen, row_by_id, mu_thickness),
            observed_x20=chosen.x20, y=+1.0,
        ))
        obs.append(Observation(
            source=src, product_id=rejected.product_id, source_pair_id=pair.pair_id,
            observed_x20=rejected.x20, y=-1.0,
        ))
    else:
        obs.append(Observation(
            source=src, product_id=chosen.product_id, source_pair_id=pair.pair_id,
            observed_x20=chosen.x20, y=+1.0,
        ))
        obs.append(Observation(
            source=src, product_id=rejected.product_id, source_pair_id=pair.pair_id,
            observed_x20=rejected.x20, y=-1.0,
        ))
    return obs


def apply_v14_choice(
    user: UserState, pair: PairQuestion, chose: str,
    row_by_id: Dict[str, KMTableRow], mu_thickness: float,
) -> UserState:
    """選択を観測としてベイズ更新(実際の更新。EIG の q_c と同じ経路)。"""
    obs = _observations_for_choice(pair, chose, row_by_id, mu_thickness)
    new_user, _ = bayesian.apply_observations(user, obs)
    return new_user


def _fit(side: PairItem, user: UserState, pair_type: str,
         row_by_id: Dict[str, KMTableRow], mu_thickness: float) -> float:
    """BT 用の片側 fit スコア(高いほど選ばれやすい)。"""
    if pair_type == "color":
        return -delta_e_2000(_eff_lab(side, row_by_id, mu_thickness), user.theta_color.mu)
    return sum(p * x for p, x in zip(user.theta_pref.mu, side.x20))  # μ_pref · x20


def _prob_left(pair: PairQuestion, user: UserState,
               row_by_id: Dict[str, KMTableRow], mu_thickness: float) -> float:
    """Bradley-Terry: P(左を選ぶ)=σ(β_BT·(fit_左−fit_右))。事後平均で1点評価。"""
    s_l = _fit(pair.left, user, pair.pair_type, row_by_id, mu_thickness)
    s_r = _fit(pair.right, user, pair.pair_type, row_by_id, mu_thickness)
    return _sigmoid(BETA_BT * (s_l - s_r))


def _kl_user(post: UserState, prior: UserState) -> float:
    """KL(post ‖ prior) を θ_color(3)+θ_pref(20)のガウス和で [bit]。

    世界観ペアは θ_color 不変なので color 項は 0 に落ちる(自動)。
    """
    kl = 0.0
    for d in ("L", "a", "b"):
        kl += _kl_gauss(getattr(post.theta_color.mu, d), getattr(post.theta_color.var, d),
                        getattr(prior.theta_color.mu, d), getattr(prior.theta_color.var, d))
    for j in range(20):
        kl += _kl_gauss(post.theta_pref.mu[j], post.theta_pref.var[j],
                        prior.theta_pref.mu[j], prior.theta_pref.var[j])
    return kl / LN2


def eig_pair(user: UserState, pair: PairQuestion,
             row_by_id: Dict[str, KMTableRow], mu_thickness: float) -> float:
    """EIG_pair = Σ_c P(c)·KL(q_c‖q) [bit]。期待KL形(解析)。"""
    p_left = _prob_left(pair, user, row_by_id, mu_thickness)
    q_left = apply_v14_choice(user, pair, "left", row_by_id, mu_thickness)
    q_right = apply_v14_choice(user, pair, "right", row_by_id, mu_thickness)
    kl_left = _kl_user(q_left, user)
    kl_right = _kl_user(q_right, user)
    return p_left * kl_left + (1.0 - p_left) * kl_right


def best_pair(
    user: UserState, pairs: Sequence[PairQuestion], asked: Sequence[str],
    row_by_id: Dict[str, KMTableRow], mu_thickness: float,
) -> Optional[Tuple[PairQuestion, float]]:
    """未提示ペアの中で EIG 最大を返す。同点は pair_id 昇順で決定的(二度出さない)。"""
    asked_set = set(asked)
    scored: List[Tuple[float, str, PairQuestion]] = []
    for p in pairs:
        if p.pair_id in asked_set:
            continue
        eig = eig_pair(user, p, row_by_id, mu_thickness)
        scored.append((eig, p.pair_id, p))
    if not scored:
        return None
    # EIG 降順 → 同点は pair_id 昇順(決定的タイブレーク)
    scored.sort(key=lambda t: (-t[0], t[1]))
    eig, _pid, pair = scored[0]
    return pair, eig


def theta_snapshot(prev: UserState, new: UserState) -> ThetaSnapshot:
    """中間実況用: θ_pref の現在値 + 直前で σ² が最も縮んだ軸。"""
    drops = [(prev.theta_pref.var[j] - new.theta_pref.var[j], j) for j in range(20)]
    drops.sort(key=lambda t: (-t[0], t[1]))
    top_axis = AXIS_NAMES[drops[0][1]] if drops and drops[0][0] > 1e-12 else None
    return ThetaSnapshot(
        pref_mu=list(new.theta_pref.mu),
        pref_var=list(new.theta_pref.var),
        top_shrunk_axis=top_axis,
    )
