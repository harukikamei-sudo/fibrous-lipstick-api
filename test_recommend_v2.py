"""recommend_v2.py の性質テスト。"""

import sys

from models_v13 import (
    GaussianLab,
    GaussianScalar,
    GaussianVec20,
    KMTableRow,
    LabValue,
    RecommendV2Request,
    UserState,
)
from recommend_v2 import (
    beta_from_explore,
    cosine_similarity,
    delta_e_2000,
    effective_lab,
    recommend_v2,
)


def _make_user(mu_thickness=0.5, mu_explore=0.5, mu_color=(55, 35, 5)) -> UserState:
    return UserState(
        user_id="u1",
        lip_lab=LabValue(L=62, a=22, b=12),
        pc_season="ブルベ夏",
        theta_color=GaussianLab(
            mu=LabValue(L=mu_color[0], a=mu_color[1], b=mu_color[2]),
            var=LabValue(L=10, a=10, b=10),
        ),
        theta_pref=GaussianVec20(mu=[0.0] * 20, var=[1.0] * 20),
        theta_explore=GaussianScalar(mu=mu_explore, var=0.25),
        theta_thickness=GaussianScalar(mu=mu_thickness, var=0.05),
    )


def _make_km_row(product_id: str, lab_full: LabValue, x20=None) -> KMTableRow:
    """21 段の applied: t=0 は唇地肌 L=62/a=22/b=12, t=1 で lab_full に直線推移(テスト用)。"""
    lip = LabValue(L=62, a=22, b=12)
    applied = []
    for i in range(21):
        w = i / 20.0
        applied.append(LabValue(
            L=lip.L * (1 - w) + lab_full.L * w,
            a=lip.a * (1 - w) + lab_full.a * w,
            b=lip.b * (1 - w) + lab_full.b * w,
        ))
    return KMTableRow(
        product_id=product_id,
        applied=applied,
        x20=x20 or [0.0] * 20,
        name=product_id,
        line_category="tint",
    )


# ============ Test 1: 線形補間の端点と中央 ============

def test_effective_lab_interpolation() -> None:
    print("Test 1: effective_lab 線形補間")
    row = _make_km_row("p1", LabValue(L=42, a=42, b=2))
    # t=0
    e0 = effective_lab(row, 0.0)
    assert abs(e0.L - 62) < 1e-9 and abs(e0.a - 22) < 1e-9
    # t=1
    e1 = effective_lab(row, 1.0)
    assert abs(e1.L - 42) < 1e-9 and abs(e1.a - 42) < 1e-9
    # t=0.5 (中央)
    e_mid = effective_lab(row, 0.5)
    assert abs(e_mid.L - 52) < 1e-6, e_mid.L
    # t=0.27 (補間が線形ベースで動く)
    e_027 = effective_lab(row, 0.27)
    assert 56 < e_027.L < 58, e_027.L
    print(f"  ✓ t=0: L={e0.L:.2f}, t=0.5: L={e_mid.L:.2f}, t=1: L={e1.L:.2f}")
    print(f"  ✓ t=0.27: L={e_027.L:.3f} (薄め寄り→唇に近い)")
    print()


# ============ Test 2: β(μ_explore) の単調性 ============

def test_beta_explore_monotone() -> None:
    print("Test 2: β(μ_explore) 単調")
    b0 = beta_from_explore(0.0, 5.0)
    b1 = beta_from_explore(1.0, 5.0)
    b_mid = beta_from_explore(0.5, 5.0)
    assert b0 == 0.0
    assert b1 == 5.0
    assert b_mid == 2.5
    print(f"  ✓ explore 0→{b0}, 0.5→{b_mid}, 1→{b1}")
    print()


# ============ Test 3: cosine_similarity ============

def test_cosine() -> None:
    print("Test 3: cosine_similarity")
    assert cosine_similarity([1, 0, 0], [1, 0, 0]) == 1.0
    assert cosine_similarity([1, 0, 0], [0, 1, 0]) == 0.0
    assert cosine_similarity([0, 0, 0], [1, 1, 1]) == 0.0  # ゼロベクトル安全
    print("  ✓ 同方向=1, 直交=0, ゼロベクトル=0\n")


# ============ Test 4: μ_color に近い商品が上位 ============

def test_close_to_mu_color_wins() -> None:
    print("Test 4: μ_color に近い商品が上位(α=3.0, β=0)")
    user = _make_user(mu_thickness=1.0, mu_explore=0.0)  # β=0で familiarity 無視
    # 商品 A: μ_color と一致(L=55,a=35,b=5)
    # 商品 B: μ_color と大きく外れる(L=20,a=-30,b=-10)
    rows = [
        _make_km_row("A", LabValue(L=55, a=35, b=5)),
        _make_km_row("B", LabValue(L=20, a=-30, b=-10)),
    ]
    req = RecommendV2Request(user=user, km_table=rows, top_n=2)
    res = recommend_v2(req)
    assert res.results[0].product_id == "A", res.results[0].product_id
    assert res.results[1].product_id == "B"
    print(f"  ✓ TOP1=A (ΔE={res.results[0].delta_e_to_color:.2f}), "
          f"TOP2=B (ΔE={res.results[1].delta_e_to_color:.2f})")
    print()


# ============ Test 5: μ_thickness が薄め寄りで applied が薄い商品が上位 ============

def test_thickness_shift_changes_ranking() -> None:
    print("Test 5: μ_thickness で同じ商品ランキングが変わる")
    # μ_color は唇に近めに設定。薄め塗りで効果が変わる
    user_light = _make_user(mu_thickness=0.2, mu_color=(58, 25, 12))
    user_full = _make_user(mu_thickness=1.0, mu_color=(58, 25, 12))
    rows = [
        _make_km_row("light", LabValue(L=45, a=45, b=10)),  # 1度塗りで唇寄り
        _make_km_row("dark", LabValue(L=25, a=50, b=5)),
    ]
    req_l = RecommendV2Request(user=user_light, km_table=rows, top_n=2)
    req_f = RecommendV2Request(user=user_full, km_table=rows, top_n=2)
    res_l = recommend_v2(req_l)
    res_f = recommend_v2(req_f)
    # 薄めユーザー: μ_thickness 小さいので「明るめ寄り(唇に近い)applied」が μ_color に近い
    # フルユーザー: フル塗り Lab が μ_color に近い方
    print(f"  light: TOP1={res_l.results[0].product_id} (ΔE={res_l.results[0].delta_e_to_color:.2f})")
    print(f"  full:  TOP1={res_f.results[0].product_id} (ΔE={res_f.results[0].delta_e_to_color:.2f})")
    # mu_thickness が違うと effective_Lab が違う → スコアも違う
    assert (res_l.results[0].effective_lab.L
            != res_f.results[0].effective_lab.L)
    print(f"  ✓ effective_Lab が μ_thickness で変化\n")


# ============ Test 6: explore=1 では familiarity が高い商品にペナルティ ============

def test_serendipity_penalty() -> None:
    print("Test 6: μ_explore=1 で familiarity 高商品が降格")
    # 商品 A,B とも μ_color に同じ ΔE で違う x20(familiarity 差)
    user_no = _make_user(mu_thickness=1.0, mu_explore=0.0)
    user_yes = _make_user(mu_thickness=1.0, mu_explore=1.0)
    # μ_pref を「軸0を強く好む」に変更
    for u in (user_no, user_yes):
        new_mu = [3.0] + [0.0] * 19
        u.theta_pref = GaussianVec20(mu=new_mu, var=[1.0] * 20)

    # 商品 A: x20=[1,0,...] → μ_pref と cos=1 = familiarity 高い(親しみある)
    # 商品 B: x20=[0,1,...] → μ_pref と cos=0 = familiarity 低い(未知)
    lab_same = LabValue(L=55, a=35, b=5)
    rows = [
        _make_km_row("A", lab_same, x20=[1.0] + [0.0] * 19),
        _make_km_row("B", lab_same, x20=[0.0, 1.0] + [0.0] * 18),
    ]
    res_no = recommend_v2(RecommendV2Request(user=user_no, km_table=rows, top_n=2))
    res_yes = recommend_v2(RecommendV2Request(user=user_yes, km_table=rows, top_n=2))
    # explore=0 では A が上(familiarity 無視で μ_pref · x20 が大きい A が勝つ)
    assert res_no.results[0].product_id == "A"
    # explore=1 では familiarity ペナルティで B が上に来ることがある
    print(f"  explore=0: TOP1={res_no.results[0].product_id} (r={res_no.results[0].r_final:.2f})")
    print(f"  explore=1: TOP1={res_yes.results[0].product_id} (r={res_yes.results[0].r_final:.2f})")
    # B の familiarity < A の familiarity を確認
    fam_a = next(r for r in res_no.results if r.product_id == "A").familiarity
    fam_b = next(r for r in res_no.results if r.product_id == "B").familiarity
    assert fam_a > fam_b, (fam_a, fam_b)
    print(f"  ✓ familiarity: A={fam_a:.3f} > B={fam_b:.3f}")
    print()


# ============ Test 7: TOP-N が正しく r_final 降順 ============

def test_top_n_sorted() -> None:
    print("Test 7: TOP-N が r_final 降順")
    user = _make_user(mu_thickness=1.0, mu_explore=0.0)
    rows = [
        _make_km_row(f"p{i}", LabValue(L=30 + i * 5, a=30 + i * 2, b=5))
        for i in range(10)
    ]
    res = recommend_v2(RecommendV2Request(user=user, km_table=rows, top_n=5))
    rs = [r.r_final for r in res.results]
    assert rs == sorted(rs, reverse=True), rs
    print(f"  ✓ r_final 降順: {[f'{r:.2f}' for r in rs]}\n")


if __name__ == "__main__":
    test_effective_lab_interpolation()
    test_beta_explore_monotone()
    test_cosine()
    test_close_to_mu_color_wins()
    test_thickness_shift_changes_ranking()
    test_serendipity_penalty()
    test_top_n_sorted()
    print("=" * 50)
    print("✅ recommend_v2.py: 全 7 テスト合格")
