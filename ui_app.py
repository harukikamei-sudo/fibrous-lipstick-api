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
from scipy import ndimage as ndi
from skimage import color as skcolor

from lab_utils import lab_to_rgb
import km


DEFAULT_API = "https://tamable-fibrous-lipstick-api.hf.space"
ASSETS_LIPS = os.path.join(os.path.dirname(__file__), "assets", "lips")
BG = (245, 245, 245)   # 唇以外(非マスク)の表示背景
# model.png の出所(現在は Public Domain なので帰属義務は無いが透明性のため表示)
MODEL_CREDIT = '唇画像: "Mouth.jpg" (Wikimedia Commons, Public Domain)'

# 仕上げカテゴリ → 表示時の質感の強さ(テカリ/陰の偏差保持量)。
# matte は控えめに潰してマット感、gloss は強めに残してツヤ感を出す。
# 1.0 が「元写真の陰影そのまま」=ニュートラル。
TEXTURE_BY_CATEGORY = {
    "matte":  0.75,  # マット = 控えめだが潰しすぎない
    "velvet": 0.9,   # 半マット
    "tint":   1.0,   # 元の質感のまま
    "gloss":  1.5,   # グロス = テカリ強調
    "other":  1.0,   # 不明はニュートラル
}

# 塗り重ね回数 → 塗り厚 t (規約: 1度塗り = t1 = 0.3)
COAT_OPTIONS = {
    "1度塗り(薄)":      0.3,
    "2度塗り(普通)":    0.6,
    "3度塗り(しっかり)": 0.9,
    "塗り重ね(厚塗り)": 1.5,
}


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


def extract_lip_mask(rgb_uint8, central_bbox=(0.32, 0.68, 0.48, 0.66),
                     a_min=15, chroma_min=18, L_min=22, L_max=72,
                     erosion=1, dilation=0, sigma=1.8, band_half_pct=0.05):
    """RGB 画像から唇の羽化αマスク(0-1 float, HxW)を自動抽出。

    **唇の縦位置を自動検出**: 中央 bbox 内で a*×chroma が最大になる行を「唇中心」と
    みなし、その上下 band_half_pct × H の狭い帯だけをマスク検出領域にする。
    これで顔の縦位置がズレた写真でも顎影/鼻影を巻き込まない。
    """
    arr = rgb_uint8
    H, W = arr.shape[:2]
    lab = skcolor.rgb2lab(arr.astype(float) / 255.0)
    a = lab[..., 1]; b = lab[..., 2]
    chroma = np.hypot(a, b); L = lab[..., 0]
    x0, x1, y0, y1 = central_bbox
    yy, xx = np.mgrid[0:H, 0:W]

    # 段階1: 粗い中央 bbox 内で唇中心行を a*·chroma の行合計の argmax で検出
    rough_band = (xx > W * x0) & (xx < W * x1)
    rough_y = (yy > H * y0) & (yy < H * y1)
    score = np.where(rough_band & rough_y, np.clip(a, 0, None) * chroma, 0.0)
    row_score = score.sum(axis=1)
    lip_y = int(np.argmax(row_score))

    # 段階2: 唇中心 ± band_half_pct × H の狭い縦帯に検出領域を限定
    band_half = max(15, int(H * band_half_pct))
    y_top = max(int(H * y0), lip_y - band_half)
    y_bot = min(int(H * y1), lip_y + band_half)
    central = ((xx > W * x0) & (xx < W * x1)
               & (yy >= y_top) & (yy <= y_bot))
    m = (a > a_min) & (chroma > chroma_min) & (L > L_min) & (L < L_max) & central
    lbl, n = ndi.label(m)
    if n == 0:
        return np.zeros((H, W), dtype=float)
    sz = ndi.sum(np.ones_like(lbl), lbl, range(1, n + 1))
    m = lbl == (np.argmax(sz) + 1)
    m = ndi.binary_fill_holes(m)
    # 8連結(3x3 square)の構造要素+反復増で輪郭ギザギザを平滑化
    struct8 = ndi.generate_binary_structure(2, 2)
    m = ndi.binary_closing(m, structure=struct8, iterations=3)
    m = ndi.binary_opening(m, structure=struct8, iterations=2)
    if erosion > 0:
        m = ndi.binary_erosion(m, iterations=erosion)
    if dilation > 0:
        m = ndi.binary_dilation(m, iterations=dilation)
    alpha = np.clip(ndi.gaussian_filter(m.astype(float), sigma=sigma), 0, 1)
    return alpha


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


@st.dialog("塗布シミュレーション(拡大表示)", width="large")
def show_zoom_dialog(comp_img, lip_rgb_before, name, line_category, deltaE,
                     product_id, orig_lab, appl_lab,
                     pc_score=None, catalog_pc_tags=None):
    """TOP-N のカードをクリックした時の拡大モーダル。before/after 並べる。"""
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**素の唇 (Before)**")
        st.image(lip_rgb_before, use_container_width=True)
    with c2:
        st.markdown(f"**塗布後 (After)**")
        st.image(comp_img, use_container_width=True)
    st.markdown(f"### {name}")
    score_line = (f"PC スコア = **{pc_score}**(小さいほど合う)"
                  if pc_score is not None else f"ΔE = **{deltaE}**")
    st.markdown(f"カテゴリ `{line_category}` / {score_line} / id `{product_id}`")
    if catalog_pc_tags:
        st.caption(f"(参考)カタログ pc_season タグ: {', '.join(catalog_pc_tags)}  "
                   "← 推奨ロジックには未使用(答え合わせ用)")
    c3, c4 = st.columns(2)
    with c3:
        st.caption(f"商品本来 Lab = ({orig_lab[0]:.1f}, {orig_lab[1]:.1f}, {orig_lab[2]:.1f})")
        st.markdown(chip(orig_lab, ""), unsafe_allow_html=True)
    with c4:
        st.caption(f"塗布後 Lab  = ({appl_lab[0]:.1f}, {appl_lab[1]:.1f}, {appl_lab[2]:.1f})")
        st.markdown(chip(appl_lab, ""), unsafe_allow_html=True)


def composite_lip(rgb_uint8, alpha, applied_lab, texture_strength=1.0):
    """唇に applied_lab を塗る(顔/周辺はそのまま残す)。

    L の扱い: 唇マスク内の L 平均からの**偏差**(=ハイライト/陰のテカリ・凹凸成分)を
    保持したまま、平均だけ applied_lab.L にシフトする。
        L_new = L_applied + texture_strength × (L_orig - mean_in_lip(L_orig))
    texture_strength: 0=フラット(L_applied一色で凹凸消える)、1=元の質感そのまま、
                     >1=テカリ/陰を強調。
    a,b は applied_lab で置換。α で元画像と合成し、唇の縁を自然に馴染ませる。
    """
    base = rgb_uint8.astype(float) / 255.0
    lab = skcolor.rgb2lab(base)
    L_orig = lab[..., 0]
    mw = np.clip(alpha, 0.0, 1.0).astype(float)
    w_sum = float(mw.sum())
    L_mean = (L_orig * mw).sum() / w_sum if w_sum > 0 else float(L_orig.mean())
    L_app, a_app, b_app = (float(applied_lab[0]), float(applied_lab[1]),
                           float(applied_lab[2]))
    rec = lab.copy()
    rec[..., 0] = L_app + texture_strength * (L_orig - L_mean)
    rec[..., 1] = a_app
    rec[..., 2] = b_app
    rec_rgb = np.clip(skcolor.lab2rgb(rec), 0, 1)
    a3 = mw[..., None]
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

        # 唇画像のソース選択: アップロード優先 → 既定写真 → ダミー
        source_options = ["アップロード"]
        if photos: source_options.append("既定の写真")
        source_options.append("ダミー生成")
        source = st.radio("唇画像のソース", source_options, horizontal=True,
                          index=0 if photos else (len(source_options) - 1))

        uploaded = None; photo_key = None; preset_for_dummy = None
        if source == "アップロード":
            uploaded = st.file_uploader(
                "顔写真をアップロード(正面ポートレート推奨)",
                type=["jpg", "jpeg", "png", "webp"],
                help="中央下に唇が写った正面写真でうまく動きます。背景がシンプルだとなお良し。")
            if uploaded is None:
                st.caption("⬆️ ここに画像をドロップ。アップロードしない場合は他のソースを選択")
            mask_adj = st.slider(
                "マスク範囲 微調整 (締める ← 0 → 緩める)", -2, 2, 0, 1,
                help="塗布領域が小さすぎる/大きすぎる時に画像ごとに調整。0=既定")
        elif source == "既定の写真":
            keys = [k for k, _ in photos]
            labels = [lab for _, lab in photos]
            sel = st.selectbox("画像", labels, index=0)
            photo_key = keys[labels.index(sel)]
        else:
            preset_for_dummy = st.selectbox(
                "ダミー唇の色(プリセット)", list(km.LIP_PRESETS), index=1)

        coat_label = st.radio("塗り重ね", list(COAT_OPTIONS), index=1,
                              help="マット/ベルベットは1〜2度で十分発色、ティント/グロスは重ねるほど深まる")
        t = COAT_OPTIONS[coat_label]
        pc_sel = st.selectbox(
            "あなたのパーソナルカラー",
            ["(指定なし)"] + list(km.PC_SEASONS),
            help="指定すると論文ベースの理想Lab領域に近い順にランク付け(カタログタグは未使用)"
        )
        pc_season = None if pc_sel == "(指定なし)" else pc_sel
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
    if source == "アップロード":
        if uploaded is None:
            st.info("⬅️ サイドバーで顔写真をアップロードしてください。")
            return
        lip_rgb = np.asarray(Image.open(uploaded).convert("RGB"))
        # マスク調整スライダーで bbox/しきい値を画像ごとにチューニング
        # +adj=緩める(範囲広め)、-adj=締める(範囲狭め)
        adj = mask_adj
        # +adj=帯を厚く+しきい値緩める / -adj=帯を薄く+しきい値締める
        kwargs = {
            "central_bbox": (
                max(0.20, 0.32 - 0.02 * adj),   # 横方向のみ slider で伸縮
                min(0.80, 0.68 + 0.02 * adj),
                0.42,                            # 縦は広めに取り、内部で band 抽出
                0.72,
            ),
            "a_min": max(10, 15 - adj),
            "chroma_min": max(12, 18 - adj),
            "L_min": max(18, 22 - adj),
            "band_half_pct": max(0.025, 0.05 + 0.015 * adj),  # 帯の厚みを slider で
        }
        lip_alpha = extract_lip_mask(lip_rgb, **kwargs)
        if lip_alpha.sum() < 100:
            st.error("唇マスクを抽出できませんでした。スライダーを + 側に振るか、"
                     "正面・中央下に唇が写った写真を試してください。")
            return
        lip_lab = measure_lip_lab(lip_rgb, lip_alpha).tolist()
        src_label = f"アップロード ({uploaded.name}) / 調整={adj:+d}"
        credit = "⚠️ アップロード画像のライセンスは利用者が確認すること"
    elif photo_key == "model":
        lip_rgb, lip_alpha = _read_rgba(os.path.join(ASSETS_LIPS, "model.png"))
        lip_lab = measure_lip_lab(lip_rgb, lip_alpha).tolist()
        src_label = "既定モデル"
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
        # 唇マスクの輪郭を画面で確認できるようにオーバーレイ表示
        # (取りこぼし/はみ出しの診断用。アップロード時は特に重要)
        show_mask = st.checkbox("唇マスクの輪郭を確認", value=(source == "アップロード"),
                                help="塗布領域のフチを緑線で重ねる。塗り残しやはみ出しのチェック用")
        if show_mask:
            ov = lip_rgb.copy()
            mb = (lip_alpha > 0.5)
            edge = mb ^ ndi.binary_erosion(mb, iterations=2)
            ov[edge] = [0, 255, 0]
            st.image(ov, caption="マスク輪郭(緑線)", use_container_width=True)
        st.markdown(
            "**下地 Lab(写真から実測)**" if (source == "アップロード" or photo_key)
            else "**下地 Lab(プリセット)**", unsafe_allow_html=True)
        st.markdown(
            chip(lip_lab, f"L={lip_lab[0]:.1f} a={lip_lab[1]:.1f} b={lip_lab[2]:.1f}"),
            unsafe_allow_html=True)
        if credit:
            st.caption(credit)

    # レコメンド ボタンで API を叩き、結果を session_state に保存
    # (zoom ボタン等の再実行を跨いで保持。l_blend/t 変更時は再API呼び出し不要で
    #  画像だけ即時更新可能)
    if run:
        payload = {"lip_lab": {"L": lip_lab[0], "a": lip_lab[1], "b": lip_lab[2]},
                   "t": t, "top_n": top_n}
        if cat != "(指定なし)":
            payload["line_category"] = cat
        if target_lab is not None:
            payload["target_lab"] = {"L": target_lab[0], "a": target_lab[1],
                                     "b": target_lab[2]}
        if pc_season is not None:
            payload["pc_season"] = pc_season
        try:
            res = requests.post(f"{api_base}/recommend", json=payload, timeout=60)
            if res.status_code != 200:
                st.error(f"API エラー {res.status_code}: {res.text[:300]}")
                return
            st.session_state["recs"] = res.json()
            st.session_state["recs_target_used"] = target_lab is not None
            st.session_state["recs_pc_used"] = pc_season
        except requests.RequestException as e:
            st.error(f"API 呼び出し失敗: {e}")
            return

    if "recs" not in st.session_state:
        st.info("← サイドバーで条件を選んで「レコメンド」を押してください。")
        return

    data = st.session_state["recs"]
    method = data.get("filter_method", "")
    if method == "pc_season_target_region":
        sort_mode = f"PC「{data.get('pc_season')}」の理想Lab領域に近い順(論文ベース)"
    elif method == "delta_e_to_target":
        sort_mode = "目標色に近い順"
    else:
        sort_mode = "唇に近い(自然な)順"
    st.subheader(f"TOP {len(data['results'])}  (候補 {data['count']} 件中)")
    st.caption(f"並べ替え: {sort_mode} / {coat_label} / 質感はカテゴリで自動  "
               f"💡 各画像下の「🔍 拡大」で詳細表示")

    cols = st.columns(min(len(data["results"]), 5))
    for i, it in enumerate(data["results"]):
        appl = [it["applied_lab"]["L"], it["applied_lab"]["a"], it["applied_lab"]["b"]]
        orig = [it["original_lab"]["L"], it["original_lab"]["a"], it["original_lab"]["b"]]
        ts = TEXTURE_BY_CATEGORY.get(it["line_category"], 1.0)
        comp = composite_lip(lip_rgb, lip_alpha, appl, texture_strength=ts)
        with cols[i % len(cols)]:
            st.image(comp, use_container_width=True)
            st.markdown(f"**{i+1}. {it['name']}**")
            pc_part = (f" / PC={it['pc_score']}" if it.get("pc_score") is not None
                       else f" / ΔE={it['delta_e']}")
            st.caption(f"`{it['line_category']}`{pc_part} / {it['id']}")
            tags = it.get("catalog_pc_tags") or []
            if tags:
                st.caption(f"(参考)サイトタグ: {', '.join(tags)}")
            st.markdown(chip(orig, "商品本来"), unsafe_allow_html=True)
            if st.button("🔍 拡大", key=f"zoom_{i}", use_container_width=True):
                show_zoom_dialog(comp, lip_rgb, it["name"], it["line_category"],
                                 it["delta_e"], it["id"], orig, appl,
                                 pc_score=it.get("pc_score"),
                                 catalog_pc_tags=tags)


if __name__ == "__main__":
    main()
