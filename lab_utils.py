"""色空間変換ユーティリティ。

extract_lab.py(画像処理)と将来の km.py(K-M計算)で共有する色変換のみを集約。
画像取得・クラスタリング・ファイル I/O はここに置かない。

依存:
  pip install numpy scikit-image
"""

import numpy as np
from skimage import color as skcolor


__all__ = [
    "rgb_to_lab",
    "lab_to_rgb",
    "lab_to_reflectance",
    "reflectance_to_lab",
    "compute_saturation",
    "compute_hue_deg",
    "is_red_hue",
]


# ============ RGB ↔ Lab ============

def rgb_to_lab(rgb):
    """RGB(0-255, shape (3,) または スカラ tuple) → Lab(np.array shape (3,))。"""
    arr = np.asarray(rgb, dtype=float).reshape(1, 1, 3) / 255.0
    lab = skcolor.rgb2lab(arr)
    return lab[0, 0]


def lab_to_rgb(lab):
    """Lab(shape (3,)) → RGB(0-255, np.array shape (3,)) sRGB ガンマ補正済み。

    範囲外色は [0, 255] にクランプ。
    """
    lab_arr = np.asarray(lab, dtype=float).reshape(1, 1, 3)
    srgb = skcolor.lab2rgb(lab_arr)  # 0-1, sRGB(gamma)
    srgb = np.clip(srgb, 0.0, 1.0).reshape(3)
    return srgb * 255.0


# ============ Lab ↔ 反射率(linear sRGB 近似, D65) ============
#
# K-M 計算では各波長(チャネル)の反射率が必要。MVP では linear sRGB の各
# チャネル値(0〜1)を「R, G, B 帯域の反射率近似」として扱う。
# sRGB ガンマ補正 ↔ linear の変換は数学的に可逆なので、Lab→反射率→Lab の
# 往復誤差は浮動小数精度の範囲。

def _srgb_to_linear(c):
    """sRGB(ガンマ補正、0-1) → linear sRGB(0-1)。要素毎に処理。"""
    c = np.asarray(c, dtype=float)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(c):
    """linear sRGB(0-1) → sRGB(ガンマ補正、0-1)。"""
    c = np.asarray(c, dtype=float)
    return np.where(c <= 0.0031308, 12.92 * c, 1.055 * (c ** (1.0 / 2.4)) - 0.055)


def lab_to_reflectance(lab):
    """Lab → 反射率 R(R, G, B 各チャネル 0〜1 の linear sRGB 近似、D65)。"""
    rgb_255 = lab_to_rgb(lab)
    srgb = np.clip(rgb_255 / 255.0, 0.0, 1.0)
    return _srgb_to_linear(srgb)


def reflectance_to_lab(reflectance):
    """反射率 R(linear sRGB, 0〜1, shape (3,)) → Lab(shape (3,))。"""
    refl = np.clip(np.asarray(reflectance, dtype=float), 0.0, 1.0)
    srgb = _linear_to_srgb(refl)
    return rgb_to_lab(srgb * 255.0)


# ============ HSV 系(K-means クラスタ選定で使用) ============

def compute_saturation(rgb):
    """RGB(0-255, shape (3,)) → HSV の彩度 S (0〜1)。"""
    r, g, b = np.asarray(rgb, dtype=float) / 255.0
    mx = max(r, g, b)
    mn = min(r, g, b)
    return (mx - mn) / mx if mx > 0 else 0.0


def compute_hue_deg(rgb):
    """RGB(0-255, shape (3,)) → 色相 H (0〜360°)。"""
    r, g, b = np.asarray(rgb, dtype=float) / 255.0
    mx = max(r, g, b)
    mn = min(r, g, b)
    diff = mx - mn
    if diff == 0:
        return 0.0
    if mx == r:
        h = (60.0 * ((g - b) / diff) + 360.0) % 360.0
    elif mx == g:
        h = 60.0 * ((b - r) / diff) + 120.0
    else:
        h = 60.0 * ((r - g) / diff) + 240.0
    return h


def is_red_hue(hue_deg):
    """色相が赤系(0-60° or 300-360°)か。"""
    return hue_deg <= 60 or hue_deg >= 300
