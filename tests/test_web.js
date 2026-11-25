/* 웹앱 서버(Code.gs) 자동 시험. 구글 계정 없이 실행된다.   실행: node --test tests/test_web.js */
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const { makeGas } = require('./gas_runtime.js');
const NOW = Date.UTC(2026, 10, 25, 1);   /* 한국시간 2026-11-25 10시 */
const CODE = fs.readFileSync(path.join(__dirname, '..', 'web', 'Code.gs'), 'utf8');

const day = (date, items, core) => ({ action: 'save', day: { date, author: '홍길동', core: core || ['핵심 한 줄'], stats: { '수집': 5, '광고 제외': 1 } }, items });
const todo = (text, due, priority, who) => ({ kind: '할 일', text, due: due || '', priority: priority || '보통', who: who || '본인', refs: '[M01]' });
const did = text => ({ kind: '한 일', text, refs: '[M02]' });

function ready(opt) {
  const g = makeGas(CODE, opt);
  g.setup();
  g.add = (name, role) => g.api.addMember_(g.api.book_(), name, '영업1팀', role || '팀원');
  g.lead = g.add('홍길동', '팀장');
  g.post = (body, who) => JSON.parse(g.api.doPost({ postData: { contents: JSON.stringify({ token: (who || g.lead).token, ...body }) } }).text);
  g.login = who => g.api.apiLogin(who.code).session;
  g.s = g.login(g.lead);
  return g;
}
function filled() {
  const g = ready();
  g.post(day('2026-10-30', [did('한빛정공 견적서 발송'), todo('계약서 초안 작성', '2026-11-03', '긴급')]));
  g.post(day('2026-11-23', [did('재고 조사 완료함'), todo('도면 수정본 송부', '2026-11-30', '보통', '박대리')]));
  g.post(day('2026-11-24', [did('한빛정공 견적서 재발송'), did('안전교육 이수함'), todo('납기 회신', '2026-11-24', '긴급', '대성오토'), todo('차량 점검 예약')]));
  return g;
}

test('처음 설정: 표 4개가 생기고, 팀원마다 다른 열쇠가 나오며 서버에는 해시만 남는다', () => {
  const g = ready(), m = g.add('김민지');
  assert.deepStrictEqual(Object.keys(g.sheets), ['팀원', '일지', '업무기록', '하루메모']);
  assert.match(g.lead.code, /^T01-[a-z2-9]{10}$/);
  assert.match(m.token, /^T02\.[a-z2-9]{40}$/);
  const all = JSON.stringify(g.props) + JSON.stringify(Object.values(g.sheets).map(s => s.grid));
  [g.lead.code, g.lead.token, m.code, m.token].forEach(x => assert.ok(!all.includes(x)));
  assert.throws(() => g.add(' '), /이름/);
});

test('업로드: 열쇠가 틀리거나 비면 거절, 맞으면 저장', () => {
  const g = ready();
  for (const token of ['wrong', '', undefined, null]) assert.strictEqual(g.post({ ...day('2026-11-24', [did('a')]), token }).ok, false);
  assert.strictEqual(g.sheets['업무기록'].getLastRow(), 1);
  assert.strictEqual(g.post({ action: 'ping' }).ok, true);
  assert.strictEqual(g.post(day('2026-11-24', [did('a')])).saved, 1);
  const raw = makeGas(CODE);   /* 설정 전에는 빈 열쇠로도 통과하지 못한다 */
  assert.strictEqual(JSON.parse(raw.api.doPost({ postData: { contents: '{"token":null,"action":"ping"}' } }).text).ok, false);
});

test('업로드: 잘못된 값은 아무것도 저장하지 않는다', () => {
  const g = ready();
  const bad = [day('2026-02-30', [did('a')]), day('24일', [did('a')]), day('2026-11-24', [{ kind: '해킹', text: 'a' }]), day('2026-11-24', [did('')]),
    day('2026-11-24', [todo('a', '내일')]), day('2026-11-24', [todo('a', '', '최우선')]), day('2026-11-24', 'x'), day('2026-11-24', Array(301).fill(did('a')))];
  bad.forEach(b => assert.strictEqual(g.post(b).ok, false));
  assert.strictEqual(g.sheets['업무기록'].getLastRow(), 1);
  assert.strictEqual(g.sheets['일지'].getLastRow(), 1);
});

test('같은 날짜를 다시 올리면 그 날만 바뀌고 완료 표시는 남는다', () => {
  const g = filled();
  const id = g.api.apiTodos(g.s).rows.find(r => r.text === '납기 회신').id;
  assert.strictEqual(g.api.apiSetDone(g.s, id, true).ok, true);
  const r = g.post(day('2026-11-24', [todo('납기 회신', '2026-11-24', '긴급', '대성오토'), did('새로 적은 일')]));
  assert.strictEqual(r.replaced, 4);
  const o = g.api.apiOpen(g.s, '', '2026-11-24');
  assert.deepStrictEqual(o.items.map(i => [i.text, i.done]), [['납기 회신', true], ['새로 적은 일', false]]);
  assert.strictEqual(g.api.apiOpen(g.s, '', '2026-11-23').items.length, 2);
  assert.strictEqual(g.sheets['일지'].getLastRow(), 4);
});

test('똑같은 할 일이 두 줄이어도 따로 체크된다', () => {
  const g = ready();
  g.post(day('2026-11-24', [todo('확인 전화'), todo('확인 전화')]));
  const ids = g.api.apiTodos(g.s).rows.map(r => r.id);
  assert.strictEqual(new Set(ids).size, 2);
  g.api.apiSetDone(g.s, ids[0], true);
  assert.deepStrictEqual(g.api.apiTodos(g.s).rows.map(r => r.done), [true, false]);
});

test('시트: 수식으로 실행되지 않고, 날짜와 원래 글자가 그대로 돌아온다', () => {
  const g = ready();
  const texts = ['=IMPORTXML("http://x")', '+82 확인', '-3% 조정', '@담당', "'따옴표"];
  g.post(day('2026-11-24', texts.map(did)));
  assert.ok(!JSON.stringify(g.sheets['업무기록'].grid).includes('#수식실행'));
  assert.deepStrictEqual(g.api.apiOpen(g.s, '', '2026-11-24').items.map(i => i.text), texts);
  g.sheets['업무기록'].grid[1][1] = new Date('2026-11-24T00:00:00+09:00');   /* 사람이 시트에서 고쳐 날짜 형식이 된 경우 */
  assert.strictEqual(g.api.apiOpen(g.s, '', '2026-11-24').items.length, 5);
});

test('검색: 키워드(여러 낱말은 모두 포함, 대소문자 무시, 요청자 포함)', () => {
  const g = filled(), find = keyword => g.api.apiSearch(g.s, { keyword }).rows.map(r => r.text);
  assert.deepStrictEqual(find('견적서'), ['한빛정공 견적서 재발송', '한빛정공 견적서 발송']);
  assert.deepStrictEqual(find('  견적서   재발송 '), ['한빛정공 견적서 재발송']);
  assert.deepStrictEqual(find('박대리'), ['도면 수정본 송부']);
  assert.deepStrictEqual(find('없는말'), []);
  assert.deepStrictEqual(find('.*'), []);
  g.post(day('2026-11-25', [did('ERP 점검')]));
  assert.deepStrictEqual(find('erp'), ['ERP 점검']);
});

test('검색: 하루, 기간(양 끝 포함), 한쪽만 있는 기간, 잘못된 기간', () => {
  const g = filled(), dates = q => [...new Set(g.api.apiSearch(g.s, q).rows.map(r => r.date))];
  assert.deepStrictEqual(dates({ from: '2026-11-23', to: '2026-11-23' }), ['2026-11-23']);
  assert.deepStrictEqual(dates({ from: '2026-11-23', to: '2026-11-24' }), ['2026-11-24', '2026-11-23']);
  assert.deepStrictEqual(dates({ from: '2026-11-24' }), ['2026-11-24']);
  assert.deepStrictEqual(dates({ to: '2026-10-31' }), ['2026-10-30']);
  assert.deepStrictEqual(dates({ oldest: true })[0], '2026-10-30');
  assert.match(g.api.apiSearch(g.s, { from: '2026-11-24', to: '2026-11-01' }).error, /늦습니다/);
  assert.strictEqual(g.api.apiSearch(g.s, { from: "x' OR 1" }).ok, false);
});

test('검색: 종류·상태를 키워드, 기간과 함께 건다. 핵심과 메모도 찾는다', () => {
  const g = filled();
  g.api.apiSaveNote(g.s, '2026-11-20', '맑음', '워크숍 장소가 좋았다');
  const find = q => g.api.apiSearch(g.s, q).rows.map(r => r.text);
  assert.deepStrictEqual(find({ status: 'urgent' }), ['납기 회신', '계약서 초안 작성']);
  assert.deepStrictEqual(find({ status: 'urgent', from: '2026-11-01' }), ['납기 회신']);
  assert.deepStrictEqual(find({ kinds: ['한 일'], keyword: '한빛', to: '2026-11-01' }), ['한빛정공 견적서 발송']);
  assert.deepStrictEqual(find({ kinds: ['메모'] }), ['워크숍 장소가 좋았다']);
  assert.strictEqual(find({ kinds: ['핵심'] }).length, 3);
});

test('로그인 없이는 어떤 조회·수정도 되지 않는다', () => {
  const g = filled();
  for (const s of ['', null, undefined, 'guess', '__proto__', 'T01|']) {
    for (const r of [g.api.apiOpen(s, ''), g.api.apiSearch(s, {}), g.api.apiTodos(s), g.api.apiSetDone(s, 'x', true), g.api.apiSaveNote(s, '2026-11-24', '', 'x'), g.api.apiMe(s), g.api.apiTeam(s, '2026-11-01', '2026-11-30')]) {
      assert.strictEqual(r.code, 'AUTH');
      assert.deepStrictEqual(Object.keys(r).sort(), ['code', 'error', 'ok']);
    }
  }
});

test('웹에서 부를 수 있는 함수는 정해진 것뿐이고, 메뉴 함수는 웹에서 열쇠를 내주지 않는다', () => {
  const g = ready();
  const open = g.fns.filter(f => !f.endsWith('_')).sort();
  assert.deepStrictEqual(open, ['apiLogin', 'apiLogout', 'apiMe', 'apiOpen', 'apiSaveNote', 'apiSearch', 'apiSetDone', 'apiTeam', 'apiTodos', 'doGet', 'doPost',
    'menuAddMember', 'menuReissue', 'menuSetup', 'menuToggleOpen', 'onOpen']);
  const before = { ...g.props };
  ['onOpen', 'menuSetup', 'menuAddMember', 'menuReissue', 'menuToggleOpen'].forEach(f => assert.throws(() => g.api[f](), /getUi/));
  assert.deepStrictEqual({ ...g.props }, before);
});

test('코드를 10번 틀리면 그 사람만 10분 잠긴다. 6시간 뒤와 재발급 뒤에는 다시 로그인', () => {
  let now = NOW;
  const g = ready({ now: () => now }), m = g.add('김민지');
  for (let i = 0; i < 10; i++) assert.match(g.api.apiLogin('T02-wrong').error, /맞지 않/);
  assert.match(g.api.apiLogin(m.code).error, /잠겼/);
  assert.strictEqual(g.api.apiLogin(g.lead.code).ok, true);
  for (let i = 0; i < 12; i++) assert.match(g.api.apiLogin('T99-x').error, /맞지 않/);
  now += 601e3;
  const s = g.login(m);
  assert.strictEqual(g.api.apiTodos(s).ok, true);
  const again = g.api.issue_({ id: 'T02', name: '김민지' });
  assert.strictEqual(g.api.apiTodos(s).code, 'AUTH');
  assert.strictEqual(g.api.apiLogin(m.code).ok, false);
  assert.strictEqual(g.post({ action: 'ping' }, m).ok, false);
  const s2 = g.login(again);
  now += 6 * 3600e3;
  assert.strictEqual(g.api.apiTodos(s2).code, 'AUTH');
});

test('달력: 건수, 남은 할 일, 기분, 이전·다음 기록, 다른 달 보기', () => {
  const g = filled();
  g.api.apiSaveNote(g.s, '2026-11-23', '뿌듯', '');
  const o = g.api.apiOpen(g.s, '', '');
  assert.deepStrictEqual([o.date, o.prev, o.next], ['2026-11-24', '2026-11-23', '']);
  assert.deepStrictEqual(o.calendar['2026-11-23'], { count: 2, open: 1, mood: '뿌듯' });
  assert.deepStrictEqual(o.day.stats, { '수집': 5, '받은 업무 메일': 0, '본인 메일': 0, '보낸 메일': 0, '광고 제외': 1 });
  const p = g.api.apiOpen(g.s, '', '2026-11-24', '2026-10');
  assert.deepStrictEqual(Object.keys(p.calendar), ['2026-10-30']);
  const e = g.api.apiOpen(g.s, '', '2026-11-01');
  assert.deepStrictEqual([e.day, e.prev, e.next], [null, '2026-10-30', '2026-11-23']);
});

test('메모: 저장, 고침, 지움, 잘못된 값 거절', () => {
  const g = ready();
  assert.strictEqual(g.api.apiSaveNote(g.s, '2026-11-24', '맑음', ' 첫 메모 ').text, '첫 메모');
  g.api.apiSaveNote(g.s, '2026-11-24', '지침', '고친 메모');
  assert.deepStrictEqual(g.api.apiOpen(g.s, '', '2026-11-24').note, { mood: '지침', text: '고친 메모' });
  assert.strictEqual(g.sheets['하루메모'].getLastRow(), 2);
  g.api.apiSaveNote(g.s, '2026-11-24', '', '');
  assert.strictEqual(g.sheets['하루메모'].getLastRow(), 1);
  assert.strictEqual(g.api.apiSaveNote(g.s, '2026-13-01', '', 'x').ok, false);
  assert.strictEqual(g.api.apiSaveNote(g.s, '2026-11-24', '<b>', 'x').ok, false);
  assert.strictEqual(g.api.apiSaveNote(g.s, '2026-11-24', '', 'x'.repeat(501)).ok, false);
});

test('시트가 꽉 차도 저장되고, 잠금은 항상 풀린다', () => {
  const g = ready();
  g.sheets['업무기록'].max = 3;
  assert.strictEqual(g.post(day('2026-11-24', Array(10).fill(0).map((_, i) => did('일 ' + i)))).ok, true);
  assert.strictEqual(g.post(day('2026-11-24', [])).replaced, 10);
  assert.strictEqual(g.api.apiOpen(g.s, '', '2026-11-24').items.length, 0);
  g.api.apiSetDone(g.s, '없는ID', true);
  assert.strictEqual(g.log.filter(x => x === 'lock').length, g.log.filter(x => x === 'unlock').length);
});

/* ---------------------------------------------------------------- 팀 */
function team() {
  const g = ready({ now: () => NOW }), by = n => [g.lead, g.kim, g.park][n];
  g.kim = g.add('김민지'); g.park = g.add('박준호');
  for (let r = 1; r < 4; r++) g.sheets['팀원'].grid[r][5] = '2026-11-20';
  g.post(day('2026-11-24', [did('팀장 일'), todo('팀장 할 일', '2026-11-24', '긴급')]), by(0));
  g.post(day('2026-11-24', [did('김 일 1'), did('김 일 2'), todo('김 할 일', '2026-11-20')]), by(1));
  g.post(day('2026-11-23', [did('박 일'), todo('박 할 일')]), by(2));
  g.k = g.login(g.kim); g.p = g.login(g.park);
  return g;
}

test('팀: 같은 시트에 쌓이고, 이름을 속여도 열쇠 주인의 기록이 된다', () => {
  const g = team();
  const b = day('2026-11-25', [did('속인 일')]);
  b.day.author = '홍길동'; b.day['팀원ID'] = 'T01'; b.items[0]['팀원ID'] = 'T01';
  assert.strictEqual(g.post(b, g.park).name, '박준호');
  assert.strictEqual(g.api.apiSearch(g.s, { keyword: '속인' }).rows[0].member, 'T03');
  assert.deepStrictEqual([...new Set(g.sheets['업무기록'].grid.slice(1).map(r => r[11]))].sort(), ['김민지', '박준호', '홍길동']);
});

test('팀: 같은 날을 다시 올려도 다른 팀원의 기록은 그대로다', () => {
  const g = team();
  assert.strictEqual(g.post(day('2026-11-24', [did('고친 일')]), g.kim).replaced, 3);
  assert.strictEqual(g.api.apiOpen(g.s, 'T01', '2026-11-24').items.length, 2);
  assert.strictEqual(g.api.apiOpen(g.s, 'T02', '2026-11-24').items.length, 1);
  assert.strictEqual(g.sheets['일지'].getLastRow(), 4);
});

test('팀: 두 사람이 같은 문장을 올려도 완료 표시가 섞이지 않는다', () => {
  const g = team();
  g.post(day('2026-11-25', [todo('주간보고 제출')]), g.kim);
  g.post(day('2026-11-25', [todo('주간보고 제출')]), g.park);
  const mine = g.api.apiTodos(g.k).rows.find(r => r.text === '주간보고 제출');
  g.api.apiSetDone(g.k, mine.id, true);
  assert.deepStrictEqual(g.api.apiTodos(g.s).rows.filter(r => r.text === '주간보고 제출').map(r => [r.name, r.done]), [['김민지', true], ['박준호', false]]);
});

test('권한: 팀원은 자기 기록만 보고, 남의 것은 조회·수정이 막힌다', () => {
  const g = team();
  assert.deepStrictEqual(g.api.apiMe(g.k).members.map(m => m.name), ['김민지']);
  assert.deepStrictEqual([...new Set(g.api.apiSearch(g.k, {}).rows.map(r => r.member))], ['T02']);
  assert.deepStrictEqual([...new Set(g.api.apiTodos(g.k).rows.map(r => r.member))], ['T02']);
  for (const r of [g.api.apiOpen(g.k, 'T01', ''), g.api.apiSearch(g.k, { members: ['T01'] }), g.api.apiTodos(g.k, ['T03']), g.api.apiTeam(g.k, '2026-11-23', '2026-11-29'), g.api.apiSearch(g.k, { members: ['__proto__'] })]) {
    assert.strictEqual(r.ok, false);
    assert.deepStrictEqual(Object.keys(r).sort(), ['error', 'ok']);
  }
  const other = g.api.apiTodos(g.s).rows.find(r => r.member === 'T01');
  assert.match(g.api.apiSetDone(g.k, other.id, true).error, /찾지 못/);
});

test('권한: 팀장은 모두 보지만 남의 완료 표시를 바꾸거나 메모를 볼 수 없다', () => {
  const g = team();
  g.api.apiSaveNote(g.k, '2026-11-24', '지침', '비밀 메모');
  assert.deepStrictEqual(g.api.apiOpen(g.s, 'T02', '2026-11-24').note, { mood: '', text: '' });
  assert.strictEqual(g.api.apiOpen(g.s, 'T02', '2026-11-24').calendar['2026-11-24'].mood, '');
  assert.ok(!JSON.stringify([g.api.apiSearch(g.s, {}), g.api.apiSearch(g.s, { kinds: ['메모'] }), g.api.apiTeam(g.s, '2026-11-01', '2026-11-30')]).includes('비밀'));
  assert.strictEqual(g.api.apiSearch(g.k, { keyword: '비밀' }).total, 1);
  assert.match(g.api.apiSetDone(g.s, g.api.apiTodos(g.s, ['T02']).rows[0].id, true).error, /본인만/);
  g.api.apiSaveNote(g.s, '2026-11-24', '맑음', '팀장 메모');
  assert.strictEqual(g.api.apiOpen(g.k, '', '2026-11-24').note.text, '비밀 메모');
});

test('권한: 팀원끼리 보기를 켜면 서로 보고, 끄면 바로 막힌다', () => {
  const g = team();
  g.props.TEAM_OPEN = '1';
  assert.strictEqual(g.api.apiOpen(g.k, 'T01', '2026-11-24').items.length, 2);
  assert.strictEqual(g.api.apiTeam(g.k, '2026-11-23', '2026-11-29').ok, true);
  assert.match(g.api.apiSetDone(g.k, g.api.apiTodos(g.k, ['T01']).rows[0].id, true).error, /본인만/);
  g.props.TEAM_OPEN = '0';
  assert.strictEqual(g.api.apiOpen(g.k, 'T01', '2026-11-24').ok, false);
});

test('사용 중지: 로그인·업로드가 바로 막히고 기록은 남는다', () => {
  const g = team();
  g.sheets['팀원'].grid[2][4] = '중지';
  assert.strictEqual(g.api.apiTodos(g.k).code, 'AUTH');
  assert.strictEqual(g.api.apiLogin(g.kim.code).ok, false);
  assert.strictEqual(g.post(day('2026-11-25', [did('x')]), g.kim).ok, false);
  assert.strictEqual(g.api.apiOpen(g.s, 'T02', '2026-11-24').items.length, 3);
});

test('열쇠 구분: 업로드 열쇠로 로그인하거나 접속 코드로 업로드할 수 없다', () => {
  const g = team();
  assert.strictEqual(g.api.apiLogin(g.kim.token).ok, false);
  assert.strictEqual(g.post({ action: 'ping' }, { token: g.kim.code }).ok, false);
  assert.strictEqual(g.post({ action: 'ping' }, { token: 'T01.' + g.kim.token.slice(4) }).ok, false);
});

test('팀 현황: 제출률(평일, 등록일 이후, 오늘은 낸 사람만), 한 일, 지연, 긴급을 센다', () => {
  const g = team(), d = g.api.apiTeam(g.s, '2026-11-16', '2026-11-29'), row = n => d.members.find(m => m.name === n);
  assert.strictEqual(d.days.length, 10);
  /* 등록 11/20(금). 분모는 20, 23, 24일 = 3일 */
  assert.deepStrictEqual([row('홍길동').submitted, row('홍길동').expected], [1, 3]);
  assert.deepStrictEqual([row('김민지').done, row('김민지').open, row('김민지').late], [2, 1, 1]);
  assert.deepStrictEqual([row('홍길동').late, row('홍길동').urgent], [1, 1]);
  assert.deepStrictEqual(d.total, { submitted: 3, expected: 9, done: 4, open: 3, late: 2, urgent: 1 });
  assert.deepStrictEqual(d.risks.map(i => i.text), ['김 할 일', '팀장 할 일']);
  g.post(day('2026-11-25', [did('오늘 일')]), g.kim);
  assert.strictEqual(g.api.apiTeam(g.s, '2026-11-16', '2026-11-29').total.expected, 10);
  g.post(day('2026-11-21', [did('토요일 일')]), g.kim);
  assert.strictEqual(g.api.apiTeam(g.s, '2026-11-16', '2026-11-29').days.length, 11);
  assert.strictEqual(g.api.apiTeam(g.s, '2026-01-01', '2026-11-29').ok, false);
  assert.strictEqual(g.api.apiTeam(g.s, '2026-11-29', '2026-11-01').ok, false);
});

test('검색: 팀원 조건과 기한 지남 조건, 이름으로 찾기', () => {
  const g = team(), find = q => g.api.apiSearch(g.s, q).rows.map(r => r.text);
  assert.deepStrictEqual(find({ members: ['T03'], kinds: ['한 일'] }), ['박 일']);
  assert.deepStrictEqual(find({ status: 'late' }), ['팀장 할 일', '김 할 일']);
  assert.strictEqual(g.api.apiSearch(g.s, { keyword: '김민지' }).people, 1);
});

test('동시 업로드: 서버가 바쁘면 BUSY 로 알리고 아무것도 쓰지 않는다', () => {
  let busy = false;
  const g = ready({ busy: () => busy }), n = g.sheets['업무기록'].getLastRow();
  busy = true;
  assert.match(g.post(day('2026-11-24', [did('a')])).error, /^BUSY/);
  assert.strictEqual(g.sheets['업무기록'].getLastRow(), n);
  busy = false;
  assert.strictEqual(g.post(day('2026-11-24', [did('a')])).ok, true);
});

test('팀원 10명이 20일치를 올려도 건수가 정확하다', () => {
  const g = ready({ now: () => NOW }), all = [g.lead];
  for (let i = 0; i < 9; i++) all.push(g.add('팀원' + i));
  for (let d = 1; d <= 20; d++) all.forEach((m, i) => g.post(day('2026-11-' + String(d).padStart(2, '0'), [did('일 ' + i), did('둘째 일'), todo('할 일 ' + i)]), m));
  assert.strictEqual(g.sheets['업무기록'].getLastRow() - 1, 600);
  assert.strictEqual(g.api.apiTeam(g.s, '2026-11-01', '2026-11-30').total.done, 400);
  assert.strictEqual(g.api.apiSearch(g.s, {}).rows.length, 500);
});

test('혼자 쓰던 예전 표는 기록을 지키며 팀용으로 바뀐다', () => {
  const g = makeGas(CODE, { now: () => NOW });
  g.setup();
  g.sheets['업무기록'].grid = [['기록ID', '날짜', '구분', '내용', '요청자', '기한', '우선순위', '근거', '상태', '순번'], ['20261124-aa', '2026-11-24', '할 일', '옛 할 일', '본인', '', '보통', '[M01]', '완료', '1']];
  g.sheets['일지'].grid = [['날짜', '요일', '작성자', '핵심', '한 일', '할 일', '확인 필요', '수집', '받은 업무 메일', '본인 메일', '보낸 메일', '광고 제외', '업로드 시각'], ['2026-11-24', '화', '홍길동', '', '0', '1', '0', '1', '1', '0', '0', '0', 'x']];
  g.sheets['하루메모'].grid = [['날짜', '기분', '메모', '수정 시각'], ['2026-11-24', '맑음', '옛 메모', 'x']];
  g.props.UPLOAD_TOKEN = 'old'; g.props.VIEW_CODE = 'old';
  g.setup(); g.setup();
  assert.ok(!('UPLOAD_TOKEN' in g.props) && !('VIEW_CODE' in g.props));
  const lead = g.api.addMember_(g.api.book_(), '홍길동', '', '팀장'), s = g.api.apiLogin(lead.code).session;
  const o = g.api.apiOpen(s, '', '2026-11-24');
  assert.deepStrictEqual([o.items[0].text, o.items[0].done, o.note.text], ['옛 할 일', true, '옛 메모']);
  const up = JSON.parse(g.api.doPost({ postData: { contents: JSON.stringify({ token: lead.token, ...day('2026-11-24', [todo('옛 할 일')]) }) } }).text);
  assert.strictEqual(up.replaced, 1);
  assert.strictEqual(g.api.apiTodos(s).rows[0].done, true);
  g.sheets['일지'].grid[0][0] = '바꾼 이름';
  assert.throws(() => g.setup(), /첫 줄/);
});

test('시트 메뉴: 처음 설정 → 팀원 추가 → 재발급을 실제 순서대로 누른다', () => {
  const answers = [], shown = [];
  const ui = { ButtonSet: {}, Button: { OK: 'OK', YES: 'YES' },
    prompt: () => { const a = answers.shift(); return { getSelectedButton: () => (a === null ? 'CANCEL' : 'OK'), getResponseText: () => a }; },
    alert: (title, text) => { shown.push(title + ' ' + (text || '')); return answers.length && /권한/.test(text || '') ? answers.shift() : 'OK'; } };
  const g = makeGas(CODE, { ui, now: () => NOW });
  answers.push('홍길동', '영업1팀');
  g.api.menuSetup();
  answers.push('김민지', '', 'NO');
  g.api.menuAddMember();
  answers.push('이서연', '영업1팀', 'YES');
  g.api.menuAddMember();
  assert.deepStrictEqual(g.api.members_(g.api.book_()).map(m => [m.id, m.name, m.role]), [['T01', '홍길동', '팀장'], ['T02', '김민지', '팀원'], ['T03', '이서연', '팀장']]);
  const keys = () => shown.filter(x => /T02-/.test(x)).map(x => /T02-[a-z2-9]{10}/.exec(x)[0]);
  const code = keys()[0];
  assert.strictEqual(g.api.apiLogin(code).ok, true);
  answers.push('t02');
  g.api.menuReissue();
  assert.strictEqual(g.api.apiLogin(code).ok, false);
  assert.strictEqual(g.api.apiLogin(keys()[1]).ok, true);
  answers.push(null);
  g.api.menuAddMember();                       /* 취소하면 아무 일도 없다 */
  g.api.menuSetup();                           /* 다시 눌러도 열쇠가 바뀌지 않는다 */
  assert.match(shown.pop(), /이미/);
  assert.strictEqual(g.sheets['팀원'].getLastRow(), 4);
});
