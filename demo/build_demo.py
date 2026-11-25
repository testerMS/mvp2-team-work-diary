"""구글 계정 없이 눌러 볼 수 있는 체험판(demo/index.html)을 만든다. 팀원과 기록은 모두 가상이다.

web/Index.html 과 web/Code.gs 를 그대로 쓰고, 구글 시트 자리에 가상 시트를 넣는다.
사용법: python demo/build_demo.py
"""
import datetime as dt
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent" / "scripts"))
import publish_diary as pub

TODAY = dt.date(2026, 11, 25)
TEAM = [("홍길동", "영업1팀", "팀장"), ("김민지", "영업1팀", "팀원"), ("박준호", "영업1팀", "팀원"), ("이서연", "영업지원", "팀원"), ("최도윤", "영업지원", "팀원")]
# 사람: (한 일, 할 일(내용, 요청자), 공유)
WORK = {
    "홍길동": (["주간회의 주재함", "대성오토 납기 단축 협의함", "팀 실적 자료 검토함", "신규 거래처 계약 조건 검토함", "월간 목표 점검표 작성함", "협력사 간담회 참석함", "견적 승인 4건 처리함"],
             [("4분기 영업 계획 보고", "본부장"), ("대성오토 납기 단축안 회신", "대성오토"), ("팀원 면담 일정 확정", "본인"), ("협력사 평가표 제출", "구매팀")],
             ["포장재 단가 12월부터 3% 인상 예정", "품질팀 11월 불량률 1.2%로 공유함"]),
    "김민지": (["한빛정공 견적서 발송함", "신규 거래처 전화 상담 3건 진행함", "제품 시연 자료 수정함", "한빛정공 방문 일정 확정함", "견적 비교표 작성함", "거래처 문의 메일 회신함"],
             [("한빛정공 최종 견적 회신", "한빛정공"), ("시연 장비 예약", "본인"), ("거래처 등록 서류 준비", "총무팀"), ("방문 결과 보고서 작성", "홍길동"), ("브레이크 패드 단가 확인", "생산팀")],
             ["한빛정공 담당자 12월부터 변경 예정"]),
    "박준호": (["해솔물류 운송 단가 협의함", "거래처 현장 방문함", "도면 수정 요청 접수함", "출하 일정 조율함", "클레임 원인 조사함", "샘플 발송 완료함"],
             [("운송 단가 비교표 제출", "홍길동"), ("도면 수정본 송부", "거래처"), ("클레임 조치 결과 회신", "새봄기계"), ("출하 지연 사유서 작성", "물류팀")],
             ["해솔물류 연말 배차 12월 24일 마감"]),
    "이서연": (["거래명세서 발행함", "11월 매출 집계함", "계약서 검토본 정리함", "세금계산서 수정 발행함", "미수금 현황표 갱신함", "재고 차이 확인함"],
             [("미수금 안내문 발송", "재무팀"), ("계약서 원본 보관 확인", "법무팀"), ("11월 마감 자료 제출", "재무팀"), ("ERP 권한 신청", "전산팀")],
             ["11월 마감 자료 제출일 11월 30일로 확정됨"]),
    "최도윤": (["ERP 주문 등록 12건 처리함", "고객 만족도 설문 정리함", "카탈로그 시안 검토함", "행사 부스 견적 접수함", "사은품 재고 확인함", "홈페이지 문의 5건 답변함"],
             [("카탈로그 시안 의견 회신", "홍보팀"), ("행사 부스 신청", "홍보팀"), ("설문 결과 1쪽 요약", "홍길동"), ("홈페이지 제품 사진 교체", "전산팀")],
             ["전시회 부스 배정 결과 12월 3일 발표 예정"]),
}
SKIP = {("박준호", "2026-11-10"), ("박준호", "2026-11-19"), ("최도윤", "2026-11-06"), ("최도윤", "2026-11-20"), ("최도윤", "2026-11-24"),
        ("이서연", "2026-11-13"), ("박준호", "2026-11-03")}
TODAY_DONE = {"김민지", "이서연"}   # 25일 오전까지 올린 사람
NOTES = [["홍길동", "2026-11-24", "바쁨", "납기 회신부터 끝내기"], ["홍길동", "2026-11-20", "뿌듯", "방안 좋다는 말을 들었다"], ["김민지", "2026-11-24", "맑음", "견적서 한 번에 통과"]]


def seeds():
    rnd, days, done = random.Random(20261125), [], []
    sample = pub.load_day(ROOT / "agent" / "samples" / "result")      # MVP1 샘플 메일로 실제로 만든 보고서
    for name, _, _ in TEAM:
        did, todos, share = WORK[name]
        turn = 0
        for n in range((TODAY - dt.date(2026, 11, 2)).days + 1):
            d = dt.date(2026, 11, 2) + dt.timedelta(n)
            iso = d.isoformat()
            if d.weekday() > 4 or (name, iso) in SKIP or (d == TODAY and name not in TODAY_DONE):
                continue
            if name == "홍길동" and iso == sample["day"]["date"]:
                days.append([name, sample])
                continue
            ref = iter(f"[M{k:02d}]" for k in range(1, 30))
            mine = rnd.sample(did, rnd.choice([1, 2, 3, 3, 4, 5]) if d < TODAY else 1)
            items = [{"kind": "한 일", "text": t, "refs": next(ref)} for t in mine]
            for _ in range(rnd.choice([0, 1, 1, 1, 2]) if d < TODAY else 1):
                text, who = todos[turn % len(todos)]
                turn += 1
                due = d + dt.timedelta(rnd.choice([1, 2, 3, 5, 7]))
                due += dt.timedelta({5: 2, 6: 1}.get(due.weekday(), 0))
                gap = (due - d).days
                items.append({"kind": "할 일", "text": f"{text}" if turn <= len(todos) else f"{text} ({d.month}월 {d.day}일 요청분)", "who": who, "due": due.isoformat(),
                              "priority": "긴급" if gap <= 1 else "높음" if gap <= 3 else "보통", "refs": next(ref)})
                age = (TODAY - due).days
                if age > 4 or (age >= 0 and rnd.random() < .72) or (age < 0 and rnd.random() < .18):
                    done.append([name, iso, items[-1]["text"]])
            if rnd.random() < .2:
                items.append({"kind": "공유", "text": rnd.choice(share), "refs": next(ref)})
            if rnd.random() < .45:
                items.append({"kind": "계획", "text": rnd.choice(did).replace("함", "").strip() + " 예정", "refs": next(ref)})
            mail = len(items) + rnd.randint(0, 3)
            ads = rnd.randint(1, 4)
            own, sent = rnd.randint(1, 2), rnd.randint(0, 2)
            days.append([name, {"day": {"date": iso, "core": [mine[0]], "stats": {"수집": mail + ads + own + sent, "받은 업무 메일": mail, "본인 메일": own, "보낸 메일": sent, "광고 제외": ads}}, "items": items}])
    return {"team": TEAM, "days": days, "done": done, "notes": NOTES}


def build():
    web = ROOT / "web"
    code, runtime = (web / "Code.gs").read_text(encoding="utf-8"), (ROOT / "tests" / "gas_runtime.js").read_text(encoding="utf-8")
    names = ", ".join(re.findall(r"(?m)^function (\w+)\(", code))
    data = json.dumps(seeds(), ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\!--")
    script = f"""<div class="demo"><span>체험판입니다. 팀원과 기록은 모두 가상이며 바꾼 내용은 새로 고치면 사라집니다.</span><label>보는 사람 <select id="demoUser"></select></label></div>
<script>
{runtime}
(function () {{
  const factory = function (env) {{
    const {{ SpreadsheetApp, PropertiesService, CacheService, LockService, Utilities, ContentService, HtmlService, Date }} = env;
{code}
    return {{ {names} }};
  }};
  const g = window.makeGas('', {{ factory, now: () => Date.UTC(2026, 10, 25, 1) }}), d = {data}, key = {{}}, s = {{}};
  g.setup();
  d.team.forEach(m => {{ key[m[0]] = g.api.addMember_(g.api.book_(), m[0], m[1], m[2]); }});
  g.sheets['팀원'].grid.slice(1).forEach(r => {{ r[5] = '2026-11-02'; }});
  d.days.forEach(x => {{ const r = JSON.parse(g.api.doPost({{ postData: {{ contents: JSON.stringify(Object.assign({{ action: 'save', token: key[x[0]].token }}, x[1])) }} }}).text); if (!r.ok) console.error(r.error); }});
  d.team.forEach(m => {{ s[m[0]] = g.api.apiLogin(key[m[0]].code).session; }});
  const lead = d.team[0][0];
  g.api.apiTodos(s[lead]).rows.forEach(i => {{ if (d.done.some(x => x[0] === i.name && x[1] === i.date && x[2] === i.text)) g.api.apiSetDone(s[i.name], i.id, true); }});
  d.notes.forEach(n => g.api.apiSaveNote(s[n[0]], n[1], n[2], n[3]));
  window.DEMO_TODAY = '2026-11-25';
  window.DEMO_SESSION = s[lead];
  const pick = document.getElementById('demoUser');
  pick.innerHTML = d.team.map(m => '<option value="' + m[0] + '">' + m[0] + ' (' + m[2] + ')</option>').join('');
  pick.value = lead;
  pick.addEventListener('change', () => window.dispatchEvent(new CustomEvent('demo-user', {{ detail: s[pick.value] = g.api.apiLogin(key[pick.value].code).session }})));
  /* 체험판은 아무 코드나 받아 고른 사람으로 다시 들어간다 */
  window.DEMO_CALL = (fn, args) => JSON.parse(JSON.stringify(fn === 'apiLogin' ? g.api.apiLogin(key[pick.value].code) : g.api[fn].apply(null, args)));
}})();
</script>"""
    html = (web / "Index.html").read_text(encoding="utf-8")
    assert html.count("<!--DEMO-->") == 1
    out = html.replace("<!--DEMO-->", script).replace("<title>업무 다이어리</title>", "<title>업무 다이어리 체험판</title>")
    (ROOT / "demo" / "index.html").write_text(out, encoding="utf-8")
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"[체험판] demo/index.html {len(build()):,}자")
