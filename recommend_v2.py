"""設計書 v1.3 Part IV / VI 統合スコアによる推奨。

入力(ステートレス):
    user: UserState (4 パラメータの事後)
    km_table: List[KMTableRow] (各商品の 21段 applied_Lab + x_20)

出力:
    商品ごとの effective_Lab / f / familiarity / R_final と TOP-N。

数式(設計書 §8 / §10):
    effective_Lab(c, user) = linear_interp(km_table[c], μ_thickness)
    f(c, user) = -α · ΔE2000(effective_Lab, μ_color) + μ_pref · c.x_20
    familiarity(c, user) = w1·I_dialog + w2·cos(μ_pref, c.x_20) + w3·ΔE_inv(...)
    β(μ_explore) = β_max · μ_explore
    R_final(c, user) = f - β · familiarity
"""

from __future__ import annotations

import math
from typing import List, Sequence

import numpy as np
from skimage import color as skcolor

from models_v13 import (
    KMTableRow,
    LabValue,
    RecommendV2Item,
    RecommendV2Request,
    RecommendV2Response,
    UserState,
)


# ============ §5.4 線形補間 ============

def effective_lab(row: KMTableRow, mu_thickness: float) -> LabValue:
    """μ_thickness で 21 段テーブルから Lab を線形補間。

    設計書 §5.4: t_lower = floor(μ_t × 20), t_upper = min(t_lower+1, 20),
                 w = (μ_t × 20) - t_lower, Lab = (1-w)·Lab_lower + w·Lab_upper。
    """
    mu_t = max(0.0, min(1.0, mu_thickness))
    t_idx_f = mu_t * 20.0
    t_lower = int(math.floor(t_idx_f))
    t_upper = min(t_lower + 1, 20)
    w = t_idx_f - t_lower
    lo = row.applied[t_lower]
    hi = row.applied[t_upper]
    return LabValue(
        L=lo.L * (1 - w) + hi.L * w,
        a=lo.a * (1 - w) + hi.a * w,
        b=lo.b * (1 - w) + hi.b * w,
    )


# ============ ΔE2000(skimage.color) ============

def delta_e_2000(lab1: LabValue, lab2: LabValue) -> float:
    """CIEDE2000。skimage 標準実装を使用。"""
    a = np.array([[[lab1.L, lab1.a, lab1.b]]], dtype=np.float64)
    b = np.array([[[lab2.L, lab2.a, lab2.b]]], dtype=np.float64)
    return float(skcolor.deltaE_ciede2000(a, b)[0, 0])


# ============ f(c, user): Part IV ============

def f_score(
    eff_lab: LabValue,
    mu_color: LabValue,
    mu_pref: Sequence[float],
    x20: Sequence[float],
    alpha: float,
) -> tuple[float, float, float]:
    """Returns (f, delta_e, pref_match)."""
    dE = delta_e_2000(eff_lab, mu_color)
    pref_match = sum(p * x for p, x in zip(mu_pref, x20))
    return -alpha * dE + pref_match, dE, pref_match


# ============ familiarity(c, user): Part VI ============

def cosine_similarity(u: Sequence[float], v: Sequence[float]) -> float:
    nu = math.sqrt(sum(x * x for x in u))
    nv = math.sqrt(sum(x * x for x in v))
    if nu == 0 or nv == 0:
        return 0.0
    return sum(a * b for a, b in zip(u, v)) / (nu * nv)


def delta_e_inv(eff_lab: LabValue, mu_color: LabValue) -> float:
    """ΔE が小さいほど大きい値を返す(0〜1)。1/(1+ΔE) を採用。"""
    dE = delta_e_2000(eff_lab, mu_color)
    return 1.0 / (1.0 + dE)


def familiarity(
    eff_lab: LabValue,
    mu_color: LabValue,
    mu_pref: Sequence[float],
    x20: Sequence[float],
    weights: Sequence[float],
    dialog_named: bool = False,
) -> float:
    """設計書 §10.1:
        familiarity = w1·I(対話で好み明言) + w2·cos(μ_pref, c.x_20)
                    + w3·ΔE_inv(effective_Lab, μ_color)
    """
    w1, w2, w3 = weights
    i_dialog = 1.0 if dialog_named else 0.0
    cos = cosine_similarity(mu_pref, x20)
    dEi = delta_e_inv(eff_lab, mu_color)
    return w1 * i_dialog + w2 * cos + w3 * dEi


# ============ β(μ_explore) ============

def beta_from_explore(mu_explore: float, beta_max: float) -> float:
    """探索好きユーザーほど familiarity ペナルティを強くして「未知の自分」を提示。

    explore=0(探索嫌い): β=0 → familiarity ペナルティなし=親しみある商品をそのまま推す
    explore=1(探索好き): β=β_max → familiarity 高い商品を強く減点=未知商品を上位に
    """
    return beta_max * max(0.0, min(1.0, mu_explore))


# ============ 推奨本体 ============

def recommend_v2(req: RecommendV2Request) -> RecommendV2Response:
    user: UserState = req.user
    mu_thickness = user.theta_thickness.mu
    mu_color = user.theta_color.mu
    mu_pref = user.theta_pref.mu
    mu_explore = user.theta_explore.mu
    beta = beta_from_explore(mu_explore, req.beta_max)

    items: List[RecommendV2Item] = []
    for row in req.km_table:
        eff = effective_lab(row, mu_thickness)
        f, dE, pref_match = f_score(eff, mu_color, mu_pref, row.x20, req.alpha)
        fam = familiarity(
            eff, mu_color, mu_pref, row.x20, req.familiarity_weights,
            dialog_named=False,
        )
        r_final = f - beta * fam
        items.append(RecommendV2Item(
            product_id=row.product_id,
            name=row.name,
            line_category=row.line_category,
            effective_lab=eff,
            delta_e_to_color=dE,
            pref_match=pref_match,
            f_score=f,
            familiarity=fam,
            r_final=r_final,
            catalog_pc_tags=row.pc_tags,
            image_url=row.image_url,
        ))

    items.sort(key=lambda it: it.r_final, reverse=True)

    if not req.rerank:
        # ===== 従来パス(完全後方互換): R_final 降順 =====
        top = items[: req.top_n]
        _flag_serendipity(top)
        return RecommendV2Response(
            user_id=user.user_id,
            mu_thickness=mu_thickness,
            beta_used=beta,
            reranked_by_eig=False,
            used_explore_weight=None,
            results=top,
        )

    # ===== EIG 再ランクパス(rerank=True のときだけ発動)=====
    # 循環 import 回避のため遅延 import(active_learning は recommend_v2 を import する)
    import active_learning as al

    w = req.explore_weight if req.explore_weight is not None else mu_explore
    candidates = [
        al.Candidate(product_id=it.product_id, effective_lab=it.effective_lab,
                     r_final=it.r_final)
        for it in items
    ]
    scored = al.next_best(candidates, user.theta_color, mu_explore=w)

    by_id = {it.product_id: it for it in items}
    reranked: List[RecommendV2Item] = []
    for s in scored:
        it = by_id[s.product_id]
        it.eig_bits = s.eig_bits
        it.p_like = s.p_like
        it.score = s.score
        reranked.append(it)

    top = reranked[: req.top_n]
    _flag_serendipity(top)
    return RecommendV2Response(
        user_id=user.user_id,
        mu_thickness=mu_thickness,
        beta_used=beta,
        reranked_by_eig=True,
        used_explore_weight=max(0.0, min(1.0, w)),
        results=top,
    )


def _flag_serendipity(top: List[RecommendV2Item]) -> None:
    """返却 TOP-N に is_serendipity を立てる(設計書 Part VI / §7.4 の配線)。

    判定基準(明文化・自己校正・β 非依存):
      返却 TOP-N の中で
        (a) delta_e_to_color > median(ΔE)   … μ_color から遠い(似合い圏の外)
        (b) familiarity      < median(fam)  … 馴染みが薄い(未知)
      の **両方**を満たす「遠い×未知」象限の商品を冒険枠とする。

    - β(探索性)に依存しないので、explore 事前が低くてもフラグは立ち、
      ユーザーが反応 → is_serendipity=True 観測 → θ_explore が動ける。
    - TOP-N 内の相対判定なので絶対閾値のチューニング不要(ユーザー間で頑健)。
    - 要素が 3 未満、または ΔE/familiarity が全て同値で中央値分割が退化する場合は
      フラグ無し(無理に立てない)。
    """
    import statistics

    if len(top) < 3:
        return
    med_de = statistics.median(it.delta_e_to_color for it in top)
    med_fam = statistics.median(it.familiarity for it in top)
    for it in top:
        it.is_serendipity = (it.delta_e_to_color > med_de) and (it.familiarity < med_fam)
