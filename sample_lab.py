"""スウォッチ画像の領域から Lab を抽出し、ライン散乱係数 S を校正する CLI。

用途: 「薄づき / 濃い(フル発色) / 素肌(下地)」の 3 領域を画像から指定し、
各領域の代表色 Lab を取り出して estimate_s に投げ、仕上げタイプの S を得る。
LINE_S_PRESETS(km.py)を実測値で更新するための校正ツール。

領域指定は 2 通り:
  (a) 座標モード   : --thin/--full/--substrate を "X,Y,W,H"(左上座標+幅高さ)で
  (b) GUI モード   : --gui でウィンドウ表示、ドラッグで矩形選択(tkinter, 追加依存なし)

座標決めの補助:
  --info            画像の W×H を表示して終了
  --preview OUT.png 指定した領域を画像に重ねた確認用 PNG を保存

例:
  # 寸法確認
  python sample_lab.py swatch.jpg --info
  # 座標指定で S 算出
  python sample_lab.py swatch.jpg --thin 400,300,60,60 --full 200,300,60,60 \
      --substrate 600,50,60,60 --t-light 0.3
  # GUI で選択
  python sample_lab.py swatch.jpg --gui

依存: numpy, pillow (+ GUI モードは標準の tkinter)。estimate_s/km/lab_utils を利用。
"""

import argparse
import sys
from io import BytesIO

import numpy as np
from PIL import Image

from lab_utils import rgb_to_lab, lab_to_rgb
import km
from estimate_s import estimate_s_scalar


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
    """領域(box=(x,y,w,h))の代表 RGB を中央値で返す。

    中央値は鏡面ハイライトやエッジ画素に対して頑健。
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
    """領域の RGB / Lab を 1 行で整形。"""
    lab = rgb_to_lab(rgb)
    return (f"  {name:10s} RGB=({rgb[0]:5.1f},{rgb[1]:5.1f},{rgb[2]:5.1f})  "
            f"Lab=({lab[0]:6.2f},{lab[1]:6.2f},{lab[2]:6.2f})"), lab


# ============ プレビュー(領域の重ね描き) ============

def save_preview(pil_img, boxes, out_path):
    """boxes={name:(x,y,w,h)} を画像に矩形+ラベルで重ねて保存。"""
    from PIL import ImageDraw
    colors = {"thin": (0, 200, 255), "full": (255, 60, 60),
              "substrate": (60, 255, 60)}
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
    """ドラッグで 3 領域(thin/full/substrate)を選ぶ。

    操作: 各領域をドラッグで矩形指定 → Enter で確定して次へ。
          substrate は s でスキップ可。戻り値は {name:(x,y,w,h)|None}。
    """
    try:
        import tkinter as tk
        from PIL import ImageTk
    except Exception as e:
        print(f"GUI を初期化できません({e})。座標モード(--thin/--full/...)を使ってください。",
              file=sys.stderr)
        sys.exit(2)

    W, H = pil_img.size
    scale = min(1.0, 1000.0 / max(W, H))   # 画面に収まるよう縮小表示
    disp = pil_img.resize((int(W * scale), int(H * scale)))
    order = [("thin", "薄づき(light)"), ("full", "濃い/フル発色(full)"),
             ("substrate", "素肌/下地(substrate)")]
    regions = {name: None for name, _ in order}
    st = {"i": 0, "start": None, "rect": None, "cur": None}

    root = tk.Tk()
    root.title("領域選択")
    tkimg = ImageTk.PhotoImage(disp)
    cv = tk.Canvas(root, width=disp.width, height=disp.height, cursor="cross")
    cv.pack()
    cv.create_image(0, 0, anchor="nw", image=tkimg)
    lab = tk.Label(root, font=("", 14))
    lab.pack(fill="x")

    def refresh():
        if st["i"] < len(order):
            lab.config(text=f"[{st['i']+1}/{len(order)}] {order[st['i']][1]} を"
                            f"ドラッグ → Enter で次 / substrate は s でスキップ")
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
        x1, y1 = e.x, e.y
        bx, by = min(x0, x1), min(y0, y1)
        bw, bh = abs(x1 - x0), abs(y1 - y0)
        # 表示座標 → 元画像ピクセルへ逆変換
        st["cur"] = (int(bx / scale), int(by / scale),
                     max(1, int(bw / scale)), max(1, int(bh / scale)))

    def commit(_e=None):
        if st["i"] >= len(order):
            return
        if st["cur"] is None:
            lab.config(text="領域が未選択です。ドラッグしてください")
            return
        name = order[st["i"]][0]
        regions[name] = st["cur"]
        cv.itemconfig(st["rect"], outline="cyan")
        st["rect"] = None
        st["start"] = None
        st["cur"] = None
        st["i"] += 1
        refresh()
        if st["i"] >= len(order):
            root.after(400, root.destroy)

    def skip(_e=None):
        if st["i"] < len(order) and order[st["i"]][0] == "substrate":
            st["i"] += 1
            refresh()
            root.after(200, root.destroy)

    cv.bind("<ButtonPress-1>", on_press)
    cv.bind("<B1-Motion>", on_drag)
    cv.bind("<ButtonRelease-1>", on_release)
    root.bind("<Return>", commit)
    root.bind("s", skip)
    root.bind("q", lambda e: root.destroy())
    refresh()
    root.mainloop()
    return regions


# ============ S 算出 + 出力 ============

def report(full_lab, thin_lab, sub_lab, t_light, dr_min):
    """3 領域の Lab から K/S と単一スカラー S を算出して表示。"""
    ks = km.ks_from_lab(full_lab)
    print(f"\n商品 K/S(full から): {ks.round(3).tolist()}")

    if thin_lab is None:
        print("薄づき(thin)が無いため S は算出できません(full の Lab のみ)。")
        return

    res = estimate_s_scalar(full_lab, thin_lab, t_light=t_light,
                            substrate_lab=sub_lab, dr_min=dr_min)
    print(f"\n=== ライン S 推定 (t_light={t_light} 固定, dr_min={dr_min}, "
          f"{'素肌下地' if sub_lab is not None else '白基板仮定'}) ===")
    print(f"  ch別 S    : {res['per_channel_s']}")
    print(f"  ΔR(full-thin): {res['delta_r']}  (dr_min={dr_min} 未満は除外)")
    print(f"  物理整合   : {res['monotonic']}  (薄付きが素肌〜フルの間か)")
    print(f"  採用ch    : {res['adopted']}  ({res['n_adopted']}/3)")
    if res["s"] is None:
        print(f"  ⚠️ S: 算出不可 — {res['note']}")
    else:
        mark = "⚠️ " if res["status"] != "ok" else ""
        print(f"  {mark}推定 S(単一スカラー) = {res['s']}   [{res['status']}] {res['note']}")
        print(f"  → LINE_S_PRESETS に入れるなら [{res['s']}]×3")


def main():
    ap = argparse.ArgumentParser(description="スウォッチ画像 → Lab → ライン S 校正")
    ap.add_argument("image", help="画像ファイルパス or http(s) URL")
    ap.add_argument("--thin", type=parse_box, help="薄づき領域 X,Y,W,H")
    ap.add_argument("--full", type=parse_box, help="濃い/フル発色領域 X,Y,W,H")
    ap.add_argument("--substrate", type=parse_box, help="素肌/下地領域 X,Y,W,H")
    ap.add_argument("--t-light", type=float, default=0.3, help="薄づきの厚み t(規約固定値, 既定 0.3)")
    ap.add_argument("--dr-min", type=float, default=0.03,
                    help="チャネル採用の反射率差しきい値(既定 0.03)")
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
        regions = select_regions_gui(pil)
        thin, full, sub = regions["thin"], regions["full"], regions["substrate"]
    else:
        thin, full, sub = args.thin, args.full, args.substrate

    if full is None:
        ap.error("--full(濃い/フル発色領域)は必須です(または --gui で選択)")

    boxes = {"thin": thin, "full": full, "substrate": sub}
    if args.preview:
        save_preview(pil, boxes, args.preview)

    arr = np.asarray(pil)
    print(f"画像: {args.image}  ({W}x{H})\n領域サンプル(中央値):")
    full_rgb, n = sample_region(arr, full)
    line, full_lab = describe(f"full(n={n})", full_rgb)
    print(line)

    thin_lab = None
    if thin is not None:
        thin_rgb, n = sample_region(arr, thin)
        line, thin_lab = describe(f"thin(n={n})", thin_rgb)
        print(line)

    sub_lab = None
    if sub is not None:
        sub_rgb, n = sample_region(arr, sub)
        line, sub_lab = describe(f"substr(n={n})", sub_rgb)
        print(line)

    report(full_lab, thin_lab, sub_lab, args.t_light, args.dr_min)


if __name__ == "__main__":
    main()
