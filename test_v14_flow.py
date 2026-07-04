"""v14 逐次ペア比較の E2E 疎通(A3)。

start → next×N → done の一気通貫、逐次EIGが同一ペアを二度出さないこと、
effective_lab が lip_lab に依存して変わること、v13 エンドポイントの回帰なし。
"""

import sys

from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_v14_flow() -> None:
    print("Test 1: start → next×N → done(逐次・二度出しなし・theta_snapshot あり)")
    r = client.post("/v14/pair_compare/start", json={
        "lip_lab": {"L": 62, "a": 22, "b": 12},
        "scenes": ["school", "friends"],
        "pc_season": "ブルベ夏",
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["n_pairs_total"] == 8, d["n_pairs_total"]
    assert d["first_pair"]["left"]["effective_lab"], "effective_lab 欠落"
    assert d["candidate_count"] >= 1 and d["catalog_size"] >= 1, d

    session = d["session"]
    cur_pair = d["first_pair"]
    seen: set = set()
    answered = 0
    while True:
        pid = cur_pair["pair_id"]
        assert pid not in seen, f"同一ペアを二度提示: {pid}"   # 二度出さない
        seen.add(pid)
        rn = client.post("/v14/pair_compare/next", json={
            "session": session, "pair_id": pid, "chose": "left",
        })
        assert rn.status_code == 200, rn.text
        dn = rn.json()
        answered += 1
        session = dn["session"]
        assert len(dn["theta_snapshot"]["pref_mu"]) == 20, "theta_snapshot 不正"
        assert dn["candidate_count"] >= 1
        if dn["done"]:
            assert dn["next_pair"] is None, "done なのに next_pair がある"
            break
        cur_pair = dn["next_pair"]
        assert cur_pair is not None, "未完了なのに next_pair が無い"
        assert answered <= 12, "done にならない(無限ループの疑い)"
    assert answered == 8, f"answered={answered} != 8"
    print(f"  ✓ {answered} 問で done / 二度出しなし / theta_snapshot(20次元)あり")


def test_effective_lab_depends_on_lip() -> None:
    print("Test 2: effective_lab が lip_lab に依存して変わる")

    def first_left_eff(lip):
        d = client.post("/v14/pair_compare/start", json={"lip_lab": lip}).json()
        e = d["first_pair"]["left"]["effective_lab"]
        return (round(e["L"], 3), round(e["a"], 3), round(e["b"], 3))

    e1 = first_left_eff({"L": 62, "a": 22, "b": 12})
    e2 = first_left_eff({"L": 40, "a": 50, "b": 20})
    assert e1 != e2, (e1, e2)
    print(f"  ✓ lip 変化で effective_lab 変化: {e1} != {e2}")


def test_determinism_first_pair() -> None:
    print("Test 3: 同一入力 → 同一 first_pair(EIG最大の決定的タイブレーク)")
    body = {"lip_lab": {"L": 62, "a": 22, "b": 12}, "scenes": ["date"]}
    p1 = client.post("/v14/pair_compare/start", json=body).json()["first_pair"]["pair_id"]
    p2 = client.post("/v14/pair_compare/start", json=body).json()["first_pair"]["pair_id"]
    assert p1 == p2, (p1, p2)
    print(f"  ✓ first_pair 一致: {p1}")


def test_concierge_speech_endpoint() -> None:
    print("Test 5: /v14/concierge_speech(explore/recommend/decide)疎通")
    # explore: start の session をそのまま渡す(spoken_axes 相乗り)
    d = client.post("/v14/pair_compare/start", json={
        "lip_lab": {"L": 62, "a": 22, "b": 12}, "scenes": ["school", "friends"]}).json()
    r = client.post("/v14/concierge_speech", json={
        "phase": "explore", "session": d["session"], "step": "pair_compare"})
    assert r.status_code == 200, r.text
    dd = r.json()
    assert dd["session"] is not None, "explore は session を返す"
    if dd["speech"]:
        assert dd["speech"]["type"] in ("axis_realization", "step_intro"), dd["speech"]
    # decide
    rf = client.post("/v14/concierge_speech", json={"phase": "decide", "is_final": True}).json()
    assert rf["speech"]["type"] == "decision_final", rf
    rc = client.post("/v14/concierge_speech", json={"phase": "decide", "is_final": False}).json()
    assert rc["speech"]["type"] == "decision_confirm", rc
    print("  ✓ concierge_speech explore(session往復)/ decide 疎通")


def test_v13_regression() -> None:
    print("Test 4: v13 エンドポイント回帰なし")
    r = client.get("/v13/pair_compare/init")
    assert r.status_code == 200 and len(r.json()["pairs"]) >= 1
    rr = client.post("/v13/pair_compare/apply", json={
        "choices": [{"pair_id": p["pair_id"], "chose": "left"}
                    for p in r.json()["pairs"]],
        "pc_season": "ブルベ夏",
    })
    assert rr.status_code == 200, rr.text
    print("  ✓ /v13/pair_compare/init + apply 健在")


if __name__ == "__main__":
    test_v14_flow()
    test_effective_lab_depends_on_lip()
    test_determinism_first_pair()
    test_concierge_speech_endpoint()
    test_v13_regression()
    print("=" * 50)
    print("✅ v14_flow: 全 5 テスト合格")
