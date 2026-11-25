"""팀원 PC 처음 설정. 질문에 답하면 .env 를 만들고 팀 데이터베이스 연결을 확인한다.

사용법: python join_team.py
비밀번호와 열쇠는 화면에 보이지 않게 입력받아 이 PC의 .env 에만 저장한다.
"""
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))
import mailcore
import publish_diary as pub

# (이름, 질문, 숨김 여부, 비워도 되는지)
QUESTIONS = [
    ("DIARY_URL", "팀장에게 받은 웹 앱 주소", False, False),
    ("DIARY_TOKEN", "팀장에게 받은 내 업로드 열쇠", True, False),
    ("MAIL_HOST", "메일 서버 (Gmail: imap.gmail.com / 네이버: imap.naver.com)", False, True),
    ("MAIL_USER", "메일 아이디(주소)", False, True),
    ("MAIL_PASSWORD", "메일 앱 비밀번호", True, True),
    ("MAIL_FOLDERS", "읽을 메일함 (예: INBOX 또는 INBOX,보낸메일함)", False, True),
    ("MY_ADDRESSES", "내 메일 주소 (쉼표로 여러 개)", False, True),
    ("TRUSTED_SENDERS", "항상 업무로 볼 회사·거래처 도메인 (쉼표로 여러 개)", False, True),
    ("REPORT_AUTHOR", "보고서에 적을 내 이름", False, True),
]


def read_values(path):
    """.env 파일만 읽는다(환경변수는 섞지 않는다)."""
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def merge(template, values):
    """양식의 설명은 그대로 두고 값만 채운다. 양식에 없는 값은 맨 아래에 붙인다."""
    left, lines = dict(values), []
    for line in template.splitlines():
        key = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and key in left:
            line = f"{key}={left.pop(key)}"
        lines.append(line)
    lines += [f"{k}={v}" for k, v in left.items()]
    return "\n".join(lines) + "\n"


def ask(old, read=input, secret=getpass.getpass):
    values = dict(old)
    for key, text, hidden, optional in QUESTIONS:
        had = old.get(key, "")
        note = " [Enter: 그대로]" if had else " [Enter: 나중에]" if optional else ""
        while True:
            v = (secret if hidden else read)(f"{text}{note}: ")
            v = "".join(c for c in v if c.isprintable()).strip()   # 붙여 넣을 때 섞인 줄바꿈 제거
            if not v:
                if had or optional:
                    break
                print("  꼭 필요한 값입니다.")
                continue
            if key == "DIARY_URL":
                try:
                    pub.check_url(v)
                except pub.UploadError as e:
                    print(f"  {e}")
                    continue
            values[key] = v
            break
    return values


def main(path=None, read=input, secret=getpass.getpass):
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    path = path or ROOT / ".env"
    old = {k: v for k, v in read_values(path).items() if v}
    print("팀 업무 다이어리 설정을 시작합니다. 입력한 값은 이 PC의 .env 에만 저장됩니다.\n")
    values = ask(old, read, secret)
    try:
        name = pub.send(values["DIARY_URL"], {"action": "ping", "token": values["DIARY_TOKEN"]})["name"]
    except pub.UploadError as e:
        print(f"\n[설정 확인] {e}\n저장하지 않았습니다. 값을 확인하고 다시 실행해 주세요.", file=sys.stderr)
        return 1
    values.setdefault("MAIL_PORT", "993")
    path.write_text(merge((ROOT / ".env.example").read_text(encoding="utf-8"), values), encoding="utf-8")
    print(f"\n[연결] {name} 님으로 팀 데이터베이스에 연결되었습니다.")
    print("본인 이름이 맞는지 확인하세요. 다르면 팀장에게 열쇠를 다시 받으세요.")
    print("이제 python run_daily.py --upload 로 오늘 기록을 올릴 수 있습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
