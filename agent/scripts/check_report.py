"""업무보고(report.md)를 원본(mails.json, excluded.csv)과 대조해 점검한다.

사용법: python scripts/check_report.py output/2026-11-24
경고가 0건이면 종료 코드 0, 있으면 1.
"""
import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mailcore as mc
from draft_report import find_deadline, sentences, short_date

SECTIONS = ["1. 오늘의 핵심", "2. 오늘 한 일", "3. 진행·공유 사항", "4. 할 일", "5. 내일 계획", "6. 확인 필요 사항", "7. 메일 처리 현황"]
AMOUNT = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:억|천만|백만|만)?\s*원|\d+(?:\.\d+)?\s*%")


def check(report, data, excluded):
    warn = []
    parts = dict(re.findall(r"(?ms)^## (.+?)\s*\n(.*?)(?=^## |\Z)", report))
    warn += [f"항목 누락: '{s}'" for s in SECTIONS if s not in parts]
    mails = {m["id"]: m for m in data["mails"]}
    refs = set(re.findall(r"\[(M\d+)\]", report))
    warn += [f"없는 메일 번호 {r}를 근거로 적음" for r in sorted(refs - set(mails))]
    warn += [f"{i}({mails[i]['subject']})이(가) 보고서에 없음" for i in sorted(set(mails) - refs)]
    # 본인 메일은 확인 필요 칸에만 있으면 안 되고 업무 칸(2~5)에 반영되어야 한다.
    work = "".join(parts.get(s, "") for s in SECTIONS[1:5])
    warn += [f"본인 메일 {i}이(가) 업무 칸(2~5)에 반영되지 않음" for i, m in mails.items()
             if m["kind"] == "self" and not m["flags"] and f"[{i}]" not in work]
    for m in mails.values():
        blocked = [f for f in m["flags"] if f.startswith(("광고 의심", "본인 주소 도용", "AI 지시문"))]
        if blocked and f"[{m['id']}]" in work:
            warn.append(f"{m['id']}은(는) '{blocked[0]}' 메일인데 업무 칸에 들어감. 확인 필요 사항으로 옮길 것")
    kept_subjects = {m["subject"] for m in mails.values()}
    for row in excluded:
        subject = row["제목"].lstrip("'")
        if len(subject) >= 5 and subject not in kept_subjects and subject in report:
            warn.append(f"광고로 제외한 메일이 들어감: '{subject}'")
    for label, pattern in mc.PII:
        if pattern.search(report):
            warn.append(f"개인정보({label})로 보이는 값이 있음")
    squash = lambda t: re.sub(r"[\s,]", "", t)
    base = dt.date.fromisoformat(data["date"])
    for name, body in parts.items():
        if name == SECTIONS[6]:
            continue
        for line in body.splitlines():
            ids = re.findall(r"\[(M\d+)\]", line)
            source = squash(" ".join(mails[i]["subject"] + mails[i]["body"] for i in ids if i in mails)
                            or " ".join(m["subject"] + m["body"] for m in mails.values()))
            for amount in AMOUNT.findall(line):
                if not re.search(r"(?<!\d)" + re.escape(squash(amount)), source):
                    warn.append(f"원본에 없는 수치 '{amount}': {line.strip()[:40]}")
            if name in SECTIONS[1:4] + SECTIONS[4:6] and line.startswith("□") and "해당 없음" not in line \
                    and "수집 경고" not in line and not ids:
                warn.append(f"근거 메일 번호가 없음: {line.strip()[:40]}")
    for row in re.findall(r"(?m)^\| (\d+) \|(.+)\|\s*$", parts.get(SECTIONS[3], "")):
        cells = [c.strip() for c in row[1].split("|")]
        ids = [i for i in re.findall(r"M\d+", cells[-1]) if i in mails]
        if len(cells) != 5 or not ids:
            warn.append(f"할 일 {row[0]}번의 열 개수 또는 근거 번호 확인")
            continue
        if cells[3] not in ("긴급", "높음", "보통"):
            warn.append(f"할 일 {row[0]}번 우선순위 '{cells[3]}'는 기준표에 없음")
        possible = {short_date(find_deadline(s, base)) for i in ids
                    for s in sentences(mails[i]["subject"] + "\n" + mails[i]["body"])} | {"미정"}
        if cells[2] not in possible:
            warn.append(f"할 일 {row[0]}번 기한 '{cells[2]}'의 근거가 메일에 없음")
    s = data["stats"]
    for key in ("수집", "받은 업무 메일", "본인 메일", "보낸 메일", "광고 제외"):
        if f"{key} {s[key]}건" not in parts.get(SECTIONS[6], ""):
            warn.append(f"메일 처리 현황의 '{key}' 건수가 {s[key]}건과 다름")
    return warn


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    argv = sys.argv[1:] if argv is None else argv
    folder = Path(argv[0]) if argv else Path(".")
    missing = [n for n in ("report.md", "mails.json", "excluded.csv") if not (folder / n).exists()]
    if missing:
        print(f"{folder} 에 {', '.join(missing)} 이(가) 없습니다. collect_mail.py, draft_report.py 를 먼저 실행하세요.")
        return 2
    with (folder / "excluded.csv").open(encoding="utf-8-sig", newline="") as f:
        excluded = list(csv.DictReader(f))
    warn = check((folder / "report.md").read_text(encoding="utf-8-sig"),
                 json.loads((folder / "mails.json").read_text(encoding="utf-8")), excluded)
    for w in warn:
        print(f"[경고] {w}")
    print(f"[점검] 경고 {len(warn)}건")
    return 1 if warn else 0


if __name__ == "__main__":
    sys.exit(main())
