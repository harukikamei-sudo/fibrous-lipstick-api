"""Fibrous Lipstick — Streamlit UI(レベル2: 唇画像に塗布シミュを合成)。

唇プリセットを選んで /recommend を叩き、TOP-N を「唇画像に塗布後の色を合成した
ビジュアル」で見せる薄いクライアント。計算は API 側(km/estimate_s)に任せる。

合成ロジック(唇領域のみ):
  - L チャネル: 元画像と applied_lab を比率ブレンド(既定 50:50)。元の陰影/質感を残す
  - a, b チャネル: applied_lab で置換(色味は塗布後に)
  → 「口紅を塗った唇」っぽいビジュアルになる

唇画像(プリセット 5 枚)は assets/lips/lip_<preset>.png(PNG, α で唇マスク)。
無ければダミー唇シェイプを動的生成。将来 Kawano さんデータは load_lip_image() を
差し替えれば対応可能(インターフェース固定)。

起動:
  pip install -r requirements-ui.txt
  streamlit run ui_app.py

依存: streamlit, requests, numpy, pillow, scikit-image
"""

import os

import numpy as np
import requests
import streamlit as st
from PIL import Image, ImageDraw
from skimage import color as skcolor

from lab_utils import lab_to_rgb
import km


DEFAULT_API = "https://tamable-fibrous-lipstick-api.hf.space"
ASSETS_LIPS = os.path.join(os.path.dirname(__file__), "assets", "lips")
BG = (245, 245, 245)   # 唇以外(非マスク)の表示背景


# ============ 色ユーティリティ ============

def lab_to_hex(lab):
    r, g, b = (int(round(v)) for v in lab_to_rgb(lab))
    return f"#{r:02x}{g:02x}{b:02x}"


def chip(lab, label=""):
    return (f"<div style='background:{lab_to_hex(lab)};height:34px;border-radius:6px;"
            f"border:1px solid #ccc'></div>"
            f"<div style='font-size:11px;color:#666;text-align:center'>{label}</div>")


# ============ 唇画像のロード(Format A: assets / フォールバック: ダミー) ============
#
# load_lip_image(preset_name) -> (rgb_uint8 HxWx3, mask HxW bool)
# 将来 Kawano さんのデータ形式が固まったら、この関数の内部だけ差し替える。

def _dummy_lip(preset_name, w=400, h=300):
    """assets が無い時のダミー唇(楕円ベース、α マスク付き)。"""
    lab = km.LIP_PRESETS.get(preset_name, [60.0, 20.0, 12.0])
    base = tuple(int(round(v)) for v in lab_to_rgb(lab))
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # 上唇(やや薄い楕円)+ 下唇(大きい楕円)
    d.ellipse([w * 0.15, h * 0.28, w * 0.85, h * 0.55], fill=base + (255,))
    d.ellipse([w * 0.13, h * 0.46, w * 0.87, h * 0.80], fill=base + (255,))
    # 口の合わせ目(やや暗いライン)
    d.line([(w * 0.20, h * 0.53), (w * 0.80, h * 0.53)],
           fill=(max(base[0] - 60, 0), max(base[1] - 40, 0), max(base[2] - 40, 0), 255),
           width=3)
    # 下唇ハイライト(L 変化=質感のため。半透明の明るい楕円)
    hi = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(hi).ellipse([w * 0.38, h * 0.58, w * 0.62, h * 0.70],
                               fill=(255, 255, 255, 90))
    im = Image.alpha_composite(im, hi)
    arr = np.asarray(im)
    return arr[..., :3].copy(), arr[..., 3] > 128


def load_lip_image(preset_name):
    """唇プリセット名 → (rgb_uint8, mask)。assets 優先、無ければダミー。"""
    path = os.path.join(ASSETS_LIPS, f"lip_{preset_name}.png")
    if os.path.exists(path):
        im = Image.open(path).convert("RGBA")
        arr = np.asarray(im)
        if arr[..., 3].max() > 0:          # α があれば唇マスクに使う
            return arr[..., :3].copy(), arr[..., 3] > 128
        return arr[..., :3].copy(), np.ones(arr.shape[:2], bool)  # 全面=唇とみなす
    return _dummy_lip(preset_name)


# ============ 色合成(唇領域に applied_lab を乗せる) ============

def composite_lip(rgb_uint8, mask, applied_lab, l_blend=0.5):
    """唇領域を applied_lab で塗る。

    L は元画像と applied_lab を (1-l_blend):l_blend でブレンド(陰影/質感を残す)、
    a,b は applied_lab で置換。非マスク領域は表示用に背景色で塗る。
    """
    lab = skcolor.rgb2lab(rgb_uint8.astype(float) / 255.0)
    out = lab.copy()
    L, a, b = float(applied_lab[0]), float(applied_lab[1]), float(applied_lab[2])
    out[..., 0] = np.where(mask, (1 - l_blend) * lab[..., 0] + l_blend * L, lab[..., 0])
    out[..., 1] = np.where(mask, a, lab[..., 1])
    out[..., 2] = np.where(mask, b, lab[..., 2])
    rgb = (np.clip(skcolor.lab2rgb(out), 0, 1) * 255).astype(np.uint8)
    rgb[~mask] = BG
    return rgb


# ============ Streamlit ============

def main():
    st.set_page_config(page_title="Fibrous Lipstick Recommender", layout="wide")
    st.title("💄 唇に塗ったらこう見える — 口紅レコメンド (Lv2)")
    st.caption("唇の色を選ぶと、全商品を『塗った後の色』で計算し、唇画像に合成して近い順に表示。")

    with st.sidebar:
        st.header("条件")
        api_base = st.text_input("API ベースURL", DEFAULT_API).rstrip("/")

        lip_key = st.selectbox("唇の色(下地)", list(km.LIP_PRESETS), index=1)
        lip_lab = km.LIP_PRESETS[lip_key]
        st.markdown(chip(lip_lab, f"{lip_key}  Lab={lip_lab}"), unsafe_allow_html=True)

        t = st.slider("塗り厚 t(塗り重ね量)", 0.1, 3.0, 1.0, 0.1)
        l_blend = st.slider("質感ブレンド(L)", 0.0, 1.0, 0.5, 0.05,
                            help="0=元の唇の明暗を完全保持 / 1=塗布後Lで塗りつぶし")
        cat = st.selectbox("仕上げで絞り込み", ["(指定なし)"] + list(km.LINE_CATEGORIES))
        top_n = st.slider("表示件数", 1, 10, 5)

        use_target = st.checkbox("目標色を指定して寄せる(off=唇に近い順)")
        target_lab = None
        if use_target:
            tl = st.number_input("目標 L*", 0.0, 100.0, 50.0)
            ta = st.number_input("目標 a*", -50.0, 80.0, 40.0)
            tb = st.number_input("目標 b*", -50.0, 60.0, 20.0)
            target_lab = [tl, ta, tb]

        run = st.button("レコメンド", type="primary", use_container_width=True)

    # 選択中の唇画像(プレビュー)
    lip_rgb, lip_mask = load_lip_image(lip_key)
    src = "assets" if os.path.exists(os.path.join(ASSETS_LIPS, f"lip_{lip_key}.png")) else "ダミー生成"
    with st.sidebar:
        st.image(lip_rgb, caption=f"唇画像: {lip_key}({src})", use_container_width=True)

    if not run:
        st.info("← サイドバーで唇の色を選んで「レコメンド」を押してください。")
        return

    payload = {"lip_lab": {"L": lip_lab[0], "a": lip_lab[1], "b": lip_lab[2]},
               "t": t, "top_n": top_n}
    if cat != "(指定なし)":
        payload["line_category"] = cat
    if target_lab is not None:
        payload["target_lab"] = {"L": target_lab[0], "a": target_lab[1], "b": target_lab[2]}

    try:
        res = requests.post(f"{api_base}/recommend", json=payload, timeout=60)
    except requests.RequestException as e:
        st.error(f"API 呼び出し失敗: {e}")
        return
    if res.status_code != 200:
        st.error(f"API エラー {res.status_code}: {res.text[:300]}")
        return

    data = res.json()
    sort_mode = "目標色に近い順" if target_lab is not None else "唇に近い(自然な)順"
    st.subheader(f"TOP {len(data['results'])}  (候補 {data['count']} 件中)")
    st.caption(f"並べ替え: {sort_mode} / 塗り厚 t={t} / 質感ブレンド={l_blend}")

    cols = st.columns(min(len(data["results"]), 5))
    for i, it in enumerate(data["results"]):
        appl = [it["applied_lab"]["L"], it["applied_lab"]["a"], it["applied_lab"]["b"]]
        orig = [it["original_lab"]["L"], it["original_lab"]["a"], it["original_lab"]["b"]]
        comp = composite_lip(lip_rgb, lip_mask, appl, l_blend=l_blend)
        with cols[i % len(cols)]:
            st.image(comp, use_container_width=True)
            st.markdown(f"**{i+1}. {it['name']}**")
            st.caption(f"`{it['line_category']}` ΔE={it['delta_e']} / {it['id']}")
            st.markdown(chip(orig, "商品本来"), unsafe_allow_html=True)


if __name__ == "__main__":
    main()
