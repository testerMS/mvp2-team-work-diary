"""메일 읽기, 본인 메일 판별, 광고 판정, 개인정보 가림에 쓰는 공통 함수.

표준 라이브러리만 사용한다. 판정 기준은 코드가 아니라
references/ad-filter-rules.md 의 표에서 읽는다.
"""
import base64
import datetime as dt
import html
import imaplib
import os
import re
from email import message_from_bytes
from email.policy import default as default_policy
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULES_FILE = ROOT / "references" / "ad-filter-rules.md"
# 한국은 서머타임이 없어 +9시간 고정. 윈도우에서 tzdata 설치가 필요 없다.
KST = dt.timezone(dt.timedelta(hours=9))
WEEKDAYS = "월화수목금토일"
# 한 통이 보고서 전체를 덮지 않도록 하는 본문 상한. 넘으면 "본문 일부만 읽음"으로 표시한다.
MAX_BODY = 8000


class ConfigError(Exception):
    """사용자가 설정을 고치면 해결되는 오류."""


# ---------------------------------------------------------------- 설정
def load_env(path=None):
    """.env 를 읽는다. 이미 있는 환경변수가 우선한다."""
    path = Path(path) if path else ROOT / ".env"
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    values.update({k: v for k, v in os.environ.items() if k.startswith(("MAIL_", "REPORT_", "MY_", "TRUSTED_", "BLOCKED_", "DIARY_"))})
    return values


def split_list(text):
    return [x.strip() for x in (text or "").split(",") if x.strip()]


def korean_date(day):
    return f"{day.year}. {day.month}. {day.day}.({WEEKDAYS[day.weekday()]})"


# ---------------------------------------------------------------- 메일 해석
def fix_text(text):
    """인코딩 표시 없이 들어온 한글 헤더(EUC-KR 등)를 되살린다."""
    text = str(text or "")
    if any(0xDC80 <= ord(c) <= 0xDCFF for c in text):
        raw = text.encode("utf-8", "surrogateescape")
        for charset in ("utf-8", "cp949"):
            try:
                text = raw.decode(charset)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", "replace")
    return re.sub(r"\s+", " ", text).strip()


def header(msg, name):
    """깨진 헤더 하나 때문에 메일 전체를 놓치지 않도록 예외를 안에서 처리한다."""
    try:
        value = msg.get(name)
    except Exception:
        value = None
    if value is None:
        value = next((v for k, v in msg.raw_items() if k.lower() == name.lower()), "")
    text = str(value)
    if "�" in text or any(0xDC80 <= ord(c) <= 0xDCFF for c in text):
        raw = next((v for k, v in msg.raw_items() if k.lower() == name.lower()), "")
        text = str(raw)
    return fix_text(text)


def decode_part(part):
    raw = part.get_payload(decode=True) or b""
    for charset in (part.get_content_charset(), "utf-8", "cp949"):
        if not charset:
            continue
        if charset.lower() in ("ks_c_5601-1987", "euc-kr", "euc_kr"):
            charset = "cp949"  # cp949 는 euc-kr 을 포함하므로 확장 한글도 읽힌다.
        try:
            return raw.decode(charset)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "replace")


def html_to_text(source):
    source = re.sub(r"(?is)<(script|style|head|title)\b.*?</\1>", " ", source)
    source = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>", "\n", source)
    return html.unescape(re.sub(r"(?s)<[^>]+>", " ", source))


QUOTE_MARKERS = re.compile(
    r"^\s*(-{2,}\s*(original message|원본 메일|원본 메시지|forwarded message|전달된 메일).*"
    r"|on .{5,120} wrote:|\d{4}년 .{5,80}(작성|썼습니다).*:?)\s*$", re.I)


def clean_body(text, keep_quoted=False):
    """이전 메일 인용과 서명을 뗀다. 남는 본문이 없으면 원문을 그대로 쓴다."""
    lines, out = text.replace("\r\n", "\n").replace("​", "").split("\n"), []
    for line in lines:
        if not keep_quoted:
            if QUOTE_MARKERS.match(line) or line.rstrip("\r") in ("--", "-- "):
                break
            if line.lstrip().startswith(">"):
                continue
        out.append(re.sub(r"[ \t ]+", " ", line).strip())
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    if not body and not keep_quoted:
        return clean_body(text, keep_quoted=True)
    return body


def parse_recipients(values):
    """최신 Python 의 getaddresses 는 빈 값이나 어긋난 주소가 섞이면 전체를 버린다.
    받는 사람이 사라지면 '보낸 메일'이 '본인 메일'로 잘못 분류되므로 하나씩 느슨하게 읽는다."""
    out = []
    for value in values:
        if not value:
            continue
        found = re.findall(r"[^\s<>,;:\"()]+@[^\s<>,;:\"()]+", value)
        out += [a.lower() for a in found] or ["(해석 불가)"]
    return out


def parse_mail(raw,received=None, source="", folder=""):
    msg = message_from_bytes(raw, policy=default_policy)
    plain, rich, files = [], [], []
    for part in msg.walk():
        if part.is_multipart():
            continue
        try:
            name = part.get_filename()
        except Exception:
            name = None
        if name or part.get_content_disposition() == "attachment":
            files.append(fix_text(name or "이름 없는 첨부"))
        elif part.get_content_type() == "text/plain":
            plain.append(decode_part(part))
        elif part.get_content_type() == "text/html":
            rich.append(decode_part(part))
    rich_text = "\n".join(html_to_text(x) for x in rich)
    full = "\n".join(plain) if "".join(plain).strip() else rich_text
    if received is None:
        try:
            received = parsedate_to_datetime(header(msg, "Date"))
            if received.tzinfo is None:
                received = received.replace(tzinfo=KST)
        except (ValueError, TypeError, IndexError):
            received = None
    sender = (getaddresses([header(msg, "From")]) or [("", "")])[0]
    recipients = parse_recipients([header(msg, h) for h in ("To", "Cc", "Bcc")])
    subject = header(msg, "Subject") or "(제목 없음)"
    # 제목이 "FW:" 인 전달 메일은 인용문이 곧 내용이므로 남긴다.
    forwarded = bool(re.match(r"(?i)\s*(fw|fwd|전달)\s*:", subject))
    body = clean_body(full, keep_quoted=forwarded)
    return {
        "message_id": header(msg, "Message-ID") or f"{source}:{subject}:{received}",
        "from_name": sender[0].strip('" '), "from_addr": sender[1].lower(),
        "recipients": recipients, "subject": subject,
        "received": received.astimezone(KST) if received else None,
        "body": body[:MAX_BODY], "truncated": len(body) > MAX_BODY,
        "full_text": full + "\n" + rich_text, "attachments": files, "folder": folder,
        "headers": {k.lower(): fix_text(v) for k, v in reversed(list(msg.raw_items()))},
    }


# ---------------------------------------------------------------- 수집
def read_eml_folder(path):
    path = Path(path)
    if not path.is_dir():
        raise ConfigError(f"메일 폴더를 찾을 수 없습니다: {path}")
    return [parse_mail(p.read_bytes(), source=p.name, folder=path.name) for p in sorted(path.glob("*.eml"))]


def encode_folder(name):
    """한글 메일함 이름을 IMAP 규격(수정 UTF-7)으로 바꾼다. 예: 내게쓴메일함"""
    out, buf = [], []

    def flush():
        if buf:
            data = base64.b64encode("".join(buf).encode("utf-16-be")).decode().rstrip("=").replace("/", ",")
            out.append(f"&{data}-")
            buf.clear()
    for ch in name:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            buf.append(ch)
    flush()
    return "".join(out)


def decode_folder(name):
    def repl(m):
        if not m.group(1):
            return "&"
        data = m.group(1).replace(",", "/")
        return base64.b64decode(data + "=" * (-len(data) % 4)).decode("utf-16-be")
    return re.sub(r"&([^-]*)-", repl, name)


def connect(cfg):
    missing = [k for k in ("MAIL_HOST", "MAIL_USER", "MAIL_PASSWORD") if not cfg.get(k)]
    if missing:
        raise ConfigError(f".env 에 {', '.join(missing)} 값이 없습니다. .env.example 을 복사해 채워 주세요.")
    try:
        client = imaplib.IMAP4_SSL(cfg["MAIL_HOST"], int(cfg.get("MAIL_PORT") or 993), timeout=30)
    except OSError as e:
        raise ConfigError(f"메일 서버에 연결하지 못했습니다({cfg['MAIL_HOST']}): {e}")
    try:
        client.login(cfg["MAIL_USER"], cfg["MAIL_PASSWORD"])
    except imaplib.IMAP4.error:
        client.shutdown()
        raise ConfigError("메일 로그인에 실패했습니다. 계정 비밀번호가 아니라 '앱 비밀번호'인지, "
                          "메일 설정에서 IMAP 사용이 켜져 있는지 확인해 주세요.")
    return client


def list_folders(client):
    _, rows = client.list()
    names = []
    for row in rows or []:
        m = re.search(r'(?:"((?:[^"\\]|\\.)*)"|(\S+))\s*$', (row or b"").decode("ascii", "replace"))
        if m:
            names.append(decode_folder(m.group(1) if m.group(1) is not None else m.group(2)))
    return names


# strftime("%b")는 윈도우 한글 환경에서 "11월"이 될 수 있어 직접 만든다.
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def imap_date(day):
    return f"{day.day:02d}-{MONTHS[day.month - 1]}-{day.year}"


def read_imap(cfg, day, warnings):
    client = connect(cfg)
    mails, opened = [], 0
    try:
        for folder in split_list(cfg.get("MAIL_FOLDERS")) or ["INBOX"]:
            # readonly=True + BODY.PEEK: 읽음 표시를 포함해 메일함을 바꾸지 않는다.
            quoted = '"' + encode_folder(folder).replace("\\", "\\\\").replace('"', '\\"') + '"'
            status, _ = client.select(quoted, readonly=True)
            if status != "OK":
                warnings.append(f"메일함 '{folder}'을(를) 열지 못해 건너뜀")
                continue
            opened += 1
            # 서버 시간대가 달라도 빠지지 않게 앞뒤 하루를 넉넉히 찾고, 아래에서 한국시간으로 거른다.
            _, data = client.search(None, "SINCE", imap_date(day - dt.timedelta(1)),
                                    "BEFORE", imap_date(day + dt.timedelta(2)))
            for num in (data[0] or b"").split():
                _, rows = client.fetch(num, "(INTERNALDATE BODY.PEEK[])")
                row = next((r for r in rows or [] if isinstance(r, tuple)), None)
                if row is None:
                    warnings.append(f"'{folder}'의 메일 1건을 읽지 못함")
                    continue
                # INTERNALDATE 위치는 서버마다 본문 앞 또는 뒤라서 둘 다 본다.
                meta = row[0] + b" " + b" ".join(r for r in rows if isinstance(r, bytes))
                received = None
                m = re.search(rb'INTERNALDATE "\s*(\d{1,2})-(\w{3})-(\d{4}) (\d\d):(\d\d):(\d\d) ([+-])(\d\d)(\d\d)"', meta)
                if m:
                    g = [x.decode() for x in m.groups()]
                    off = dt.timedelta(hours=int(g[7]), minutes=int(g[8])) * (1 if g[6] == "+" else -1)
                    received = dt.datetime(int(g[2]), MONTHS.index(g[1]) + 1, int(g[0]), int(g[3]),
                                           int(g[4]), int(g[5]), tzinfo=dt.timezone(off))
                mails.append(parse_mail(row[1], received=received, source=f"{folder}/{num.decode()}", folder=folder))
    finally:
        try:
            client.logout()
        except Exception:
            pass
    if not opened:
        raise ConfigError("지정한 메일함을 하나도 열지 못했습니다. "
                          "python scripts/collect_mail.py --list-folders 로 이름을 확인해 주세요.")
    return mails


# ---------------------------------------------------------------- 본인 메일
def normalize_addr(addr):
    local, _, domain = addr.lower().strip().partition("@")
    local = local.split("+")[0]  # me+todo@… 도 본인 주소로 본다.
    if domain in ("gmail.com", "googlemail.com"):
        local, domain = local.replace(".", ""), "gmail.com"
    return f"{local}@{domain}"


def auth_failed(mail):
    """받는 서버가 남긴 발신자 인증 결과. 주소를 도용한 '내가 보낸 척' 메일을 거른다."""
    result = mail["headers"].get("authentication-results", "").lower()
    if "dmarc=fail" in result:
        return True
    return bool(re.search(r"spf=(fail|softfail)", result)) and "dkim=pass" not in result


def direction(mail, mine):
    """self: 본인→본인, sent: 본인→타인, received: 받은 메일, spoofed: 본인 주소 도용 의심"""
    mine = {normalize_addr(a) for a in mine}
    if normalize_addr(mail["from_addr"]) not in mine:
        return "received"
    if auth_failed(mail):
        return "spoofed"
    to = {normalize_addr(a) for a in mail["recipients"]}
    return "self" if not to or to & mine else "sent"


# ---------------------------------------------------------------- 광고 판정
def squash(text):
    return re.sub(r"\s+", "", text or "").lower()


def load_rules(path=RULES_FILE):
    rules, limits = [], {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not line.strip().startswith("|"):
            continue
        if len(cells) == 5 and re.fullmatch(r"[A-Z]\d+", cells[0]):
            score = "확정" if cells[3] == "확정" else int(cells[3])
            rules.append({"id": cells[0], "where": cells[1], "words": [squash(w) for w in split_list(cells[2])],
                          "score": score, "why": cells[4]})
        elif len(cells) == 3 and cells[0] in ("광고 제외", "광고 의심"):
            limits[cells[0]] = int(cells[1])
    if not rules or len(limits) != 2:
        raise ConfigError(f"{path} 의 표를 읽지 못했습니다. 열 개수(5열)와 기준점수 표를 확인해 주세요.")
    return rules, limits


def domain_match(addr, entries):
    addr = addr.lower()
    domain = addr.partition("@")[2]
    for e in (x.lower().lstrip("@") for x in entries):
        if addr == e or ("@" not in e and domain and (domain == e or domain.endswith("." + e))):
            return True
    return False


def judge_ad(mail, rules, limits, trusted=(), blocked=()):
    """(판정, 점수, 이유). 판정은 '업무' '광고 의심' '광고'."""
    if domain_match(mail["from_addr"], blocked):
        return "광고", 999, ["차단 발신자"]
    if domain_match(mail["from_addr"], trusted) and not auth_failed(mail):
        return "업무", 0, ["신뢰 발신자"]
    subject = squash(mail["subject"])
    plain_subject = re.sub(r"^((re|fw|fwd|회신|전달):)+", "", subject)
    body, local = squash(mail["full_text"]), mail["from_addr"].partition("@")[0]
    score, reasons = 0, []
    for r in rules:
        where, words = r["where"], r["words"]
        if where == "제목 맨앞":
            hit = any(plain_subject.startswith(w) for w in words)
        elif where == "제목":
            hit = any(w in subject for w in words)
        elif where == "본문":
            hit = any(w in body for w in words)
        elif where == "발신자":
            hit = any(w in local for w in words)
        elif where == "헤더 있음":
            hit = any(w in mail["headers"] for w in words)
        elif where == "헤더 값":  # 이름=값
            hit = any(w.partition("=")[2] in squash(mail["headers"].get(w.partition("=")[0], ""))
                      for w in words if w.partition("=")[0] in mail["headers"])
        else:
            raise ConfigError(f"광고 기준표 {r['id']}의 위치 '{where}'를 알 수 없습니다.")
        if hit:
            if r["score"] == "확정":
                return "광고", 999, [f"{r['id']} {r['why']}"]
            score += r["score"]
            reasons.append(f"{r['id']} {r['why']}({r['score']:+d})")
    if score >= limits["광고 제외"]:
        return "광고", score, reasons
    return ("광고 의심" if score >= limits["광고 의심"] else "업무"), score, reasons


# ---------------------------------------------------------------- 보안, 개인정보
PII = [
    ("주민번호", re.compile(r"(?<!\d)\d{6}\s?-\s?[1-8]\d{6}(?!\d)")),
    ("카드번호", re.compile(r"(?<!\d)(?:\d{4}[- ]){3}\d{4}(?!\d)")),
    ("전화번호", re.compile(r"(?<!\d)(?:\+82[- ]?)?0?1[016789][-. ]?\d{3,4}[-. ]?\d{4}(?!\d)|(?<!\d)0\d{1,2}[-)]\s?\d{3,4}-\d{4}(?!\d)")),
    ("계좌번호", re.compile(r"(?<=계좌)[^\n\d]{0,20}\d[\d-]{8,18}\d")),
    ("이메일", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
]


def mask(text):
    for label, pattern in PII:
        text = pattern.sub(f"[{label} 가림]", text)
    return text


INJECTION = re.compile(
    r"(이전|앞선|위의?|기존)\s*(모든\s*)?(지시|명령|규칙|프롬프트)[^\n]{0,15}(무시|잊)"
    r"|ignore (all )?(previous|prior|above) instructions|시스템 프롬프트|system prompt", re.I)
