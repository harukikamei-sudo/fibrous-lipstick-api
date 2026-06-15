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
from typing import Dict, List, Sequence

import numpy as np
from skimage import color as skcolor

from catalog_x20 import AXIS_LABELS_JA, AXIS_NAMES
from models_v13 import (
    KMTableRow,
    LabValue,
    ProductTrait,
    ReasonAxis,
    RecommendReasons,
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


# ============ A2: 推薦理由(reasons)の構築 ============
# RHO: top_axes は「事後分散 var ≤ RHO·TAU2_PREF の確信ある軸」だけ喋る。
# ※ フロント F3(conciergeScript.ts)の発話トリガー RHO と同値を共有すること
#   (型生成に乗らないので .env / 定数ファイルで同期し、参照先をコメントで明記)。
RHO_CONFIDENT = 0.5
TAU2_PREF = 1.0          # = pair_compare.TAU2_PREF(A1 で constants へ一元化予定)
# is_系バイナリ形態軸と、それに相関する連続軸(共線性)。表示のタイブレークにのみ使う。
IS_BINARY_AXES = {"is_tint", "is_balm", "is_gloss"}
CONTINUOUS_PROXY = {"is_gloss": "glossy", "is_tint": "longlasting", "is_balm": "moisturizing"}
TIEBREAK_MARGIN = 0.20   # 拮抗判定(差が20%以内なら連続軸を優先表示)。スコアには無影響。

# candidate_count(A2-fix・competitive set 方式)。
# ※ 当初 fix の「R_final>プール中央値の個数」は中央値分割が常に≈N/2で観測が進んでも減らず、
#   「145→…→5」の絞り込み演出に使えないため破棄。TOP-N 最下位スコアから margin·(1位−N位)
#   以内にいる候補数(事後が尖るほど分離して減る)に置換(A4 ハーネスで単調性を検証・調整)。
MARGIN_COMPETITIVE = 0.15


def _competitive_count(
    r_finals_desc: Sequence[float], top_n: int, margin: float = MARGIN_COMPETITIVE
) -> int:
    """残候補数 = TOP-N 最下位スコアから margin·(1位−N位)以内にいる候補の数。

    threshold = score[N位] − margin·(score[1位] − score[N位]),  count = #{R_final ≥ threshold}。
    序盤(事後 flat)はスコアが団子で多く、観測が進み事後が尖ると分離して減る。
    退化(スプレッド≈0=全同値/TOP-N団子)時は TOP-N 件数にフォールバック。
    """
    n = len(r_finals_desc)
    if n == 0:
        return 0
    k = min(top_n, n)
    s_top, s_bot = r_finals_desc[0], r_finals_desc[k - 1]
    spread = s_top - s_bot
    if spread <= 1e-9:
        return k  # 退化 → TOP-N フォールバック
    threshold = s_bot - margin * spread
    return sum(1 for s in r_finals_desc if s >= threshold)


def _percentile_high_good(values: Sequence[float], x: float) -> float:
    """x が values 内でどれだけ上位か(高い値=高パーセンタイル、[0,1])。

    タイは中間順位、要素1件は 1.0。絶対閾値を持たない「順位率」
    (_flag_serendipity と同じ自己校正の哲学)。
    """
    n = len(values)
    if n <= 1:
        return 1.0
    less = sum(1 for v in values if v < x)
    equal = sum(1 for v in values if v == x)
    return (less + 0.5 * (equal - 1)) / (n - 1)


def _top_axes_with_tiebreak(eligible: List[tuple]) -> List[tuple]:
    """eligible=[(axis, contribution)](contribution 降順)に共線性タイブレークを適用。

    is_系バイナリ軸とその連続プロキシ(is_gloss↔glossy 等)の寄与が TIEBREAK_MARGIN
    以内で拮抗するとき、表示は連続軸を優先する(Mina に伝わるのは形態名より質感の言葉)。
    これは表示選択の規則でありスコア計算には一切影響しない。
    """
    contrib_by_axis = dict(eligible)
    out: List[tuple] = []
    used: set = set()
    for axis, c in eligible:
        if axis in used:
            continue
        proxy = CONTINUOUS_PROXY.get(axis)
        if proxy is not None and proxy not in used and proxy in contrib_by_axis:
            pc = contrib_by_axis[proxy]
            denom = max(abs(c), abs(pc), 1e-9)
            if abs(c - pc) / denom <= TIEBREAK_MARGIN:
                out.append((proxy, pc))
                used.add(proxy)
                used.add(axis)
                continue
        out.append((axis, c))
        used.add(axis)
    return out


def _build_reasons(
    x20: Sequence[float], mu_pref: Sequence[float], pref_var: Sequence[float],
    dE: float, pref_contrib: float,
    pool_dEs: Sequence[float], pool_pref_contribs: Sequence[float],
    pref_evidence: Dict[str, List[str]],
) -> RecommendReasons:
    """1商品分の reasons を構築(数値・ラベル・来歴のみ。文章化はフロント)。"""
    color_pct = _percentile_high_good([-d for d in pool_dEs], -dE)
    pref_pct = _percentile_high_good(pool_pref_contribs, pref_contrib)

    # top_axes: 正寄与かつ確信のある軸のみ。共線性タイブレークを適用して最大2。
    eligible = [
        (AXIS_NAMES[k], mu_pref[k] * x20[k])
        for k in range(20)
        if mu_pref[k] * x20[k] > 0 and pref_var[k] <= RHO_CONFIDENT * TAU2_PREF
    ]
    eligible.sort(key=lambda t: (-t[1], t[0]))
    top_axes = [
        ReasonAxis(axis=a, label=AXIS_LABELS_JA[a], contribution=round(c, 4),
                   evidence=list(pref_evidence.get(a, []))[:2])
        for a, c in _top_axes_with_tiebreak(eligible)[:2]
    ]

    # product_traits: 商品側で値が突出した軸。is_系除く・top_axes と重複除く。最大2。
    chosen = {ra.axis for ra in top_axes}
    traits = [
        (AXIS_NAMES[k], x20[k])
        for k in range(20)
        if AXIS_NAMES[k] not in IS_BINARY_AXES and AXIS_NAMES[k] not in chosen and x20[k] > 0
    ]
    traits.sort(key=lambda t: (-t[1], t[0]))
    product_traits = [ProductTrait(axis=a, label=AXIS_LABELS_JA[a]) for a, _ in traits[:2]]

    return RecommendReasons(
        color_percentile=round(color_pct, 4),
        pref_percentile=round(pref_pct, 4),
        scene_match=False,  # A1 の I_dialog 配線で生きる。A2 時点では false 固定。
        top_axes=top_axes,
        product_traits=product_traits,
    )


def _attach_reasons(
    top: List[RecommendV2Item], req: RecommendV2Request, all_items: List[RecommendV2Item],
    mu_pref: Sequence[float], pref_var: Sequence[float], beta: float,
    pref_evidence: Dict[str, List[str]],
) -> None:
    """返却 TOP-N に reasons を付与。パーセンタイルは候補プール(全 km_table)基準。"""
    w2 = req.familiarity_weights[1]
    x20_by_id = {row.product_id: list(row.x20) for row in req.km_table}

    def _pref_contrib(it: RecommendV2Item) -> float:
        # pref_contrib = μ_pref·x20 − β·w2·cos(μ_pref, x20)(意味での再グルーピング)
        return it.pref_match - beta * w2 * cosine_similarity(mu_pref, x20_by_id[it.product_id])

    pool_dEs = [it.delta_e_to_color for it in all_items]
    pool_pref_contribs = [_pref_contrib(it) for it in all_items]
    for it in top:
        it.reasons = _build_reasons(
            x20_by_id[it.product_id], mu_pref, pref_var,
            it.delta_e_to_color, _pref_contrib(it), pool_dEs, pool_pref_contribs,
            pref_evidence,
        )


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

    # 決定性(A2-fix): 同点は商品ID昇順で安定化(同一入力 → 同一 TOP-N を保証)。
    items.sort(key=lambda it: (-it.r_final, it.product_id))

    # 残候補数(A2-fix・competitive set)+ プール総数。表示専用で TOP-N 選定には不使用。
    pref_evidence = user.pref_evidence or {}
    candidate_count = _competitive_count([it.r_final for it in items], req.top_n)
    catalog_size = len(req.km_table)

    if not req.rerank:
        # ===== 従来パス(完全後方互換): R_final 降順 =====
        top = items[: req.top_n]
        _flag_serendipity(top)
        _attach_reasons(top, req, items, mu_pref, user.theta_pref.var, beta, pref_evidence)
        return RecommendV2Response(
            user_id=user.user_id,
            mu_thickness=mu_thickness,
            beta_used=beta,
            reranked_by_eig=False,
            used_explore_weight=None,
            candidate_count=candidate_count,
            catalog_size=catalog_size,
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
    _attach_reasons(top, req, items, mu_pref, user.theta_pref.var, beta, pref_evidence)
    return RecommendV2Response(
        user_id=user.user_id,
        mu_thickness=mu_thickness,
        beta_used=beta,
        reranked_by_eig=True,
        used_explore_weight=max(0.0, min(1.0, w)),
        candidate_count=candidate_count,
        catalog_size=catalog_size,
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
