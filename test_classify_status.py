"""Tests for extract_lab.classify_status.

These tests pin the existing pure classification behavior without importing
native image-processing extensions that classify_status does not use.
"""

import sys
import types


def _install_import_stubs() -> None:
    sklearn = types.ModuleType("sklearn")
    sklearn.__path__ = []
    cluster = types.ModuleType("sklearn.cluster")

    class KMeans:
        def __init__(self, *args, **kwargs):
            raise AssertionError("KMeans should not be used by classify_status tests")

    cluster.KMeans = KMeans  # type: ignore[attr-defined]  # 動的に注入するスタブ
    sklearn.cluster = cluster  # type: ignore[attr-defined]  # 動的に注入するスタブ
    sys.modules["sklearn"] = sklearn
    sys.modules["sklearn.cluster"] = cluster

    scipy = types.ModuleType("scipy")
    scipy.__path__ = []
    ndimage = types.ModuleType("scipy.ndimage")

    def binary_dilation(*args, **kwargs):
        raise AssertionError(
            "binary_dilation should not be used by classify_status tests"
        )

    ndimage.binary_dilation = binary_dilation  # type: ignore[attr-defined]  # 動的に注入するスタブ
    scipy.ndimage = ndimage  # type: ignore[attr-defined]  # 動的に注入するスタブ
    sys.modules["scipy"] = scipy
    sys.modules["scipy.ndimage"] = ndimage


_install_import_stubs()

from extract_lab import (  # noqa: E402
    AUTO_HIGH_ADJ_MIN,
    AUTO_HIGH_EDGE_MAX,
    AUTO_HIGH_SIZE_MIN,
    classify_status,
)


def test_threshold_constants_are_unchanged() -> None:
    print("Test 1: threshold constant names and values are unchanged")
    assert AUTO_HIGH_EDGE_MAX == 0.05
    assert AUTO_HIGH_SIZE_MIN == 0.30
    assert AUTO_HIGH_ADJ_MIN == 0.10
    print("  OK")


def test_edge_density_boundary() -> None:
    print("Test 2: edge_density must be strictly below AUTO_HIGH_EDGE_MAX")
    assert classify_status({
        "status": "auto",
        "edge_density": AUTO_HIGH_EDGE_MAX - 0.001,
        "size_ratio": 1.0,
        "adj": 1.0,
        "is_container": True,
    }) == "auto_high"
    assert classify_status({
        "status": "auto",
        "edge_density": AUTO_HIGH_EDGE_MAX,
        "size_ratio": 1.0,
        "adj": 1.0,
        "is_container": True,
    }) == "auto_low"
    assert classify_status({
        "status": "auto",
        "edge_density": AUTO_HIGH_EDGE_MAX + 0.001,
        "size_ratio": 1.0,
        "adj": 1.0,
        "is_container": True,
    }) == "auto_low"
    print("  OK")


def test_size_ratio_boundary() -> None:
    print("Test 3: size_ratio must be strictly above AUTO_HIGH_SIZE_MIN")
    assert classify_status({
        "status": "auto",
        "edge_density": 0.0,
        "size_ratio": AUTO_HIGH_SIZE_MIN + 0.001,
        "adj": 1.0,
        "is_container": True,
    }) == "auto_high"
    assert classify_status({
        "status": "auto",
        "edge_density": 0.0,
        "size_ratio": AUTO_HIGH_SIZE_MIN,
        "adj": 1.0,
        "is_container": True,
    }) == "auto_low"
    assert classify_status({
        "status": "auto",
        "edge_density": 0.0,
        "size_ratio": AUTO_HIGH_SIZE_MIN - 0.001,
        "adj": 1.0,
        "is_container": True,
    }) == "auto_low"
    print("  OK")


def test_adj_boundary_for_container() -> None:
    print("Test 4: container adj must be strictly above AUTO_HIGH_ADJ_MIN")
    assert classify_status({
        "status": "auto",
        "edge_density": 0.0,
        "size_ratio": 1.0,
        "adj": AUTO_HIGH_ADJ_MIN + 0.001,
        "is_container": True,
    }) == "auto_high"
    assert classify_status({
        "status": "auto",
        "edge_density": 0.0,
        "size_ratio": 1.0,
        "adj": AUTO_HIGH_ADJ_MIN,
        "is_container": True,
    }) == "auto_low"
    assert classify_status({
        "status": "auto",
        "edge_density": 0.0,
        "size_ratio": 1.0,
        "adj": AUTO_HIGH_ADJ_MIN - 0.001,
        "is_container": True,
    }) == "auto_low"
    print("  OK")


def test_is_container_states() -> None:
    print("Test 5: is_container True/False/None/missing states")
    assert classify_status({
        "status": "auto",
        "edge_density": 0.0,
        "size_ratio": 1.0,
        "adj": 0.0,
        "is_container": True,
    }) == "auto_low"
    assert classify_status({
        "status": "auto",
        "edge_density": 0.0,
        "size_ratio": 1.0,
        "adj": 0.0,
        "is_container": False,
    }) == "auto_high"
    assert classify_status({
        "status": "auto",
        "edge_density": 0.0,
        "size_ratio": 1.0,
        "adj": 0.0,
        "is_container": None,
    }) == "auto_high"
    assert classify_status({
        "status": "auto",
        "edge_density": 0.0,
        "size_ratio": 1.0,
        "adj": 0.0,
    }) == "auto_high"
    print("  OK")


def test_none_metrics_are_auto_low() -> None:
    print("Test 6: each None metric returns auto_low")
    assert classify_status({
        "status": "auto",
        "edge_density": None,
        "size_ratio": 1.0,
        "adj": 1.0,
        "is_container": True,
    }) == "auto_low"
    assert classify_status({
        "status": "auto",
        "edge_density": 0.0,
        "size_ratio": None,
        "adj": 1.0,
        "is_container": True,
    }) == "auto_low"
    assert classify_status({
        "status": "auto",
        "edge_density": 0.0,
        "size_ratio": 1.0,
        "adj": None,
        "is_container": False,
    }) == "auto_low"
    print("  OK")


def test_non_auto_status_is_returned_as_is() -> None:
    print("Test 7: non-auto status is returned as-is")
    assert classify_status({
        "status": "excluded",
        "edge_density": 0.0,
        "size_ratio": 1.0,
        "adj": 1.0,
        "is_container": True,
    }) == "excluded"
    assert classify_status({
        "status": "manual_review",
        "edge_density": None,
        "size_ratio": None,
        "adj": None,
        "is_container": None,
    }) == "manual_review"
    print("  OK")


if __name__ == "__main__":
    test_threshold_constants_are_unchanged()
    test_edge_density_boundary()
    test_size_ratio_boundary()
    test_adj_boundary_for_container()
    test_is_container_states()
    test_none_metrics_are_auto_low()
    test_non_auto_status_is_returned_as_is()
    print("=" * 50)
    print("classify_status: all 7 tests passed")
