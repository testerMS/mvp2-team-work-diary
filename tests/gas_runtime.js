/* 구글 Apps Script 의 시트·속성·캐시 기능을 흉내 내는 시험용 환경. Node 와 브라우저(체험판)에서 함께 쓴다. */
(function (root) {
  function makeGas(codeText, opt) {
    opt = opt || {};
    const clock = { now: opt.now || (() => Date.now()) };
    const log = [];
    function Sheet(name) { this.name = name; this.grid = []; this.fmt = {}; this.max = 1000; this.frozen = 0; }
    Sheet.prototype = {
      getLastRow() { let n = this.grid.length; while (n && !(this.grid[n - 1] || []).some(v => v !== '' && v !== undefined)) n--; return n; },
      getMaxRows() { return this.max; },
      insertRowsAfter(at, n) { if (at !== this.max) throw new Error('mock: insertRowsAfter'); this.max += n; },
      setFrozenRows(n) { this.frozen = n; },
      deleteRows(start, n) {
        if (start < 1 || start + n - 1 > this.max) throw new Error('범위를 벗어남');
        if (this.max - n <= this.frozen) throw new Error('고정되지 않은 행을 모두 삭제할 수 없습니다.');
        this.grid.splice(start - 1, n); this.max -= n;
      },
      getRange(r, c, h, w) {
        const sh = this; h = h || 1; w = w || 1;
        if (r < 1 || r + h - 1 > sh.max) throw new Error('범위를 벗어남: ' + r + '+' + h);
        const each = f => { for (let i = 0; i < h; i++) for (let j = 0; j < w; j++) f(r - 1 + i, c - 1 + j, i, j); };
        const store = (i, j, v) => {
          while (sh.grid.length <= i) sh.grid.push([]);
          v = v === null || v === undefined ? '' : v;
          const text = sh.fmt['*' + j] || sh.fmt[i + ',' + j];
          if (typeof v === 'string' && v[0] === "'") v = v.slice(1);
          else if (typeof v === 'string' && v[0] === '=') v = '#수식실행:' + v;
          else if (!text && typeof v === 'string' && /^\d{4}-\d\d-\d\d$/.test(v)) v = new Date(v + 'T00:00:00+09:00');
          sh.grid[i][j] = text && typeof v !== 'string' && !(v instanceof Date) ? String(v) : v;
        };
        return {
          setNumberFormat(f) { each((i, j) => { if (f === '@') { if (h >= 900) sh.fmt['*' + j] = true; else sh.fmt[i + ',' + j] = true; } }); return this; },
          setValues(v) { if (v.length !== h || v[0].length !== w) throw new Error('mock: 크기 다름'); each((i, j, a, b) => store(i, j, v[a][b])); return this; },
          setValue(v) { store(r - 1, c - 1, v); return this; },
          getValues() { const out = []; each((i, j, a, b) => { (out[a] = out[a] || [])[b] = sh.grid[i] && sh.grid[i][j] !== undefined ? sh.grid[i][j] : ''; }); return out; },
          setFontWeight() { return this; }, setBackground() { return this; }
        };
      }
    };
    const sheets = {}, props = {}, cache = {};
    const ss = { getId: () => 'SHEET', getSheetByName: n => sheets[n] || null, insertSheet: n => (sheets[n] = new Sheet(n)) };
    const pad = n => String(n).padStart(2, '0');
    const env = {
      SpreadsheetApp: { getActiveSpreadsheet: () => ss, openById: id => { if (id !== 'SHEET') throw new Error('no sheet'); return ss; }, flush() {},
        getUi() { if (!opt.ui) throw new Error('Cannot call SpreadsheetApp.getUi() from this context.'); return opt.ui; } },
      PropertiesService: { getScriptProperties: () => ({ getProperty: k => (k in props ? props[k] : null), setProperty: (k, v) => { props[k] = String(v); }, deleteProperty: k => { delete props[k]; } }) },
      CacheService: { getScriptCache: () => ({
        get: k => (cache[k] && cache[k].until > clock.now() ? cache[k].v : null),
        put: (k, v, sec) => { cache[k] = { v: String(v), until: clock.now() + sec * 1000 }; }, remove: k => { delete cache[k]; } }) },
      LockService: { getScriptLock: () => ({ tryLock() { if (opt.busy && opt.busy()) return false; log.push('lock'); return true; }, releaseLock() { log.push('unlock'); } }) },
      Utilities: {
        DigestAlgorithm: { SHA_256: 1 },
        computeDigest: (_, text) => {              /* Node 는 진짜 SHA-256, 체험판(브라우저)은 간단한 대용 */
          if (typeof require === 'function' && typeof module !== 'undefined') return [...require('crypto').createHash('sha256').update(text).digest()].map(b => (b > 127 ? b - 256 : b));
          const out = [];
          for (let k = 0; k < 32; k++) { let h = 2166136261 + k; for (const c of text) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } out.push(((h >>> 11) & 255) - 128); }
          return out;
        },
        getUuid: () => 'xxxxxxxx-xxxx-4xxx-8xxx-xxxxxxxxxxxx'.replace(/x/g, () => Math.floor(Math.random() * 16).toString(16)),
        formatDate(d, tz, f) {
          const k = new Date(d.getTime() + 9 * 3600e3), day = k.getUTCFullYear() + '-' + pad(k.getUTCMonth() + 1) + '-' + pad(k.getUTCDate());
          return f === 'yyyy-MM-dd' ? day : day + ' ' + pad(k.getUTCHours()) + ':' + pad(k.getUTCMinutes()) + ':' + pad(k.getUTCSeconds());
        } },
      ContentService: { MimeType: { JSON: 'json' }, createTextOutput: t => ({ text: t, setMimeType() { return this; } }) },
      HtmlService: { XFrameOptionsMode: { ALLOWALL: 1 }, createHtmlOutputFromFile: f => ({ file: f, setTitle() { return this; }, addMetaTag() { return this; }, setXFrameOptionsMode() { return this; } }) }
    };
    /* 시험에서 정한 '지금'을 new Date() 에도 쓴다 */
    if (opt.now) env.Date = class extends Date { constructor(...a) { a.length ? super(...a) : super(opt.now()); } };
    const names = Object.keys(env);
    const fns = [...codeText.matchAll(/^function (\w+)\(/gm)].map(m => m[1]);
    /* opt.factory: 문자열 실행이 막힌 곳(체험판)에서 쓰도록 미리 만들어 둔 함수 */
    const api = opt.factory ? opt.factory(env) : new Function(...names, codeText + '\nreturn {' + fns.join(',') + '};')(...names.map(n => env[n]));
    return { api, sheets, props, cache, log, clock, fns, setup() { api.prepare_(); } };
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = { makeGas }; else root.makeGas = makeGas;
})(typeof window !== 'undefined' ? window : globalThis);
