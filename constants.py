"""共有定数(循環 import 回避のための一元置き場)。

pair_compare / scene_priors / recommend_v2 が同じ θ_pref 事前分散 TAU2_PREF を
参照する。pair_compare ⇄ scene_priors は相互に必要(pair_compare が
scene_priors.build_pref_prior を呼び、scene_priors が TAU2_PREF を要る)ため、
定数だけここへ切り出して循環を断つ(A1)。
"""

from __future__ import annotations

# θ_pref の flat 事前分散(設計書 §11)。シーン事前はこの値を KAPPA 倍に縮める。
TAU2_PREF: float = 1.0
