"""設計書 v1.3 用の型定義。

GAS+Spreadsheet が state を保持し、本 API はステートレス計算サーバーとして
動作する想定。すべての user 状態はリクエスト毎に GAS から渡してもらい、
更新後の状態を返す。永続化は本 API では行わない。
"""

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ============ 基礎型 ============

class LabValue(BaseModel):
    L: float
    a: float
    b: float


PCSeason = Literal["イエベ春", "ブルベ夏", "イエベ秋", "ブルベ冬"]


# ============ User 状態(GAS が users シートに保持) ============

class GaussianScalar(BaseModel):
    """1次元ガウス: N(μ, σ²)"""
    mu: float
    var: float = Field(..., gt=0, description="分散 σ²")


class GaussianLab(BaseModel):
    """Lab 3次元独立ガウス: 各成分 N(μ_j, σ²_j)"""
    mu: LabValue
    var: LabValue = Field(..., description="各成分の分散 σ²(>0)")


class GaussianVec20(BaseModel):
    """20次元独立ガウス(pref ベクトル用)"""
    mu: List[float] = Field(..., min_length=20, max_length=20)
    var: List[float] = Field(..., min_length=20, max_length=20)


class UserState(BaseModel):
    """ユーザー1人の全パラメータ。設計書 §2.1 / §7。

    GAS から `/update_user` / `/recommend/v2` に丸ごと渡してもらう。
    """
    user_id: str
    lip_lab: LabValue = Field(..., description="ノーリップ唇 Lab(初回診断で固定)")
    pc_season: Optional[PCSeason] = Field(None, description="Kawano の PC 判定結果")
    theta_color: GaussianLab
    theta_pref: GaussianVec20
    theta_explore: GaussianScalar = Field(
        ...,
        description="セレンディピティ反応性。設計書既定 μ=0.5, σ²=0.25"
    )
    theta_thickness: GaussianScalar = Field(
        ...,
        description="塗り方好み(0=薄め, 1=濃いめ)。設計書既定 μ=0.5, σ²=0.1"
    )


# ============ 観測ログ(Kawano AR → ハルキ) ============

ObservationSource = Literal[
    "pc_diagnosis",      # Part I    PC 診断由来
    "pair_color",        # Part II   色ペア比較
    "pair_worldview",    # Part II   世界観ペア比較
    "dialog",            # Part III  対話確認
    "behavior",          # 行動データ(クリック等)
    "ar_view_like",      # Part V    AR で「いいね」
    "ar_view_dislike",   # Part V    AR で「微妙」
]


class Observation(BaseModel):
    """設計書 §9.3 + §7.1 の観測経路を統一表現。

    - 色観測(Lab): pair_color / behavior / ar_view_like で使用
    - x_20 観測: pair_worldview / dialog で使用
    - thickness 観測: ar_view_like のみで使用
    - explore 観測: serendipity 経由の ar_view_like/dislike で使用
    """
    source: ObservationSource
    product_id: Optional[str] = None
    observed_lab: Optional[LabValue] = Field(
        None,
        description="θ_color 更新用。AR の場合は applied_Lab(K-M 結果)、"
                    "ペア/行動の場合は商品のマスストーン Lab"
    )
    observed_x20: Optional[List[float]] = Field(
        None, min_length=20, max_length=20,
        description="θ_pref 更新用。商品の c.x_20 ベクトル(ペア)もしくは対話入力ベクトル"
    )
    thickness: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="θ_thickness 更新用。AR スライダー値(0〜1)"
    )
    is_serendipity: bool = Field(
        False, description="セレンディピティ提示への反応か(θ_explore 更新トリガ)"
    )
    y: float = Field(
        1.0,
        description="観測の符号。like=+1, dislike=-1, ペアの選ばれた側=+1(基本+1で運用)"
    )
    viewed_seconds: Optional[float] = None
    timestamp: Optional[str] = None


# ============ ペア比較(Part II) ============

class PairItem(BaseModel):
    """ペア比較で提示する1選択肢。"""
    product_id: str
    name: str
    image_url: Optional[str] = None
    lab: LabValue
    x20: List[float] = Field(..., min_length=20, max_length=20)


class PairQuestion(BaseModel):
    """1ペア=2選択肢 + メタ情報。"""
    pair_id: str
    pair_type: Literal["color", "worldview"]
    left: PairItem
    right: PairItem


class PairChoice(BaseModel):
    """ユーザーが1ペアで選んだ側。"""
    pair_id: str
    chose: Literal["left", "right"]


# ============ /pair_compare ============

class PairInitResponse(BaseModel):
    pairs: List[PairQuestion]


class PairApplyRequest(BaseModel):
    """10問の選択結果を事前分布に変換する。

    state は持たないので、ペア定義(=サーバー側 PAIR_BANK)+ 選択を受け取って
    μ_0/σ²_0 を返す。GAS は返り値を users シートに書き込む。
    """
    choices: List[PairChoice] = Field(..., min_length=1, max_length=20)
    pc_season: Optional[PCSeason] = Field(
        None,
        description="Part I の PC 結果(あれば)。色事前は PC 由来の μ_color_0 と"
                    "ペア由来の観測を合成した posterior になる"
    )
    warmness: Optional[float] = Field(
        None, description="Part I の warmness 値(σ²_color_0 のシグモイドに使う)"
    )


class PairApplyResponse(BaseModel):
    """事前分布構築結果。GAS は users シートに保存。"""
    theta_color: GaussianLab
    theta_pref: GaussianVec20
    theta_explore: GaussianScalar
    theta_thickness: GaussianScalar
    n_color_obs: int
    n_worldview_obs: int


# ============ /update_user ============

class UpdateUserRequest(BaseModel):
    """既存 user 状態 + 新観測リスト → 更新後 user 状態。"""
    user: UserState
    observations: List[Observation] = Field(..., min_length=1, max_length=100)


class UpdateUserResponse(BaseModel):
    user: UserState
    n_applied: Dict[str, int] = Field(
        ..., description="各 θ で何件の観測が適用されたか(診断用)"
    )


# ============ /recommend/v2 ============

class KMTableRow(BaseModel):
    """ある (user, product) ペアの 21 段階 applied_Lab。

    GAS 側で /compute_km_table の結果を保存しておき、/recommend/v2 で
    丸ごと送る。サーバー側にユーザー毎テーブルを置かない設計。
    """
    product_id: str
    applied: List[LabValue] = Field(
        ..., min_length=21, max_length=21,
        description="t=0.00, 0.05, ..., 1.00 の21段(設計書 §5.3)"
    )
    x20: List[float] = Field(..., min_length=20, max_length=20)
    pc_tags: List[str] = Field(default_factory=list, description="答え合わせ用")
    name: str = ""
    line_category: str = ""


class RecommendV2Request(BaseModel):
    """主軸: user state だけ送れば内部でカタログから K-M テーブルを作って推奨を返す。

    advanced: caller がすでに K-M テーブルを保持していて再計算を避けたい場合は
    `km_table` を直接渡せる(その場合 user.lip_lab は表示用としてのみ使う)。
    """
    user: UserState
    km_table: Optional[List["KMTableRow"]] = Field(
        None,
        description="任意。caller が事前計算済みテーブルを持っているなら渡せる。"
                    "未指定なら API 内部で user.lip_lab + 全カタログから生成。"
    )
    line_category: Optional[Literal["tint", "gloss", "matte", "velvet", "other"]] = Field(
        None, description="仕上げで絞り込み(任意)"
    )
    top_n: int = Field(5, ge=1, le=50)
    alpha: float = Field(3.0, description="色差感度(設計書既定 3.0)")
    beta_max: float = Field(5.0, description="セレンディピティ最大係数(既定 5.0)")
    familiarity_weights: List[float] = Field(
        default_factory=lambda: [4.0, 3.0, 2.0],
        min_length=3, max_length=3,
        description="[w1 対話明言, w2 cosine, w3 ΔE_inv](既定 4,3,2)"
    )


class RecommendV2Item(BaseModel):
    product_id: str
    name: str
    line_category: str
    effective_lab: LabValue = Field(..., description="μ_thickness で補間した塗布後 Lab")
    delta_e_to_color: float = Field(..., description="ΔE2000(effective_Lab, μ_color)")
    pref_match: float = Field(..., description="μ_pref · c.x_20")
    f_score: float = Field(..., description="-α·ΔE + μ_pref·c.x_20(Part IV)")
    familiarity: float = Field(..., description="familiarity(c, user)(Part VI)")
    r_final: float = Field(..., description="f - β(μ_explore)·familiarity(Part VI)")
    catalog_pc_tags: List[str] = Field(default_factory=list)


class RecommendV2Response(BaseModel):
    user_id: str
    mu_thickness: float = Field(..., description="このリクエスト時点の μ_thickness")
    beta_used: float = Field(..., description="μ_explore から計算された β")
    results: List[RecommendV2Item]
