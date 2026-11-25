/* 구글에 배포하기 전에 내 PC에서 똑같이 돌려 보는 시험 서버. 기록은 끄면 사라진다.
   실행: node tests/local_server.js   →  http://127.0.0.1:8787/  (팀장 코드: T01-lead-test, 팀원 코드: T02-member-test)
   업로드 시험용: DIARY_URL=http://127.0.0.1:8787/exec   DIARY_TOKEN=T01.upload-test 또는 T02.upload-test */
const http = require('http');
const fs = require('fs');
const path = require('path');
const { makeGas } = require('./gas_runtime.js');
const web = path.join(__dirname, '..', 'web');
const g = makeGas(fs.readFileSync(path.join(web, 'Code.gs'), 'utf8'));
g.setup();
const keys = (id, code) => { g.props['KEY_' + id] = JSON.stringify({ code: g.api.sha_(id + '-' + code), token: g.api.sha_(id + '.upload-test') }); };
g.api.addMember_(g.api.book_(), '홍길동', '영업1팀', '팀장'); keys('T01', 'lead-test');
g.api.addMember_(g.api.book_(), '김민지', '영업1팀', '팀원'); keys('T02', 'member-test');
const shim = `<script>
window.google={script:{get run(){const h={};const p=new Proxy({},{get:(_,k)=>k==='withSuccessHandler'?f=>(h.ok=f,p):k==='withFailureHandler'?f=>(h.no=f,p):(...a)=>{fetch('/call',{method:'POST',body:JSON.stringify([k,a])}).then(r=>r.json()).then(r=>r.error&&r.thrown?h.no(new Error(r.error)):h.ok(r)).catch(h.no)}});return p}}};
</script>`;
let result = '';
const port = Number(process.argv[2] || 8787);
http.createServer((req, res) => {
  let body = '';
  req.on('data', d => { body += d; });
  req.on('end', () => {
    const send = (t, type) => { res.writeHead(200, { 'Content-Type': type + '; charset=utf-8' }); res.end(t); };
    if (req.method === 'POST' && req.url === '/exec') {           /* 구글처럼 결과를 302 주소로 돌려준다 */
      result = g.api.doPost({ postData: { contents: body } }).text;
      res.writeHead(302, { Location: '/echo' }); res.end();
    } else if (req.url === '/echo') send(result, 'application/json');
    else if (req.method === 'POST' && req.url === '/call') {
      const [fn, args] = JSON.parse(body);
      try {
        if (!g.fns.includes(fn) || fn.endsWith('_')) throw new Error('없는 함수');
        send(JSON.stringify(g.api[fn](...args)), 'application/json');
      } catch (e) { send(JSON.stringify({ thrown: true, error: e.message }), 'application/json'); }
    } else if (req.url === '/') send(fs.readFileSync(path.join(web, 'Index.html'), 'utf8').replace('<!--DEMO-->', () => shim), 'text/html');
    else { res.writeHead(404); res.end(); }
  });
}).listen(port, '127.0.0.1', () => console.log('http://127.0.0.1:' + port + '/'));
