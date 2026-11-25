"""점검을 통과한 업무보고(report.md)를 팀 공용 구글 시트 데이터베이스에 올린다.

누구의 기록인지는 .env 의 업로드 열쇠(DIARY_TOKEN)로 정해진다. 보고서의 작성자 이름은 쓰지 않는다.

사용법
  python scripts/publish_diary.py output/2026-11-24              # 하루
  python scripts/publish_diary.py output/2026-11-23 output/2026-11-24
  python scripts/publish_diary.py --all output                   # output 안의 모든 날짜
  python scripts/publish_diary.py --dry-run output/2026-11-24    # 올리지 않고 올릴 내용만 확인
  python scripts/publish_diary.py --ping                         # 연결 확인

올리는 것: 보고서의 항목(개인정보를 가린 문장)과 건수
올리지 않는 것: 메일 원문, 광고 제외 목록, 메일 계정 정보
"""
import argparse
import csv
import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_report
import mailcore as mc

SECTION_KIND = {"2. 오늘 한 일": "한 일", "3. 진행·공유 사항": "공유", "5. 내일 계획": "계획", "6. 확인 필요 사항": "확인"}
REF = re.compile(r"\s*\[M\d+\]")


class UploadError(Exception):
    pass


RETRY_WAIT = (3, 8, 15)   # 여러 팀원이 같은 시간에 올려 서버가 바쁠 때 다시 시도하는 간격(초)


def iso_due(text, base):
    """'11. 26.(목)' → '2026-11-26'. 12월 보고서의 '1. 5.'는 다음 해로 본다."""
    m = re.match(r"(\d{1,2})\.\s*(\d{1,2})\.", text)
    if not m:
        return ""
    year = base.year
    for y in (year, year + 1, year - 1):
        try:
            day = dt.date(y, int(m[1]), int(m[2]))
        except ValueError:
            continue
        # 보고서에는 요일이 함께 적혀 있으므로 요일이 맞는 해를 고른다.
        w = re.search(r"\(([월화수목금토일])\)", text)
        if abs((day - base).days) <= 366 and (not w or mc.WEEKDAYS[day.weekday()] == w[1]):
            return day.isoformat()
    return ""


def split_refs(text):
    refs = "".join(x.strip() for x in REF.findall(text))
    return REF.sub("", text).strip(), refs


def bullets(body):
    """□ 항목과 그 아래 ○, - 줄을 한 항목으로 묶는다."""
    items = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("□"):
            items.append(line[1:].strip())
        elif line and items and not line.startswith("|"):
            items[-1] += " " + re.sub(r"^[○-]\s*", "", line)
    return [x for x in items if x and x != "해당 없음"]


def to_payload(report, data):
    base = dt.date.fromisoformat(data["date"])
    parts = dict(re.findall(r"(?ms)^## (.+?)\s*\n(.*?)(?=^## |\Z)", report))
    core = [split_refs(x)[0] for x in bullets(parts.get("1. 오늘의 핵심", "")) if x != "보고할 업무 메일 없음"]
    author = re.search(r"(?m)^□ 작성자:\s*(.*)$", report)
    items = []
    for name, kind in SECTION_KIND.items():
        for x in bullets(parts.get(name, "")):
            text, refs = split_refs(x)
            items.append({"kind": kind, "text": text[:2000], "refs": refs})
    for row in re.findall(r"(?m)^\| \d+ \|(.+)\|\s*$", parts.get("4. 할 일", "")):
        c = [x.strip() for x in row.split("|")]
        if len(c) != 5:
            raise UploadError("할 일 표의 열 개수가 맞지 않습니다. check_report.py 로 확인해 주세요.")
        items.append({"kind": "할 일", "text": c[0][:2000], "who": c[1], "due": iso_due(c[2], base),
                      "priority": c[3] if c[3] in ("긴급", "높음", "보통") else "", "refs": c[4]})
    return {"day": {"date": data["date"], "author": author[1].strip() if author else "", "core": core, "stats": data["stats"]},
            "items": items}


def load_day(folder):
    """보고서를 읽고 점검한다. 경고가 있거나 개인정보가 남아 있으면 올리지 않는다."""
    folder = Path(folder)
    missing = [n for n in ("report.md", "mails.json", "excluded.csv") if not (folder / n).exists()]
    if missing:
        raise UploadError(f"{folder} 에 {', '.join(missing)} 이(가) 없습니다.")
    report = (folder / "report.md").read_text(encoding="utf-8-sig")
    data = json.loads((folder / "mails.json").read_text(encoding="utf-8"))
    with (folder / "excluded.csv").open(encoding="utf-8-sig", newline="") as f:
        excluded = list(csv.DictReader(f))
    warnings = check_report.check(report, data, excluded)
    if warnings:
        raise UploadError(f"점검 경고 {len(warnings)}건이 있어 올리지 않았습니다. 먼저 고쳐 주세요: {warnings[0]}")
    payload = to_payload(report, data)
    text = json.dumps(payload, ensure_ascii=False)
    for label, pattern in mc.PII:
        if pattern.search(text):
            raise UploadError(f"개인정보({label})로 보이는 값이 있어 올리지 않았습니다.")
    return payload


def settings():
    cfg = mc.load_env()
    url, token = cfg.get("DIARY_URL", ""), cfg.get("DIARY_TOKEN", "")
    if not url or not token:
        raise UploadError(".env 에 DIARY_URL, DIARY_TOKEN 값이 없습니다. python join_team.py 를 실행해 주세요.")
    check_url(url)
    return url, token


def check_url(url):
    """열쇠를 엉뚱한 곳으로 보내지 않도록 구글 웹앱 주소(또는 내 PC 시험 서버)만 허용한다."""
    p = urllib.parse.urlparse(url)
    google = p.scheme == "https" and p.hostname == "script.google.com" and p.path.endswith("/exec")
    local = p.scheme == "http" and p.hostname in ("127.0.0.1", "localhost")
    if not (google or local):
        raise UploadError("DIARY_URL 은 https://script.google.com/ 으로 시작하고 /exec 로 끝나는 웹 앱 주소여야 합니다.")


def send(url, body, timeout=60):
    req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:   # 구글은 결과를 302 주소로 돌려준다(자동으로 따라감)
            text = res.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        hint = " 웹 앱 주소와 배포 상태를 확인해 주세요." if e.code in (401, 403, 404) else ""
        raise UploadError(f"서버가 오류를 돌려주었습니다({e.code}).{hint}")
    except OSError as e:
        raise UploadError(f"웹 앱에 연결하지 못했습니다: {e}")
    try:
        out = json.loads(text)
    except ValueError:
        raise UploadError("웹 앱이 기록을 받지 못했습니다. 배포할 때 '액세스 권한'을 '모든 사용자'로 했는지 확인해 주세요.")
    if not out.get("ok"):
        raise UploadError(out.get("error", "알 수 없는 오류"))
    return out


def send_retry(url, body, wait=RETRY_WAIT):
    for seconds in (*wait, None):
        try:
            return send(url, body)
        except UploadError as e:
            if not str(e).startswith("BUSY") or seconds is None:
                raise UploadError(str(e).removeprefix("BUSY: "))
            print(f"[기다림] 다른 팀원이 저장하는 중이라 {seconds}초 뒤 다시 시도합니다.")
            time.sleep(seconds)


def publish(folders, dry_run=False):
    url = token = ""
    if not dry_run:
        url, token = settings()
    failed = 0
    for folder in folders:
        try:
            payload = load_day(folder)
            if dry_run:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
                continue
            out = send_retry(url, {"action": "save", "token": token, **payload})
            again = f" (이전 {out['replaced']}건 교체)" if out["replaced"] else ""
            print(f"[업로드] {out['name']} {out['date']} 기록 {out['saved']}건 저장{again}")
        except UploadError as e:
            failed += 1
            print(f"[업로드 안 함] {Path(folder).name}: {e}", file=sys.stderr)
    return failed


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="업무보고를 구글 시트에 올린다")
    ap.add_argument("folders", nargs="*", help="report.md 가 있는 폴더")
    ap.add_argument("--all", metavar="폴더", help="이 폴더 안의 날짜 폴더(2026-11-24 형식)를 모두 올린다")
    ap.add_argument("--dry-run", action="store_true", help="올리지 않고 내용만 보여 준다")
    ap.add_argument("--ping", action="store_true", help="연결만 확인한다")
    args = ap.parse_args(argv)
    try:
        if args.ping:
            url, token = settings()
            print("[연결]", send(url, {"action": "ping", "token": token})["message"])
            return 0
        folders = list(args.folders)
        if args.all:
            folders += sorted(p for p in Path(args.all).glob("*") if re.fullmatch(r"\d{4}-\d\d-\d\d", p.name))
        if not folders:
            print("올릴 폴더를 적어 주세요. 예: python scripts/publish_diary.py output/2026-11-24")
            return 2
        return 1 if publish(folders, args.dry_run) else 0
    except UploadError as e:
        print(f"[설정 확인] {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
