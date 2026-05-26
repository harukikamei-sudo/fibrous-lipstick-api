"""ライン散乱係数 S の逆推定(雛形)。

K-M(Kubelka-Munk)モデルで、ライン共通の散乱係数 S を、
完全発色 Lab(full_lab)と薄付き Lab(light_lab)から逆算する。

実装は後フェーズで行う。
"""


def estimate_s(full_lab, light_lab, t_light=0.3):
    """ライン S を逆推定する。

    Args:
        full_lab: フル発色の Lab (shape (3,))
        light_lab: t=t_light で観測した Lab (shape (3,))
        t_light: 薄付きの厚み t (デフォルト 0.3)

    Returns:
        S: 散乱係数(各チャネル独立、shape (3,))
    """
    raise NotImplementedError("estimate_s は phase: estimate_s で実装予定")
