"""active_learning.py の性質テスト(EIG / next_best)。"""


from models_v13 import GaussianLab, LabValue
from active_learning import (
    Candidate,
    SIGMA2_AR_LIKE,
    expected_information_gain,
    kl_color_if_liked,
    next_best,
    p_like,
)
import bayesian


def _theta(mu=(50.0, 30.0, 15.0), var=(10.0, 10.0, 10.0)) -> GaussianLab:
    return GaussianLab(
        mu=LabValue(L=mu[0], a=mu[1], b=mu[2]),
        var=LabValue(L=var[0], a=var[1], b=var[2]),
    )


def _lab(L, a, b) -> LabValue:
    return LabValue(L=L, a=a, b=b)


# ============ 定数のドリフト防止 ============

def test_sigma_matches_bayesian() -> None:
    print("Test 1: SIGMA2_AR_LIKE が bayesian と一致(ドリフト防止)")
    assert SIGMA2_AR_LIKE == bayesian.SIGMA2_BY_SOURCE["ar_view_like"]
    print(f"  ✓ SIGMA2_AR_LIKE={SIGMA2_AR_LIKE} == bayesian の値")
    print()


# ============ KL は ‖r − μ‖² で単調増加 ============

def test_kl_increases_with_distance() -> None:
    print("Test 2: KL(like時) は μ_color から遠いほど大きい")
    th = _theta()
    near = kl_color_if_liked(th, _lab(52, 31, 16))   # μ にほぼ一致
    mid = kl_color_if_liked(th, _lab(60, 40, 25))
    far = kl_color_if_liked(th, _lab(80, 60, 45))
    assert near < mid < far, (near, mid, far)
    print(f"  ✓ KL: near={near:.3f} < mid={mid:.3f} < far={far:.3f} [nat]")
    print()


# ============ p_like は ΔE で単調減少 ============

def test_plike_monotone_decreasing() -> None:
    print("Test 3: p_like は ΔE が大きいほど小さい(知覚シグモイド)")
    th = _theta()
    p_near = p_like(th, _lab(51, 31, 16))
    p_mid = p_like(th, _lab(62, 42, 26))
    p_far = p_like(th, _lab(85, 62, 46))
    assert p_near > p_mid > p_far, (p_near, p_mid, p_far)
    assert 0.0 < p_far and p_near < 1.0
    print(f"  ✓ p_like: near={p_near:.3f} > mid={p_mid:.3f} > far={p_far:.3f}")
    print()


# ============ EIG は中間距離でピーク(explore/exploit スイートスポット) ============

def test_eig_peaks_at_intermediate() -> None:
    print("Test 4: EIG は中間距離でピーク(両端より大きい)")
    th = _theta()
    # μ=(50,30,15) から L 方向に距離を変えた候補列
    cands = [_lab(50 + d, 30, 15) for d in [0, 5, 10, 15, 20, 30, 45, 60]]
    eigs = [expected_information_gain(th, c).eig_bits for c in cands]
    peak_idx = max(range(len(eigs)), key=lambda i: eigs[i])
    print("  EIG[bit]:", [f"{e:.2f}" for e in eigs])
    # ピークが両端でない = 中間にスイートスポットがある
    assert 0 < peak_idx < len(eigs) - 1, f"ピークが端 (idx={peak_idx})"
    print(f"  ✓ ピークは中間 (idx={peak_idx}, ΔE方向に内側)")
    print()


# ============ next_best: w=0 は R_final 降順 ============

def test_w0_equals_rfinal_order() -> None:
    print("Test 5: w=0(純 exploit)→ R_final 降順と一致")
    th = _theta()
    cands = [
        Candidate("a", _lab(80, 60, 45), r_final=-5.0),   # 遠い・低 R
        Candidate("b", _lab(51, 31, 16), r_final=-1.0),   # 近い・高 R
        Candidate("c", _lab(60, 40, 25), r_final=-3.0),
    ]
    scored = next_best(cands, th, mu_explore=0.0)
    order = [s.product_id for s in scored]
    expected = [c.product_id for c in sorted(cands, key=lambda c: c.r_final, reverse=True)]
    assert order == expected, (order, expected)
    print(f"  ✓ w=0 順 {order} == R_final 降順 {expected}")
    print()


# ============ next_best: w=1 は EIG 降順 ============

def test_w1_equals_eig_order() -> None:
    print("Test 6: w=1(純 explore)→ EIG 降順と一致")
    th = _theta()
    cands = [
        Candidate("a", _lab(80, 60, 45), r_final=-1.0),
        Candidate("b", _lab(51, 31, 16), r_final=-1.0),
        Candidate("c", _lab(62, 42, 26), r_final=-1.0),
    ]
    scored = next_best(cands, th, mu_explore=1.0)
    order = [s.product_id for s in scored]
    eig_sorted = sorted(scored, key=lambda s: s.eig_bits, reverse=True)
    expected = [s.product_id for s in eig_sorted]
    assert order == expected, (order, expected)
    print(f"  ✓ w=1 順 {order} == EIG 降順")
    print()


# ============ explore_weight で先頭が変わりうる(exploit↔explore) ============

def test_weight_shifts_head() -> None:
    print("Test 7: w を上げると先頭が exploit から explore 寄りに動きうる")
    th = _theta()
    cands = [
        Candidate("exploit", _lab(51, 31, 16), r_final=0.0),   # 近い・高 R・低 EIG
        Candidate("explore", _lab(62, 42, 26), r_final=-4.0),  # 中距離・低 R・高 EIG
    ]
    head_w0 = next_best(cands, th, mu_explore=0.0)[0].product_id
    head_w1 = next_best(cands, th, mu_explore=1.0)[0].product_id
    print(f"  w=0 先頭={head_w0} / w=1 先頭={head_w1}")
    assert head_w0 == "exploit", head_w0
    assert head_w1 == "explore", head_w1
    print("  ✓ w=0→exploit / w=1→explore に先頭が切替")
    print()


# ============ w のクランプ + 空入力 ============

def test_clamp_and_empty() -> None:
    print("Test 8: μ_explore クランプ / 空候補")
    th = _theta()
    assert next_best([], th, mu_explore=0.5) == []
    cands = [Candidate("a", _lab(55, 35, 20), -1.0), Candidate("b", _lab(60, 40, 25), -2.0)]
    # w=2.0 でも w=1.0 と同じ(クランプ)
    s_over = next_best(cands, th, mu_explore=2.0)
    s_one = next_best(cands, th, mu_explore=1.0)
    assert [x.product_id for x in s_over] == [x.product_id for x in s_one]
    print("  ✓ 空候補=[] / w>1 はクランプされ w=1 と一致")
    print()


if __name__ == "__main__":
    test_sigma_matches_bayesian()
    test_kl_increases_with_distance()
    test_plike_monotone_decreasing()
    test_eig_peaks_at_intermediate()
    test_w0_equals_rfinal_order()
    test_w1_equals_eig_order()
    test_weight_shifts_head()
    test_clamp_and_empty()
    print("=" * 50)
    print("✅ active_learning.py: 全 8 テスト合格")
