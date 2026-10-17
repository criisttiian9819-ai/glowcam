/**
 * GlowCam — control de accesos (Google Apps Script vinculado a una hoja de cálculo).
 *
 * - Menú «GlowCam → Abrir panel»: crear chatters, activar/desactivar, cambiar clave,
 *   liberar ordenador y borrar.
 * - Aplicación web (doGet): la extensión comprueba aquí si una clave es válida.
 *
 * La hoja «Chatters» es la base de datos: solo el dueño de la hoja puede verla.
 */

var SHEET_NAME = 'Chatters';
var HEADERS = ['Usuario', 'Clave', 'Activo', 'Ordenador', 'Creado', 'Último uso', 'Notas'];
var COL = { user: 1, key: 2, active: 3, device: 4, created: 5, lastUse: 6, notes: 7 };
var KEY_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; // sin 0/O ni 1/I

// ------------------------------------------------------------------ menú y panel

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('GlowCam')
    .addItem('Abrir panel', 'openPanel')
    .addToUi();
}

function openPanel() {
  getSheet_();
  var html = HtmlService.createHtmlOutputFromFile('Panel').setTitle('GlowCam · Accesos');
  SpreadsheetApp.getUi().showSidebar(html);
}

function getSheet_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(SHEET_NAME);
  if (!sh) {
    sh = ss.insertSheet(SHEET_NAME, 0);
    sh.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS]).setFontWeight('bold')
      .setBackground('#ff5fa2').setFontColor('#141418');
    sh.setFrozenRows(1);
    sh.setColumnWidths(1, HEADERS.length, 150);
    sh.setColumnWidth(2, 190);
  }
  return sh;
}

function newKey_() {
  var parts = [];
  for (var p = 0; p < 3; p++) {
    var s = '';
    for (var i = 0; i < 4; i++) {
      s += KEY_ALPHABET.charAt(Math.floor(Math.random() * KEY_ALPHABET.length));
    }
    parts.push(s);
  }
  return 'GLOW-' + parts.join('-');
}

function rows_() {
  var sh = getSheet_();
  var last = sh.getLastRow();
  if (last < 2) return [];
  var data = sh.getRange(2, 1, last - 1, HEADERS.length).getValues();
  return data.map(function (r, i) {
    return {
      row: i + 2,
      user: String(r[0] || ''),
      key: String(r[1] || ''),
      active: r[2] === true || String(r[2]).toUpperCase() === 'TRUE' || String(r[2]).toUpperCase() === 'SÍ',
      device: String(r[3] || ''),
      created: r[4] ? new Date(r[4]).toISOString() : '',
      lastUse: r[5] ? new Date(r[5]).toISOString() : '',
      notes: String(r[6] || ''),
    };
  }).filter(function (u) { return u.user || u.key; });
}

function findByUser_(user) {
  var all = rows_();
  for (var i = 0; i < all.length; i++) if (all[i].user.toLowerCase() === String(user).toLowerCase()) return all[i];
  return null;
}

function findByKey_(key) {
  key = String(key || '').trim().toUpperCase();
  if (!key) return null;
  var all = rows_();
  for (var i = 0; i < all.length; i++) if (all[i].key.toUpperCase() === key) return all[i];
  return null;
}

// ------------------------------------------------------------------ acciones del panel

function listUsers() {
  return rows_().map(function (u) {
    return { user: u.user, key: u.key, active: u.active, hasDevice: !!u.device, created: u.created, lastUse: u.lastUse, notes: u.notes };
  });
}

function createUser(name, notes) {
  name = String(name || '').trim();
  if (!name) throw new Error('Escribe un nombre de usuario.');
  if (findByUser_(name)) throw new Error('Ya existe un chatter llamado «' + name + '».');
  var key = newKey_();
  while (findByKey_(key)) key = newKey_();
  getSheet_().appendRow([name, key, true, '', new Date(), '', String(notes || '')]);
  return { user: name, key: key };
}

function setActive(user, active) {
  var u = findByUser_(user);
  if (!u) throw new Error('No existe ese chatter.');
  getSheet_().getRange(u.row, COL.active).setValue(!!active);
  return listUsers();
}

function regenerateKey(user) {
  var u = findByUser_(user);
  if (!u) throw new Error('No existe ese chatter.');
  var key = newKey_();
  while (findByKey_(key)) key = newKey_();
  var sh = getSheet_();
  sh.getRange(u.row, COL.key).setValue(key);
  sh.getRange(u.row, COL.device).setValue(''); // la clave nueva se puede activar en cualquier ordenador
  return { user: u.user, key: key };
}

function resetDevice(user) {
  var u = findByUser_(user);
  if (!u) throw new Error('No existe ese chatter.');
  getSheet_().getRange(u.row, COL.device).setValue('');
  return listUsers();
}

function deleteUser(user) {
  var u = findByUser_(user);
  if (!u) throw new Error('No existe ese chatter.');
  getSheet_().deleteRow(u.row);
  return listUsers();
}

function getWebAppUrl() {
  try { return ScriptApp.getService().getUrl() || ''; } catch (e) { return ''; }
}

// ------------------------------------------------------------------ comprobación desde la extensión

function doGet(e) {
  var p = (e && e.parameter) || {};
  if (p.action !== 'check') {
    return json_({ ok: false, reason: 'bad_request' });
  }
  var lock = LockService.getScriptLock();
  try { lock.waitLock(5000); } catch (err) { /* seguimos sin bloqueo */ }
  try {
    return json_(check_(p.key, p.device));
  } finally {
    try { lock.releaseLock(); } catch (err) { /* nada */ }
  }
}

function check_(key, device) {
  key = String(key || '').trim().toUpperCase();
  device = String(device || '').trim().slice(0, 80);
  if (!/^GLOW-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$/.test(key)) return { ok: false, reason: 'invalid' };
  var u = findByKey_(key);
  if (!u) return { ok: false, reason: 'invalid' };
  if (!u.active) return { ok: false, reason: 'disabled' };
  var sh = getSheet_();
  if (!u.device && device) {
    sh.getRange(u.row, COL.device).setValue(device);
  } else if (u.device && device && u.device !== device) {
    return { ok: false, reason: 'device' };
  }
  // «Último uso»: como mucho una escritura cada 10 minutos
  var now = new Date();
  var prev = u.lastUse ? new Date(u.lastUse) : null;
  if (!prev || now - prev > 10 * 60 * 1000) sh.getRange(u.row, COL.lastUse).setValue(now);
  return { ok: true, user: u.user };
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
