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
# model.png の帰属(CC BY 3.0 はクレジット表示が必要)
MODEL_CREDIT = '唇画像: "My Red Lips" by Trina — CC BY 3.0 / Wikimedia Commons'


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
    """assets が無い時のダミー唇。

    キューピッドボウ(上唇の山)+ ふっくら下唇のシルエットを曲線で生成し、
    中央ハイライト・合わせ目の陰・縁の陰影で立体感を付ける(L 変化=質感)。
    2x スーパーサンプリングしてアンチエイリアス。
    """
    lab = km.LIP_PRESETS.get(preset_name, [60.0, 20.0, 12.0])
    base = np.asarray(lab_to_rgb(lab), dtype=float)   # (3,) 0-255

    ss = 2
    W, H = w * ss, h * ss
    cx = W * 0.5
    x0, x1 = W * 0.14, W * 0.86
    hw = (x1 - x0) / 2.0
    ym = H * 0.50                                     # 口の合わせ目
    xs = np.linspace(x0, x1, 280)
    u = (xs - cx) / hw                                # -1..1

    # 上唇トップ: 全体のふくらみ(1-u^2) から中央にキューピッドボウの窪み
    top = ym - H * 0.15 * ((1 - u ** 2) - 0.38 * np.exp(-(u / 0.16) ** 2))
    # 下唇ボトム: ふっくら丸み
    bot = ym + H * 0.23 * np.clip(1 - u ** 2, 0, 1) ** 0.75

    # シルエット(上唇・下唇ポリゴン)→ マスク
    mimg = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mimg)
    up = ([(xs[i], top[i]) for i in range(len(xs))]
          + [(xs[i], ym) for i in range(len(xs) - 1, -1, -1)])
    lo = ([(xs[i], ym) for i in range(len(xs))]
          + [(xs[i], bot[i]) for i in range(len(xs) - 1, -1, -1)])
    md.polygon(up, fill=255)
    md.polygon(lo, fill=255)
    mask = np.asarray(mimg) > 0

    # 陰影フィールド: 下唇ハイライト - 合わせ目の陰 - 縁の暗がり
    yy, xx = np.mgrid[0:H, 0:W]
    hl = np.exp(-(((xx - cx) / (W * 0.15)) ** 2 + ((yy - (ym + H * 0.12)) / (H * 0.07)) ** 2))
    mline = np.exp(-((yy - ym) / (H * 0.016)) ** 2)
    rim = ((xx - cx) / hw) ** 2
    shade = 0.45 * hl - 0.5 * mline - 0.12 * rim
    rgb = np.clip(base[None, None, :] * (1 + 0.55 * shade[..., None]), 0, 255).astype(np.uint8)

    out = np.zeros((H, W, 4), np.uint8)
    out[..., :3] = rgb
    out[..., 3] = np.where(mask, 255, 0)
    im = Image.fromarray(out, "RGBA").resize((w, h), Image.LANCZOS)
    arr = np.asarray(im)
    rgb_s = arr[..., :3].astype(float)
    al = arr[..., 3].astype(float) / 255.0      # resize で縁が羽化される
    rgb_s[al < 0.5] = BG                          # 唇外は背景色
    return rgb_s.astype(np.uint8), al


def _read_rgba(path):
    """RGBA PNG → (rgb_uint8, alpha 0-1)。α 無しは全面=唇(1.0)。"""
    arr = np.asarray(Image.open(path).convert("RGBA"))
    al = arr[..., 3].astype(float) / 255.0
    if al.max() <= 0:
        al = np.ones(arr.shape[:2])
    return arr[..., :3].copy(), al


def lip_image_source(preset_name):
    """この preset で使う唇画像のソース種別を返す: 'preset'|'model'|'dummy'。"""
    if os.path.exists(os.path.join(ASSETS_LIPS, f"lip_{preset_name}.png")):
        return "preset"
    if os.path.exists(os.path.join(ASSETS_LIPS, "model.png")):
        return "model"
    return "dummy"


def load_lip_image(preset_name):
    """唇プリセット名 → (rgb_uint8, alpha 0-1)。

    優先: assets/lips/lip_<preset>.png(プリセット個別) > model.png(全プリセット共用の
    実写モデル) > ダミー生成。実写では α=唇マスク(羽化済み)。
    """
    src = lip_image_source(preset_name)
    if src == "preset":
        return _read_rgba(os.path.join(ASSETS_LIPS, f"lip_{preset_name}.png"))
    if src == "model":
        return _read_rgba(os.path.join(ASSETS_LIPS, "model.png"))
    return _dummy_lip(preset_name)


# ============ 色合成(唇領域に applied_lab を乗せる) ============

def measure_lip_lab(rgb_uint8, alpha, alpha_min=0.7):
    """唇マスクのコア領域(α>alpha_min)から代表 Lab を中央値で算出。

    羽化された縁を避けて唇の本体だけを採るため α しきい値は高めに(0.7)。
    """
    core = alpha >= alpha_min
    if not core.any():
        core = alpha > 0
    lab = skcolor.rgb2lab(rgb_uint8.astype(float) / 255.0)
    pix = lab[core]
    L, a, b = np.median(pix, axis=0)
    return np.array([float(L), float(a), float(b)])


def list_lip_photos():
    """assets/lips にある利用可能な唇写真をリスト。

    Returns: list[(key, label)]。key は load_lip_image() 用の識別子。
      'model'        : 共用 model.png
      'preset:<name>': lip_<name>.png(プリセット個別)
    """
    found = []
    if os.path.exists(os.path.join(ASSETS_LIPS, "model.png")):
        found.append(("model", "実写モデル (model.png)"))
    for name in km.LIP_PRESETS:
        if os.path.exists(os.path.join(ASSETS_LIPS, f"lip_{name}.png")):
            found.append((f"preset:{name}", f"プリセット個別: {name}"))
    return found


def composite_lip(rgb_uint8, alpha, applied_lab, l_blend=0.5):
    """唇に applied_lab を塗る(顔・周辺はそのまま残す)。

    全画素を Lab で「L は元と applied_lab を (1-l_blend):l_blend ブレンド(陰影/質感を
    残す)、a,b は applied_lab で置換」して再着色し、α(唇マスク, 0-1)で元画像と合成する。
    α が羽化されているので唇の縁が自然に馴染む。
    """
    base = rgb_uint8.astype(float) / 255.0
    lab = skcolor.rgb2lab(base)
    rec = lab.copy()
    L, a, b = float(applied_lab[0]), float(applied_lab[1]), float(applied_lab[2])
    rec[..., 0] = (1 - l_blend) * lab[..., 0] + l_blend * L
    rec[..., 1] = a
    rec[..., 2] = b
    rec_rgb = np.clip(skcolor.lab2rgb(rec), 0, 1)
    a3 = np.clip(alpha, 0.0, 1.0)[..., None]
    out = rec_rgb * a3 + base * (1 - a3)
    return (out * 255).astype(np.uint8)


# ============ Streamlit ============

def main():
    st.set_page_config(page_title="Fibrous Lipstick Recommender", layout="wide")
    st.title("💄 唇に塗ったらこう見える — 口紅レコメンド (Lv2)")
    st.caption("唇の色を選ぶと、全商品を『塗った後の色』で計算し、唇画像に合成して近い順に表示。")

    photos = list_lip_photos()

    with st.sidebar:
        st.header("条件")
        api_base = st.text_input("API ベースURL", DEFAULT_API).rstrip("/")

        # 唇画像の選択(写真がある時は写真ベース=計算と表示が一致。
        # 無い時のみダミー+プリセット Lab にフォールバック)
        if photos:
            keys = [k for k, _ in photos]
            labels = [lab for _, lab in photos]
            sel = st.selectbox("唇画像", labels, index=0)
            photo_key = keys[labels.index(sel)]
            preset_for_dummy = None
        else:
            st.info("assets/lips に写真が無いのでダミー唇を使います")
            photo_key = None
            preset_for_dummy = st.selectbox(
                "ダミー唇の色(プリセット)", list(km.LIP_PRESETS), index=1)

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

    # 唇画像のロードと「下地 Lab」決定
    # 写真がある場合: 画像の唇領域から Lab を実測 → 計算の下地と表示が一致
    # 写真が無い場合: プリセット Lab からダミー生成(プリセット = 描画色 = 下地)
    if photo_key == "model":
        lip_rgb, lip_alpha = _read_rgba(os.path.join(ASSETS_LIPS, "model.png"))
        lip_lab = measure_lip_lab(lip_rgb, lip_alpha).tolist()
        src_label = "実写モデル(共用)"
        credit = MODEL_CREDIT
    elif photo_key and photo_key.startswith("preset:"):
        name = photo_key.split(":", 1)[1]
        lip_rgb, lip_alpha = _read_rgba(os.path.join(ASSETS_LIPS, f"lip_{name}.png"))
        lip_lab = measure_lip_lab(lip_rgb, lip_alpha).tolist()
        src_label = f"プリセット個別: {name}"
        credit = None
    else:
        lip_rgb, lip_alpha = _dummy_lip(preset_for_dummy)
        lip_lab = list(km.LIP_PRESETS[preset_for_dummy])  # ダミーの描画色=下地
        src_label = f"ダミー({preset_for_dummy})"
        credit = None

    with st.sidebar:
        st.image(lip_rgb, caption=f"唇画像: {src_label}", use_container_width=True)
        st.markdown(
            "**下地 Lab(写真から実測)**" if photo_key
            else "**下地 Lab(プリセット)**", unsafe_allow_html=True)
        st.markdown(
            chip(lip_lab, f"L={lip_lab[0]:.1f} a={lip_lab[1]:.1f} b={lip_lab[2]:.1f}"),
            unsafe_allow_html=True)
        if credit:
            st.caption(credit)

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
        comp = composite_lip(lip_rgb, lip_alpha, appl, l_blend=l_blend)
        with cols[i % len(cols)]:
            st.image(comp, use_container_width=True)
            st.markdown(f"**{i+1}. {it['name']}**")
            st.caption(f"`{it['line_category']}` ΔE={it['delta_e']} / {it['id']}")
            st.markdown(chip(orig, "商品本来"), unsafe_allow_html=True)


if __name__ == "__main__":
    main()
