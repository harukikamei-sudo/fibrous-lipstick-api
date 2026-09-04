"""/v13/* エンドポイントの単体テスト(正常系 + エラーケース)。

test_v13_flow.py は E2E、こちらは個別エンドポイント毎の正常/異常を網羅する。
"""

import sys

from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def hr(title: str) -> None:
    print(f"\n--- {title} ---")


def assert_status(resp, expected: int, label: str) -> None:
    if resp.status_code != expected:
        print(f"  ✗ {label}: expected {expected}, got {resp.status_code}: {resp.text[:200]}")
        sys.exit(1)
    print(f"  ✓ {label}: {expected}")


def make_user(pc: str = "ブルベ夏") -> dict:
    pairs = client.get("/v13/pair_compare/init").json()["pairs"]
    apply = client.post("/v13/pair_compare/apply", json={
        "choices": [{"pair_id": p["pair_id"], "chose": "left"} for p in pairs],
        "pc_season": pc,
    }).json()
    return {
        "user_id": "test",
        "lip_lab": {"L": 62, "a": 22, "b": 12},
        "pc_season": pc,
        "theta_color": apply["theta_color"],
        "theta_pref": apply["theta_pref"],
        "theta_explore": apply["theta_explore"],
        "theta_thickness": apply["theta_thickness"],
    }


# ============ /v13/pair_compare/init ============

def test_pair_init_returns_10_pairs() -> None:
    hr("/v13/pair_compare/init: 10 ペア返る")
    r = client.get("/v13/pair_compare/init")
    assert_status(r, 200, "GET /v13/pair_compare/init")
    data = r.json()
    assert "pairs" in data, "pairs キーなし"
    assert len(data["pairs"]) == 10, f"ペア数 {len(data['pairs'])} != 10"
    for p in data["pairs"]:
        assert p["pair_type"] in ("color", "worldview")
        assert "left" in p and "right" in p
        for side in (p["left"], p["right"]):
            assert "product_id" in side
            assert "lab" in side and {"L", "a", "b"} <= side["lab"].keys()
            assert len(side["x20"]) == 20
    n_color = sum(1 for p in data["pairs"] if p["pair_type"] == "color")
    n_wv = sum(1 for p in data["pairs"] if p["pair_type"] == "worldview")
    print(f"  ✓ 内訳: color={n_color}, worldview={n_wv}")
    assert n_color == 5 and n_wv == 5


# ============ /v13/pair_compare/apply ============

def test_pair_apply_normal() -> None:
    hr("/v13/pair_compare/apply: 正常系")
    pairs = client.get("/v13/pair_compare/init").json()["pairs"]
    r = client.post("/v13/pair_compare/apply", json={
        "choices": [{"pair_id": p["pair_id"], "chose": "left"} for p in pairs],
        "pc_season": "ブルベ夏",
    })
    assert_status(r, 200, "POST /v13/pair_compare/apply")
    d = r.json()
    for k in ["theta_color", "theta_pref", "theta_explore", "theta_thickness",
              "n_color_obs", "n_worldview_obs"]:
        assert k in d, f"{k} がレスポンスに無い"
    assert d["n_color_obs"] == 5 and d["n_worldview_obs"] == 5
    assert len(d["theta_pref"]["mu"]) == 20
    print(f"  ✓ μ_color L={d['theta_color']['mu']['L']:.1f}, n_color={d['n_color_obs']}")


def test_pair_apply_unknown_pair_id() -> None:
    hr("/v13/pair_compare/apply: 未知 pair_id は飛ばされる")
    r = client.post("/v13/pair_compare/apply", json={
        "choices": [{"pair_id": "unknown_pair_999", "chose": "left"}],
        "pc_season": "ブルベ夏",
    })
    assert_status(r, 200, "未知 pair_id でも 200")
    d = r.json()
    assert d["n_color_obs"] == 0 and d["n_worldview_obs"] == 0
    print("  ✓ 未知ペアは集計に入らない (n_color=0, n_wv=0)")


def test_pair_apply_empty_choices_400() -> None:
    hr("/v13/pair_compare/apply: 空 choices は 422")
    r = client.post("/v13/pair_compare/apply", json={
        "choices": [],
        "pc_season": "ブルベ夏",
    })
    assert_status(r, 422, "空 choices は 422 Validation Error")


def test_pair_apply_no_pc_uses_neutral() -> None:
    hr("/v13/pair_compare/apply: pc_season 未指定でも動く")
    pairs = client.get("/v13/pair_compare/init").json()["pairs"]
    r = client.post("/v13/pair_compare/apply", json={
        "choices": [{"pair_id": p["pair_id"], "chose": "left"} for p in pairs[:5]],
    })
    assert_status(r, 200, "pc_season 未指定でも 200")
    d = r.json()
    print(f"  ✓ neutral μ_color L={d['theta_color']['mu']['L']:.1f}")


# ============ /v13/update_user ============

def test_update_user_normal() -> None:
    hr("/v13/update_user: 正常系(AR like)")
    user = make_user()
    before_mu_t = user["theta_thickness"]["mu"]
    r = client.post("/v13/update_user", json={
        "user": user,
        "observations": [{
            "source": "ar_view_like",
            "product_id": "rmd_blur_fudge_03",
            "observed_lab": {"L": 46, "a": 42, "b": 21},
            "thickness": 0.9,
            "y": 1.0,
        }],
    })
    assert_status(r, 200, "POST /v13/update_user")
    d = r.json()
    new_mu_t = d["user"]["theta_thickness"]["mu"]
    assert new_mu_t > before_mu_t, "thickness が上昇していない"
    assert d["n_applied"]["theta_thickness"] == 1
    assert d["n_applied"]["theta_color"] == 1
    print(f"  ✓ μ_thickness: {before_mu_t:.3f} → {new_mu_t:.3f}")


def test_update_user_extras_accepted() -> None:
    hr("/v13/update_user: extras(F4-fix #4 の kept/decided)を受理し更新を壊さない")
    user = make_user()
    r = client.post("/v13/update_user", json={
        "user": user,
        "observations": [{
            "source": "ar_view_like",
            "product_id": "rmd_blur_fudge_03",
            "observed_lab": {"L": 46, "a": 42, "b": 21},
            "thickness": 0.9,
            "y": 1.0,
            "extras": {"action": "decide", "kept": True, "decided": True},
        }],
    })
    assert_status(r, 200, "POST /v13/update_user (extras 付き)")
    d = r.json()
    # extras はベイズ更新に未使用 = 通常どおり color/thickness が 1 件適用される
    assert d["n_applied"]["theta_color"] == 1 and d["n_applied"]["theta_thickness"] == 1
    print("  ✓ extras 付き観測を受理(更新は通常どおり)")


def test_update_user_empty_obs_422() -> None:
    hr("/v13/update_user: observations 空は 422")
    user = make_user()
    r = client.post("/v13/update_user", json={
        "user": user, "observations": [],
    })
    assert_status(r, 422, "空 observations")


def test_update_user_dislike_does_not_move_color() -> None:
    hr("/v13/update_user: dislike は θ_color を一切動かさない(修正1)")
    user = make_user()
    before = user["theta_color"]
    r = client.post("/v13/update_user", json={
        "user": user,
        "observations": [{
            "source": "ar_view_dislike",
            "product_id": "rmd_blur_fudge_03",
            "observed_lab": {"L": 80, "a": 40, "b": 20},  # 明るい色を ✕
            "y": -1.0,
        }],
    })
    assert_status(r, 200, "dislike 観測")
    d = r.json()
    after = d["user"]["theta_color"]
    # μ も σ² も prior と完全一致(dislike は色を歪めない)
    for k in ("L", "a", "b"):
        assert after["mu"][k] == before["mu"][k], f"dislike で μ_{k} が動いた"
        assert after["var"][k] == before["var"][k], f"dislike で σ²_{k} が動いた"
    assert d["n_applied"]["theta_color"] == 0, d["n_applied"]
    print(f"  ✓ μ_color_L 不変 {before['mu']['L']:.2f}, theta_color n_applied=0")


# ============ /v13/recommend ============

def test_recommend_normal() -> None:
    hr("/v13/recommend: 正常系 TOP-N")
    user = make_user()
    r = client.post("/v13/recommend", json={"user": user, "top_n": 5})
    assert_status(r, 200, "POST /v13/recommend")
    d = r.json()
    assert len(d["results"]) == 5
    for it in d["results"]:
        for k in ["product_id", "name", "line_category", "effective_lab",
                  "delta_e_to_color", "pref_match", "f_score",
                  "familiarity", "r_final", "image_url"]:
            assert k in it, f"{k} がレスポンスに無い"
        assert {"L", "a", "b"} <= it["effective_lab"].keys()
    # 降順チェック
    rs = [it["r_final"] for it in d["results"]]
    assert rs == sorted(rs, reverse=True), "R_final 降順でない"
    print("  ✓ TOP-5 全フィールド OK, image_url 含む")
    img = d["results"][0]["image_url"]
    assert img and img.startswith("http"), f"image_url が URL でない: {img}"
    print(f"  ✓ TOP-1 image_url: {img[:60]}...")


def test_recommend_with_line_filter() -> None:
    hr("/v13/recommend: line_category フィルタ")
    user = make_user()
    r = client.post("/v13/recommend", json={
        "user": user, "top_n": 10, "line_category": "matte",
    })
    assert_status(r, 200, "matte 絞り込み")
    d = r.json()
    for it in d["results"]:
        assert it["line_category"] == "matte", \
            f"matte 以外: {it['product_id']} ({it['line_category']})"
    print(f"  ✓ TOP-{len(d['results'])} 全部 matte")


def test_recommend_thickness_changes_eff_lab() -> None:
    hr("/v13/recommend: μ_thickness で effective_lab が変わる")
    user_a = make_user()
    user_b = make_user()
    user_a["theta_thickness"]["mu"] = 0.2
    user_b["theta_thickness"]["mu"] = 0.9
    ra = client.post("/v13/recommend", json={"user": user_a, "top_n": 3}).json()
    rb = client.post("/v13/recommend", json={"user": user_b, "top_n": 3}).json()
    # 共通する product を見つけて effective_lab を比較
    a_ids = {r["product_id"]: r for r in ra["results"]}
    common = None
    for r in rb["results"]:
        if r["product_id"] in a_ids:
            common = (a_ids[r["product_id"]], r)
            break
    if common:
        a_eff = common[0]["effective_lab"]
        b_eff = common[1]["effective_lab"]
        assert abs(a_eff["L"] - b_eff["L"]) > 0.5, "L が変化していない"
        print(f"  ✓ μ_t=0.2: L={a_eff['L']:.1f}, μ_t=0.9: L={b_eff['L']:.1f}")
    else:
        print("  ⚠ 共通商品なし(両方とも個人化が強く効いた)")


def test_recommend_serendipity_explore_high() -> None:
    hr("/v13/recommend: μ_explore で β が変わる")
    user = make_user()
    user["theta_explore"]["mu"] = 0.0
    r0 = client.post("/v13/recommend", json={"user": user, "top_n": 1}).json()
    user["theta_explore"]["mu"] = 1.0
    r1 = client.post("/v13/recommend", json={"user": user, "top_n": 1}).json()
    assert r0["beta_used"] == 0.0
    assert r1["beta_used"] == 5.0
    print(f"  ✓ explore=0→β={r0['beta_used']}, explore=1→β={r1['beta_used']}")


def test_recommend_default_no_rerank() -> None:
    hr("/v13/recommend: 既定は rerank なし(後方互換)")
    user = make_user()
    r = client.post("/v13/recommend", json={"user": user, "top_n": 5})
    assert_status(r, 200, "default recommend")
    d = r.json()
    assert d["reranked_by_eig"] is False
    assert d["used_explore_weight"] is None
    # eig 診断は None(従来出力に EIG が混ざらない)
    for it in d["results"]:
        assert it["eig_bits"] is None and it["p_like"] is None and it["score"] is None
    # 並びは r_final 降順(従来通り)
    rs = [it["r_final"] for it in d["results"]]
    assert rs == sorted(rs, reverse=True)
    print("  ✓ reranked_by_eig=False, eig 系 None, r_final 降順")


def test_recommend_rerank_w0_equals_default() -> None:
    hr("/v13/recommend: rerank=true + w=0 は既定と同じ並び(純 exploit)")
    user = make_user()
    base = client.post("/v13/recommend", json={"user": user, "top_n": 5}).json()
    rk = client.post("/v13/recommend", json={
        "user": user, "top_n": 5, "rerank": True, "explore_weight": 0.0}).json()
    assert rk["reranked_by_eig"] is True
    assert rk["used_explore_weight"] == 0.0
    base_ids = [it["product_id"] for it in base["results"]]
    rk_ids = [it["product_id"] for it in rk["results"]]
    assert base_ids == rk_ids, (base_ids, rk_ids)
    # rerank時は eig 診断が乗る
    for it in rk["results"]:
        assert it["eig_bits"] is not None and it["p_like"] is not None
    print(f"  ✓ w=0 並び == 既定, eig_bits 付与: {rk_ids[:3]}")


def test_recommend_rerank_explore_weight_default() -> None:
    hr("/v13/recommend: rerank=true + explore_weight 省略 → θ_explore.mu 使用")
    user = make_user()
    user["theta_explore"]["mu"] = 0.7
    r = client.post("/v13/recommend", json={"user": user, "top_n": 5, "rerank": True}).json()
    assert abs(r["used_explore_weight"] - 0.7) < 1e-9, r["used_explore_weight"]
    print(f"  ✓ used_explore_weight={r['used_explore_weight']} == θ_explore.mu")


def test_recommend_rerank_top1_de_monotonic() -> None:
    hr("/v13/recommend: w 0→0.5→1 で top1 の ΔE が単調増加(exploit→explore)")
    user = make_user()
    de = []
    for w in (0.0, 0.5, 1.0):
        r = client.post("/v13/recommend", json={
            "user": user, "top_n": 5, "rerank": True, "explore_weight": w}).json()
        de.append(r["results"][0]["delta_e_to_color"])
    print(f"  top1 ΔE: w0={de[0]:.2f} w0.5={de[1]:.2f} w1={de[2]:.2f}")
    assert de[0] <= de[1] <= de[2], f"ΔE が単調増加でない: {de}"
    print("  ✓ w を上げるほど遠い色(探索的)が先頭に")


def test_popular_static_ranking() -> None:
    hr("/v13/popular: ユーザー非依存・代表性ランキング(決定的・top_n 尊重)")
    r = client.get("/v13/popular?top_n=5")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["catalog_size"] >= 1
    assert 1 <= len(d["results"]) <= 5, d["results"]
    reps = [it["representativeness"] for it in d["results"]]
    assert all(0.0 <= x <= 1.0 for x in reps), reps
    # 代表性は降順(中心に近い=高い が先頭)
    assert reps == sorted(reps, reverse=True), f"representativeness 降順でない: {reps}"
    # 決定的: 2 回呼んで同一
    ids1 = [it["product_id"] for it in d["results"]]
    ids2 = [it["product_id"] for it in client.get("/v13/popular?top_n=5").json()["results"]]
    assert ids1 == ids2, (ids1, ids2)
    # lip なし → effective_lab は None(ユーザー非依存)
    assert all(it.get("effective_lab") is None for it in d["results"]), "lip なしで effective_lab が出た"
    print(f"  ✓ 定番 TOP-1: {ids1[0]} (rep={reps[0]:.3f}), 決定的")


def test_popular_with_lip_returns_effective_lab() -> None:
    hr("/v13/popular?lip_* → 各定番に effective_lab(本人の唇に重ねる用)。ランキングは不変")
    base = client.get("/v13/popular?top_n=5").json()["results"]
    r = client.get("/v13/popular?top_n=5&lip_l=62&lip_a=22&lip_b=12&mu_thickness=0.5")
    assert r.status_code == 200, r.text
    d = r.json()["results"]
    # ランキング(順序)は lip 有無で不変(ユーザー非依存)
    assert [x["product_id"] for x in d] == [x["product_id"] for x in base], "lip でランキングが変わった"
    for it in d:
        eff = it.get("effective_lab")
        assert eff and all(k in eff for k in ("L", "a", "b")), it
    print(f"  ✓ effective_lab 付与 (例 {d[0]['product_id']}: L*{d[0]['effective_lab']['L']:.0f})、順序不変")


if __name__ == "__main__":
    # /v13/pair_compare/init
    test_pair_init_returns_10_pairs()
    # /v13/pair_compare/apply
    test_pair_apply_normal()
    test_pair_apply_unknown_pair_id()
    test_pair_apply_empty_choices_400()
    test_pair_apply_no_pc_uses_neutral()
    # /v13/update_user
    test_update_user_normal()
    test_update_user_extras_accepted()
    test_update_user_empty_obs_422()
    test_update_user_dislike_does_not_move_color()
    # /v13/recommend
    test_recommend_normal()
    test_recommend_with_line_filter()
    test_recommend_thickness_changes_eff_lab()
    test_recommend_serendipity_explore_high()
    # /v13/recommend + 能動学習(rerank)
    test_recommend_default_no_rerank()
    test_recommend_rerank_w0_equals_default()
    test_recommend_rerank_explore_weight_default()
    test_recommend_rerank_top1_de_monotonic()
    # /v13/popular
    test_popular_static_ranking()
    test_popular_with_lip_returns_effective_lab()
    print("\n" + "=" * 50)
    print("✅ /v13/* endpoints: 全 18 テスト合格")
