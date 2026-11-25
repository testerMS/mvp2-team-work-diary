"""수집 → 광고 제외 → 초안 → 점검 → HTML (→ 구글 시트 업로드) 을 한 번에 실행한다. (AI, API 키 없이 동작)

  python run_daily.py                   # 오늘, .env 에 적은 메일함
  python run_daily.py --date 2026-11-24
  python run_daily.py --sample          # 메일 계정 없이 샘플 메일로 체험
  python run_daily.py --upload          # 점검 경고가 없으면 다이어리(구글 시트)에 올린다
"""
import datetime as dt
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_report
import collect_mail
import draft_report
import mailcore
import publish_diary
import render_html


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    upload = "--upload" in args
    if upload:
        args.remove("--upload")
        if "--sample" in args:
            print("[설정 확인] 샘플(가상 기록)은 실제 다이어리에 섞이지 않도록 자동으로 올리지 않습니다.", file=sys.stderr)
            return 2
    if "--sample" in args:
        args.remove("--sample")
        os.environ["REPORT_AUTHOR"] = "홍길동(가상)"
        args += ["--eml-dir", str(ROOT / "samples" / "mailbox"), "--date", "2026-11-24",
                 "--me", "me@mycompany.example", "--trusted", "mycompany.example",
                 "--out", str(ROOT / "output" / "sample")]
    if not any(a == "--out" or a.startswith("--out=") for a in args):
        day = next((args[i + 1] for i, a in enumerate(args[:-1]) if a == "--date"), None) \
            or next((a.split("=", 1)[1] for a in args if a.startswith("--date=")), None) \
            or dt.datetime.now(mailcore.KST).date().isoformat()
        args += ["--out", str(ROOT / "output" / day)]
    out = next((args[i + 1] for i, a in enumerate(args[:-1]) if a == "--out"), None) \
        or next(a.split("=", 1)[1] for a in args if a.startswith("--out="))
    code = collect_mail.main(args)
    if code or "--list-folders" in args:
        return code
    draft_report.main([out])
    warnings = check_report.main([out])
    render_html.main([out])
    if upload:
        # 경고가 있으면 publish_diary 가 스스로 멈춘다. 확인되지 않은 기록은 올라가지 않는다.
        return publish_diary.main([out]) or warnings
    return warnings


if __name__ == "__main__":
    sys.exit(main())
