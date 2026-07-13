"""concierge_speech.generate の単体テスト + conciergeScript.ts との出力一致(パリティ)確認。

発話ロジック・文面は conciergeScript.ts と同一に保つ。ここでは同一入力で **API 側 Python の
出力が TS のテンプレ文面と一致する**ことを固定文字列で照合(= TS≡API のパリティ実証)。
発話 API は既存の推薦ロジックに触らないので、他テストへの影響はない。

トーン: 上品なホテルのコンシェルジュ風(ですます・絵文字)。名前 {name} は無ければ「あなた」。
"""

import concierge_speech as cs
from models_v13 import (
    ConciergeSpeechRequest,
    GaussianLab,
    GaussianScalar,
    GaussianVec20,
    LabValue,
    ProductTrait,
    ReasonAxis,
    RecommendReasons,
    UserState,
    V14Session,
)

# AXIS_NAMES 順: 6=sheer, 2=brightness, 19=korean(参照: catalog_x20.AXIS_NAMES)


def _user(pref_mu, pref_var) -> UserState:
    return UserState(
        user_id="u_test",
        lip_lab=LabValue(L=62, a=22, b=12),
        theta_color=GaussianLab(mu=LabValue(L=60, a=20, b=10), var=LabValue(L=25, a=25, b=25)),
        theta_pref=GaussianVec20(mu=pref_mu, var=pref_var),
        theta_explore=GaussianScalar(mu=0.5, var=0.25),
        theta_thickness=GaussianScalar(mu=0.5, var=0.1),
    )


def _session(pref_mu, pref_var, spoken=None) -> V14Session:
    return V14Session(user=_user(pref_mu, pref_var), spoken_axes=spoken or [])


def _reasons(top_axes=None, traits=None) -> RecommendReasons:
    return RecommendReasons(
        color_percentile=0.5, pref_percentile=0.5, scene_match=False,
        top_axes=top_axes or [], product_traits=traits or [],
    )


# ベース: 全軸 var=1.0(未確信)、mu=0。特定軸だけ確信させて実況を誘発する。
def _flat(mu=0.0, var=1.0):
    return [mu] * 20, [var] * 20


def test_explore_axis_realization():
    print("Test: explore=新規確信軸で実況 + spoken_axes 追記")
    mu, var = _flat()
    mu[6], var[6] = 0.8, 0.3   # sheer: 確信(≤0.5)かつ 好意(>0)
    r = cs.generate(ConciergeSpeechRequest(phase="explore", session=_session(mu, var), step="pair_compare"))
    assert r.speech and r.speech.type == "axis_realization"
    assert r.speech.text == "なるほど、透け感がお好みなんですね ✨", r.speech.text
    assert r.session.spoken_axes == ["sheer"], r.session.spoken_axes
    print(f"  ✓ {r.speech.text} / spoken={r.session.spoken_axes}")


def test_explore_no_repeat():
    print("Test: 同一軸は二度実況しない(spoken 済み)→ step_intro")
    mu, var = _flat()
    mu[6], var[6] = 0.8, 0.3   # sheer のみ確信
    r = cs.generate(ConciergeSpeechRequest(
        phase="explore", session=_session(mu, var, spoken=["sheer"]), step="pair_compare"))
    assert r.speech and r.speech.type == "step_intro", r.speech
    assert r.speech.text == "これから2色ずつお見せします。ピンとくる方を選ぶだけで、好みを学んでいきますね ✨"
    assert r.session.spoken_axes == ["sheer"]   # 不変
    print(f"  ✓ 二度言わず step_intro / spoken 不変={r.session.spoken_axes}")


def test_explore_budget():
    print("Test: 予算3を超えたら実況しない")
    mu, var = _flat()
    for k in (1, 2, 6, 19):    # 4軸を確信させる
        mu[k], var[k] = 0.8, 0.3
    spoken = ["saturation", "brightness", "sheer"]   # 既に3回=予算満了
    r = cs.generate(ConciergeSpeechRequest(
        phase="explore", session=_session(mu, var, spoken=spoken), step="pair_compare"))
    assert r.speech and r.speech.type == "step_intro", r.speech   # korean が確信でも予算切れ
    print("  ✓ 予算満了で実況せず step_intro")


def test_explore_positive_only():
    print("Test: μ_pref<0(否定方向)の確信軸は実況しない(#3)")
    mu, var = _flat()
    mu[19], var[19] = -0.9, 0.2   # korean: 確信だが否定方向
    r = cs.generate(ConciergeSpeechRequest(phase="explore", session=_session(mu, var), step="pair_compare"))
    assert r.speech and r.speech.type == "step_intro", r.speech
    assert r.session.spoken_axes == []
    print("  ✓ 否定方向は黙る(step_intro)")


def test_explore_pick_most_confident():
    print("Test: 複数確信軸は var 最小(最も確信)を選ぶ")
    mu, var = _flat()
    mu[6], var[6] = 0.8, 0.3    # sheer
    mu[2], var[2] = 0.8, 0.2    # brightness(より確信)
    r = cs.generate(ConciergeSpeechRequest(phase="explore", session=_session(mu, var), step="pair_compare"))
    assert r.speech.text == "なるほど、明るさがお好みなんですね ✨", r.speech.text
    assert r.session.spoken_axes == ["brightness"]
    print(f"  ✓ 最確信を選択: {r.speech.text}")


def test_recommend_hybrid():
    print("Test: recommend=top_axes+product_traits → reason_hybrid")
    reasons = _reasons(
        top_axes=[ReasonAxis(axis="sheer", label="透け感", contribution=0.5, evidence=[])],
        traits=[ProductTrait(axis="glossy", label="ツヤ")],
    )
    r = cs.generate(ConciergeSpeechRequest(phase="recommend", reasons=reasons))
    assert r.speech.type == "reason_hybrid"
    assert r.speech.text == "あなたは透け感がお好きですよね。だからこれを ✨。しかもツヤが出るタイプなんです", r.speech.text
    print(f"  ✓ {r.speech.text}")


def test_recommend_user_with_evidence():
    print("Test: recommend=top_axes(evidence=pair_id)→ 一言ラベルに変換(生ID を出さない)")
    reasons = _reasons(top_axes=[ReasonAxis(
        axis="sheer", label="透け感", contribution=0.5, evidence=["wv_09_sweet_vs_classy"])])
    r = cs.generate(ConciergeSpeechRequest(phase="recommend", reasons=reasons))
    assert r.speech.type == "reason_user"
    assert r.speech.text == "さっき『甘い vs クラシー』で選んでいたのが効いています。だからこれを ✨", r.speech.text
    print(f"  ✓ {r.speech.text}")


def test_recommend_user_unknown_evidence_fallback():
    print("Test: recommend=evidence が未知/非pair_id → 生値を出さず軸ラベルにフォールバック")
    reasons = _reasons(top_axes=[ReasonAxis(
        axis="sheer", label="透け感", contribution=0.5, evidence=["3問目で選んだ"])])
    r = cs.generate(ConciergeSpeechRequest(phase="recommend", reasons=reasons))
    assert r.speech.text == "あなたは透け感がお好きですよね。だからこれを ✨", r.speech.text  # 生値 "3問目で選んだ" は出さない
    print(f"  ✓ {r.speech.text}")


def test_recommend_product_only():
    print("Test: recommend=product_traits のみ → reason_product")
    r = cs.generate(ConciergeSpeechRequest(
        phase="recommend", reasons=_reasons(traits=[ProductTrait(axis="glossy", label="ツヤ")])))
    assert r.speech.type == "reason_product"
    assert r.speech.text == "この色はツヤが出るタイプなんです", r.speech.text
    print(f"  ✓ {r.speech.text}")


def test_recommend_serendipity():
    print("Test: recommend + is_serendipity → serendipity_offer")
    r = cs.generate(ConciergeSpeechRequest(
        phase="recommend", reasons=_reasons(top_axes=[ReasonAxis(
            axis="sheer", label="透け感", contribution=0.5, evidence=[])]), is_serendipity=True))
    assert r.speech.type == "serendipity_offer"
    assert r.speech.text == "こちらは少し冒険枠ですが…いつもと違うあなたも、素敵かもしれませんよ 👀"
    print(f"  ✓ {r.speech.text}")


def test_recommend_empty_fallback():
    print("Test: recommend で reasons 空/None → step_intro フォールバック")
    r1 = cs.generate(ConciergeSpeechRequest(phase="recommend", reasons=_reasons()))
    r2 = cs.generate(ConciergeSpeechRequest(phase="recommend", reasons=None))
    for r in (r1, r2):
        assert r.speech.type == "step_intro"
        assert r.speech.text == "おまたせしました。あなたのための色を選んでまいりました 👍", r.speech.text
    print("  ✓ 軸なし/None とも step_intro(recommend)にフォールバック")


def test_recommend_combination_single_scene():
    print("Test: recommend で reasons 無 + 単一シーン → COMBINATION_PATTERNS")
    r = cs.generate(ConciergeSpeechRequest(phase="recommend", reasons=None, scenes=["school"]))
    assert r.speech.type == "reason_user"
    assert r.speech.text == "学校で浮かない、さりげなく可愛い色を選んでまいりました ✨", r.speech.text
    # 複数シーンは該当キー無し → step_intro("recommend") にフォールバック
    r2 = cs.generate(ConciergeSpeechRequest(phase="recommend", reasons=None, scenes=["school", "date"]))
    assert r2.speech.type == "step_intro"
    assert r2.speech.text == "おまたせしました。あなたのための色を選んでまいりました 👍", r2.speech.text
    print("  ✓ 単一=専用文 / 複数=step_intro フォールバック(現状動作維持)")


def test_name_fallback():
    print("Test: {name}=所有格/主語(名前+さん / あなた)")
    assert cs._fill_name("{name}のための色", "ミナ") == "ミナさんのための色"
    assert cs._fill_name("{name}は好き", None) == "あなたは好き"
    print("  ✓ ミナ→ミナさん / 無し→あなた(所有格・主語)")


def test_name_vocative():
    print("Test: {name_voc}=呼びかけ(名前あれば「、名前さん」/ 無ければ省略)")
    assert cs._fill_name("ようこそ{name_voc}。", "ミナ") == "ようこそ、ミナさん。"
    assert cs._fill_name("ようこそ{name_voc}。", None) == "ようこそ。"   # 「、あなた」ごと省略
    # intro 全文の出し分け
    assert cs._step_intro("intro", "ミナ").text == "ようこそ、ミナさん。今日はぴったりの一本を一緒に見つけましょうね ✨"
    assert cs._step_intro("intro", None).text == "ようこそ。今日はぴったりの一本を一緒に見つけましょうね ✨"
    print("  ✓ 名前あり=呼びかけ / 無名=省略")


def test_decide():
    print("Test: decide=is_final で終端 / else 確認")
    rf = cs.generate(ConciergeSpeechRequest(phase="decide", is_final=True))
    rc = cs.generate(ConciergeSpeechRequest(phase="decide", is_final=False))
    assert rf.speech.type == "decision_final"
    assert rf.speech.text == "どちらもお似合いの範囲です。あとは今日の気分で選んで大丈夫ですよ 👍"
    assert rc.speech.type == "decision_confirm"
    assert rc.speech.text == "いいですね。その2〜3本ならどれもお似合いですよ。じっくり見比べてくださいね ✨"
    print(f"  ✓ final={rf.speech.text} / confirm={rc.speech.text}")


# ── conciergeScript.ts の期待文面(TS 側テンプレから転記)。API がこれと一致すれば TS≡API。──
#    {name} 無し(=「あなた」)入力での **全枠** を照合する(単一入力での全枠一致=パリティ実証)。
TS_PARITY = [
    ("step_intro/intro", "ようこそ。今日はぴったりの一本を一緒に見つけましょうね ✨"),
    ("step_intro/scene_select", "まず、どんなときに使いたいか教えてください。シーンで似合う色って変わるんですよ 👀"),
    ("step_intro/capture_wrist", "手首の内側を見せてくださいますか? 血管の色から、似合う色のヒントが分かるんです ✨"),
    ("step_intro/capture_lip", "次は唇の色を。塗ったときの仕上がりを計算しますね 👀"),
    ("step_intro/pc_confirm", "あなたのパーソナルカラー、これで合っていそうですか?"),
    ("step_intro/pair_compare", "これから2色ずつお見せします。ピンとくる方を選ぶだけで、好みを学んでいきますね ✨"),
    ("step_intro/recommend", "おまたせしました。あなたのための色を選んでまいりました 👍"),
    ("axis_realization/透け感", "なるほど、透け感がお好みなんですね ✨"),
    ("reason_user/pairlabel", "さっき『甘い vs クラシー』で選んでいたのが効いています。だからこれを ✨"),
    ("reason_user/no_evidence", "あなたは透け感がお好きですよね。だからこれを ✨"),
    ("reason_product", "この色はツヤが出るタイプなんです"),
    ("reason_hybrid", "あなたは透け感がお好きですよね。だからこれを ✨。しかもツヤが出るタイプなんです"),
    ("serendipity", "こちらは少し冒険枠ですが…いつもと違うあなたも、素敵かもしれませんよ 👀"),
    ("decision_confirm", "いいですね。その2〜3本ならどれもお似合いですよ。じっくり見比べてくださいね ✨"),
    ("decision_final", "どちらもお似合いの範囲です。あとは今日の気分で選んで大丈夫ですよ 👍"),
    ("combination/school", "学校で浮かない、さりげなく可愛い色を選んでまいりました ✨"),
    ("combination/friends", "お友達と会う日に、気分の上がる色を集めました 👀"),
    ("combination/date", "デートにぴったりの、そっと華やぐ色を選びましたよ ✨"),
    ("combination/special", "特別な日に映える、とっておきの色をご用意しました 👍"),
]


def test_ts_parity_table():
    print("Test: TS(conciergeScript.ts)≡ API(concierge_speech.py)出力一致表(全枠)")
    # API 側で同じ入力を生成(名前無し=「あなた」)
    api = {
        "step_intro/intro": cs._step_intro("intro").text,
        "step_intro/scene_select": cs._step_intro("scene_select").text,
        "step_intro/capture_wrist": cs._step_intro("capture_wrist").text,
        "step_intro/capture_lip": cs._step_intro("capture_lip").text,
        "step_intro/pc_confirm": cs._step_intro("pc_confirm").text,
        "step_intro/pair_compare": cs._step_intro("pair_compare").text,
        "step_intro/recommend": cs._step_intro("recommend").text,
        "axis_realization/透け感": cs._axis_realization("透け感").text,
        "reason_user/pairlabel": cs._reason_speech(_reasons(top_axes=[ReasonAxis(
            axis="sweetness", label="甘さ", contribution=0.5, evidence=["wv_09_sweet_vs_classy"])])).text,
        "reason_user/no_evidence": cs._reason_speech(_reasons(top_axes=[ReasonAxis(
            axis="sheer", label="透け感", contribution=0.5, evidence=[])])).text,
        "reason_product": cs._reason_speech(_reasons(traits=[ProductTrait(axis="glossy", label="ツヤ")])).text,
        "reason_hybrid": cs._reason_speech(_reasons(
            top_axes=[ReasonAxis(axis="sheer", label="透け感", contribution=0.5, evidence=[])],
            traits=[ProductTrait(axis="glossy", label="ツヤ")])).text,
        "serendipity": cs._serendipity().text,
        "decision_confirm": cs._decision_confirm().text,
        "decision_final": cs._decision_final().text,
        "combination/school": cs._combination_speech(["school"]).text,
        "combination/friends": cs._combination_speech(["friends"]).text,
        "combination/date": cs._combination_speech(["date"]).text,
        "combination/special": cs._combination_speech(["special"]).text,
    }
    print(f"  {'ケース':<26}{'一致':<5} テキスト")
    for key, ts_text in TS_PARITY:
        got = api[key]
        ok = got == ts_text
        print(f"  {key:<26}{'✓' if ok else '✗ NG':<5} {got}")
        assert ok, f"TS≠API: {key}\n  TS ={ts_text}\n  API={got}"
    print("  ✓ 全枠(19)で TS≡API 一致")


if __name__ == "__main__":
    test_explore_axis_realization()
    test_explore_no_repeat()
    test_explore_budget()
    test_explore_positive_only()
    test_explore_pick_most_confident()
    test_recommend_hybrid()
    test_recommend_user_with_evidence()
    test_recommend_user_unknown_evidence_fallback()
    test_recommend_product_only()
    test_recommend_serendipity()
    test_recommend_empty_fallback()
    test_recommend_combination_single_scene()
    test_name_fallback()
    test_name_vocative()
    test_decide()
    test_ts_parity_table()
    print("=" * 50)
    print("✅ concierge_speech: 全 16 テスト合格(TS パリティ全枠含む)")
