"""mails.json 으로 업무보고 초안(report.md)을 만든다.

규칙만으로 만드는 초안이라 AI 없이도 완성본으로 쓸 수 있고,
Claude 스킬로 쓸 때는 이 초안을 references/report-rules.md 에 따라 다듬는다.

사용법: python scripts/draft_report.py output/2026-11-24
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mailcore as mc

ACTION = re.compile(r"부탁|주세요|주십시오|주시기|바랍니다|바람\b|요청드|요청 드|요청합니다|필요합니다|해야|제출|회신 ?(바|요|부)|확인 ?(바|요청|부)|하기$|할 것|예정$")
DONE = re.compile(r"완료|마쳤|끝냈|처리했|처리함|제출했|제출함|발송했|발송함|보냈|종료")
NOT_DONE = re.compile(r"완료(해|하[여고]|바|까지|예정|되면|될|할)|미완료|완료 ?(부탁|요청|못)")
PLAN = re.compile(r"^(내일|명일|차주|다음 ?주)|내일 (계획|할)")
URGENT = re.compile(r"긴급|즉시|지금 바로|오늘 중|금일 중|urgent|asap", re.I)
GREETING = re.compile(r"^(안녕하세요|안녕하십니까|수고|감사합니다|고맙습니다|[^\s]{2,12}(입니다|드림|올림)\.?$)|^.{0,20}(감사합니다|고맙습니다|수고하세요)\.?$")
SELF_LABEL = re.compile(r"^\[?(완료|한 ?일|할 ?일|해야 ?할 ?일|to-?do|내일 ?(?:계획|할 ?일)?|계획|메모|기록)\]?\s*(?:[:：]|$|(?<=\])\s*)", re.I)


def sentences(body):
    parts = []
    for line in body.split("\n"):
        # "11. 26." 같은 날짜에서 끊기지 않도록, 숫자 뒤 마침표는 문장 끝으로 보지 않는다.
        parts += re.split(r"(?<=[^\d\s][.!?])\s+", line)
    return [p.strip() for p in parts if p.strip()]


def find_deadline(text, base):
    """문장 속 기한을 날짜로 바꾼다. base 는 메일을 받은 날. 못 찾으면 None."""
    m = re.search(r"(20\d{2})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})", text)
    year, md = (int(m[1]), (m[2], m[3])) if m else (base.year, None)
    if not m:
        m = re.search(r"(?<!\d)(\d{1,2})\s*월\s*(\d{1,2})\s*일", text) or \
            re.search(r"(?<![\d/.])(\d{1,2})\s?[/.]\s?(\d{1,2})(?=\s?(?:\.|\(|까지|\s|$))(?!\s?(?:%|억|만|배|시간))", text)
        md = (m[1], m[2]) if m else None
    if md:
        try:
            day = dt.date(year, int(md[0]), int(md[1]))
        except ValueError:
            return None
        # 12월에 받은 "1월 5일까지"는 내년으로 본다(반년 넘게 지난 날짜일 때).
        if len(m.groups()) == 2 and (base - day).days > 180:
            try:
                day = day.replace(year=base.year + 1)
            except ValueError:
                return None
        return day
    for pattern, days in ((r"오늘|금일|당일", 0), (r"내일|명일", 1), (r"모레", 2)):
        if re.search(pattern, text):
            return base + dt.timedelta(days)
    m = re.search(r"(다음 ?주|차주|이번 ?주|금주)?\s*([월화수목금토일])요일", text)
    if m:
        monday = base - dt.timedelta(base.weekday())
        target = monday + dt.timedelta(mc.WEEKDAYS.index(m[2]))
        if m[1] and m[1].replace(" ", "") in ("다음주", "차주"):
            return target + dt.timedelta(7)
        # "금요일까지"인데 이번 주 금요일이 지났으면 다음 주 금요일
        return target if target >= base or m[1] else target + dt.timedelta(7)
    return None


def priority(deadline, text, base):
    if URGENT.search(text) or (deadline and (deadline - base).days <= 1):
        return "긴급"
    if deadline and (deadline - base).days <= 3:
        return "높음"
    return "보통"


def short_date(day):
    return f"{day.month}. {day.day}.({mc.WEEKDAYS[day.weekday()]})" if day else "미정"


def cell(text):
    return re.sub(r"\s+", " ", text).replace("|", "/").strip()


def clean_item(line):
    line = re.sub(r"^\s*(?:[-*•□○·▶]|\d{1,2}[.)](?=\s))\s*", "", line)
    return re.sub(r"^\[[ xX✓]?\]\s*", "", line).strip()


def split_self(mail):
    """본인 메일을 완료/할 일/계획/메모로 나눈다. 앞의 소제목(완료:, 할 일:)이 다음 줄에도 이어진다."""
    out = {"done": [], "todo": [], "plan": [], "memo": []}
    label_map = {"완료": "done", "한일": "done", "할일": "todo", "해야할일": "todo", "todo": "todo", "to-do": "todo",
                 "내일": "plan", "내일계획": "plan", "내일할일": "plan", "계획": "plan", "메모": "memo", "기록": "memo"}

    def head(text):
        m = SELF_LABEL.match(text)
        if m and (m.group(0).rstrip().endswith((":", "：", "]")) or m.end() == len(text)):
            return label_map.get(re.sub(r"\s", "", m[1]).lower()), text[m.end():].strip()
        return None, text

    subject = re.sub(r"(?i)^((re|fw|fwd)\s*:\s*)+", "", mail["subject"])
    current, rest_subject = head(subject)
    lines = [x for x in mail["body"].split("\n") if x.strip()]
    if not lines:  # 제목만 적어 보낸 메모
        lines = [rest_subject or subject]
    for raw in lines:
        raw = raw.strip()
        checked = re.match(r"^[-*•]?\s*\[([ xX✓])\]", raw)
        label, text = head(re.sub(r"^\s*[-*•□○·▶]\s*(?=\[?(?:완료|할 ?일|내일|메모))", "", raw))
        if label and not checked:
            current = label
            if not text:
                continue
        text = clean_item(text if label and not checked else raw)
        if not text or GREETING.match(text):
            continue
        if checked:
            bucket = "todo" if checked[1] == " " else "done"
        elif label or current:
            bucket = current
        elif PLAN.search(text):
            bucket = "plan"
        elif DONE.search(text) and not NOT_DONE.search(text):
            bucket = "done"
        elif ACTION.search(text):
            bucket = "todo"
        else:
            bucket = "memo"
        out[bucket].append(text)
    return out


def build(data):
    base = dt.date.fromisoformat(data["date"])
    done, share, todo, plan, check = [], [], [], [], []
    for m in data["mails"]:
        ref = f"[{m['id']}]"
        if m["flags"]:
            check.append(f"{m['from']} \"{m['subject']}\": {', '.join(m['flags'])} {ref}")
        # 광고 의심, 도용, 지시문 포함 메일의 내용은 사람이 확인하기 전까지 업무로 옮기지 않는다.
        if any(f.startswith(("광고 의심", "본인 주소 도용", "AI 지시문")) for f in m["flags"]):
            continue
        if m["kind"] == "self":
            part = split_self(m)
            done += [f"{x} {ref}" for x in part["done"]]
            plan += [f"{x} {ref}" for x in part["plan"]]
            share += [f"(메모) {x} {ref}" for x in part["memo"]]
            for x in part["todo"]:
                d = find_deadline(x, base)
                todo.append([x, "본인", d, priority(d, x, base), ref])
            if not any(part.values()):
                check.append(f"본인 메일 \"{m['subject']}\": 내용을 파악하지 못함 {ref}")
        elif m["kind"] == "sent":
            extra = f" (첨부 {len(m['attachments'])}건)" if m["attachments"] else ""
            done.append(f"\"{m['subject']}\" 메일 발송{extra} {ref}")
        else:
            lines = [s for s in sentences(m["body"]) if not GREETING.match(s)]
            # "감사합니다", "참고 부탁드립니다"처럼 행동이 없는 인사말은 할 일로 보지 않는다.
            acts = [s for s in lines if ACTION.search(s) and not re.search(r"참고 ?(부탁|바랍|하시기)|양해|협조에 감사", s)
                    and not (DONE.search(s) and not NOT_DONE.search(s))]
            if acts:
                d = next((x for x in (find_deadline(s, base) for s in acts) if x), None)
                todo.append([f"{m['subject']}: {' '.join(acts[:2])}", m["from"], d,
                             priority(d, m["subject"] + " " + " ".join(acts), base), ref])
            else:
                first = " ".join(lines[:2]) if lines else "본문 없음"
                share.append(f"{m['from']}: {m['subject']} - {first} {ref}")
    rank = {"긴급": 0, "높음": 1, "보통": 2}
    todo.sort(key=lambda t: (rank[t[3]], t[2] or dt.date.max))
    for i, t in enumerate(todo, 1):
        if t[2] == base + dt.timedelta(1):
            plan.append(f"할 일 {i}번 처리(기한 {short_date(t[2])}) {t[4]}")
    check += [f"기한 미정: 할 일 {i}번 {t[4]}" for i, t in enumerate(todo, 1) if not t[2] and t[1] != "본인"]
    check += [f"수집 경고: {w}" for w in data.get("warnings", [])]

    urgent = [f"{i}번" for i, t in enumerate(todo, 1) if t[3] == "긴급"]
    core = []
    if data["mails"]:
        core.append(f"오늘 한 일 {len(done)}건, 새 할 일 {len(todo)}건, 공유 사항 {len(share)}건임")
        if urgent:
            core.append(f"긴급 처리 필요: 할 일 {', '.join(urgent)}")
        if check:
            core.append(f"확인 필요 사항 {len(check)}건 있음")

    def bullets(items):
        return "\n".join(f"□ {cell(x)}" for x in items) or "□ 해당 없음"
    table = "해당 없음"
    if todo:
        rows = ["| 번호 | 할 일 | 요청자 | 기한 | 우선순위 | 근거 |", "|---|---|---|---|---|---|"]
        rows += [f"| {i} | {cell(t[0])} | {cell(t[1])} | {short_date(t[2])} | {t[3]} | {t[4]} |" for i, t in enumerate(todo, 1)]
        table = "\n".join(rows)
    s = data["stats"]
    status = (f"□ 수집 {s['수집']}건 (받은 업무 메일 {s['받은 업무 메일']}건, 본인 메일 {s['본인 메일']}건, "
              f"보낸 메일 {s['보낸 메일']}건, 광고 제외 {s['광고 제외']}건)")
    text = (mc.ROOT / "assets" / "report-template.md").read_text(encoding="utf-8")
    values = {"보고일": mc.korean_date(base), "작성자": data.get("author") or "미정",
              "메일함": data.get("mailbox", ""), "핵심": bullets(core) if core else "□ 보고할 업무 메일 없음",
              "한일": bullets(done), "공유": bullets(share), "할일": table, "계획": bullets(plan),
              "확인": bullets(check), "현황": status}
    # 한 번에 바꿔야 메일 본문에 {{계획}} 같은 글자가 있어도 다시 치환되지 않는다.
    return re.sub(r"\{\{(\w+)\}\}", lambda m: values.get(m[1], m[0]), text)


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or not (Path(argv[0]) / "mails.json").exists():
        print("사용법: python scripts/draft_report.py <mails.json 이 있는 폴더>. 먼저 collect_mail.py 를 실행하세요.")
        return 2
    folder = Path(argv[0])
    data = json.loads((folder / "mails.json").read_text(encoding="utf-8"))
    (folder / "report.md").write_text(build(data), encoding="utf-8")
    print(f"[초안] {folder / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
