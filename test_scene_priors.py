"""scene_priors.py(シーン事前分布)のテスト(A1)。

build_pref_prior の純ロジック(flat / 縮小 / 符号衝突 / 希釈)と
scene_mentioned_axes を検証する。app / skimage 不要=ローカルでも軽く回る。
apply エンドポイント経由の統合は test_v13_endpoints.py 側(TestClient の流儀)。
"""

from catalog_x20 import AXIS_NAMES
from constants import TAU2_PREF
from scene_priors import (
    KAPPA,
    SCENE_LABELS,
    SCENE_MU_PREF,
    build_pref_prior,
    scene_mentioned_axes,
)


def _idx(name: str) -> int:
    return AXIS_NAMES.index(name)


def test_flat_when_empty_or_unknown() -> None:
    print("Test 1: scenes 空 / 未知キーのみ → 完全 flat(後方互換)")
    for scenes in ([], ["bogus"], ["xxx", "yyy"]):
        mu, var = build_pref_prior(scenes)
        assert mu == [0.0] * 20, (scenes, mu)
        assert all(abs(v - TAU2_PREF) < 1e-12 for v in var), (scenes, var)
    print("  ✓ mu=0, var=TAU2_PREF(flat)")


def test_single_scene_shrinks_mentioned_only() -> None:
    print("Test 2: 単一シーンは言及軸のみ var=KAPPA·TAU2、非言及は flat")
    scene = "date"
    mu, var = build_pref_prior([scene])
    mentioned = set(SCENE_MU_PREF[scene].keys())
    for axis in AXIS_NAMES:
        i = _idx(axis)
        if axis in mentioned:
            assert abs(var[i] - KAPPA * TAU2_PREF) < 1e-9, (axis, var[i])
            assert mu[i] != 0.0, axis            # 言及軸は μ がテーブル値
        else:
            assert abs(var[i] - TAU2_PREF) < 1e-9, (axis, var[i])
            assert mu[i] == 0.0, axis
    print(f"  ✓ {scene}: 言及{len(mentioned)}軸が KAPPA·TAU2 に縮小、他 flat")


def test_sign_conflict_returns_flat() -> None:
    print("Test 3: school+special の符号衝突軸は flat に戻る")
    mu, var = build_pref_prior(["school", "special"])
    # makeup_intensity: school<0 × special>0 → 衝突 → flat(設計どおり)
    for axis in ("saturation", "makeup_intensity"):
        i = _idx(axis)
        assert abs(var[i] - TAU2_PREF) < 1e-9, (axis, var[i], "衝突軸は flat のはず")
    # 片方しか言及しない軸で符号一致なら縮む(例: special のみの longlasting)
    i_ll = _idx("longlasting")
    assert var[i_ll] < TAU2_PREF, var[i_ll]
    print("  ✓ saturation/makeup_intensity は flat、longlasting は縮小")


def test_scene_mentioned_axes() -> None:
    print("Test 4: scene_mentioned_axes は言及軸の和集合")
    axes = scene_mentioned_axes(["school", "date"])
    assert axes == set(SCENE_MU_PREF["school"]) | set(SCENE_MU_PREF["date"]), axes
    assert scene_mentioned_axes([]) == set()
    assert scene_mentioned_axes(["bogus"]) == set()
    # 全軸が AXIS_NAMES に存在
    assert all(a in AXIS_NAMES for a in axes), axes
    print(f"  ✓ {len(axes)} 軸の和集合 / 空・未知は空集合 / 全軸 AXIS_NAMES 整合")


def test_scene_labels_cover_all() -> None:
    print("Test 5: SCENE_LABELS は4シーンを網羅")
    assert set(SCENE_LABELS) == set(SCENE_MU_PREF), (SCENE_LABELS, SCENE_MU_PREF)
    assert set(SCENE_MU_PREF) == {"school", "friends", "date", "special"}
    print(f"  ✓ {SCENE_LABELS}")


if __name__ == "__main__":
    test_flat_when_empty_or_unknown()
    test_single_scene_shrinks_mentioned_only()
    test_sign_conflict_returns_flat()
    test_scene_mentioned_axes()
    test_scene_labels_cover_all()
    print("=" * 50)
    print("✅ scene_priors.py: 全 5 テスト合格")
