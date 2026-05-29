"""設計書 v1.3 全フローの統合疎通テスト(TestClient ベース)。

シナリオ(Kawano 視点):
    1. GET  /v13/pair_compare/init → 10 ペア取得
    2. POST /v13/pair_compare/apply (PC=ブルベ夏 + 全 left 選択)
        → 4 つの事前分布 (θ_color/θ_pref/θ_explore/θ_thickness)
    3. UserState を組み立て(lip_lab を caller が知っている前提)
    4. POST /v13/recommend → 初回 TOP-N
    5. AR like 観測 1 件(濃いめ thickness=0.9)を /v13/update_user
    6. POST /v13/recommend → μ_thickness が動き、effective_Lab が変化することを確認
"""

import json
import sys

from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def hr(title: str) -> None:
    print(f"\n--- {title} ---")


# ============ 1. ペア提示 ============

hr("1. GET /v13/pair_compare/init")
r = client.get("/v13/pair_compare/init")
assert r.status_code == 200, r.text
pairs = r.json()["pairs"]
print(f"pairs: {len(pairs)}")
assert len(pairs) >= 8, "ペアが不足"


# ============ 2. 全 left 選択 → 事前分布 ============

hr("2. POST /v13/pair_compare/apply")
choices = [{"pair_id": p["pair_id"], "chose": "left"} for p in pairs]
r = client.post("/v13/pair_compare/apply", json={
    "choices": choices,
    "pc_season": "ブルベ夏",
    "warmness": -8.0,
})
assert r.status_code == 200, r.text
prior = r.json()
print(f"θ_color: μ=L{prior['theta_color']['mu']['L']:.2f} "
      f"a{prior['theta_color']['mu']['a']:.2f} "
      f"b{prior['theta_color']['mu']['b']:.2f} "
      f"σ²_L={prior['theta_color']['var']['L']:.4f}")
print(f"θ_pref top-3 abs μ: ", sorted(
    enumerate(prior["theta_pref"]["mu"]), key=lambda x: -abs(x[1]))[:3])
print(f"θ_thickness: μ={prior['theta_thickness']['mu']:.3f} "
      f"σ²={prior['theta_thickness']['var']:.4f}")


# ============ 3. UserState を組み立て ============

hr("3. UserState 組み立て")
user_state = {
    "user_id": "mina_test",
    "lip_lab": {"L": 62.0, "a": 22.0, "b": 12.0},
    "pc_season": "ブルベ夏",
    "theta_color": prior["theta_color"],
    "theta_pref": prior["theta_pref"],
    "theta_explore": prior["theta_explore"],
    "theta_thickness": prior["theta_thickness"],
}
print(f"user_id={user_state['user_id']}, lip_lab={user_state['lip_lab']}")


# ============ 4. 初回 /v13/recommend ============

hr("4. POST /v13/recommend (初回)")
r = client.post("/v13/recommend", json={"user": user_state, "top_n": 5})
assert r.status_code == 200, r.text
res1 = r.json()
print(f"μ_thickness={res1['mu_thickness']:.3f}, β={res1['beta_used']:.2f}")
print(f"TOP-5:")
for it in res1["results"]:
    eff = it["effective_lab"]
    print(f"  {it['product_id']:32s} eff=L{eff['L']:5.1f} a{eff['a']:5.1f} b{eff['b']:5.1f} "
          f"ΔE={it['delta_e_to_color']:5.2f} R={it['r_final']:7.2f}")
top1_initial = res1["results"][0]["product_id"]


# ============ 5. AR like 観測(濃いめ thickness=0.9)を /v13/update_user ============

hr("5. POST /v13/update_user (AR like x 10件, thickness=0.9)")
observations = []
top1_eff = res1["results"][0]["effective_lab"]
for _ in range(10):
    observations.append({
        "source": "ar_view_like",
        "product_id": top1_initial,
        "observed_lab": top1_eff,
        "thickness": 0.9,
        "y": 1.0,
    })
r = client.post("/v13/update_user", json={
    "user": user_state, "observations": observations
})
assert r.status_code == 200, r.text
upd = r.json()
print(f"n_applied: {upd['n_applied']}")
user2 = upd["user"]
print(f"μ_thickness: {user_state['theta_thickness']['mu']:.3f} "
      f"→ {user2['theta_thickness']['mu']:.3f}")
assert user2["theta_thickness"]["mu"] > user_state["theta_thickness"]["mu"], \
    "thickness が濃いめ方向に動いていない"


# ============ 6. 更新後 /v13/recommend ============

hr("6. POST /v13/recommend (観測後)")
r = client.post("/v13/recommend", json={"user": user2, "top_n": 5})
assert r.status_code == 200, r.text
res2 = r.json()
print(f"μ_thickness={res2['mu_thickness']:.3f}, β={res2['beta_used']:.2f}")
print(f"TOP-5:")
for it in res2["results"]:
    eff = it["effective_lab"]
    print(f"  {it['product_id']:32s} eff=L{eff['L']:5.1f} a{eff['a']:5.1f} b{eff['b']:5.1f} "
          f"ΔE={it['delta_e_to_color']:5.2f} R={it['r_final']:7.2f}")

# 初回と観測後で effective_Lab が変化してることを確認
eff1 = res1["results"][0]["effective_lab"]
eff2 = next(
    (r["effective_lab"] for r in res2["results"]
     if r["product_id"] == res1["results"][0]["product_id"]),
    None,
)
if eff2 is not None:
    print(f"\n同 product (TOP1 initial) の effective_Lab 変化:")
    print(f"  before: L={eff1['L']:.2f} → after: L={eff2['L']:.2f}")
    assert abs(eff1["L"] - eff2["L"]) > 0.5, \
        "μ_thickness が動いても effective_Lab が変化していない"

print("\n" + "=" * 60)
print("✅ v1.3 統合フロー: 全 6 ステップ疎通成功")
