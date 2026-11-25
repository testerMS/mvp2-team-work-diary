/**
 * 업무 다이어리 (MVP2 팀) 서버. 구글 시트를 팀 공용 데이터베이스로, 이 스크립트를 웹사이트로 쓴다.
 *
 *  - doPost : 팀원 각자의 PC에서 하루치 기록을 올리는 입구 (개인 업로드 열쇠 필요)
 *  - doGet  : 화면
 *  - api... : 화면이 부르는 기능 (개인 접속 코드로 로그인해야 동작)
 *
 * 권한: 팀장은 팀 전체를 본다. 팀원은 자기 기록만 본다(메뉴에서 '팀원끼리 보기'를 켜면 서로 본다).
 *       완료 표시와 메모는 본인만 바꾼다. 컨디션과 메모는 팀장에게도 보이지 않는다.
 * 주의: 이름이 _ 로 끝나지 않는 함수는 웹에서 누구나 부를 수 있다.
 *       그래서 기록을 돌려주는 함수는 모두 guarded_ 를 거치고, 열쇠·코드는 시트 메뉴에서만 보여 준다.
 */
const TABLES = {
  '팀원': ['팀원ID', '이름', '부서', '역할', '상태', '등록일'],
  '일지': ['날짜', '요일', '작성자', '핵심', '한 일', '할 일', '확인 필요', '수집', '받은 업무 메일', '본인 메일', '보낸 메일', '광고 제외', '업로드 시각', '팀원ID'],
  '업무기록': ['기록ID', '날짜', '구분', '내용', '요청자', '기한', '우선순위', '근거', '상태', '순번', '팀원ID', '이름'],
  '하루메모': ['날짜', '기분', '메모', '수정 시각', '팀원ID']
};
const KEY_COL = { '팀원': '팀원ID', '일지': '날짜', '업무기록': '날짜', '하루메모': '날짜' };
const KINDS = ['한 일', '공유', '할 일', '계획', '확인'];
const PRIORITIES = ['긴급', '높음', '보통'];
const MOODS = ['', '뿌듯', '맑음', '보통', '바쁨', '지침'];
const WEEK = '일월화수목금토';
const SESSION_SECONDS = 21600;   /* 6시간 */
const MAX_FAILS = 10;
const MAX_RESULTS = 500;

/* ------------------------------------------------------------ 시트 메뉴 */
function onOpen() {
  SpreadsheetApp.getUi().createMenu('업무 다이어리')
    .addItem('① 처음 설정 (표와 팀장 열쇠 만들기)', 'menuSetup')
    .addItem('② 팀원 추가', 'menuAddMember')
    .addSeparator()
    .addItem('열쇠·코드 다시 발급', 'menuReissue')
    .addItem('팀원끼리 보기 켜기/끄기', 'menuToggleOpen')
    .addToUi();
}

/* 메뉴 함수는 맨 먼저 getUi()를 부른다. 웹에서 부르면 여기서 오류가 나 아무것도 노출되지 않는다. */
function menuSetup() {
  const ui = SpreadsheetApp.getUi();
  const ss = prepare_();
  if (members_(ss).length) {
    ui.alert('표를 확인했습니다. 팀원이 이미 있어 열쇠는 새로 만들지 않았습니다.');
    return;
  }
  const name = ask_(ui, '처음 설정', '팀장(본인) 이름을 적어 주세요.');
  if (!name) return;
  const dept = ask_(ui, '처음 설정', '부서 이름을 적어 주세요. (비워도 됩니다)');
  if (dept === null) return;
  showKeys_(ui, addMember_(ss, name, dept, '팀장'));
}

function menuAddMember() {
  const ui = SpreadsheetApp.getUi();
  const ss = book_();
  const name = ask_(ui, '팀원 추가', '이름을 적어 주세요.');
  if (!name) return;
  const dept = ask_(ui, '팀원 추가', '부서 이름을 적어 주세요. (비워도 됩니다)');
  if (dept === null) return;
  const lead = ui.alert('팀원 추가', '팀장 권한(팀 전체 보기)을 줄까요?', ui.ButtonSet.YES_NO);
  showKeys_(ui, addMember_(ss, name, dept, lead === ui.Button.YES ? '팀장' : '팀원'));
}

function menuReissue() {
  const ui = SpreadsheetApp.getUi();
  const list = members_(book_());
  const id = ask_(ui, '열쇠·코드 다시 발급', '팀원ID를 적어 주세요. 예전 열쇠와 코드는 바로 못 쓰게 됩니다.\n\n' +
    list.map(function (m) { return m.id + '  ' + m.name; }).join('\n'));
  if (!id) return;
  const m = list.filter(function (x) { return x.id === id.toUpperCase(); })[0];
  if (!m) { ui.alert('그런 팀원ID가 없습니다.'); return; }
  showKeys_(ui, issue_(m));
}

function menuToggleOpen() {
  const ui = SpreadsheetApp.getUi();
  const on = props_().getProperty('TEAM_OPEN') === '1';
  const ans = ui.alert('팀원끼리 보기', on ? '지금 켜져 있습니다. 끄면 팀원은 자기 기록만 봅니다. 끌까요?' :
    '지금 꺼져 있습니다. 켜면 모든 팀원이 서로의 업무 기록과 팀 현황을 봅니다. (컨디션과 메모는 계속 본인만) 켤까요?', ui.ButtonSet.YES_NO);
  if (ans === ui.Button.YES) props_().setProperty('TEAM_OPEN', on ? '0' : '1');
}

function ask_(ui, title, text) {
  const res = ui.prompt(title, text, ui.ButtonSet.OK_CANCEL);
  return res.getSelectedButton() === ui.Button.OK ? String(res.getResponseText()).trim() : null;
}

function showKeys_(ui, k) {
  ui.alert(k.name + ' 님 열쇠 (지금 한 번만 보입니다)',
    '접속 코드 (웹 로그인)\n' + k.code + '\n\n업로드 열쇠 (agent 의 DIARY_TOKEN)\n' + k.token +
    '\n\n복사해서 본인에게만 전해 주세요. 잃어버리면 "열쇠·코드 다시 발급"을 쓰세요.', ui.ButtonSet.OK);
}

/* ------------------------------------------------------------ 팀원과 열쇠 */
/** 표를 만들거나, 혼자 쓰던 예전 표에 팀원 열을 덧붙인다. */
function prepare_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet(), p = props_();
  p.setProperty('SHEET_ID', ss.getId());
  Object.keys(TABLES).forEach(function (name) {
    const sh = table_(ss, name), head = TABLES[name], have = sh.getRange(1, 1, 1, head.length).getValues()[0];
    const missing = head.filter(function (h, i) { return have[i] !== h; });
    if (!missing.length) return;
    const start = head.length - missing.length;
    if (have.slice(0, start).join('|') !== head.slice(0, start).join('|')) throw new Error('"' + name + '" 시트의 첫 줄이 바뀌어 있습니다. 첫 줄을 되돌린 뒤 다시 실행해 주세요.');
    sh.getRange(1, start + 1, sh.getMaxRows(), missing.length).setNumberFormat('@');
    sh.getRange(1, start + 1, 1, missing.length).setValues([missing]).setFontWeight('bold').setBackground('#e8ebfa');
    const n = sh.getLastRow() - 1;
    if (n > 0) {
      /* 예전 기록의 주인은 첫 팀장(T01)이 된다. */
      const rows = [];
      for (let i = 0; i < n; i++) rows.push(missing.map(function (h) { return h === '팀원ID' ? 'T01' : ''; }));
      sh.getRange(2, start + 1, n, missing.length).setValues(rows);
    }
  });
  ['UPLOAD_TOKEN', 'VIEW_CODE'].forEach(function (k) { if (p.getProperty(k)) p.deleteProperty(k); });
  return ss;
}

function members_(ss) {
  return read_(ss, '팀원').map(function (r) {
    return { id: r['팀원ID'], name: r['이름'], dept: r['부서'], role: r['역할'] === '팀장' ? '팀장' : '팀원', active: r['상태'] !== '중지', joined: r['등록일'] };
  });
}

function addMember_(ss, name, dept, role) {
  name = String(name || '').trim(); dept = String(dept || '').trim();
  if (!name || name.length > 20 || dept.length > 30) throw new Error('이름은 20자, 부서는 30자까지 적을 수 있습니다.');
  return locked_(function () {
    const last = members_(ss).reduce(function (n, m) { return Math.max(n, Number(m.id.slice(1)) || 0); }, 0);
    const m = { id: 'T' + String(last + 1).padStart(2, '0'), name: name };
    append_(ss, '팀원', [{ '팀원ID': m.id, '이름': name, '부서': dept, '역할': role, '상태': '사용', '등록일': now_().slice(0, 10) }]);
    return issue_(m);
  });
}

/** 열쇠와 코드를 만든다. 서버에는 해시만 남기므로 다시 볼 수 없다. */
function issue_(m) {
  const code = m.id + '-' + randomKey_(10), token = m.id + '.' + randomKey_(40);
  props_().setProperty('KEY_' + m.id, JSON.stringify({ code: sha_(code), token: sha_(token) }));
  return { id: m.id, name: m.name, code: code, token: token };
}

/** 열쇠(또는 코드)의 주인을 찾는다. 없거나 사용 중지면 null. */
function owner_(ss, key, field) {
  const m = /^(T\d{2,4})[-.]/.exec(String(key || ''));
  const saved = m ? props_().getProperty('KEY_' + m[1]) : null;
  if (!saved || JSON.parse(saved)[field] !== sha_(String(key))) return null;
  return members_(ss).filter(function (x) { return x.id === m[1] && x.active; })[0] || null;
}

function sha_(text) {
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, text)
    .map(function (b) { return ((b + 256) % 256).toString(16).padStart(2, '0'); }).join('');
}

function props_() { return PropertiesService.getScriptProperties(); }

function randomKey_(len) {
  const abc = 'abcdefghjkmnpqrstuvwxyz23456789';   /* 헷갈리는 글자(0 o 1 l i)는 뺐다 */
  let out = '';
  while (out.length < len) {
    const hex = Utilities.getUuid().replace(/-/g, '');
    /* UUID의 고정 자리(13번째부터)를 피해 앞 12글자를 두 글자씩 쓴다 */
    for (let i = 0; i + 2 <= 12 && out.length < len; i += 2) {
      const n = parseInt(hex.substr(i, 2), 16);
      if (n < 248) out += abc[n % 31];             /* 248 = 31 x 8. 치우침이 없게 나머지는 버린다 */
    }
  }
  return out;
}

/* ------------------------------------------------------------ 시트 읽고 쓰기 */
function book_() {
  const id = props_().getProperty('SHEET_ID');
  if (!id) throw new Error('아직 설정하지 않았습니다. 시트 메뉴의 업무 다이어리 > ① 처음 설정을 실행하세요.');
  return SpreadsheetApp.openById(id);
}

function table_(ss, name) {
  let sh = ss.getSheetByName(name);
  const head = TABLES[name];
  if (!sh) sh = ss.insertSheet(name);
  if (sh.getLastRow() === 0) {
    /* 모두 글자로 저장한다. 날짜가 시간대에 따라 하루 밀리거나 내용이 수식으로 실행되지 않게 한다. */
    sh.getRange(1, 1, sh.getMaxRows(), head.length).setNumberFormat('@');
    sh.getRange(1, 1, 1, head.length).setValues([head]).setFontWeight('bold').setBackground('#e8ebfa');
    sh.setFrozenRows(1);
  }
  return sh;
}

function cellText_(v) {
  if (v instanceof Date) return Utilities.formatDate(v, 'Asia/Seoul', 'yyyy-MM-dd');
  const s = v === null || v === undefined ? '' : String(v);
  return /^'[=+\-@']/.test(s) ? s.slice(1) : s;
}

function safeCell_(v) {
  const s = String(v === null || v === undefined ? '' : v);
  return /^[=+\-@']/.test(s) ? "'" + s : s;   /* 수식 주입 방지 */
}

function read_(ss, name) {
  const sh = ss.getSheetByName(name);
  if (!sh || sh.getLastRow() < 2) return [];
  const head = TABLES[name];
  return sh.getRange(2, 1, sh.getLastRow() - 1, head.length).getValues().map(function (row, i) {
    const o = { _row: i + 2 };
    head.forEach(function (h, c) { o[h] = cellText_(row[c]); });
    return o;
  }).filter(function (o) { return o[KEY_COL[name]]; });
}

function append_(ss, name, rows) {
  if (!rows.length) return;
  const sh = table_(ss, name), head = TABLES[name];
  const start = sh.getLastRow() + 1, lack = start + rows.length - 1 - sh.getMaxRows();
  if (lack > 0) sh.insertRowsAfter(sh.getMaxRows(), lack);
  const range = sh.getRange(start, 1, rows.length, head.length);
  range.setNumberFormat('@');
  range.setValues(rows.map(function (r) { return head.map(function (h) { return safeCell_(r[h]); }); }));
}

function removeRows_(ss, name, rowNumbers) {
  if (!rowNumbers.length) return;
  const sh = ss.getSheetByName(name);
  /* 시트는 고정 줄만 남기고 모두 지울 수 없어, 마지막 남은 줄이면 빈 줄을 하나 덧댄다. */
  if (sh.getMaxRows() - rowNumbers.length < 2) sh.insertRowsAfter(sh.getMaxRows(), 1);
  const list = rowNumbers.slice().sort(function (a, b) { return b - a; });
  let i = 0;
  while (i < list.length) {              /* 이어진 줄은 한 번에, 아래에서 위로 지워 번호가 밀리지 않게 한다. */
    let j = i;
    while (j + 1 < list.length && list[j + 1] === list[j] - 1) j++;
    sh.deleteRows(list[j], j - i + 1);
    i = j + 1;
  }
}

/** 여러 팀원이 한꺼번에 올려도 한 사람씩 차례로 쓴다. 너무 오래 기다리면 BUSY 로 알려 다시 시도하게 한다. */
function locked_(work) {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(20000)) throw new Error('BUSY: 다른 팀원이 저장하는 중입니다. 잠시 뒤 다시 시도해 주세요.');
  try { return work(); } finally { lock.releaseLock(); }
}

function now_() { return Utilities.formatDate(new Date(), 'Asia/Seoul', 'yyyy-MM-dd HH:mm:ss'); }

function validDate_(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(s || ''));
  if (!m) return false;
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  return d.getUTCFullYear() === +m[1] && d.getUTCMonth() === +m[2] - 1 && d.getUTCDate() === +m[3];
}

function dayNo_(date) { return Math.round(Date.parse(date + 'T00:00:00Z') / 864e5); }
function dateOf_(no) { return new Date(no * 864e5).toISOString().slice(0, 10); }
function weekNo_(date) { return new Date(date + 'T00:00:00Z').getUTCDay(); }
function errText_(err) { return String(err && err.message || err); }

function hash_(text) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619); }
  return (h >>> 0).toString(16).padStart(8, '0');
}

/* ------------------------------------------------------------ 업로드 */
function doPost(e) {
  let out;
  try {
    const body = JSON.parse(e.postData.contents);
    const me = owner_(book_(), body.token, 'token');
    if (!me) throw new Error('업로드 열쇠가 맞지 않거나 사용이 중지되었습니다.');
    if (body.action === 'ping') out = { ok: true, message: me.name + ' 님으로 연결되었습니다.', name: me.name };
    else if (body.action === 'save') out = saveDay_(me, body);
    else throw new Error('알 수 없는 요청입니다.');
  } catch (err) {
    out = { ok: false, error: errText_(err) };
  }
  return ContentService.createTextOutput(JSON.stringify(out)).setMimeType(ContentService.MimeType.JSON);
}

/**
 * 하루치를 저장한다. 누구의 기록인지는 보낸 이름이 아니라 열쇠로 정해지므로 남의 이름으로 올릴 수 없다.
 * 같은 날짜를 다시 올리면 자기의 그 날만 바뀌고, 체크해 둔 완료 표시는 유지한다.
 */
function saveDay_(me, body) {
  const day = body.day || {}, items = body.items;
  if (!validDate_(day.date)) throw new Error('날짜 형식이 맞지 않습니다: ' + day.date);
  if (!Array.isArray(items) || items.length > 300) throw new Error('기록은 하루 300건까지 올릴 수 있습니다.');
  items.forEach(function (it, i) {
    if (KINDS.indexOf(it.kind) < 0) throw new Error((i + 1) + '번째 기록의 구분이 맞지 않습니다: ' + it.kind);
    if (!it.text || String(it.text).length > 2000) throw new Error((i + 1) + '번째 기록의 내용이 비었거나 너무 깁니다.');
    if (it.due && !validDate_(it.due)) throw new Error((i + 1) + '번째 기록의 기한이 맞지 않습니다: ' + it.due);
    if (it.priority && PRIORITIES.indexOf(it.priority) < 0) throw new Error((i + 1) + '번째 기록의 우선순위가 맞지 않습니다.');
  });
  return locked_(function () {
    const mine = function (r) { return r['날짜'] === day.date && r['팀원ID'] === me.id; };
    const ss = book_(), old = read_(ss, '업무기록').filter(mine), oldDays = read_(ss, '일지').filter(mine);
    const key = function (seen, kind, text, who) {           /* 같은 문장이 두 번 나오면 #2, #3 으로 구분한다 */
      const k = [kind, text, who || ''].join('|');
      seen[k] = (seen[k] || 0) + 1;
      return k + '#' + seen[k];
    };
    const done = {}, seenOld = {}, seenNew = {};
    old.forEach(function (r) { const k = key(seenOld, r['구분'], r['내용'], r['요청자']); if (r['상태'] === '완료') done[k] = true; });
    const rows = items.map(function (it, i) {
      const k = key(seenNew, it.kind, String(it.text), String(it.who || ''));
      return {
        '기록ID': [me.id, day.date.replace(/-/g, ''), hash_(k)].join('-'), '날짜': day.date, '구분': it.kind, '내용': it.text,
        '요청자': it.who || '', '기한': it.due || '', '우선순위': it.priority || '', '근거': it.refs || '',
        '상태': it.kind === '할 일' ? (done[k] ? '완료' : '미완료') : '', '순번': i + 1, '팀원ID': me.id, '이름': me.name
      };
    });
    const s = day.stats || {}, count = function (k) { return items.filter(function (i) { return i.kind === k; }).length; };
    /* 새 줄을 먼저 쓰고 옛 줄을 지운다. 중간에 끊겨도 기록이 사라지지 않는다. */
    append_(ss, '업무기록', rows);
    append_(ss, '일지', [{
      '날짜': day.date, '요일': WEEK[weekNo_(day.date)], '작성자': me.name, '핵심': (day.core || []).join('\n'),
      '한 일': count('한 일'), '할 일': count('할 일'), '확인 필요': count('확인'), '수집': s['수집'],
      '받은 업무 메일': s['받은 업무 메일'], '본인 메일': s['본인 메일'], '보낸 메일': s['보낸 메일'], '광고 제외': s['광고 제외'],
      '업로드 시각': now_(), '팀원ID': me.id
    }]);
    removeRows_(ss, '업무기록', old.map(function (r) { return r._row; }));
    removeRows_(ss, '일지', oldDays.map(function (r) { return r._row; }));
    SpreadsheetApp.flush();
    return { ok: true, date: day.date, name: me.name, saved: rows.length, replaced: old.length };
  });
}

/* ------------------------------------------------------------ 로그인과 권한 */
function doGet() {
  return HtmlService.createHtmlOutputFromFile('Index')
    .setTitle('업무 다이어리')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1')
    /* 구글 사이트 도구, 노션에 끼워 넣을 수 있게 한다. */
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function apiLogin(code) {
  try {
    const ss = book_(), cache = CacheService.getScriptCache();
    code = String(code || '').trim();
    const id = (/^(T\d{2,4})-/.exec(code) || [])[1] || '';
    return locked_(function () {
      /* 잠금은 사람마다 따로 센다. 한 사람이 틀려도 다른 팀원은 들어올 수 있다. */
      const known = id && props_().getProperty('KEY_' + id), fails = known ? Number(cache.get('f:' + id) || 0) : 0;
      if (fails >= MAX_FAILS) return { ok: false, error: '여러 번 틀려 잠시 잠겼습니다. 10분 뒤에 다시 시도해 주세요.' };
      const me = owner_(ss, code, 'code');
      if (!me) {
        if (known) cache.put('f:' + id, String(fails + 1), 600);
        return { ok: false, error: '접속 코드가 맞지 않습니다.' };
      }
      cache.remove('f:' + id);
      const session = Utilities.getUuid();
      cache.put('s:' + session, me.id + '|' + sha_(code), SESSION_SECONDS);   /* 코드를 다시 발급하면 예전 로그인은 풀린다 */
      return { ok: true, session: session };
    });
  } catch (err) {
    return { ok: false, error: errText_(err) };
  }
}

function apiLogout(session) {
  CacheService.getScriptCache().remove('s:' + String(session || ''));
  return { ok: true };
}

/** 로그인한 사람을 확인하고 work(사람, 시트)를 실행한다. 사람에는 볼 수 있는 팀원 목록(see)이 들어 있다. */
function guarded_(session, work) {
  try {
    const seen = session ? CacheService.getScriptCache().get('s:' + String(session)) : null;
    const part = String(seen || '').split('|'), saved = seen ? props_().getProperty('KEY_' + part[0]) : null;
    const ss = saved && JSON.parse(saved).code === part[1] ? book_() : null;
    const all = ss ? members_(ss) : [], me = all.filter(function (m) { return m.id === part[0] && m.active; })[0];
    if (!me) return { ok: false, code: 'AUTH', error: '다시 로그인해 주세요.' };
    me.team = me.role === '팀장' || props_().getProperty('TEAM_OPEN') === '1';
    me.see = me.team ? all : [me];
    const out = work(me, ss);
    out.ok = true;
    return out;
  } catch (err) {
    return { ok: false, error: errText_(err) };
  }
}

function canSee_(me, id) { return me.see.some(function (m) { return m.id === id; }); }

/** 볼 수 있는 팀원만 남긴다. ids 가 비면 볼 수 있는 모두. */
function scope_(me, ids) {
  const want = Array.isArray(ids) ? ids.map(String) : [], ok = {};
  want.forEach(function (id) { if (!canSee_(me, id)) throw new Error('볼 수 없는 팀원의 기록입니다.'); });
  me.see.forEach(function (m) { if (!want.length || want.indexOf(m.id) >= 0) ok[m.id] = m.name; });
  return ok;
}

function apiMe(session) {
  return guarded_(session, function (me) {
    const pick = function (m) { return { id: m.id, name: m.name, dept: m.dept, role: m.role, active: m.active }; };
    return { me: pick(me), team: me.team, members: me.see.map(pick) };
  });
}

/* ------------------------------------------------------------ 조회 */
function itemOut_(r) {
  return { id: r['기록ID'], date: r['날짜'], kind: r['구분'], text: r['내용'], who: r['요청자'], due: r['기한'],
    priority: r['우선순위'], refs: r['근거'], done: r['상태'] === '완료', order: Number(r['순번']) || 0, member: r['팀원ID'] };
}

function items_(ss, scope) {
  return read_(ss, '업무기록').map(itemOut_).filter(function (i) { return scope[i.member]; })
    .map(function (i) { i.name = scope[i.member]; return i; });
}

function byOrder_(a, b) {
  return a.date < b.date ? 1 : a.date > b.date ? -1 : a.member < b.member ? -1 : a.member > b.member ? 1 : a.order - b.order;
}

function extra_(id, date, kind, text, order, member, name) {
  return { id: id, date: date, kind: kind, text: text, who: '', due: '', priority: '', refs: '', done: false, order: order, member: member, name: name };
}

function isLate_(i, today) { return i.kind === '할 일' && !i.done && !!i.due && i.due < today; }

/** 한 사람의 하루와 달력. member 가 비면 본인, date 가 비면 가장 최근 기록. */
function apiOpen(session, member, date, month) {
  return guarded_(session, function (me, ss) {
    member = member || me.id;
    const scope = scope_(me, [member]), own = member === me.id;
    const of = function (r) { return r['팀원ID'] === member; };
    const days = read_(ss, '일지').filter(of), items = items_(ss, scope);
    const notes = own ? read_(ss, '하루메모').filter(of) : [];          /* 컨디션과 메모는 본인에게만 */
    const dates = days.concat(notes).map(function (d) { return d['날짜']; }).sort()
      .filter(function (d, i, a) { return i === 0 || a[i - 1] !== d; });
    if (!validDate_(date)) date = days.length ? days.map(function (d) { return d['날짜']; }).sort().pop() : now_().slice(0, 10);
    if (!/^\d{4}-\d{2}$/.test(month || '')) month = date.slice(0, 7);
    const cal = {}, stats = {};
    const at = function (d) { return cal[d] || (cal[d] = { count: 0, open: 0, mood: '' }); };
    days.forEach(function (d) { if (d['날짜'].slice(0, 7) === month) at(d['날짜']); });
    items.forEach(function (i) {
      if (i.date.slice(0, 7) !== month) return;
      at(i.date).count++;
      if (i.kind === '할 일' && !i.done) at(i.date).open++;
    });
    notes.forEach(function (n) { if (n['날짜'].slice(0, 7) === month) at(n['날짜']).mood = n['기분']; });
    const d = days.filter(function (x) { return x['날짜'] === date; })[0] || null;
    const n = notes.filter(function (x) { return x['날짜'] === date; })[0] || null;
    if (d) ['수집', '받은 업무 메일', '본인 메일', '보낸 메일', '광고 제외'].forEach(function (k) { stats[k] = Number(d[k]) || 0; });
    return {
      member: member, name: scope[member], own: own, date: date, month: month, calendar: cal, total: dates.length,
      prev: dates.filter(function (x) { return x < date; }).pop() || '',
      next: dates.filter(function (x) { return x > date; })[0] || '',
      day: d ? { core: d['핵심'] ? d['핵심'].split('\n') : [], stats: stats, uploaded: d['업로드 시각'] } : null,
      items: items.filter(function (i) { return i.date === date; }).sort(byOrder_),
      note: n ? { mood: n['기분'], text: n['메모'] } : { mood: '', text: '' }
    };
  });
}

/** 검색. q = { keyword, from, to, kinds[], status, members[], oldest }. 하루 검색은 from 과 to 를 같게 준다. */
function apiSearch(session, q) {
  return guarded_(session, function (me, ss) {
    q = q || {};
    if (q.from && !validDate_(q.from)) throw new Error('시작 날짜를 확인해 주세요.');
    if (q.to && !validDate_(q.to)) throw new Error('끝 날짜를 확인해 주세요.');
    if (q.from && q.to && q.from > q.to) throw new Error('시작 날짜가 끝 날짜보다 늦습니다.');
    const scope = scope_(me, q.members), words = String(q.keyword || '').toLowerCase().split(/\s+/).filter(String);
    const kinds = Array.isArray(q.kinds) ? q.kinds : [], days = {}, people = {}, today = now_().slice(0, 10);
    let rows = items_(ss, scope);
    read_(ss, '일지').forEach(function (d) {
      const m = d['팀원ID'];
      if (d['핵심'] && scope[m]) rows.push(extra_('core-' + m + d['날짜'], d['날짜'], '핵심', d['핵심'], -1, m, scope[m]));
    });
    if (scope[me.id]) read_(ss, '하루메모').forEach(function (n) {
      if (n['메모'] && n['팀원ID'] === me.id) rows.push(extra_('note-' + n['날짜'], n['날짜'], '메모', n['메모'], 999, me.id, me.name));
    });
    rows = rows.filter(function (r) {
      if (q.from && r.date < q.from) return false;
      if (q.to && r.date > q.to) return false;
      if (kinds.length && kinds.indexOf(r.kind) < 0) return false;
      if (q.status === 'open' && !(r.kind === '할 일' && !r.done)) return false;
      if (q.status === 'done' && !(r.kind === '할 일' && r.done)) return false;
      if (q.status === 'late' && !isLate_(r, today)) return false;
      if (q.status === 'urgent' && r.priority !== '긴급') return false;
      const hay = [r.text, r.who, r.kind, r.priority, r.due, r.name].join(' ').toLowerCase();
      return words.every(function (w) { return hay.indexOf(w) >= 0; });   /* 띄어 쓴 낱말은 모두 들어 있어야 한다 */
    }).sort(byOrder_);
    if (q.oldest) rows.sort(function (a, b) { return a.date < b.date ? -1 : a.date > b.date ? 1 : byOrder_(a, b); });
    rows.forEach(function (r) { days[r.date] = 1; people[r.member] = 1; });
    return { total: rows.length, days: Object.keys(days).length, people: Object.keys(people).length, rows: rows.slice(0, MAX_RESULTS) };
  });
}

function apiTodos(session, members) {
  return guarded_(session, function (me, ss) {
    return { rows: items_(ss, scope_(me, members)).filter(function (i) { return i.kind === '할 일'; }).sort(byOrder_) };
  });
}

/** 기간 동안의 팀 현황. 제출률의 분모는 (사용 중인 팀원) x (오늘까지의 평일, 등록일 이후)이다. */
function apiTeam(session, from, to) {
  return guarded_(session, function (me, ss) {
    if (!me.team) throw new Error('팀 현황은 팀장만 볼 수 있습니다.');
    if (!validDate_(from) || !validDate_(to) || from > to) throw new Error('기간을 확인해 주세요.');
    if (dayNo_(to) - dayNo_(from) > 92) throw new Error('팀 현황은 석 달까지 볼 수 있습니다.');
    const today = now_().slice(0, 10), scope = scope_(me, []), items = items_(ss, scope);
    const logs = read_(ss, '일지').filter(function (d) { return scope[d['팀원ID']]; });
    const span = dayNo_(to) - dayNo_(from) + 1;
    const now = period_(me.see, logs, items, from, to, today);
    const before = period_(me.see, logs, items, dateOf_(dayNo_(from) - span), dateOf_(dayNo_(from) - 1), today);
    const open = items.filter(function (i) { return i.kind === '할 일' && !i.done; });
    now.members.forEach(function (m) {
      const list = open.filter(function (i) { return i.member === m.id; });
      m.open = list.length;
      m.late = list.filter(function (i) { return isLate_(i, today); }).length;
      m.urgent = list.filter(function (i) { return i.priority === '긴급'; }).length;
    });
    const soon = dateOf_(dayNo_(today) + 1);
    const risks = open.filter(function (i) { return i.priority === '긴급' || (i.due && i.due <= soon); })
      .sort(function (a, b) { return (a.due || '9') < (b.due || '9') ? -1 : (a.due || '9') > (b.due || '9') ? 1 : 0; });
    return {
      from: from, to: to, today: today, days: now.days, members: now.members,
      total: { submitted: now.submitted, expected: now.expected, done: now.done, open: open.length,
        late: open.filter(function (i) { return isLate_(i, today); }).length, urgent: open.filter(function (i) { return i.priority === '긴급'; }).length },
      before: { submitted: before.submitted, expected: before.expected, done: before.done },
      risks: risks.slice(0, 30), riskTotal: risks.length
    };
  });
}

function period_(people, logs, items, from, to, today) {
  const days = [], cell = {}, sum = { submitted: 0, expected: 0, done: 0 };
  const inside = function (d) { return d >= from && d <= to; };
  logs.forEach(function (l) { if (inside(l['날짜'])) cell[l['팀원ID'] + l['날짜']] = { done: 0, todo: 0 }; });
  items.forEach(function (i) {
    const c = cell[i.member + i.date];
    if (!c) return;
    if (i.kind === '한 일') c.done++;
    if (i.kind === '할 일') c.todo++;
  });
  for (let n = dayNo_(from); n <= dayNo_(to); n++) {
    const d = dateOf_(n), w = weekNo_(d);
    /* 주말은 기록이 있는 날만 보인다 */
    if ((w > 0 && w < 6) || people.some(function (m) { return cell[m.id + d]; })) days.push(d);
  }
  const members = people.map(function (m) {
    const out = { id: m.id, name: m.name, dept: m.dept, role: m.role, active: m.active, joined: m.joined, cells: {}, submitted: 0, expected: 0, done: 0 };
    days.forEach(function (d) {
      const c = cell[m.id + d], w = weekNo_(d);
      if (c) { out.cells[d] = c; out.submitted++; out.done += c.done; }
      /* 아직 오지 않은 날, 등록 전, 주말은 내지 않은 것으로 세지 않는다. 오늘은 낸 사람만 센다. */
      if (c || (m.active && w > 0 && w < 6 && d < today && d >= m.joined)) out.expected++;
    });
    return out;
  }).filter(function (m) { return m.active || m.submitted; });
  members.forEach(function (m) { sum.submitted += m.submitted; sum.expected += m.expected; sum.done += m.done; });
  return { days: days, members: members, submitted: sum.submitted, expected: sum.expected, done: sum.done };
}

/* ------------------------------------------------------------ 고치기 (본인 것만) */
function apiSetDone(session, id, done) {
  return guarded_(session, function (me, ss) {
    return locked_(function () {
      const row = read_(ss, '업무기록').filter(function (r) { return r['기록ID'] === String(id) && r['구분'] === '할 일'; })[0];
      if (!row || !canSee_(me, row['팀원ID'])) throw new Error('할 일을 찾지 못했습니다.');
      if (row['팀원ID'] !== me.id) throw new Error('완료 표시는 본인만 바꿀 수 있습니다.');
      ss.getSheetByName('업무기록').getRange(row._row, TABLES['업무기록'].indexOf('상태') + 1).setValue(done ? '완료' : '미완료');
      return { id: row['기록ID'], done: !!done };
    });
  });
}

function apiSaveNote(session, date, mood, text) {
  return guarded_(session, function (me, ss) {
    if (!validDate_(date)) throw new Error('날짜를 확인해 주세요.');
    if (MOODS.indexOf(mood || '') < 0) throw new Error('컨디션 값을 확인해 주세요.');
    text = String(text || '').trim();
    if (text.length > 500) throw new Error('메모는 500자까지 적을 수 있습니다.');
    return locked_(function () {
      const old = read_(ss, '하루메모').filter(function (r) { return r['날짜'] === date && r['팀원ID'] === me.id; });
      if (mood || text) append_(ss, '하루메모', [{ '날짜': date, '기분': mood || '', '메모': text, '수정 시각': now_(), '팀원ID': me.id }]);
      removeRows_(ss, '하루메모', old.map(function (r) { return r._row; }));
      return { mood: mood || '', text: text };
    });
  });
}
