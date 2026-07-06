"""コンシェルジュ発話生成(F3 を API 化)。

フロント `color-capture/src/lib/conciergeScript.ts` のロジックと文面を **同一に保つ**
(TS≡API パリティテストで担保)。RN 版と Next 版で二重実装しないため、発話生成を
バックエンドに一本化する(6/29 MTG 方針転換)。既存の reasons(A2)/ theta_snapshot
(A3・session 内)を **日本語文面に変換するだけ**で、新しい推薦データやスコアは作らない。

【トーン】上品なホテルのコンシェルジュ風(中間トーン=基本やわらか・時々かしこまる)。
  語尾はですます。絵文字あり(✨👍👀)。対象は Mina(15歳・メイク初心者・失敗不安)。
  文面は Haruki 作成の確定版(旧「妖精・タメ口/ Kawano 3パターン待ち」から変更)。
  LLM は使わない(デモ安定性・出力統制)。
【名前】{name} プレースホルダは _fill_name で解決。名前があれば「名前+さん」、無ければ
  「あなた」。現状 UserState に name フィールドは無い=実質「あなた」固定。将来 name 入力が
  付いたら _extract_name が拾い、テンプレの {name} がそのまま効く(テンプレは残す)。
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


def _fill_name(text: str, name: Optional[str] = None) -> str:
    """{name} を解決。名前があれば「名前+さん」、無ければ「あなた」。
    conciergeScript.ts の fillName と同一(変更時は両方直す)。"""
    return text.replace("{name}", f"{name}さん" if name else "あなた")


def _extract_name(req: ConciergeSpeechRequest) -> Optional[str]:
    """名前の取得元。現状 UserState に name フィールドは無い=常に None(→「あなた」)。
    将来 UserState.name 等が付いたら explore(session を往復)で自動的に拾う。"""
    user = getattr(req.session, "user", None) if req.session else None
    return getattr(user, "name", None) if user else None


# ── 探索フェーズ: ステップ固定説明({name} は _fill_name で解決)──
STEP_INTRO = {
    "intro": "ようこそ、{name}。今日はぴったりの一本を一緒に見つけましょうね ✨",
    "scene_select": "まず、どんなときに使いたいか教えてください。シーンで似合う色って変わるんですよ 👀",
    "capture_wrist": "手首の内側を見せてくださいますか? 血管の色から、似合う色のヒントが分かるんです ✨",
    "capture_lip": "次は唇の色を。塗ったときの仕上がりを計算しますね 👀",
    "pc_confirm": "{name}のパーソナルカラー、これで合っていそうですか?",
    "pair_compare": "これから2色ずつお見せします。ピンとくる方を選ぶだけで、好みを学んでいきますね ✨",
    "recommend": "おまたせしました。{name}のための色を選んでまいりました 👍",
}

# シーン起点パターン(単一シーン4つのみ・確定)。キー = ソート済みシーンの "+" 連結。
# 複数シーン選択時はここに該当キーが無い → step_intro("recommend") にフォールバック(現状動作維持)。
# 複数選択の網羅・第2軸(スタイル)は Phase 2(未実装)。
COMBINATION_PATTERNS = {
    "school": "学校で浮かない、さりげなく可愛い色を選んでまいりました ✨",
    "friends": "お友達と会う日に、気分の上がる色を集めました 👀",
    "date": "デートにぴったりの、そっと華やぐ色を選びましたよ ✨",
    "special": "特別な日に映える、とっておきの色をご用意しました 👍",
}


def _step_intro(step: Optional[str], name: Optional[str] = None) -> Optional[ConciergeSpeech]:
    if not step:
        return None
    text = STEP_INTRO.get(step)
    return ConciergeSpeech(type="step_intro", text=_fill_name(text, name)) if text else None


def _axis_realization(axis_label: str) -> ConciergeSpeech:
    return ConciergeSpeech(type="axis_realization", text=f"なるほど、{axis_label}がお好みなんですね ✨")


# reasons.top_axes[].evidence は「その軸を最も動かした pair_id」の列(bayesian.compute_pref_evidence)。
# 生の pair_id(例 wv_09_sweet_vs_classy)を文面にそのまま出さないよう、一言ラベルに変換する。
# ※ pair_compare._PAIR_SPECS のラベルと同一(型生成に乗らないためここに転記・変更時は両方直す)。
_PAIR_LABELS = {
    "color_01_bright_vs_deep": "明るい vs 深い",
    "color_02_warm_vs_cool": "暖色寄り vs 寒色寄り",
    "color_03_vivid_vs_nude": "鮮やか vs ヌード",
    "color_04_pink_vs_coral": "ピンク vs コーラル",
    "color_05_rose_vs_red": "ローズ vs レッド",
    "wv_06_girly_vs_mature": "ガーリー vs マチュア",
    "wv_07_korean_vs_konare": "韓国っぽい vs こなれ",
    "wv_08_juicy_vs_matte": "ジューシー vs マット",
    "wv_09_sweet_vs_classy": "甘い vs クラシー",
    "wv_10_daily_vs_statement": "デイリー vs ステートメント",
}


def _user_origin_text(axis, name: Optional[str] = None) -> str:
    ev = axis.evidence[0] if getattr(axis, "evidence", None) else None
    pair_label = _PAIR_LABELS.get(ev) if ev else None
    if pair_label:
        return f"さっき『{pair_label}』で選んでいたのが効いています。だからこれを ✨"
    # evidence が pair_id でない/無い場合は生値を出さず、軸ラベルで説明(生 ID 漏洩を防ぐ)。
    return _fill_name("{name}は" + f"{axis.label}がお好きですよね。だからこれを ✨", name)


def _product_origin_text(trait_label: str) -> str:
    return f"この色は{trait_label}が出るタイプなんです"


def _reason_speech(reasons: Optional[RecommendReasons], name: Optional[str] = None) -> Optional[ConciergeSpeech]:
    if reasons is None:
        return None
    top_axis = reasons.top_axes[0] if reasons.top_axes else None
    trait = reasons.product_traits[0] if reasons.product_traits else None
    # 両方あれば接続(理想形): ユーザー起点 × 商品起点
    if top_axis and trait:
        # productOriginText の「この色は」接頭を落として接続(TS の .replace(/^この色は/,"") と同じ)
        product_tail = _product_origin_text(trait.label).removeprefix("この色は")
        return ConciergeSpeech(
            type="reason_hybrid", text=f"{_user_origin_text(top_axis, name)}。しかも{product_tail}"
        )
    if top_axis:
        return ConciergeSpeech(type="reason_user", text=_user_origin_text(top_axis, name))
    if trait:
        return ConciergeSpeech(type="reason_product", text=_product_origin_text(trait.label))
    return None


def _serendipity(name: Optional[str] = None) -> ConciergeSpeech:
    return ConciergeSpeech(
        type="serendipity_offer",
        text=_fill_name("こちらは少し冒険枠ですが…いつもと違う{name}も、素敵かもしれませんよ 👀", name),
    )


def _decision_confirm() -> ConciergeSpeech:
    return ConciergeSpeech(
        type="decision_confirm",
        text="いいですね。その2〜3本ならどれもお似合いですよ。じっくり見比べてくださいね ✨",
    )


def _decision_final() -> ConciergeSpeech:
    return ConciergeSpeech(
        type="decision_final",
        text="どちらもお似合いの範囲です。あとは今日の気分で選んで大丈夫ですよ 👍",
    )


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
    name = _extract_name(req)

    if req.phase == "decide":
        speech = _decision_final() if req.is_final else _decision_confirm()
        return ConciergeSpeechResponse(speech=speech, session=None)

    if req.phase == "recommend":
        if req.reasons is not None:
            if req.is_serendipity:
                return ConciergeSpeechResponse(speech=_serendipity(name))
            r = _reason_speech(req.reasons, name)
            if r is not None:
                return ConciergeSpeechResponse(speech=r)
        # フォールバック: 組み合わせ起点 or ステップ導入
        speech = _combination_speech(req.scenes or []) or _step_intro(req.step or "recommend", name)
        return ConciergeSpeechResponse(speech=speech)

    # explore: session(spoken_axes)を往復。新規確信軸があれば実況、無ければ step_intro。
    sess = req.session
    if sess is None:
        return ConciergeSpeechResponse(speech=_step_intro(req.step, name))
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
    return ConciergeSpeechResponse(speech=_step_intro(req.step, name), session=sess)
