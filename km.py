"""K-M(Kubelka-Munk)モデルによる applied_Lab 計算と
user_product_lab_table バッチ生成(雛形)。

実装は後フェーズで行う。
"""


def compute_applied_lab(lip_lab, product_k_s, line_s, t):
    """K-M 式で applied_Lab を計算。

    Args:
        lip_lab: 唇地肌の Lab (shape (3,))
        product_k_s: 商品の K/S 比(各チャネル)
        line_s: ライン散乱係数 S (各チャネル)
        t: 厚み(0〜1)

    Returns:
        applied_lab: 重ね塗り後の Lab (shape (3,))
    """
    raise NotImplementedError("compute_applied_lab は phase: compute_km_table で実装予定")


def compute_km_table(lip_lab, products, lines, t_steps=21):
    """user_product_lab_table を生成。

    Args:
        lip_lab: 唇地肌の Lab
        products: 商品リスト(各要素は dict、Lab/k_s 等を含む)
        lines: ライン情報(各要素は dict、S を含む)
        t_steps: 厚み段階数(デフォルト 21)

    Returns:
        table: 商品 × t_steps の applied_lab テーブル
    """
    raise NotImplementedError("compute_km_table は phase: compute_km_table で実装予定")
