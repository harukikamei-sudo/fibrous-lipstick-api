"""塗り重ねスウォッチ画像の領域から Lab を抽出し、ライン散乱係数 S を校正する CLI。

用途: 「素肌(下地) / 1度塗り / 2度塗り」の 3 領域を画像から指定し、各領域の代表色
Lab を取り出して estimate_s_layered(3点フィット)に投げ、その仕上げタイプの単一
スカラー S を得る。LINE_S_PRESETS(km.py)を実測値で更新するための校正ツール。

「2度塗り=R∞」とは仮定せず、素肌+2つの厚みから K/S と S を同時推定するので、
シアーなティント(何度塗っても不透明にならない)でも筋の通った S が出る。

領域指定は 2 通り:
  (a) 座標モード : --substrate/--coat1/--coat2 を "X,Y,W,H"(左上座標+幅高さ)で
  (b) GUI モード : --gui でウィンドウ表示、ドラッグで矩形選択(tkinter, 追加依存なし)

座標決めの補助:
  --info            画像の W×H を表示して終了
  --preview OUT.png 指定した領域を画像に重ねた確認用 PNG を保存

例:
  python sample_lab.py swatch.png --info
  python sample_lab.py swatch.png --substrate 700,250,90,60 \
      --coat1 460,740,120,90 --coat2 500,360,120,90 --preview check.png
  python sample_lab.py swatch.png --gui

依存: numpy, pillow, scipy (+ GUI は標準の tkinter)。estimate_s/km/lab_utils を利用。
"""

import argparse
import sys
from io import BytesIO

import numpy as np
from PIL import Image

from lab_utils import rgb_to_lab
import km
from estimate_s import estimate_s_layered


# 3 領域の定義(順序が GUI の選択順・凡例色に対応)
REGIONS = [
    ("substrate", "素肌/下地", (60, 255, 60)),
    ("coat1",     "1度塗り",   (0, 200, 255)),
    ("coat2",     "2度塗り",   (255, 60, 60)),
]


# ============ 画像ロード ============

def load_image(path_or_url):
    """ローカルパス or http(s) URL から RGB の PIL Image を返す。"""
    if path_or_url.startswith(("http://", "https://")):
        import requests
        res = requests.get(path_or_url, timeout=30,
                           headers={"User-Agent": "sample_lab"})
        res.raise_for_status()
        return Image.open(BytesIO(res.content)).convert("RGB")
    return Image.open(path_or_url).convert("RGB")


# ============ 領域サンプリング ============

def parse_box(s):
    """'X,Y,W,H' → (x, y, w, h) の int タプル。"""
    parts = [int(round(float(v))) for v in s.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("領域は 'X,Y,W,H' の 4 値で指定")
    return tuple(parts)


def sample_region(img_arr, box):
    """領域(box=(x,y,w,h))の代表 RGB を中央値で返す(ハイライト/エッジに頑健)。

    Returns: (rgb_median: np.array shape (3,), n_pixels: int)
    """
    x, y, w, h = box
    H, W = img_arr.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"領域が画像外: box={box}, 画像={W}x{H}")
    patch = img_arr[y0:y1, x0:x1].reshape(-1, 3).astype(float)
    return np.median(patch, axis=0), patch.shape[0]


def describe(name, rgb):
    """領域の RGB / Lab を 1 行で整形し、Lab を返す。"""
    lab = rgb_to_lab(rgb)
    print(f"  {name:14s} RGB=({rgb[0]:5.1f},{rgb[1]:5.1f},{rgb[2]:5.1f})  "
          f"Lab=({lab[0]:6.2f},{lab[1]:6.2f},{lab[2]:6.2f})")
    return lab


# ============ プレビュー(領域の重ね描き) ============

def save_preview(pil_img, boxes, out_path):
    """boxes={name:(x,y,w,h)} を画像に矩形+ラベルで重ねて保存。"""
    from PIL import ImageDraw
    colors = {name: c for name, _, c in REGIONS}
    img = pil_img.copy()
    draw = ImageDraw.Draw(img)
    for name, box in boxes.items():
        if box is None:
            continue
        x, y, w, h = box
        c = colors.get(name, (255, 255, 0))
        draw.rectangle([x, y, x + w, y + h], outline=c, width=3)
        draw.text((x + 2, y + 2), name, fill=c)
    img.save(out_path)
    print(f"プレビュー保存: {out_path}")


# ============ GUI 領域選択(tkinter, 追加依存なし) ============

def select_regions_gui(pil_img):
    """ドラッグで 3 領域(素肌/1度/2度)を順に選ぶ。

    操作: 各領域をドラッグで矩形指定 → Enter で確定して次へ。
    戻り値は {name:(x,y,w,h)|None}。
    """
    try:
        import tkinter as tk
        from PIL import ImageTk
    except Exception as e:
        print(f"GUI を初期化できません({e})。座標モードを使ってください。",
              file=sys.stderr)
        sys.exit(2)

    W, H = pil_img.size
    scale = min(1.0, 1000.0 / max(W, H))   # 画面に収まるよう縮小表示
    disp = pil_img.resize((int(W * scale), int(H * scale)))
    regions = {name: None for name, _, _ in REGIONS}
    st = {"i": 0, "start": None, "rect": None, "cur": None}

    root = tk.Tk()
    root.title("領域選択: 素肌 → 1度塗り → 2度塗り")
    tkimg = ImageTk.PhotoImage(disp)
    cv = tk.Canvas(root, width=disp.width, height=disp.height, cursor="cross")
    cv.pack()
    cv.create_image(0, 0, anchor="nw", image=tkimg)
    lab = tk.Label(root, font=("", 14))
    lab.pack(fill="x")

    def refresh():
        if st["i"] < len(REGIONS):
            lab.config(text=f"[{st['i']+1}/{len(REGIONS)}] {REGIONS[st['i']][1]} を"
                            f"ドラッグ → Enter で次へ")
        else:
            lab.config(text="完了。ウィンドウを閉じてください(または q)")

    def on_press(e):
        st["start"] = (e.x, e.y)
        if st["rect"]:
            cv.delete(st["rect"])
        st["rect"] = cv.create_rectangle(e.x, e.y, e.x, e.y,
                                         outline="yellow", width=2)

    def on_drag(e):
        if st["start"]:
            cv.coords(st["rect"], st["start"][0], st["start"][1], e.x, e.y)

    def on_release(e):
        if not st["start"]:
            return
        x0, y0 = st["start"]
        bx, by = min(x0, e.x), min(y0, e.y)
        bw, bh = abs(e.x - x0), abs(e.y - y0)
        st["cur"] = (int(bx / scale), int(by / scale),
                     max(1, int(bw / scale)), max(1, int(bh / scale)))

    def commit(_e=None):
        if st["i"] >= len(REGIONS):
            return
        if st["cur"] is None:
            lab.config(text="領域が未選択です。ドラッグしてください")
            return
        regions[REGIONS[st["i"]][0]] = st["cur"]
        cv.itemconfig(st["rect"], outline="cyan")
        st["rect"] = st["start"] = st["cur"] = None
        st["i"] += 1
        refresh()
        if st["i"] >= len(REGIONS):
            root.after(400, root.destroy)

    cv.bind("<ButtonPress-1>", on_press)
    cv.bind("<B1-Motion>", on_drag)
    cv.bind("<ButtonRelease-1>", on_release)
    root.bind("<Return>", commit)
    root.bind("q", lambda e: root.destroy())
    refresh()
    root.mainloop()
    return regions


# ============ S 算出 + 検証出力 ============

def report(sub_lab, coat1_lab, coat2_lab, t1, coat_ratio, dr_min):
    """3 領域の Lab から K/S と単一スカラー S を 3 点フィットで算出し、検証表示。"""
    res = estimate_s_layered(sub_lab, coat1_lab, coat2_lab, t1=t1,
                             coat_ratio=coat_ratio, dr_min=dr_min)
    print(f"\n=== ライン S 推定(3点フィット t1={t1}, 2度=t1×{coat_ratio}, "
          f"dr_min={dr_min}) ===")
    print(f"  ch別 K/S  : {res['per_channel_ks']}")
    print(f"  ch別 S    : {res['per_channel_s']}")
    print(f"  フィット残差: {res['rmse']}  (rmse_max=0.02)")
    print(f"  採用ch    : {res['adopted']}  ({res['n_adopted']}/3)")
    print(f"  復元フル発色(R∞) Lab: {res['rinf_lab']}  ← '商品色'(漸近)")

    if res["s"] is None:
        print(f"  ⚠️ S: 算出不可 — {res['note']}")
        return

    mark = "⚠️ " if res["status"] != "ok" else ""
    print(f"  {mark}推定 S(単一スカラー) = {res['s']}   [{res['status']}] {res['note']}")
    print(f"  → LINE_S_PRESETS に入れるなら [{res['s']}]×3")

    # 検証: 素肌の上に S と 各ch K/S で塗り重ねて、R∞ へ寄るか確認
    s = res["s"]
    ks = np.array(res["per_channel_ks"], dtype=float)
    rinf = np.array(res["rinf_lab"], dtype=float)
    sub = np.asarray(sub_lab, dtype=float)
    dE = lambda p, q: float(np.sqrt(np.sum((np.asarray(p) - np.asarray(q)) ** 2)))
    print("  塗り重ね予測(素肌→フル発色へ寄るか):")
    print(f"    {'塗り':>6} {'t':>5}  {'applied Lab':>22}  ΔE(素肌) ΔE(R∞)")
    for coats in [0, 1, 2, 4, 8, 16]:
        t = coats * t1
        lab = km.compute_applied_lab(sub, ks, np.full(3, s), t)
        print(f"    {coats:>5}回 {t:>5.2f}  ({lab[0]:6.2f},{lab[1]:6.2f},{lab[2]:6.2f})"
              f"   {dE(lab, sub):6.1f}  {dE(lab, rinf):6.1f}")


def main():
    ap = argparse.ArgumentParser(description="塗り重ねスウォッチ → Lab → ライン S 校正")
    ap.add_argument("image", help="画像ファイルパス or http(s) URL")
    ap.add_argument("--substrate", type=parse_box, help="素肌/下地領域 X,Y,W,H")
    ap.add_argument("--coat1", type=parse_box, help="1度塗り領域 X,Y,W,H")
    ap.add_argument("--coat2", type=parse_box, help="2度塗り領域 X,Y,W,H")
    ap.add_argument("--t1", type=float, default=0.3, help="1度塗りの厚み t(規約固定, 既定 0.3)")
    ap.add_argument("--coat-ratio", type=float, default=2.0, help="2度塗りの厚み倍率(既定 2.0)")
    ap.add_argument("--dr-min", type=float, default=0.03, help="ch採用の反射率差しきい値(既定 0.03)")
    ap.add_argument("--gui", action="store_true", help="ドラッグで領域選択(tkinter)")
    ap.add_argument("--info", action="store_true", help="画像寸法を表示して終了")
    ap.add_argument("--preview", help="指定領域を重ねた確認 PNG の保存先")
    args = ap.parse_args()

    pil = load_image(args.image)
    W, H = pil.size
    if args.info:
        print(f"画像サイズ: {W} x {H} (W x H)")
        return

    if args.gui:
        r = select_regions_gui(pil)
        sub, coat1, coat2 = r["substrate"], r["coat1"], r["coat2"]
    else:
        sub, coat1, coat2 = args.substrate, args.coat1, args.coat2

    missing = [n for n, b in [("--substrate", sub), ("--coat1", coat1),
                              ("--coat2", coat2)] if b is None]
    if missing:
        ap.error(f"3 領域すべて必須です。不足: {', '.join(missing)}(または --gui)")

    boxes = {"substrate": sub, "coat1": coat1, "coat2": coat2}
    if args.preview:
        save_preview(pil, boxes, args.preview)

    arr = np.asarray(pil)
    print(f"画像: {args.image}  ({W}x{H})\n領域サンプル(中央値):")
    labs = {}
    for name, box in boxes.items():
        rgb, n = sample_region(arr, box)
        labs[name] = describe(f"{name}(n={n})", rgb)

    report(labs["substrate"], labs["coat1"], labs["coat2"],
           args.t1, args.coat_ratio, args.dr_min)


if __name__ == "__main__":
    main()
