"""コンシェルジュ発話生成(F3 を API 化)。

フロント `color-capture/src/lib/conciergeScript.ts` のロジックを **忠実移植**したもの。
RN 版と Next 版で二重実装しないため、発話生成をバックエンドに一本化する
(6/29 MTG 方針転換)。既存の reasons(A2)/ theta_snapshot(A3・session 内)を
**日本語文面に変換するだけ**で、新しい推薦データやスコアは作らない。

【トーン】妖精キャラ(6/14 MTG)。文面は Kawano の3パターン待ち=ここは仮テキスト。
  差し替え点は TODO(Kawano) コメントで明示。LLM は使わない(デモ安定性・出力統制)。
【状態管理】中間実況の重複/予算は V14Session.spoken_axes に相乗り(caller が session を往復)。
  spoken_axes が要るのは explore のみ(=session を往復しているフェーズ)。
【RHO 同期】CONCIERGE_RHO は recommend_v2.RHO_CONFIDENT(=0.5)と同値。skimage 依存を避け
  ここでは定数として持つ(conciergeScript.ts と同じ方針)。変更時は両方直す。
"""

from __future__ import annotations

from typing import List, Optional

from catalog_x20 import AXIS_LABELS_JA, AXIS_NAMES
from constants import TAU2_PREF
from models_v13 import (
    ConciergeSpeech,
    ConciergeSpeechRequest,
    ConciergeSpeechResponse,
    RecommendReasons,
)

CONCIERGE_RHO = 0.5            # = recommend_v2.RHO_CONFIDENT。変更時は API と conciergeScript.ts の両方直す
PAIR_REALIZATION_BUDGET = 3    # ペア比較中の中間実況の発話予算(確定仕様)

# ── 探索フェーズ: ステップ固定説明(TODO(Kawano): 妖精トーンの正式文面に差し替え。以下は仮)──
STEP_INTRO = {
    "intro": "ようこそ。あなたにぴったりの一本、一緒に探そうね",
    "scene_select": "まず、どんなときに使いたいか教えて?シーンで似合う色が変わるんだ",
    "capture_wrist": "内側の血管の色から、似合う色のヒントがわかるんだよ",
    "capture_lip": "次は唇の色を見せて。塗ったときの“仕上がり”を計算するの",
    "pc_confirm": "あなたのパーソナルカラー、これで合ってるかな?",
    "pair_compare": "2つの色、どっちが好き?選ぶだけで好みを学んでいくよ",
    "recommend": "おまたせ。あなたのための色を選んできたよ",
}

# シーン×スタイルの組み合わせ起点パターン(TODO(Kawano): 3パターン文面を流し込む)。現状空。
COMBINATION_PATTERNS: dict = {
    # 例(仮): "friends+school": "デイリーで盛れる、こなれ感のある色を選んだよ",
}


def _step_intro(step: Optional[str]) -> Optional[ConciergeSpeech]:
    if not step:
        return None
    text = STEP_INTRO.get(step)
    return ConciergeSpeech(type="step_intro", text=text) if text else None


def _axis_realization(axis_label: str) -> ConciergeSpeech:
    # TODO(Kawano): 文面差し替え。{axis} は好み軸の日本語ラベル(AXIS_LABELS_JA)。
    return ConciergeSpeech(type="axis_realization", text=f"なるほど、{axis_label}が好きみたいだね")


def _user_origin_text(axis) -> str:
    # TODO(Kawano): 文面差し替え。evidence は「{n}問目で〜を選んだ」等の来歴文字列。
    ev = axis.evidence[0] if getattr(axis, "evidence", None) else None
    if ev:
        return f"さっき{ev}。だからこれ"
    return f"あなたは{axis.label}が好きだよね。だからこれ"


def _product_origin_text(trait_label: str) -> str:
    # TODO(Kawano): 文面差し替え。
    return f"この色は{trait_label}が出るタイプだよ"


def _reason_speech(reasons: Optional[RecommendReasons]) -> Optional[ConciergeSpeech]:
    if reasons is None:
        return None
    top_axis = reasons.top_axes[0] if reasons.top_axes else None
    trait = reasons.product_traits[0] if reasons.product_traits else None
    # 両方あれば接続(理想形): ユーザー起点 × 商品起点
    if top_axis and trait:
        # productOriginText の「この色は」接頭を落として接続(TS の .replace(/^この色は/,"") と同じ)
        product_tail = _product_origin_text(trait.label).removeprefix("この色は")
        return ConciergeSpeech(
            type="reason_hybrid", text=f"{_user_origin_text(top_axis)}。しかも{product_tail}"
        )
    if top_axis:
        return ConciergeSpeech(type="reason_user", text=_user_origin_text(top_axis))
    if trait:
        return ConciergeSpeech(type="reason_product", text=_product_origin_text(trait.label))
    return None


def _serendipity() -> ConciergeSpeech:
    # TODO(Kawano): 文面差し替え。
    return ConciergeSpeech(type="serendipity_offer", text="これはちょっと冒険枠。いつもと違う自分、試してみる?")


def _decision_confirm() -> ConciergeSpeech:
    # TODO(Kawano): 文面差し替え。
    return ConciergeSpeech(type="decision_confirm", text="いいね、その2〜3本ならどれも似合うよ。じっくり見比べてね")


def _decision_final() -> ConciergeSpeech:
    # TODO(要決定: トーン確認中 / Kawano): 仮の終端台詞。
    return ConciergeSpeech(type="decision_final", text="どっちも似合う圏内だよ。あとは今日の気分で選んで大丈夫")


def _combination_key(scenes: List[str]) -> str:
    return "+".join(sorted(scenes)) if scenes else "none"


def _combination_speech(scenes: List[str]) -> Optional[ConciergeSpeech]:
    text = COMBINATION_PATTERNS.get(_combination_key(scenes))
    return ConciergeSpeech(type="reason_user", text=text) if text else None


def _newly_confident_axis(mu: List[float], var: List[float], spoken: List[str]) -> Optional[str]:
    """新たに確信した好み軸を1つ選ぶ(explore の中間実況)。

    条件: var ≤ RHO·TAU2(確信) かつ μ_pref>0(好意方向のみ・#3 承認) かつ spoken 未実況、
    予算(len(spoken) < BUDGET)内。候補が複数なら最も確信(var 最小)の軸。同点は AXIS_NAMES 順。
    """
    if len(spoken) >= PAIR_REALIZATION_BUDGET:
        return None
    threshold = CONCIERGE_RHO * TAU2_PREF
    spoken_set = set(spoken)
    best: Optional[tuple] = None
    for k in range(20):
        name = AXIS_NAMES[k]
        if name in spoken_set:
            continue
        if var[k] <= threshold and mu[k] > 0.0:
            if best is None or var[k] < best[0]:
                best = (var[k], name)
    return best[1] if best else None


def generate(req: ConciergeSpeechRequest) -> ConciergeSpeechResponse:
    """状態 → 発話。conciergeScript.ts の selectSpeech を忠実移植(挙動不変)。"""
    if req.phase == "decide":
        speech = _decision_final() if req.is_final else _decision_confirm()
        return ConciergeSpeechResponse(speech=speech, session=None)

    if req.phase == "recommend":
        if req.reasons is not None:
            if req.is_serendipity:
                return ConciergeSpeechResponse(speech=_serendipity())
            r = _reason_speech(req.reasons)
            if r is not None:
                return ConciergeSpeechResponse(speech=r)
        # フォールバック: 組み合わせ起点 or ステップ導入
        speech = _combination_speech(req.scenes or []) or _step_intro(req.step or "recommend")
        return ConciergeSpeechResponse(speech=speech)

    # explore: session(spoken_axes)を往復。新規確信軸があれば実況、無ければ step_intro。
    sess = req.session
    if sess is None:
        return ConciergeSpeechResponse(speech=_step_intro(req.step))
    axis = _newly_confident_axis(
        sess.user.theta_pref.mu, sess.user.theta_pref.var, sess.spoken_axes
    )
    if axis is not None:
        new_session = sess.model_copy(
            update={"spoken_axes": list(sess.spoken_axes) + [axis]}
        )
        return ConciergeSpeechResponse(
            speech=_axis_realization(AXIS_LABELS_JA.get(axis, axis)), session=new_session
        )
    # 実況なし → step_intro(session は不変で返す=caller は常に response.session を使えばよい)
    return ConciergeSpeechResponse(speech=_step_intro(req.step), session=sess)
