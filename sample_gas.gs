/**
 * Fibrous Lipstick API を Google スプレッドシートから叩くサンプル。
 *
 * 使い方:
 *   1. スプレッドシートの拡張機能 → Apps Script でこの内容を貼り付け
 *   2. 保存して、シートに戻ると「Lipstick API」メニューが現れる
 *      (現れなければシートを一度リロード)
 *   3. products シートの構成: A列=id, F列=image_url, K列=L, L列=a, M列=b, X列=notes
 *      (列位置は CONFIG.COLS で変更可)
 *
 * 想定シート:
 *   - "products" シートの 1 行目はヘッダ、2 行目以降がデータ
 *   - F 列(image_url)が空の行はスキップ
 */

const CONFIG = {
  API_BASE: "https://tamable-fibrous-lipstick-api.hf.space",
  SHEET_NAME: "products",
  BATCH_SIZE: 50,          // API 側の上限と一致させる
  COLS: {
    id: 1,         // A
    image_url: 6,  // F
    L: 11,         // K
    a: 12,         // L
    b: 13,         // M
    status: 24,    // X (notes 列に上書きする想定。シートに合わせて変更)
  },
  HEADER_ROWS: 1,
};


/* ============ メニュー ============ */

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("Lipstick API")
    .addItem("ヘルスチェック", "healthCheck")
    .addItem("選択行の Lab を取得", "extractSelectedRow")
    .addItem("全行を一括取得(50件ずつ)", "batchExtractAll")
    .addToUi();
}


/* ============ 単発: 1 URL → Lab ============ */

/**
 * 画像 URL から Lab を抽出して [L, a, b, status, notes] を返す。
 * 失敗時は ["", "", "", "excluded", reason] を返す。
 */
function extractLabForRow(imageUrl) {
  if (!imageUrl) return ["", "", "", "excluded", "image_url 空"];

  const res = UrlFetchApp.fetch(CONFIG.API_BASE + "/extract_lab", {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify({ image_url: imageUrl }),
    muteHttpExceptions: true,
  });

  const code = res.getResponseCode();
  const body = res.getContentText();
  if (code !== 200) {
    return ["", "", "", "excluded", "HTTP " + code + ": " + body];
  }

  const data = JSON.parse(body);
  if (data.status === "excluded" || !data.lab) {
    return ["", "", "", data.status, data.notes];
  }
  return [data.lab.L, data.lab.a, data.lab.b, data.status, data.notes];
}


/* ============ メニュー: 選択行を 1 件だけ処理 ============ */

function extractSelectedRow() {
  const sh = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(CONFIG.SHEET_NAME);
  if (!sh) {
    SpreadsheetApp.getUi().alert("シート '" + CONFIG.SHEET_NAME + "' が見つかりません");
    return;
  }
  const row = sh.getActiveCell().getRow();
  if (row <= CONFIG.HEADER_ROWS) {
    SpreadsheetApp.getUi().alert("データ行を選択してください");
    return;
  }
  const url = sh.getRange(row, CONFIG.COLS.image_url).getValue();
  const [L, a, b, status, notes] = extractLabForRow(url);
  sh.getRange(row, CONFIG.COLS.L).setValue(L);
  sh.getRange(row, CONFIG.COLS.a).setValue(a);
  sh.getRange(row, CONFIG.COLS.b).setValue(b);
  sh.getRange(row, CONFIG.COLS.status).setValue(status + " | " + notes);
}


/* ============ バッチ: products シート全体を 50 件ずつ送る ============ */

function batchExtractAll() {
  const sh = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(CONFIG.SHEET_NAME);
  if (!sh) {
    SpreadsheetApp.getUi().alert("シート '" + CONFIG.SHEET_NAME + "' が見つかりません");
    return;
  }

  const lastRow = sh.getLastRow();
  if (lastRow <= CONFIG.HEADER_ROWS) {
    SpreadsheetApp.getUi().alert("データ行がありません");
    return;
  }

  // id と image_url を読む
  const rangeRows = lastRow - CONFIG.HEADER_ROWS;
  const ids = sh.getRange(CONFIG.HEADER_ROWS + 1, CONFIG.COLS.id, rangeRows, 1).getValues();
  const urls = sh.getRange(CONFIG.HEADER_ROWS + 1, CONFIG.COLS.image_url, rangeRows, 1).getValues();

  // 有効な行だけ抽出 (id と image_url 両方ある)
  const items = [];
  for (let i = 0; i < rangeRows; i++) {
    const id = ids[i][0];
    const url = urls[i][0];
    if (id && url) {
      items.push({ rowIndex: i, id: String(id), image_url: String(url) });
    }
  }

  if (items.length === 0) {
    SpreadsheetApp.getUi().alert("有効なデータ行がありません");
    return;
  }

  // 50 件ずつ分割して送信
  let processed = 0;
  let failed = 0;
  const total = items.length;
  for (let start = 0; start < total; start += CONFIG.BATCH_SIZE) {
    const chunk = items.slice(start, start + CONFIG.BATCH_SIZE);
    const products = chunk.map(it => ({ id: it.id, image_url: it.image_url }));

    const res = UrlFetchApp.fetch(CONFIG.API_BASE + "/extract_lab_batch", {
      method: "post",
      contentType: "application/json",
      payload: JSON.stringify({ products: products }),
      muteHttpExceptions: true,
    });

    if (res.getResponseCode() !== 200) {
      Logger.log("Batch " + start + " failed: HTTP " + res.getResponseCode() + " " + res.getContentText());
      failed += chunk.length;
      continue;
    }

    const data = JSON.parse(res.getContentText());
    // results は順序保証されている前提(同じ id 列を返す)
    const byId = {};
    data.results.forEach(r => { byId[r.id] = r; });

    chunk.forEach(it => {
      const r = byId[it.id];
      const sheetRow = CONFIG.HEADER_ROWS + 1 + it.rowIndex;
      if (!r) {
        sh.getRange(sheetRow, CONFIG.COLS.status).setValue("excluded | レスポンスなし");
        failed++;
        return;
      }
      if (r.lab) {
        sh.getRange(sheetRow, CONFIG.COLS.L).setValue(r.lab.L);
        sh.getRange(sheetRow, CONFIG.COLS.a).setValue(r.lab.a);
        sh.getRange(sheetRow, CONFIG.COLS.b).setValue(r.lab.b);
      } else {
        sh.getRange(sheetRow, CONFIG.COLS.L).setValue("");
        sh.getRange(sheetRow, CONFIG.COLS.a).setValue("");
        sh.getRange(sheetRow, CONFIG.COLS.b).setValue("");
      }
      sh.getRange(sheetRow, CONFIG.COLS.status).setValue(r.status + " | " + r.notes);
      processed++;
    });

    SpreadsheetApp.flush();
  }

  SpreadsheetApp.getUi().alert(
    "完了: " + processed + " 件成功 / " + failed + " 件失敗 / 合計 " + total + " 件"
  );
}


/* ============ デバッグ用 ============ */

function healthCheck() {
  const res = UrlFetchApp.fetch(CONFIG.API_BASE + "/health", { muteHttpExceptions: true });
  SpreadsheetApp.getUi().alert(
    "HTTP " + res.getResponseCode() + ": " + res.getContentText()
  );
}
