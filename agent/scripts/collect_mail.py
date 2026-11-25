"""지정한 메일함에서 하루치 메일을 모아 광고를 빼고 mails.json 으로 저장한다.

사용법
  python scripts/collect_mail.py                          # 오늘, .env 의 메일함
  python scripts/collect_mail.py --date 2026-11-24
  python scripts/collect_mail.py --eml-dir samples/mailbox --date 2026-11-24 --me me@example.com
  python scripts/collect_mail.py --list-folders           # 메일함 이름 확인
"""
import argparse
import csv
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mailcore as mc


def sender_label(mail):
    """보고서에는 이름만 쓴다. 이름이 없으면 도메인으로 대신해 주소를 남기지 않는다."""
    name = mail["from_name"]
    if name and "@" not in name:
        return name
    return f"{mail['from_addr'].partition('@')[2] or '발신자 불명'} 발신자"


def classify(mails, day, mine, trusted=(), blocked=(), extra_warnings=()):
    rules, limits = mc.load_rules()
    kept, excluded, seen, out_of_day = [], [], set(), 0
    for m in sorted(mails, key=lambda x: x["received"] or dt.datetime.max.replace(tzinfo=mc.KST)):
        if m["message_id"] in seen:  # 같은 메일이 받은편지함과 보낸편지함에 함께 있는 경우
            continue
        seen.add(m["message_id"])
        if m["received"] and m["received"].date() != day:
            out_of_day += 1
            continue
        kind = mc.direction(m, mine)
        flags = []
        verdict, score, reasons = ("업무", 0, []) if kind in ("self", "sent") else \
            mc.judge_ad(m, rules, limits, trusted, blocked)
        if verdict == "광고":
            excluded.append({"수신시각": m["received"].strftime("%H:%M") if m["received"] else "불명",
                             "발신자": m["from_addr"], "제목": m["subject"],
                             "점수": "확정" if score == 999 else score, "제외 이유": " / ".join(reasons)})
            continue
        if verdict == "광고 의심":
            flags.append(f"광고 의심({score}점)")
        if kind == "spoofed":
            flags.append("본인 주소 도용 의심(발신자 인증 실패)")
        if mc.INJECTION.search(m["subject"] + "\n" + m["full_text"]):
            flags.append("AI 지시문 포함(따르지 않음)")
        if not m["received"]:
            flags.append("수신일시 불명")
        if m["truncated"]:
            flags.append("본문이 길어 일부만 읽음")
        # 본인 메일은 제목만 적어 보내는 경우가 많아, 첨부가 있을 때만 확인을 요청한다.
        if not m["body"] and (kind != "self" or m["attachments"]):
            flags.append("본문 없음(첨부 또는 이미지 확인)")
        kept.append({
            "id": f"M{len(kept) + 1:02d}", "kind": "received" if kind == "spoofed" else kind,
            "time": m["received"].strftime("%H:%M") if m["received"] else "불명",
            "from": mc.mask(sender_label(m)), "subject": mc.mask(m["subject"]), "body": mc.mask(m["body"]),
            "attachments": [mc.mask(a) for a in m["attachments"]], "folder": m["folder"], "flags": flags,
        })
    stats = {"수집": len(kept) + len(excluded), "광고 제외": len(excluded),
             "받은 업무 메일": sum(k["kind"] == "received" for k in kept),
             "본인 메일": sum(k["kind"] == "self" for k in kept),
             "보낸 메일": sum(k["kind"] == "sent" for k in kept)}
    return {"date": day.isoformat(), "stats": stats, "warnings": list(extra_warnings), "mails": kept}, excluded, out_of_day


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="하루치 메일 수집 + 광고 제외")
    ap.add_argument("--date", help="YYYY-MM-DD (기본: 오늘)")
    ap.add_argument("--eml-dir", help=".eml 파일 폴더 (메일 서버 대신 사용)")
    ap.add_argument("--me", help="내 메일 주소, 쉼표로 여러 개 (기본: .env 의 MY_ADDRESSES)")
    ap.add_argument("--trusted", help="항상 업무로 볼 도메인 또는 주소 (기본: .env 의 TRUSTED_SENDERS)")
    ap.add_argument("--out", help="저장 폴더 (기본: output/날짜)")
    ap.add_argument("--list-folders", action="store_true", help="메일함 이름만 보여 준다")
    args = ap.parse_args(argv)
    try:
        cfg = mc.load_env()
        if args.list_folders:
            client = mc.connect(cfg)
            print("\n".join(mc.list_folders(client)))
            client.logout()
            return 0
        try:
            day = dt.date.fromisoformat(args.date) if args.date else dt.datetime.now(mc.KST).date()
        except ValueError:
            raise mc.ConfigError(f"날짜는 2026-11-24 형식으로 적어 주세요: {args.date}")
        mine = mc.split_list(args.me or cfg.get("MY_ADDRESSES") or cfg.get("MAIL_USER"))
        if not mine:
            raise mc.ConfigError("본인 메일을 구분하려면 내 주소가 필요합니다. .env 의 MY_ADDRESSES 또는 --me 를 적어 주세요.")
        warnings = []
        if args.eml_dir:
            mails, box = mc.read_eml_folder(args.eml_dir), Path(args.eml_dir).name
        else:
            mails, box = mc.read_imap(cfg, day, warnings), ", ".join(mc.split_list(cfg.get("MAIL_FOLDERS")) or ["INBOX"])
        trusted = mc.split_list(args.trusted if args.trusted is not None else cfg.get("TRUSTED_SENDERS"))
        result, excluded, skipped = classify(mails, day, mine, trusted, mc.split_list(cfg.get("BLOCKED_SENDERS")), warnings)
        result["mailbox"], result["author"] = box, cfg.get("REPORT_AUTHOR") or "미정"
        out = Path(args.out) if args.out else mc.ROOT / "output" / day.isoformat()
        out.mkdir(parents=True, exist_ok=True)
        (out / "mails.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        # utf-8-sig: 엑셀에서 바로 열어도 한글이 깨지지 않는다.
        with (out / "excluded.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, ["수신시각", "발신자", "제목", "점수", "제외 이유"])
            w.writeheader()
            # 제목이 =, +, -, @ 로 시작하면 엑셀이 수식으로 실행할 수 있어 앞에 ' 를 붙인다.
            w.writerows([{k: f"'{v}" if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v
                          for k, v in row.items()} for row in excluded])
    except mc.ConfigError as e:
        print(f"[설정 확인] {e}", file=sys.stderr)
        return 2
    s = result["stats"]
    print(f"[수집] {day} 대상 {s['수집']}건 = 받은 업무 {s['받은 업무 메일']} + 본인 {s['본인 메일']} + 보낸 {s['보낸 메일']} + 광고 제외 {s['광고 제외']}"
          f" (다른 날짜 {skipped}건은 대상 아님)")
    for w in warnings:
        print(f"[주의] {w}")
    print(f"[저장] {out / 'mails.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
