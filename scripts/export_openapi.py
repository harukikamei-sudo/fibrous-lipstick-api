"""OpenAPI スキーマを uvicorn 起動なしでダンプする(A5)。

`app.openapi()` を直接呼んで `openapi.json` を書き出す。color-capture 側の
`openapi-typescript` はこの JSON から `src/lib/apiTypes.gen.ts` を生成する
(手書き `apiTypes.ts` と models_v13.py の乖離リスクを断つため)。

使い方:
    python scripts/export_openapi.py [出力先]   # 既定: リポジトリ直下 openapi.json

uvicorn 起動は不要。app.openapi() はルート/pydantic モデル定義からスキーマを
組むだけで、重い遅延 import(extract_lab/estimate_s)はエンドポイント呼び出し
時にしか走らないため、ここでは読み込まれない(初回 import の scipy/skimage は
recommend_v2 経由で入るので cold-start は遅め=正常)。
"""

from __future__ import annotations

import json
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from app import app  # noqa: E402  FastAPI インスタンス(app.py)


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO_ROOT, "openapi.json")
    schema = app.openapi()
    # sort_keys で安定出力(再生成時の差分ノイズを抑え、型生成の決定性を担保)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(schema, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    paths = schema.get("paths", {})
    schemas = schema.get("components", {}).get("schemas", {})
    print(f"✅ OpenAPI {schema.get('openapi', '?')} → {out}")
    print(f"   {schema['info']['title']} v{schema['info']['version']}")
    print(f"   paths={len(paths)} / schemas={len(schemas)}")


if __name__ == "__main__":
    main()
