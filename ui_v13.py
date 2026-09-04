"""設計書 v1.3 ベイズループの可視化 Streamlit UI。

特徴:
    - ペア比較→ AR 試着→ いいね/微妙→ ベイズ更新→ TOP-N 再表示 の全フロー
    - 右側 Inspector パネルで「裏で動いてる API・数式・状態の推移」をリアルタイム表示
    - 数式 Live View(LaTeX)で「いま何が計算されたか」を式に値を埋めて表示
    - 学習進化グラフ(μ_thickness / σ² の推移)
    - 観測ログのタイムライン

起動: `.venv/bin/streamlit run ui_v13.py`
    → http://localhost:8501 を開く。API は内部で TestClient(同プロセス)で叩く。
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict

import numpy as np
import pandas as pd
import streamlit as st
from fastapi.testclient import TestClient
from PIL import Image

from app import app
from ui_app import (
    TEXTURE_BY_CATEGORY,
    composite_lip,
    extract_lip_mask,
    measure_lip_lab,
)

st.set_page_config(
    page_title="Fibrous Lipstick — v1.3 ベイズループ可視化",
    layout="wide",
)

# ============ API クライアント(裏側で叩いてログ取り) ============

if "_client" not in st.session_state:
    st.session_state._client = TestClient(app)


def api_call(method: str, path: str, **kwargs) -> Dict[str, Any]:
    """API を叩いて、所要時間+ペイロードを api_log に記録する。"""
    payload = kwargs.get("json")
    t0 = time.time()
    if method == "GET":
        r = st.session_state._client.get(path)
    else:
        r = st.session_state._client.post(path, **kwargs)
    elapsed_ms = (time.time() - t0) * 1000
    record = {
        "method": method,
        "path": path,
        "status": r.status_code,
        "elapsed_ms": round(elapsed_ms, 1),
        "request": payload,
        "response": r.json() if r.status_code == 200 else {"error": r.text},
        "ts": time.time(),
    }
    st.session_state.api_log.append(record)
    return record["response"]


def _lab_to_hex_approx(lab: Dict) -> str:
    """Lab → 近似 hex。チップ表示用。"""
    import numpy as np
    from skimage import color as skcolor
    arr = np.array([[[lab["L"], lab["a"], lab["b"]]]], dtype=np.float64)
    rgb = skcolor.lab2rgb(arr)[0, 0]
    rgb = (rgb * 255).clip(0, 255).astype(int)
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def _send_observation(pid: str, eff: Dict, thickness: float,
                       like: bool, item: Dict) -> None:
    """観測を /v13/update_user に流して UserState + 履歴を更新。"""
    src = "ar_view_like" if like else "ar_view_dislike"
    user_before = st.session_state.user
    obs = {
        "source": src,
        "product_id": pid,
        "observed_lab": eff,
        "thickness": thickness,
        "y": 1.0 if like else -1.0,
    }
    res = api_call("POST", "/v13/update_user", json={
        "user": user_before, "observations": [obs],
    })
    user_after = res["user"]

    st.session_state.obs_history.append({
        "ts": time.time(),
        "source": src,
        "product_id": pid,
        "product_name": item.get("name", ""),
        "thickness": thickness,
        "y": obs["y"],
    })
    st.session_state.mu_thickness_history.append(user_after["theta_thickness"]["mu"])
    st.session_state.sigma2_thickness_history.append(user_after["theta_thickness"]["var"])
    st.session_state.mu_color_L_history.append(user_after["theta_color"]["mu"]["L"])

    st.session_state.last_update_detail = {
        "n_applied": res["n_applied"],
        "before": {
            "mu_thickness": user_before["theta_thickness"]["mu"],
            "var_thickness": user_before["theta_thickness"]["var"],
            "mu_color_L": user_before["theta_color"]["mu"]["L"],
            "var_color_L": user_before["theta_color"]["var"]["L"],
        },
        "after": {
            "mu_thickness": user_after["theta_thickness"]["mu"],
            "var_thickness": user_after["theta_thickness"]["var"],
            "mu_color_L": user_after["theta_color"]["mu"]["L"],
            "var_color_L": user_after["theta_color"]["var"]["L"],
        },
        "obs": obs,
    }
    st.session_state.user = user_after
    rec = api_call("POST", "/v13/recommend", json={
        "user": user_after, "top_n": 5,
    })
    st.session_state.last_recommend = rec


# ============ Session State 初期化 ============

DEFAULTS = {
    "api_log": [],
    "step": "init",            # init → pair_compare → ar_loop
    "pairs": None,
    "pair_idx": 0,
    "choices": [],
    "user": None,
    "obs_history": [],         # 観測の時系列ログ
    "mu_thickness_history": [],
    "sigma2_thickness_history": [],
    "mu_color_L_history": [],
    "last_update_detail": None,  # 数式 LiveView 用
    "lip_lab": {"L": 62.0, "a": 22.0, "b": 12.0},
    "pc_season": "ブルベ夏",
    # 実写合成用
    "lip_image_rgb": None,     # np.ndarray (H, W, 3) uint8
    "lip_image_alpha": None,   # np.ndarray (H, W) float
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ============ Sidebar: ユーザー状態 + Inspector ============

with st.sidebar:
    st.header("👤 ユーザー状態")
    st.session_state.pc_season = st.selectbox(
        "PC season", ["イエベ春", "ブルベ夏", "イエベ秋", "ブルベ冬"],
        index=["イエベ春", "ブルベ夏", "イエベ秋", "ブルベ冬"].index(
            st.session_state.pc_season
        ),
    )
    c1, c2, c3 = st.columns(3)
    st.session_state.lip_lab["L"] = c1.number_input(
        "唇 L", 0.0, 100.0, st.session_state.lip_lab["L"], step=1.0
    )
    st.session_state.lip_lab["a"] = c2.number_input(
        "a", -50.0, 80.0, st.session_state.lip_lab["a"], step=1.0
    )
    st.session_state.lip_lab["b"] = c3.number_input(
        "b", -50.0, 80.0, st.session_state.lip_lab["b"], step=1.0
    )

    if st.button("🔄 全リセット"):
        for k in list(st.session_state.keys()):
            if k != "_client":
                del st.session_state[k]
        st.rerun()

    st.divider()
    # ---- 唇画像アップロード(任意。AR 試着で実写合成が見える) ----
    st.subheader("👄 唇画像(任意)")
    uploaded = st.file_uploader(
        "顔写真をアップロード", type=["png", "jpg", "jpeg", "webp"],
        help="アップロードすると AR 試着タブで実写合成が見える。"
             "唇 Lab も自動計測してサイドバーに反映",
    )
    if uploaded is not None:
        img = Image.open(uploaded).convert("RGB")
        # 高解像度はリサイズ(処理速度のため)
        max_side = 600
        if max(img.size) > max_side:
            ratio = max_side / max(img.size)
            img = img.resize((int(img.size[0] * ratio), int(img.size[1] * ratio)))
        rgb = np.asarray(img)
        alpha = extract_lip_mask(rgb)
        st.session_state.lip_image_rgb = rgb
        st.session_state.lip_image_alpha = alpha
        # 自動計測した Lab を反映
        measured = measure_lip_lab(rgb, alpha)
        if measured is not None:
            st.session_state.lip_lab = {
                "L": float(measured[0]),
                "a": float(measured[1]),
                "b": float(measured[2]),
            }
            st.success(
                f"唇 Lab を計測: L={measured[0]:.1f} "
                f"a={measured[1]:.1f} b={measured[2]:.1f}"
            )
        # 画像 + マスクのプレビュー
        st.image(rgb, caption="アップロード画像", use_container_width=True)
        # 唇 mask の輪郭が見えるオーバーレイ
        overlay = rgb.copy()
        mask_bool = alpha > 0.5
        overlay[mask_bool] = (
            overlay[mask_bool] * 0.6 + np.array([60, 255, 60]) * 0.4
        ).astype(np.uint8)
        st.image(overlay, caption="唇マスク(緑)", use_container_width=True)
    elif st.session_state.lip_image_rgb is not None:
        if st.button("📷 唇画像をクリア"):
            st.session_state.lip_image_rgb = None
            st.session_state.lip_image_alpha = None
            st.rerun()
        st.caption("唇画像セット済み(クリアでリセット)")

    st.divider()

    if st.session_state.user is not None:
        u = st.session_state.user
        st.subheader("📌 Current θ")
        st.markdown(
            f"**μ_color** L={u['theta_color']['mu']['L']:.2f} "
            f"a={u['theta_color']['mu']['a']:.2f} "
            f"b={u['theta_color']['mu']['b']:.2f}"
        )
        st.markdown(
            f"**σ²_color** L={u['theta_color']['var']['L']:.4f} "
            f"a={u['theta_color']['var']['a']:.4f} "
            f"b={u['theta_color']['var']['b']:.4f}"
        )
        st.markdown(
            f"**μ_thickness** = {u['theta_thickness']['mu']:.3f}  "
            f"(σ²={u['theta_thickness']['var']:.4f})"
        )
        st.markdown(
            f"**μ_explore** = {u['theta_explore']['mu']:.3f}  "
            f"(σ²={u['theta_explore']['var']:.4f})"
        )
        # θ_pref top-3 abs
        prefs = list(enumerate(u['theta_pref']['mu']))
        top3 = sorted(prefs, key=lambda x: -abs(x[1]))[:3]
        from catalog_x20 import AXIS_NAMES
        st.markdown("**θ_pref top-3 |μ|:**")
        for j, v in top3:
            st.markdown(f"  - `{AXIS_NAMES[j]}`: {v:+.3f}")

    st.divider()
    st.subheader("🔍 直前の API")
    if st.session_state.api_log:
        last = st.session_state.api_log[-1]
        st.markdown(
            f"**{last['method']} {last['path']}**  "
            f"`{last['status']}` ⏱ {last['elapsed_ms']}ms"
        )
        with st.expander("Payload"):
            st.json(last["request"] or {})
        with st.expander("Response"):
            st.json(last["response"])
    else:
        st.caption("まだ API は叩かれてない")


# ============ Main: ヘッダー ============

st.title("💄 Fibrous Lipstick — v1.3 ベイズループ可視化")
st.caption("Kawanoさん が AR で叩く想定の API を、Streamlit から GUI で疎通体験できる版")

tab_pair, tab_ar, tab_dash = st.tabs([
    "📋 ペア比較",
    "💄 AR 試着 + 学習",
    "📊 ダッシュボード(数式・状態推移)",
])


# ============ Tab 1: ペア比較 ============

with tab_pair:
    st.header("Part II: 強制ペア比較 10 問")
    if st.session_state.pairs is None:
        st.info("「ペアを取得して開始」を押すと、lip API に 10 ペアを要求します。")
        if st.button("📥 ペアを取得して開始"):
            res = api_call("GET", "/v13/pair_compare/init")
            st.session_state.pairs = res["pairs"]
            st.session_state.pair_idx = 0
            st.session_state.choices = []
            st.rerun()
    else:
        pairs = st.session_state.pairs
        idx = st.session_state.pair_idx
        n_total = len(pairs)
        if idx < n_total:
            p = pairs[idx]
            st.progress((idx) / n_total, text=f"{idx}/{n_total} 完了")
            st.subheader(f"Q{idx+1}: {p['pair_id']}  ({p['pair_type']})")
            col_l, col_r = st.columns(2)
            for side, col in [("left", col_l), ("right", col_r)]:
                item = p[side]
                with col:
                    if item.get("image_url"):
                        st.image(item["image_url"], use_container_width=True)
                    st.markdown(f"**{item['name']}**")
                    st.caption(
                        f"Lab=({item['lab']['L']:.1f}, "
                        f"{item['lab']['a']:.1f}, "
                        f"{item['lab']['b']:.1f})"
                    )
                    if st.button(f"これ! ({'←' if side=='left' else '→'})",
                                 key=f"choose_{p['pair_id']}_{side}",
                                 use_container_width=True):
                        st.session_state.choices.append({
                            "pair_id": p["pair_id"], "chose": side,
                        })
                        st.session_state.pair_idx += 1
                        st.rerun()
        else:
            st.success(f"✅ 全 {n_total} ペア完了!")
            st.markdown("選択結果:")
            df = pd.DataFrame(st.session_state.choices)
            st.dataframe(df, use_container_width=True)

            if st.session_state.user is None:
                if st.button("🚀 事前分布を構築して UserState を作る",
                             type="primary", use_container_width=True):
                    apply_res = api_call("POST", "/v13/pair_compare/apply", json={
                        "choices": st.session_state.choices,
                        "pc_season": st.session_state.pc_season,
                    })
                    st.session_state.user = {
                        "user_id": f"mina_{int(time.time())}",
                        "lip_lab": st.session_state.lip_lab,
                        "pc_season": st.session_state.pc_season,
                        "theta_color": apply_res["theta_color"],
                        "theta_pref": apply_res["theta_pref"],
                        "theta_explore": apply_res["theta_explore"],
                        "theta_thickness": apply_res["theta_thickness"],
                    }
                    # 履歴の最初の点
                    st.session_state.mu_thickness_history.append(
                        apply_res["theta_thickness"]["mu"]
                    )
                    st.session_state.sigma2_thickness_history.append(
                        apply_res["theta_thickness"]["var"]
                    )
                    st.session_state.mu_color_L_history.append(
                        apply_res["theta_color"]["mu"]["L"]
                    )
                    st.session_state.step = "ar_loop"
                    st.success("UserState を構築しました!「AR 試着」タブへ進んでください。")
                    st.rerun()
            else:
                st.info("UserState 構築済み。「AR 試着」タブへ。")


# ============ Tab 2: AR 試着 + 学習 ============

with tab_ar:
    st.header("Part V: AR 試着 + ベイズ更新ループ")
    if st.session_state.user is None:
        st.warning("先に「ペア比較」タブで事前分布を構築してください。")
    else:
        if st.button("🔄 TOP-5 を取得"):
            res = api_call("POST", "/v13/recommend", json={
                "user": st.session_state.user, "top_n": 5,
            })
            st.session_state.last_recommend = res

        if "last_recommend" in st.session_state:
            rec = st.session_state.last_recommend
            st.markdown(
                f"**μ_thickness = {rec['mu_thickness']:.3f}**  "
                f"β = {rec['beta_used']:.2f}"
            )
            has_lip_image = (
                st.session_state.lip_image_rgb is not None
                and st.session_state.lip_image_alpha is not None
            )
            for i, item in enumerate(rec["results"]):
                with st.container(border=True):
                    cols = st.columns([2, 3, 2])
                    eff = item["effective_lab"]
                    pid = item["product_id"]

                    if has_lip_image:
                        # ★ 実写合成: 唇画像に effective_lab を塗る
                        ts = TEXTURE_BY_CATEGORY.get(
                            item.get("line_category", "other"), 1.0
                        )
                        comp = composite_lip(
                            st.session_state.lip_image_rgb,
                            st.session_state.lip_image_alpha,
                            (eff["L"], eff["a"], eff["b"]),
                            texture_strength=ts,
                        )
                        cols[0].image(comp, use_container_width=True)
                    else:
                        # 色チップ(フォールバック)
                        hex_color = _lab_to_hex_approx(eff)
                        cols[0].markdown(
                            f"<div style='background:{hex_color};height:80px;"
                            f"border-radius:8px;border:1px solid #888'></div>",
                            unsafe_allow_html=True,
                        )

                    cols[0].markdown(f"**#{i+1}** {item['name']}")
                    cols[0].caption(f"{pid} · {item['line_category']}")
                    # 商品画像(small)
                    if item.get("image_url"):
                        cols[0].image(item["image_url"], width=120)

                    cols[1].markdown(
                        f"**effective_Lab** = ({eff['L']:.1f}, {eff['a']:.1f}, {eff['b']:.1f})"
                    )
                    cols[1].markdown(
                        f"**R_final** = `{item['r_final']:.2f}`  "
                        f"ΔE={item['delta_e_to_color']:.2f}  "
                        f"familiarity={item['familiarity']:.2f}"
                    )
                    thickness = cols[2].slider(
                        "塗り厚 t",
                        0.0, 1.0,
                        float(rec["mu_thickness"]),
                        0.05,
                        key=f"thick_{pid}",
                    )
                    b1, b2 = cols[2].columns(2)
                    if b1.button("👍 いいね", key=f"like_{pid}",
                                 use_container_width=True):
                        _send_observation(pid, eff, thickness, like=True, item=item)
                        st.rerun()
                    if b2.button("😐 微妙", key=f"dis_{pid}",
                                 use_container_width=True):
                        _send_observation(pid, eff, thickness, like=False, item=item)
                        st.rerun()


# ============ Tab 3: ダッシュボード ============

with tab_dash:
    st.header("📊 裏で起きてる数式 + 状態の推移")

    detail = st.session_state.last_update_detail

    # ---- 数式 LiveView ----
    st.subheader("📐 数式 LiveView(直前のベイズ更新)")
    if detail is None:
        st.info("AR 試着で「いいね/微妙」を押すと、ここに数式の現在値が出ます。")
    else:
        obs = detail["obs"]
        bef = detail["before"]
        aft = detail["after"]

        st.markdown("**観測:**")
        st.code(json.dumps(obs, ensure_ascii=False, indent=2), language="json")

        st.markdown("**設計書 §7.5 θ_thickness 更新式の値:**")
        st.latex(r"\sigma^2_N = \frac{1}{\frac{1}{\sigma^2_0} + \frac{N}{\sigma^2_{obs}}}")
        n_thick = detail["n_applied"]["theta_thickness"]
        if n_thick > 0:
            val = f"σ²_N = 1 / (1/{bef['var_thickness']:.4f} + {n_thick}/0.05)"
            calc = 1.0 / (1.0 / bef['var_thickness'] + n_thick / 0.05)
            st.code(
                f"σ²_thickness:\n"
                f"  事前 σ² = {bef['var_thickness']:.4f}\n"
                f"  観測数 N = {n_thick}, σ²_obs = 0.05\n"
                f"  σ²_N = 1/(1/{bef['var_thickness']:.4f} + {n_thick}/0.05) = {calc:.6f}\n"
                f"  → 実装出力: {aft['var_thickness']:.6f}  (一致確認)",
                language="text",
            )
            mu_calc = calc * (
                bef['mu_thickness'] / bef['var_thickness']
                + obs['thickness'] * n_thick / 0.05
            )
            st.code(
                f"μ_thickness:\n"
                f"  μ_N = σ²_N × (μ_0/σ²_0 + Σt_k/σ²_obs)\n"
                f"      = {calc:.6f} × ({bef['mu_thickness']:.3f}/{bef['var_thickness']:.4f} "
                f"+ {obs['thickness']:.2f}/0.05)\n"
                f"      ≈ {mu_calc:.4f}\n"
                f"  → 実装出力: {aft['mu_thickness']:.4f}",
                language="text",
            )

        n_color = detail["n_applied"]["theta_color"]
        if n_color > 0 and obs.get("observed_lab"):
            st.markdown("**設計書 §7.2 θ_color (L成分) 更新式の値:**")
            st.latex(r"\sigma^2_{N,j} = \frac{1}{\frac{1}{\sigma^2_{0,j}} + \frac{y^2}{\sigma^2_{obs}}}")
            σ_obs_ar = 1.0  # ar_view_like / dislike
            y = obs["y"]
            obs_L = obs["observed_lab"]["L"]
            sig_calc = 1.0 / (1.0 / bef['var_color_L'] + (y * y) / σ_obs_ar)
            mu_calc_c = sig_calc * (
                bef['mu_color_L'] / bef['var_color_L'] + (y * obs_L) / σ_obs_ar
            )
            st.code(
                f"σ²_color_L:\n"
                f"  σ²_N = 1/(1/{bef['var_color_L']:.4f} + {y*y}/1.0) = {sig_calc:.6f}\n"
                f"  → 実装: {aft['var_color_L']:.6f}\n"
                f"μ_color_L:\n"
                f"  μ_N = {sig_calc:.4f} × ({bef['mu_color_L']:.2f}/{bef['var_color_L']:.4f} "
                f"+ {y}×{obs_L:.2f}/1.0)\n"
                f"      ≈ {mu_calc_c:.4f}\n"
                f"  → 実装: {aft['mu_color_L']:.4f}",
                language="text",
            )

    st.divider()

    # ---- グラフ ----
    st.subheader("📈 学習の進化(観測数 vs 状態)")
    if st.session_state.mu_thickness_history:
        df_hist = pd.DataFrame({
            "step": list(range(len(st.session_state.mu_thickness_history))),
            "μ_thickness": st.session_state.mu_thickness_history,
            "σ²_thickness": st.session_state.sigma2_thickness_history,
            "μ_color_L": st.session_state.mu_color_L_history,
        })
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**μ_thickness の推移**")
            st.line_chart(df_hist.set_index("step")[["μ_thickness"]])
        with c2:
            st.markdown("**σ²_thickness の推移(縮むほど「確信」)**")
            st.line_chart(df_hist.set_index("step")[["σ²_thickness"]])
        st.markdown("**μ_color_L の推移**")
        st.line_chart(df_hist.set_index("step")[["μ_color_L"]])

    st.divider()

    # ---- 観測ログ ----
    st.subheader("📋 観測ログ(時系列)")
    if st.session_state.obs_history:
        df_obs = pd.DataFrame(st.session_state.obs_history)
        df_obs["ts"] = pd.to_datetime(df_obs["ts"], unit="s")
        st.dataframe(df_obs[::-1], use_container_width=True)
    else:
        st.caption("まだ観測なし")

    st.divider()

    # ---- API ログ全件 ----
    st.subheader("🌐 API 呼び出しログ(全件)")
    if st.session_state.api_log:
        df_api = pd.DataFrame([{
            "ts": pd.to_datetime(r["ts"], unit="s"),
            "method": r["method"],
            "path": r["path"],
            "status": r["status"],
            "elapsed_ms": r["elapsed_ms"],
        } for r in st.session_state.api_log])
        st.dataframe(df_api[::-1], use_container_width=True)

        with st.expander("📄 各リクエストの生 JSON を見る"):
            for i, r in enumerate(reversed(st.session_state.api_log)):
                st.markdown(f"**#{len(st.session_state.api_log)-i} {r['method']} {r['path']}**")
                cc1, cc2 = st.columns(2)
                with cc1:
                    st.caption("Request")
                    st.json(r["request"] or {})
                with cc2:
                    st.caption("Response")
                    st.json(r["response"])
                st.divider()
