"""Fibrous Lipstick — Streamlit UI(レベル1: 色チップ表示)。

唇プリセットを選んで /recommend を叩き、TOP-N を色チップで表示するだけの薄い
クライアント。計算は API 側(km/estimate_s)に任せる。後でレベル2(唇画像合成)へ拡張。

起動:
  pip install -r requirements-ui.txt      # streamlit, requests 等
  streamlit run ui_app.py

API は既定で公開 HF Space を叩く。ローカルの uvicorn を使うなら
サイドバーの「API ベースURL」を http://127.0.0.1:8000 に変える。

依存: streamlit, requests, numpy, scikit-image(lab_utils 経由)
"""

import requests
import streamlit as st

from lab_utils import lab_to_rgb
import km


DEFAULT_API = "https://tamable-fibrous-lipstick-api.hf.space"


def lab_to_hex(lab):
    """Lab → '#rrggbb'(sRGB, クランプ済み)。色チップ表示用。"""
    r, g, b = (int(round(v)) for v in lab_to_rgb(lab))
    return f"#{r:02x}{g:02x}{b:02x}"


def chip(lab, label=""):
    """色チップ(HTML)を返す。"""
    hexc = lab_to_hex(lab)
    return (f"<div style='background:{hexc};height:48px;border-radius:6px;"
            f"border:1px solid #ccc'></div>"
            f"<div style='font-size:11px;color:#666;text-align:center'>{label}</div>")


def main():
    st.set_page_config(page_title="Fibrous Lipstick Recommender", layout="wide")
    st.title("💄 唇に塗ったらこう見える — 口紅レコメンド (Lv1)")
    st.caption("唇の色を選ぶと、全商品を『塗った後の色』で計算して近い順に出します。")

    with st.sidebar:
        st.header("条件")
        api_base = st.text_input("API ベースURL", DEFAULT_API).rstrip("/")

        lip_key = st.selectbox("唇の色(下地)", list(km.LIP_PRESETS), index=1)
        lip_lab = km.LIP_PRESETS[lip_key]
        st.markdown(chip(lip_lab, f"{lip_key}  Lab={lip_lab}"),
                    unsafe_allow_html=True)

        t = st.slider("塗り厚 t(塗り重ね量)", 0.1, 3.0, 1.0, 0.1)
        cat = st.selectbox("仕上げで絞り込み",
                           ["(指定なし)"] + list(km.LINE_CATEGORIES))
        top_n = st.slider("表示件数", 1, 10, 5)

        use_target = st.checkbox("目標色を指定して寄せる(off=唇に近い順)")
        target_lab = None
        if use_target:
            tl = st.number_input("目標 L*", 0.0, 100.0, 50.0)
            ta = st.number_input("目標 a*", -50.0, 80.0, 40.0)
            tb = st.number_input("目標 b*", -50.0, 60.0, 20.0)
            target_lab = [tl, ta, tb]
            st.markdown(chip(target_lab, "目標色"), unsafe_allow_html=True)

        run = st.button("レコメンド", type="primary", use_container_width=True)

    if not run:
        st.info("← サイドバーで唇の色を選んで「レコメンド」を押してください。")
        return

    payload = {
        "lip_lab": {"L": lip_lab[0], "a": lip_lab[1], "b": lip_lab[2]},
        "t": t,
        "top_n": top_n,
    }
    if cat != "(指定なし)":
        payload["line_category"] = cat
    if target_lab is not None:
        payload["target_lab"] = {"L": target_lab[0], "a": target_lab[1],
                                 "b": target_lab[2]}

    try:
        res = requests.post(f"{api_base}/recommend", json=payload, timeout=60)
    except requests.RequestException as e:
        st.error(f"API 呼び出し失敗: {e}")
        return
    if res.status_code != 200:
        st.error(f"API エラー {res.status_code}: {res.text[:300]}")
        return

    data = res.json()
    st.subheader(f"TOP {len(data['results'])}  (候補 {data['count']} 件中)")
    sort_mode = "目標色に近い順" if target_lab is not None else "唇に近い(自然な)順"
    st.caption(f"並べ替え基準: {sort_mode} / 塗り厚 t={t}")

    for rank, it in enumerate(data["results"], 1):
        orig = [it["original_lab"]["L"], it["original_lab"]["a"], it["original_lab"]["b"]]
        appl = [it["applied_lab"]["L"], it["applied_lab"]["a"], it["applied_lab"]["b"]]
        c0, c1, c2, c3 = st.columns([3, 1, 1, 1])
        with c0:
            st.markdown(f"**{rank}. {it['name']}**  `{it['line_category']}`")
            st.caption(f"id: {it['id']} / ΔE={it['delta_e']}")
        with c1:
            st.markdown(chip(orig, "商品本来"), unsafe_allow_html=True)
        with c2:
            st.markdown(chip(appl, "塗った後"), unsafe_allow_html=True)
        with c3:
            st.markdown(chip(lip_lab, "素の唇"), unsafe_allow_html=True)
        st.divider()


if __name__ == "__main__":
    main()
