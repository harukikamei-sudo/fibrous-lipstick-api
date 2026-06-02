/**
 * Fibrous Lipstick — UserState 永続化 GAS Web App
 *
 * lipstick_DB スプレッドシートの users / observations シートを読み書きする。
 * Kawano の Next.js (userStateStore.ts) が fetch で叩く想定。
 *
 * ===== デプロイ手順 =====
 *  1. lipstick_DB スプレッドシートを開く → 拡張機能 → Apps Script
 *  2. このコードを貼り付けて保存
 *  3. デプロイ → 新しいデプロイ → 種類「ウェブアプリ」
 *     - 実行ユーザー: 自分
 *     - アクセスできるユーザー: 全員(認証なしで叩けるMVP想定)
 *  4. 発行された Web App URL を Kawano に渡す
 *     (.env.local の NEXT_PUBLIC_DB_GAS_URL に設定)
 *
 * ===== エンドポイント(GET/POST 両対応、action パラメータで分岐) =====
 *  GET  ?action=load&user_id=xxx          → UserState (無ければ null)
 *  POST {action:"save", user: UserState}  → {ok:true}
 *  POST {action:"observe", obs:{...}}     → {ok:true, obs_id:"..."}
 *
 * ===== UserState スキーマ(lip API の v1.3 と一致) =====
 *  { user_id, lip_lab:{L,a,b}, pc_season,
 *    theta_color:{mu:{L,a,b}, var:{L,a,b}},
 *    theta_pref:{mu:[20], var:[20]},
 *    theta_explore:{mu, var},
 *    theta_thickness:{mu, var} }
 */

// ============ 設定 ============

const SS = SpreadsheetApp.getActiveSpreadsheet();
const USERS_SHEET = "users";
const OBS_SHEET = "observations";
const USERS_DATA_START_ROW = 3; // 1=群ヘッダ, 2=列名, 3〜=データ
const OBS_DATA_START_ROW = 3;

// θ_pref 20軸の正準順序(DB users シートの mu_pref_* 列順)
const PREF_AXES = [
  "hue", "saturation", "brightness", "pigmentation",
  "glossy", "moisture_finish", "sheer", "velvet", "blur",
  "is_tint", "is_balm", "is_gloss",
  "moisturizing", "longlasting", "transfer_resistance",
  "girly", "makeup_intensity", "konare", "sweetness", "korean",
];

// users シートの列インデックス(1始まり)。DB_V13_COLUMNS.md の追加後を前提。
const U = {
  user_id: 1, created_at: 2, updated_at: 3, notes: 4,
  skin_L: 5, skin_a: 6, skin_b: 7,
  warmness: 8, pc_season: 9,
  mu_color_L: 10, mu_color_a: 11, mu_color_b: 12,
  sigma2_color_L: 13, sigma2_color_a: 14, sigma2_color_b: 15,
  mu_pref_start: 16,      // mu_pref_hue 〜 mu_pref_korean = 16..35
  sigma2_pref_start: 36,  // sigma2_pref_hue 〜 = 36..55
  mu_explore: 56, sigma2_explore: 57,
  // ★v1.3 追加列(DB_V13_COLUMNS.md §1)
  lip_L: 58, lip_a: 59, lip_b: 60,
  mu_thickness: 61, sigma2_thickness: 62,
};

// observations シートの列インデックス(v1.3 追加後)
const O = {
  obs_id: 1, user_id: 2, timestamp: 3, source: 4,
  product_id_a: 5, product_id_b: 6, chosen: 7,
  dialog_text: 8, action_type: 9, target_product: 10, notes: 11,
  // ★v1.3 追加列(DB_V13_COLUMNS.md §2)
  thickness: 12, observed_lab_L: 13, observed_lab_a: 14, observed_lab_b: 15,
  y: 16, viewed_seconds: 17,
};


// ============ ルーティング ============

function doGet(e) {
  e = e || {};
  return handle(e, e.parameter || {});
}

function doPost(e) {
  e = e || {};
  var body = {};
  try {
    body = JSON.parse(e.postData.contents);
  } catch (err) {
    return json({ ok: false, error: "invalid JSON body" });
  }
  return handle(e, body);
}

function handle(e, params) {
  var action = params.action;
  try {
    if (action === "load") return json(loadUser(params.user_id));
    if (action === "save") return json(saveUser(params.user));
    if (action === "observe") return json(saveObservation(params.obs));
    if (action === "health") return json({ ok: true, ts: new Date().toISOString() });
    return json({ ok: false, error: "unknown action: " + action });
  } catch (err) {
    return json({ ok: false, error: String(err) });
  }
}

function json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}


// ============ load: user_id → UserState ============

function loadUser(userId) {
  if (!userId) return null;
  var sh = SS.getSheetByName(USERS_SHEET);
  var lastRow = sh.getLastRow();
  if (lastRow < USERS_DATA_START_ROW) return null;

  var ids = sh.getRange(USERS_DATA_START_ROW, U.user_id, lastRow - USERS_DATA_START_ROW + 1, 1)
    .getValues();
  var rowIdx = -1;
  for (var i = 0; i < ids.length; i++) {
    if (String(ids[i][0]) === String(userId)) {
      rowIdx = USERS_DATA_START_ROW + i;
      break;
    }
  }
  if (rowIdx === -1) return null;

  var row = sh.getRange(rowIdx, 1, 1, U.sigma2_thickness).getValues()[0];
  var g = function (col) { return row[col - 1]; };

  var muPref = [];
  var sigPref = [];
  for (var k = 0; k < 20; k++) {
    muPref.push(Number(g(U.mu_pref_start + k)));
    sigPref.push(Number(g(U.sigma2_pref_start + k)));
  }

  return {
    user_id: g(U.user_id),
    lip_lab: { L: Number(g(U.lip_L)), a: Number(g(U.lip_a)), b: Number(g(U.lip_b)) },
    pc_season: g(U.pc_season) || null,
    theta_color: {
      mu: { L: Number(g(U.mu_color_L)), a: Number(g(U.mu_color_a)), b: Number(g(U.mu_color_b)) },
      var: { L: Number(g(U.sigma2_color_L)), a: Number(g(U.sigma2_color_a)), b: Number(g(U.sigma2_color_b)) },
    },
    theta_pref: { mu: muPref, var: sigPref },
    theta_explore: { mu: Number(g(U.mu_explore)), var: Number(g(U.sigma2_explore)) },
    theta_thickness: { mu: Number(g(U.mu_thickness)), var: Number(g(U.sigma2_thickness)) },
  };
}


// ============ save: UserState → 行を upsert ============

function saveUser(user) {
  if (!user || !user.user_id) return { ok: false, error: "user.user_id required" };
  var sh = SS.getSheetByName(USERS_SHEET);
  var lastRow = sh.getLastRow();
  var now = new Date().toISOString();

  // 既存行を探す
  var rowIdx = -1;
  if (lastRow >= USERS_DATA_START_ROW) {
    var ids = sh.getRange(USERS_DATA_START_ROW, U.user_id, lastRow - USERS_DATA_START_ROW + 1, 1)
      .getValues();
    for (var i = 0; i < ids.length; i++) {
      if (String(ids[i][0]) === String(user.user_id)) {
        rowIdx = USERS_DATA_START_ROW + i;
        break;
      }
    }
  }
  var isNew = rowIdx === -1;
  if (isNew) rowIdx = Math.max(lastRow + 1, USERS_DATA_START_ROW);

  // 1行ぶんの配列を作る(sigma2_thickness=62列まで)
  var row = new Array(U.sigma2_thickness).fill("");
  var set = function (col, val) { row[col - 1] = val; };

  set(U.user_id, user.user_id);
  set(U.created_at, isNew ? now : (sh.getRange(rowIdx, U.created_at).getValue() || now));
  set(U.updated_at, now);
  set(U.pc_season, user.pc_season || "");

  var lip = user.lip_lab || {};
  set(U.lip_L, num(lip.L)); set(U.lip_a, num(lip.a)); set(U.lip_b, num(lip.b));

  var tc = user.theta_color || { mu: {}, var: {} };
  set(U.mu_color_L, num(tc.mu.L)); set(U.mu_color_a, num(tc.mu.a)); set(U.mu_color_b, num(tc.mu.b));
  set(U.sigma2_color_L, num(tc.var.L)); set(U.sigma2_color_a, num(tc.var.a)); set(U.sigma2_color_b, num(tc.var.b));

  var tp = user.theta_pref || { mu: [], var: [] };
  for (var k = 0; k < 20; k++) {
    set(U.mu_pref_start + k, num(tp.mu[k]));
    set(U.sigma2_pref_start + k, num(tp.var[k]));
  }

  var te = user.theta_explore || {};
  set(U.mu_explore, num(te.mu)); set(U.sigma2_explore, num(te.var));

  var tt = user.theta_thickness || {};
  set(U.mu_thickness, num(tt.mu)); set(U.sigma2_thickness, num(tt.var));

  sh.getRange(rowIdx, 1, 1, row.length).setValues([row]);
  return { ok: true, user_id: user.user_id, row: rowIdx, created: isNew };
}


// ============ observe: 観測 1 件を追記 ============

function saveObservation(obs) {
  if (!obs || !obs.user_id) return { ok: false, error: "obs.user_id required" };
  var sh = SS.getSheetByName(OBS_SHEET);
  var lastRow = sh.getLastRow();
  var rowIdx = Math.max(lastRow + 1, OBS_DATA_START_ROW);
  var now = obs.timestamp || new Date().toISOString();
  var obsId = "obs_" + new Date().getTime() + "_" + Math.floor(Math.random() * 100000);

  var lab = obs.observed_lab || {};
  var row = new Array(O.viewed_seconds).fill("");
  var set = function (col, val) { row[col - 1] = val; };

  set(O.obs_id, obsId);
  set(O.user_id, obs.user_id);
  set(O.timestamp, now);
  set(O.source, obs.source || "");
  set(O.product_id_a, obs.product_id_a || obs.product_id || "");
  set(O.product_id_b, obs.product_id_b || "");
  set(O.chosen, obs.chosen || "");
  set(O.dialog_text, obs.dialog_text || "");
  set(O.action_type, obs.action_type || "");
  set(O.target_product, obs.target_product || "");
  set(O.notes, obs.notes || "");
  // v1.3 AR 観測
  if (obs.thickness !== undefined && obs.thickness !== null) set(O.thickness, num(obs.thickness));
  if (lab.L !== undefined) { set(O.observed_lab_L, num(lab.L)); set(O.observed_lab_a, num(lab.a)); set(O.observed_lab_b, num(lab.b)); }
  if (obs.y !== undefined && obs.y !== null) set(O.y, num(obs.y));
  if (obs.viewed_seconds !== undefined && obs.viewed_seconds !== null) set(O.viewed_seconds, num(obs.viewed_seconds));

  sh.getRange(rowIdx, 1, 1, row.length).setValues([row]);
  return { ok: true, obs_id: obsId, row: rowIdx };
}


// ============ ユーティリティ ============

function num(v) {
  if (v === undefined || v === null || v === "") return "";
  var n = Number(v);
  return isNaN(n) ? "" : n;
}


// ============ エディタからの動作確認用(「実行」ボタンで安全に試せる) ============
// ↑の doGet を直接「実行」すると e=undefined で落ちるので、代わりにこれらを使う。
// 関数を選んで「実行」→ 実行ログ(Ctrl+Enter)で結果を確認。

/** save → load の往復テスト。ダミーユーザーを書いて読み戻す。 */
function TEST_saveAndLoad() {
  var dummy = {
    user_id: "TEST_USER_001",
    lip_lab: { L: 62, a: 22, b: 12 },
    pc_season: "ブルベ夏",
    theta_color: { mu: { L: 50, a: 40, b: 20 }, var: { L: 1, a: 1, b: 1 } },
    theta_pref: { mu: new Array(20).fill(0.5), var: new Array(20).fill(1) },
    theta_explore: { mu: 0.5, var: 0.25 },
    theta_thickness: { mu: 0.5, var: 0.1 },
  };
  var saveRes = saveUser(dummy);
  Logger.log("save: " + JSON.stringify(saveRes));
  var loaded = loadUser("TEST_USER_001");
  Logger.log("load: " + JSON.stringify(loaded));
}

/** observe テスト。ダミー観測を1件追記する。 */
function TEST_observe() {
  var res = saveObservation({
    user_id: "TEST_USER_001",
    source: "ar_view_like",
    product_id: "rmd_blur_fudge_03",
    observed_lab: { L: 46, a: 42, b: 21 },
    thickness: 0.9,
    y: 1.0,
  });
  Logger.log("observe: " + JSON.stringify(res));
}

/** ヘルスチェック相当。 */
function TEST_health() {
  Logger.log(JSON.stringify(handle({}, { action: "health" }).getContent()));
}
