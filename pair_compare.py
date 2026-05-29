"""Part II 強制ペア比較 — 仮データ実装(後でユーザー定義に差し替え可)。

設計書 §6: 10 ペア(色5 + 世界観5)を固定で提示し、選択結果から
θ_color と θ_pref の事前分布を構築する。

- /pair_compare/init: PAIR_BANK 全体を返す
- /pair_compare/apply: choices を観測として事前分布を計算

PAIR_BANK の中身はユーザーが後で確定するため、ここでは「カタログから
明確に対立する2商品」を機械的に抜く暫定版にしている。差し替えるなら
`_build_pair_bank()` を書き換えるだけで済む。
"""

from __future__ import annotations

import csv
import math
import os
from typing import Dict, List, Optional

from bayesian import apply_observations
from catalog_x20 import X20_COL_NAMES, load_x20_from_row
from models_v13 import (
    GaussianLab,
    GaussianScalar,
    GaussianVec20,
    LabValue,
    Observation,
    PairApplyRequest,
    PairApplyResponse,
    PairChoice,
    PairInitResponse,
    PairItem,
    PairQuestion,
    UserState,
)

CATALOG_PATH = os.path.join(os.path.dirname(__file__), "products_with_lab.csv")


# ============ §3 PC 別 μ_color_0(設計書 §3.2 表) ============

PC_MU_COLOR_0: Dict[str, LabValue] = {
    "イエベ春": LabValue(L=55, a=45, b=30),
    "イエベ秋": LabValue(L=40, a=40, b=25),
    "ブルベ夏": LabValue(L=55, a=35, b=5),
    "ブルベ冬": LabValue(L=40, a=50, b=15),
}

# §3.3 σ²_color_0 シグモイド係数
SIGMA2_BASE = 100.0
GAMMA = 2.0
DELTA = 5.0
S = 2.0
# §11 事前
TAU2_PREF = 1.0
MU_EXPLORE_0 = 0.5
TAU2_EXPLORE = 0.25
MU_THICKNESS_0 = 0.5
SIGMA2_THICKNESS_0 = 0.1


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _sigma2_color_0(warmness: Optional[float], threshold: float = 0.0) -> float:
    """設計書 §3.3:
        σ²_color_0 = σ²_base × ( 1 + γ × sigmoid( -(|w - thr| - δ) / s ) )
    境界付近(|w - thr| ≈ δ)で大きく、明確に離れたら σ²_base に戻る。
    warmness 未指定(=None)時は σ²_base のまま。
    """
    if warmness is None:
        return SIGMA2_BASE
    diff = abs(warmness - threshold)
    return SIGMA2_BASE * (1.0 + GAMMA * _sigmoid(-(diff - DELTA) / S))


# ============ カタログ → PairItem ============

def _load_catalog_rows() -> List[Dict[str, str]]:
    with open(CATALOG_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _row_to_pair_item(row: Dict[str, str]) -> PairItem:
    return PairItem(
        product_id=row["id"],
        name=row.get("color_name", ""),
        image_url=row.get("image_url") or None,
        lab=LabValue(L=float(row["L"]), a=float(row["a"]), b=float(row["b"])),
        x20=load_x20_from_row(row),
    )


# ============ 仮ペア定義(差し替え可) ============

# 各ペアは「対立する2商品の id」を CSV から指定。
# ユーザーが後で「ペア比較10問の中身を設計する」場合は、ここを書き換える。

_PAIR_SPECS = [
    # ---- 色ペア5(pair_color: θ_color + θ_pref 更新) ----
    ("color_01_bright_vs_deep",  "color",
     "rmd_glasting_water_05", "rmd_blur_fudge_03",
     "明るい vs 深い"),
    ("color_02_warm_vs_cool",    "color",
     "rmd_juicy_lasting_06",  "rmd_zero_velvet_06",
     "暖色寄り vs 寒色寄り"),
    ("color_03_vivid_vs_nude",   "color",
     "rmd_zero_velvet_03",    "rmd_dewyful_14",
     "鮮やか vs ヌード"),
    ("color_04_pink_vs_coral",   "color",
     "rmd_dewyful_16",        "rmd_the_juicy_lasting_01",
     "ピンク vs コーラル"),
    ("color_05_rose_vs_red",     "color",
     "rmd_zero_velvet_02",    "rmd_blur_fudge_01",
     "ローズ vs レッド"),
    # ---- 世界観ペア5(pair_worldview: θ_pref のみ更新) ----
    ("wv_06_girly_vs_mature",    "worldview",
     "rmd_the_juicy_lasting_01", "rmd_zero_velvet_06",
     "ガーリー vs マチュア"),
    ("wv_07_korean_vs_konare",   "worldview",
     "rmd_juicy_lasting_06",  "rmd_blur_fudge_05",
     "韓国っぽい vs こなれ"),
    ("wv_08_juicy_vs_matte",     "worldview",
     "rmd_glasting_water_05", "rmd_blur_fudge_03",
     "ジューシー vs マット"),
    ("wv_09_sweet_vs_classy",    "worldview",
     "rmd_the_juicy_lasting_01", "rmd_zero_velvet_03",
     "甘い vs クラシー"),
    ("wv_10_daily_vs_statement", "worldview",
     "rmd_dewyful_14",        "rmd_blur_fudge_01",
     "デイリー vs ステートメント"),
]


def _build_pair_bank() -> List[PairQuestion]:
    rows = {r["id"]: r for r in _load_catalog_rows()}
    pairs: List[PairQuestion] = []
    for pair_id, ptype, left_id, right_id, _label in _PAIR_SPECS:
        left = rows.get(left_id)
        right = rows.get(right_id)
        if left is None or right is None:
            # カタログから消えていたら fallback: ランダムには取らず、ペアを飛ばす
            continue
        pairs.append(PairQuestion(
            pair_id=pair_id,
            pair_type=ptype,  # type: ignore[arg-type]
            left=_row_to_pair_item(left),
            right=_row_to_pair_item(right),
        ))
    return pairs


# モジュール起動時に1回ロード。Kawano が叩く都度ファイル読み込みを避ける。
PAIR_BANK: List[PairQuestion] = _build_pair_bank()


# ============ API: /pair_compare/init ============

def get_pair_bank() -> PairInitResponse:
    return PairInitResponse(pairs=PAIR_BANK)


# ============ API: /pair_compare/apply ============

def apply_pair_choices(req: PairApplyRequest) -> PairApplyResponse:
    """選択結果を観測列に変換 → bayesian.apply_observations で事前分布構築。"""
    pair_by_id = {p.pair_id: p for p in PAIR_BANK}

    # 1. θ_color の事前(PC ベース or flat)
    if req.pc_season and req.pc_season in PC_MU_COLOR_0:
        mu_c0 = PC_MU_COLOR_0[req.pc_season]
    else:
        mu_c0 = LabValue(L=50, a=30, b=15)  # neutral
    var_c0 = _sigma2_color_0(req.warmness)
    theta_color_prior = GaussianLab(
        mu=mu_c0,
        var=LabValue(L=var_c0, a=var_c0, b=var_c0),
    )

    # 2. θ_pref の事前(flat)
    theta_pref_prior = GaussianVec20(
        mu=[0.0] * 20,
        var=[TAU2_PREF] * 20,
    )

    # 3. θ_explore / θ_thickness の事前(固定)
    theta_explore_prior = GaussianScalar(mu=MU_EXPLORE_0, var=TAU2_EXPLORE)
    theta_thickness_prior = GaussianScalar(mu=MU_THICKNESS_0, var=SIGMA2_THICKNESS_0)

    # 仮 user state
    user_seed = UserState(
        user_id="__pair_init__",
        lip_lab=LabValue(L=62, a=22, b=12),  # 仮(後で /update_user で正値に差し替え)
        pc_season=req.pc_season,
        theta_color=theta_color_prior,
        theta_pref=theta_pref_prior,
        theta_explore=theta_explore_prior,
        theta_thickness=theta_thickness_prior,
    )

    # 4. 選択結果 → 観測列
    observations: List[Observation] = []
    n_color = 0
    n_wv = 0
    for choice in req.choices:
        q = pair_by_id.get(choice.pair_id)
        if q is None:
            continue
        chosen = q.left if choice.chose == "left" else q.right
        rejected = q.right if choice.chose == "left" else q.left

        if q.pair_type == "color":
            # 色ペア: 選ばれた側を θ_color に正観測(y=+1)、x20 にも反映
            observations.append(Observation(
                source="pair_color",
                product_id=chosen.product_id,
                observed_lab=chosen.lab,
                observed_x20=chosen.x20,
                y=+1.0,
            ))
            # 選ばれなかった側も負観測として x_20 にだけ反映(色は σ² 大なので影響薄め)
            observations.append(Observation(
                source="pair_color",
                product_id=rejected.product_id,
                observed_x20=rejected.x20,
                y=-1.0,
            ))
            n_color += 1
        else:
            # 世界観ペア: x20 だけで θ_pref を更新(θ_color は不変)
            observations.append(Observation(
                source="pair_worldview",
                product_id=chosen.product_id,
                observed_x20=chosen.x20,
                y=+1.0,
            ))
            observations.append(Observation(
                source="pair_worldview",
                product_id=rejected.product_id,
                observed_x20=rejected.x20,
                y=-1.0,
            ))
            n_wv += 1

    # 5. ベイズ更新適用
    user_post, _ = apply_observations(user_seed, observations)

    return PairApplyResponse(
        theta_color=user_post.theta_color,
        theta_pref=user_post.theta_pref,
        theta_explore=user_post.theta_explore,
        theta_thickness=user_post.theta_thickness,
        n_color_obs=n_color,
        n_worldview_obs=n_wv,
    )
