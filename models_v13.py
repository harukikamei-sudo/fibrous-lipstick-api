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
    pc_season: Optional[PCSeason] = Field(None, description="Kawanoさん の PC 判定結果")
    scenes: Optional[List[str]] = Field(
        None,
        description="シーン選択(school/friends/date/special)。recommend_v2 の I_dialog"
                    "(familiarity 第1項)判定に使う(A1)。未指定なら I_dialog=0 で従来挙動。",
    )
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
    pref_evidence: Optional[Dict[str, List[str]]] = Field(
        None,
        description="θ_pref 各軸(AXIS_NAMES)の事後分散を最も縮めた観測の pair_id 列(来歴・A2)。"
                    "reasons.top_axes の evidence に使う。pair_compare 適用時に構築され、"
                    "以降の update_user では保持される(ステートレス往復で持ち回る)。",
    )


# ============ 観測ログ(Kawanoさん AR → lip API) ============

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
    source_pair_id: Optional[str] = Field(
        None,
        description="この観測が由来するペア比較の pair_id(あれば)。θ_pref の来歴"
                    "(pref_evidence)構築に使う。AR 観測等では None。",
    )
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
    scenes: Optional[List[str]] = Field(
        None,
        description="シーン選択(school/friends/date/special)。θ_pref の事前を scene_priors で"
                    "構築する(A1)。未指定なら従来どおり flat 事前(完全後方互換)。",
    )


class PairApplyResponse(BaseModel):
    """事前分布構築結果。GAS は users シートに保存。"""
    theta_color: GaussianLab
    theta_pref: GaussianVec20
    theta_explore: GaussianScalar
    theta_thickness: GaussianScalar
    n_color_obs: int
    n_worldview_obs: int
    pref_evidence: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="θ_pref 軸別の来歴(軸名→縮小寄与の大きい pair_id 列)。"
                    "caller は UserState.pref_evidence に格納して持ち回る(A2)。",
    )


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
    image_url: Optional[str] = Field(
        None, description="商品スウォッチ画像 URL(Kawanoさん AR の表示用)"
    )


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
    # ---- 能動学習(EIG 再ランク)。既定は従来挙動(完全後方互換)----
    rerank: bool = Field(
        False,
        description="True で EIG(期待情報利得)再ランクを発動。False(既定)なら"
                    "従来どおり R_final 降順で並び・出力とも完全に同一。"
    )
    explore_weight: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="EIG ブレンド重み w(0=純 exploit/R_final, 1=純 explore/EIG)。"
                    "None かつ rerank=True なら user.theta_explore.mu を使用。"
                    "rerank=False のときは無視される。"
    )


class ReasonAxis(BaseModel):
    """推薦理由の「軸別寄与」(好み起点)。文章化はフロントの責務。"""
    axis: str = Field(..., description="catalog_x20.AXIS_NAMES の軸名")
    label: str = Field(..., description="日本語ラベル(catalog_x20.AXIS_LABELS_JA)")
    contribution: float = Field(..., description="μ_pref[k]·x20[k](正寄与のみ)")
    evidence: List[str] = Field(
        default_factory=list,
        description="この軸の事後分散を最も縮めた観測の pair_id(最大2件)。"
                    "※ bayesian 更新ループの計装が必要なため A2 時点では空配列(別途配線)。",
    )


class ProductTrait(BaseModel):
    """推薦理由の「商品起点の特徴」(その商品で x20 値が突出している軸)。"""
    axis: str = Field(..., description="商品側で値が突出している x20 軸名")
    label: str = Field(..., description="日本語ラベル(catalog_x20.AXIS_LABELS_JA)")


class RecommendReasons(BaseModel):
    """推薦理由の構造化データ(A2)。文章化はフロント conciergeScript.ts の責務。

    色/好みの寄与は「出所」でなく「意味」で再グルーピングした派生指標であり、
    スコア計算(R_final)には一切影響しない。正規化はパーセンタイル方式
    (候補プール内の順位率。絶対閾値なし=_flag_serendipity と同じ自己校正の哲学)。
    """
    color_percentile: float = Field(
        ..., ge=0.0, le=1.0, description="色の似合い順位率(1=プール内で最も似合う)"
    )
    pref_percentile: float = Field(
        ..., ge=0.0, le=1.0, description="好み一致の順位率(1=最も好みに一致)"
    )
    scene_match: bool = Field(
        False,
        description="シーン選択で言及した軸に商品が合致したか(A1 の I_dialog 配線で生きる。"
                    "A2 時点では false 固定)。",
    )
    top_axes: List[ReasonAxis] = Field(
        default_factory=list,
        description="好み起点の寄与上位軸(最大2、正寄与かつ確信のある軸のみ)",
    )
    product_traits: List[ProductTrait] = Field(
        default_factory=list,
        description="商品起点の特徴軸(最大2、is_系バイナリ除く・top_axes と重複除く)",
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
    image_url: Optional[str] = Field(
        None, description="商品スウォッチ画像 URL(Kawanoさん AR の表示用)"
    )
    is_serendipity: bool = Field(
        False,
        description="セレンディピティ(冒険)枠か。返却 TOP-N 内で「μ_color から遠い"
                    "(ΔE 中央値超)かつ familiarity が低い(中央値未満)」象限の商品に立つ。"
                    "フロントはこの商品への like/dislike を is_serendipity=True の観測として"
                    "送ることで θ_explore を更新できる(設計書 §7.4 / Part VI の配線)。",
    )
    # ---- EIG 再ランク時のみ非 null(rerank=False では None)----
    eig_bits: Optional[float] = Field(
        None, description="期待情報利得 [bit](rerank=True 時のみ)"
    )
    p_like: Optional[float] = Field(
        None, description="like 確率(ΔE2000 知覚シグモイド、rerank=True 時のみ)"
    )
    score: Optional[float] = Field(
        None, description="(1−w)·norm(R_final) + w·norm(EIG)(rerank=True 時のみ)"
    )
    reasons: Optional[RecommendReasons] = Field(
        None,
        description="推薦理由の構造化データ(A2)。reasons を読まない既存クライアントは"
                    "無視できる(後方互換)。",
    )


class RecommendV2Response(BaseModel):
    user_id: str
    mu_thickness: float = Field(..., description="このリクエスト時点の μ_thickness")
    beta_used: float = Field(..., description="μ_explore から計算された β")
    reranked_by_eig: bool = Field(
        False, description="EIG 再ランクが発動したか(rerank=True 時 True)"
    )
    used_explore_weight: Optional[float] = Field(
        None, description="再ランクで実際に使った w(rerank=False では None)"
    )
    candidate_count: int = Field(
        0,
        description="残候補数(A2-fix・competitive set 方式)。現時点の事後で全候補を"
                    "スコアリングし、TOP-N 最下位スコアから margin·(1位−N位)以内にいる候補の数。"
                    "事後が尖るほど減る(=絞り込みの進行)。退化時は TOP-N 件数。"
                    "表示専用の派生指標で TOP-N 選定には不使用。"
                    "※ 当初 fix の『R_final>中央値』定義は中央値分割が常に≈N/2で減らないため破棄。",
    )
    catalog_size: int = Field(
        0, description="候補プール(km_table)の総数。フロントの『◯色から』起点に使う。"
    )
    results: List[RecommendV2Item]


# ============ v14 逐次ペア比較(A3)============

class PairV14Side(BaseModel):
    """v14 ペアの片側。effective_lab(唇に塗った想定の色)を含むのが v13 との差。"""
    product_id: str
    name: str
    image_url: Optional[str] = None
    lab: LabValue                       # 商品マスストーン Lab
    x20: List[float] = Field(..., min_length=20, max_length=20)
    effective_lab: LabValue = Field(
        ..., description="lip_lab + μ_thickness の K-M 塗布後 Lab(フロントが本人の唇を再着色)"
    )


class PairV14(BaseModel):
    pair_id: str
    pair_type: Literal["color", "worldview"]
    left: PairV14Side
    right: PairV14Side


class V14Session(BaseModel):
    """ステートレス往復セッション(UserState 相当 + 進行)。サーバ側には保存しない。"""
    user: UserState
    asked_pair_ids: List[str] = Field(default_factory=list)


class ThetaSnapshot(BaseModel):
    """フロント中間実況用: θ_pref の現在値 + 直前で最も分散が縮んだ軸。"""
    pref_mu: List[float] = Field(..., min_length=20, max_length=20)
    pref_var: List[float] = Field(..., min_length=20, max_length=20)
    top_shrunk_axis: Optional[str] = Field(
        None, description="直前の選択で σ² が最も縮んだ θ_pref 軸名(無ければ None)"
    )


class V14StartRequest(BaseModel):
    lip_lab: LabValue
    scenes: Optional[List[str]] = None
    pc_season: Optional[PCSeason] = None
    warmness: Optional[float] = None
    mu_thickness: float = Field(
        0.5, ge=0.0, le=1.0, description="effective_lab 計算の塗り厚(既定 0.5)"
    )


class V14StartResponse(BaseModel):
    session: V14Session
    n_pairs_total: int
    first_pair: PairV14
    candidate_count: int
    catalog_size: int


class V14NextRequest(BaseModel):
    session: V14Session
    pair_id: str
    chose: Literal["left", "right"]


class V14NextResponse(BaseModel):
    session: V14Session
    done: bool
    next_pair: Optional[PairV14] = None
    theta_snapshot: ThetaSnapshot
    candidate_count: int
