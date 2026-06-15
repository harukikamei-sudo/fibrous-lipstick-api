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


def test_serendipity_flag() -> None:
    print("Test 8: is_serendipity フラグ(遠い×未知 象限)")
    # mu_color に近い親しみ商品 + 遠くて未知の冒険商品を混ぜる
    user = _make_user(mu_thickness=1.0, mu_explore=0.5)
    user.theta_pref = GaussianVec20(mu=[2.0] + [0.0] * 19, var=[1.0] * 20)
    rows = []
    # 近い&馴染み(x20 が μ_pref と揃う)→ serendipity でない
    for i in range(3):
        rows.append(_make_km_row(f"near{i}", LabValue(L=55, a=35, b=5),
                                  x20=[1.0] + [0.0] * 19))
    # 遠い&未知(μ_color から離れ、x20 が μ_pref と直交)→ serendipity 候補
    rows.append(_make_km_row("far_unknown", LabValue(L=25, a=-20, b=-10),
                             x20=[0.0, 1.0] + [0.0] * 18))
    res = recommend_v2(RecommendV2Request(user=user, km_table=rows, top_n=4))
    flags = {r.product_id: r.is_serendipity for r in res.results}
    print(f"  flags: {flags}")
    # far_unknown が冒険枠、near* は非冒険枠
    assert flags.get("far_unknown") is True, "遠い×未知が serendipity になっていない"
    assert all(not flags[f"near{i}"] for i in range(3)), "近い商品に冒険枠が立っている"
    print("  ✓ 遠い×未知 のみ is_serendipity=True")
    print()


def test_serendipity_needs_min_items() -> None:
    print("Test 9: TOP-N が 3 未満なら serendipity 立てない")
    user = _make_user(mu_thickness=1.0)
    rows = [_make_km_row("a", LabValue(L=55, a=35, b=5)),
            _make_km_row("b", LabValue(L=25, a=-20, b=-10))]
    res = recommend_v2(RecommendV2Request(user=user, km_table=rows, top_n=2))
    assert all(not r.is_serendipity for r in res.results), "2件で冒険枠が立った"
    print("  ✓ 2件では全て is_serendipity=False")
    print()


def test_rerank_backward_compat() -> None:
    print("Test 10: rerank 既定 False は従来挙動(後方互換)")
    user = _make_user(mu_thickness=1.0, mu_explore=0.5)
    rows = [_make_km_row(f"p{i}", LabValue(L=30 + i * 6, a=30, b=10)) for i in range(8)]
    base = recommend_v2(RecommendV2Request(user=user, km_table=rows, top_n=5))
    assert base.reranked_by_eig is False
    assert base.used_explore_weight is None
    assert all(it.eig_bits is None and it.score is None for it in base.results)
    rs = [it.r_final for it in base.results]
    assert rs == sorted(rs, reverse=True)
    print("  ✓ reranked_by_eig=False / eig None / r_final 降順")
    print()


def test_rerank_w0_matches_default_order() -> None:
    print("Test 11: rerank=True + w=0 は既定と同じ並び")
    user = _make_user(mu_thickness=1.0, mu_explore=0.5)
    rows = [_make_km_row(f"p{i}", LabValue(L=30 + i * 6, a=30, b=10)) for i in range(8)]
    base = recommend_v2(RecommendV2Request(user=user, km_table=rows, top_n=5))
    rk = recommend_v2(RecommendV2Request(user=user, km_table=rows, top_n=5,
                                         rerank=True, explore_weight=0.0))
    assert rk.reranked_by_eig is True and rk.used_explore_weight == 0.0
    assert [it.product_id for it in base.results] == [it.product_id for it in rk.results]
    assert all(it.eig_bits is not None for it in rk.results)
    print("  ✓ w=0 並び一致 + eig_bits 付与")
    print()


def test_rerank_explore_weight_default_uses_theta() -> None:
    print("Test 12: explore_weight 省略 → θ_explore.mu 使用")
    user = _make_user(mu_thickness=1.0, mu_explore=0.65)
    rows = [_make_km_row(f"p{i}", LabValue(L=30 + i * 6, a=30, b=10)) for i in range(8)]
    rk = recommend_v2(RecommendV2Request(user=user, km_table=rows, top_n=5, rerank=True))
    assert abs(rk.used_explore_weight - 0.65) < 1e-9
    print(f"  ✓ used_explore_weight={rk.used_explore_weight} == μ_explore")
    print()


def test_explore_does_not_ignore_color() -> None:
    """最冒険(μ_explore=1 → β=5)でも色 exploit が相殺されず、色は無視されない。

    回帰防止: α:β·w3 の比が崩れて「色を無視して世界観だけで選ぶ→似合わない色を出す」
    事故(ランダムが製品化不可なのと同じ穴)に陥らないことを固定する(SIMULATOR_GUIDE §6.6 割り切り4)。
    """
    print("Test 13: 最冒険でも色は無視されない(似合わない色を出さない)")
    user = _make_user(mu_thickness=1.0, mu_explore=1.0, mu_color=(50, 30, 15))
    # μ_pref は軸0を強く好む
    user.theta_pref = GaussianVec20(mu=[3.0] + [0.0] * 19, var=[1.0] * 20)
    rows = [
        # 色ピッタリ(ΔE≈0)だが世界観は μ_pref と直交(軸1)
        _make_km_row("near_color_plainWV", LabValue(L=50, a=30, b=15),
                     x20=[0.0, 1.0] + [0.0] * 18),
        # 世界観は完璧一致(軸0)だが色は遠い(ΔE 大)
        _make_km_row("far_color_perfectWV", LabValue(L=15, a=55, b=-10),
                     x20=[1.0] + [0.0] * 19),
    ]
    # 通常推薦(rerank なし)= R_final = f - β·familiarity。β=5(最冒険)。
    res = recommend_v2(RecommendV2Request(user=user, km_table=rows, top_n=2))
    by = {r.product_id: r for r in res.results}
    near, far = by["near_color_plainWV"], by["far_color_perfectWV"]
    # 遠い色は世界観完璧でも、似合う色(近い)に負ける = 色 exploit が支配
    assert res.results[0].product_id == "near_color_plainWV", \
        f"色が無視され遠い色が勝った: TOP1={res.results[0].product_id}"
    assert near.r_final > far.r_final
    print(f"  ✓ 最冒険でも near(ΔE={near.delta_e_to_color:.1f}, R={near.r_final:.1f}) "
          f"> far(ΔE={far.delta_e_to_color:.1f}, pref完璧, R={far.r_final:.1f})")
    print()


def _user_with_pref(mu, var, mu_thickness=1.0, mu_color=(55, 35, 5)) -> UserState:
    u = _make_user(mu_thickness=mu_thickness, mu_color=mu_color)
    u.theta_pref = GaussianVec20(mu=list(mu), var=list(var))
    return u


# ============ A2: reasons テスト(14〜18)============

def test_reasons_percentile_order() -> None:
    print("Test 14: reasons パーセンタイル(近い色ほど color_percentile 高)")
    user = _make_user(mu_thickness=1.0, mu_color=(55, 35, 5))
    km = [
        _make_km_row("near", LabValue(L=55, a=35, b=5)),    # t=1 で μ_color ちょうど
        _make_km_row("mid", LabValue(L=50, a=30, b=18)),
        _make_km_row("far", LabValue(L=30, a=62, b=42)),
    ]
    res = recommend_v2(RecommendV2Request(user=user, km_table=km, top_n=3))
    by = {it.product_id: it for it in res.results}
    assert all(it.reasons is not None for it in res.results)
    assert by["near"].reasons.color_percentile > by["far"].reasons.color_percentile
    for it in res.results:
        assert 0.0 <= it.reasons.color_percentile <= 1.0
        assert 0.0 <= it.reasons.pref_percentile <= 1.0
    print(f"  ✓ near.color_pct={by['near'].reasons.color_percentile:.2f} > "
          f"far={by['far'].reasons.color_percentile:.2f}、値域[0,1]")


def test_reasons_n1_boundary() -> None:
    print("Test 15: reasons N=1 境界 → percentile=1.0")
    user = _make_user(mu_thickness=1.0)
    km = [_make_km_row("only", LabValue(L=50, a=40, b=10))]
    r = recommend_v2(RecommendV2Request(user=user, km_table=km, top_n=1)).results[0].reasons
    assert r.color_percentile == 1.0 and r.pref_percentile == 1.0
    print("  ✓ 単一候補は color/pref percentile=1.0")


def test_reasons_rho_gate_and_negative() -> None:
    print("Test 16: top_axes は 正寄与 かつ var≤RHO·TAU2 のみ(負寄与/高分散は除外)")
    mu = [0.0] * 20
    var = [1.0] * 20
    mu[6] = 1.0; var[6] = 0.3      # sheer: eligible
    mu[2] = 1.0; var[2] = 0.9      # brightness: 寄与大だが高分散 → 除外
    mu[5] = -1.0; var[5] = 0.3     # moisture_finish: 負寄与 → 除外
    user = _user_with_pref(mu, var)
    x20 = [0.0] * 20
    x20[6] = 0.8; x20[2] = 0.9; x20[5] = 0.9
    km = [_make_km_row("p", LabValue(L=50, a=40, b=10), x20=x20),
          _make_km_row("q", LabValue(L=48, a=38, b=8), x20=[0.1] * 20)]
    res = recommend_v2(RecommendV2Request(user=user, km_table=km, top_n=2))
    p = next(it for it in res.results if it.product_id == "p")
    axes = [a.axis for a in p.reasons.top_axes]
    assert "sheer" in axes, axes
    assert "brightness" not in axes, axes        # 高分散で除外(寄与は大きいのに)
    assert "moisture_finish" not in axes, axes    # 負寄与で除外
    assert all(a.contribution > 0 for a in p.reasons.top_axes)
    print(f"  ✓ top_axes={axes}(brightness=高分散除外, moisture_finish=負寄与除外)")


def test_reasons_product_traits_exclude() -> None:
    print("Test 17: product_traits は is_系除外・top_axes と重複除外")
    mu = [0.0] * 20
    var = [1.0] * 20
    mu[6] = 1.0; var[6] = 0.3      # sheer → top_axes
    user = _user_with_pref(mu, var)
    x20 = [0.0] * 20
    x20[9] = 1.0   # is_tint(バイナリ → trait 除外)
    x20[6] = 0.9   # sheer(top_axis → trait 除外)
    x20[4] = 0.7   # glossy(trait 候補)
    km = [_make_km_row("p", LabValue(L=50, a=40, b=10), x20=x20),
          _make_km_row("q", LabValue(L=48, a=38, b=8), x20=[0.1] * 20)]
    res = recommend_v2(RecommendV2Request(user=user, km_table=km, top_n=2))
    p = next(it for it in res.results if it.product_id == "p")
    traits = [t.axis for t in p.reasons.product_traits]
    assert "is_tint" not in traits, traits     # バイナリ除外
    assert "sheer" not in traits, traits        # top_axes と重複除外
    assert "glossy" in traits, traits
    print(f"  ✓ product_traits={traits}(is_tint/sheer 除外, glossy 採用)")


def test_determinism_and_tiebreak() -> None:
    print("Test 18: 決定性(同一入力で同一TOP-N)+ 同点は商品ID昇順")
    user = _make_user(mu_thickness=1.0)
    same = LabValue(L=50, a=40, b=10)
    km = [_make_km_row("b", same, x20=[0.2] * 20),
          _make_km_row("a", same, x20=[0.2] * 20),
          _make_km_row("c", same, x20=[0.2] * 20)]
    r1 = [it.product_id for it in recommend_v2(
        RecommendV2Request(user=user, km_table=km, top_n=3)).results]
    r2 = [it.product_id for it in recommend_v2(
        RecommendV2Request(user=user, km_table=km, top_n=3)).results]
    assert r1 == r2, (r1, r2)                 # 同一入力 → 同一出力
    assert r1 == ["a", "b", "c"], r1          # 同点は商品ID昇順
    print(f"  ✓ 2回一致 + 同点ID昇順: {r1}")


def test_reasons_backward_compat_additive() -> None:
    print("Test 19: rerank=False でも reasons は付くが従来フィールドは不変(後方互換)")
    user = _make_user(mu_thickness=1.0)
    km = [_make_km_row(f"p{i}", LabValue(L=50 + i, a=40, b=10)) for i in range(6)]
    res = recommend_v2(RecommendV2Request(user=user, km_table=km, top_n=5))
    assert res.reranked_by_eig is False
    assert all(it.eig_bits is None and it.score is None for it in res.results)
    assert all(it.reasons is not None for it in res.results)  # 追加フィールド
    rf = [it.r_final for it in res.results]
    assert rf == sorted(rf, reverse=True)
    print("  ✓ eig None / r_final 降順 / reasons は追加されるのみ")


def test_candidate_count_competitive() -> None:
    print("Test 20: candidate_count = competitive set(団子で多く、分離で減る)+ catalog_size")
    from recommend_v2 import _competitive_count
    packed = [1.0, 0.9, 0.8, 0.7, 0.6, 0.59, 0.58, 0.57]   # 6位以降が5位の近傍
    separated = [1.0, 0.9, 0.8, 0.7, 0.6, 0.2, 0.1, 0.05]  # 6位以降が大きく分離
    c_packed = _competitive_count(packed, top_n=5)
    c_sep = _competitive_count(separated, top_n=5)
    assert c_packed > c_sep, (c_packed, c_sep)
    assert c_sep == 5, c_sep                                # 分離時は TOP-N に寄る
    assert _competitive_count([1.0] * 8, top_n=5) == 5      # 退化(全同値)→ TOP-N
    user = _make_user(mu_thickness=1.0)
    km = [_make_km_row(f"p{i}", LabValue(L=50 + i, a=40, b=10)) for i in range(8)]
    res = recommend_v2(RecommendV2Request(user=user, km_table=km, top_n=5))
    assert res.catalog_size == 8
    assert 5 <= res.candidate_count <= 8
    print(f"  ✓ packed={c_packed} > separated={c_sep}, 退化=5, "
          f"response candidate_count={res.candidate_count}/catalog={res.catalog_size}")


def test_evidence_filled_from_user() -> None:
    print("Test 21: reasons.top_axes.evidence は user.pref_evidence から最大2件充填")
    mu = [0.0] * 20
    var = [1.0] * 20
    mu[6] = 1.0; var[6] = 0.3       # sheer → top_axes
    user = _user_with_pref(mu, var)
    user.pref_evidence = {"sheer": ["pair_03", "pair_07", "pair_09"]}
    x20 = [0.0] * 20
    x20[6] = 0.8
    km = [_make_km_row("p", LabValue(L=50, a=40, b=10), x20=x20),
          _make_km_row("q", LabValue(L=48, a=38, b=8), x20=[0.1] * 20)]
    res = recommend_v2(RecommendV2Request(user=user, km_table=km, top_n=2))
    p = next(it for it in res.results if it.product_id == "p")
    sheer = next(a for a in p.reasons.top_axes if a.axis == "sheer")
    assert sheer.evidence == ["pair_03", "pair_07"], sheer.evidence
    print(f"  ✓ sheer.evidence={sheer.evidence}(pref_evidence から最大2件)")


if __name__ == "__main__":
    test_effective_lab_interpolation()
    test_beta_explore_monotone()
    test_cosine()
    test_close_to_mu_color_wins()
    test_thickness_shift_changes_ranking()
    test_serendipity_penalty()
    test_top_n_sorted()
    test_serendipity_flag()
    test_serendipity_needs_min_items()
    test_rerank_backward_compat()
    test_rerank_w0_matches_default_order()
    test_rerank_explore_weight_default_uses_theta()
    test_explore_does_not_ignore_color()
    test_reasons_percentile_order()
    test_reasons_n1_boundary()
    test_reasons_rho_gate_and_negative()
    test_reasons_product_traits_exclude()
    test_determinism_and_tiebreak()
    test_reasons_backward_compat_additive()
    test_candidate_count_competitive()
    test_evidence_filled_from_user()
    print("=" * 50)
    print("✅ recommend_v2.py: 全 21 テスト合格")
