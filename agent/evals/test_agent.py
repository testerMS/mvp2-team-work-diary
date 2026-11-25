"""자동 시험. 메일 계정 없이 실행된다.

사용법: python evals/test_agent.py
"""
import contextlib
import datetime as dt
import imaplib
import io
import json
import re
import socketserver
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "evals")]
import check_report
import collect_mail
import draft_report
import mailcore as mc
import make_cases
import render_html

DAY = dt.date(2026, 11, 24)
ME = "me@mycompany.example"


def run(folder):
    mails = mc.read_eml_folder(ROOT / folder)
    data, excluded, skipped = collect_mail.classify(mails, DAY, [ME], ["mycompany.example"])
    report = draft_report.build(data)
    return data, excluded, skipped, report, check_report.check(report, data, excluded)


def section(report, n):
    return re.search(rf"(?ms)^## {n}\..*?\n(.*?)(?=^## |\Z)", report)[1]


class 정상1_하루전체(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.excluded, cls.skipped, cls.report, cls.warn = run("samples/mailbox")

    def test_건수(self):
        self.assertEqual(self.data["stats"], {"수집": 11, "광고 제외": 3, "받은 업무 메일": 4, "본인 메일": 3, "보낸 메일": 1})
        self.assertEqual(self.skipped, 1)

    def test_본인메일_칸나눔(self):
        self.assertIn("안전교육 이수", section(self.report, 2))
        self.assertIn("신규 거래처 등록 서류 준비", section(self.report, 4))
        self.assertIn("오전 10시 주간회의 참석", section(self.report, 5))
        self.assertIn("차량 점검 예약", section(self.report, 4))

    def test_보낸메일은_한일(self):
        self.assertIn('"견적서 송부" 메일 발송', section(self.report, 2))

    def test_인용문_기한을_쓰지_않음(self):
        self.assertNotIn("12. 31.", self.report)
        self.assertIn("11. 30.(월)", section(self.report, 4))

    def test_개인정보_광고_없음(self):
        self.assertNotIn("010-1234-5678", self.report + json.dumps(self.data, ensure_ascii=False))
        for row in self.excluded:
            self.assertNotIn(row["제목"], self.report)

    def test_점검_경고0(self):
        self.assertEqual(self.warn, [])


class 정상2_본인메일만(unittest.TestCase):
    def test_모두_반영(self):
        data, excluded, _, report, warn = run("evals/files/normal-2-self-only")
        self.assertEqual((data["stats"]["본인 메일"], excluded, warn), (4, [], []))
        self.assertIn("월간 재고 조사", section(report, 2))
        self.assertIn("전산팀에 스팸 차단 요청하기", section(report, 4))
        self.assertIn("포장재 단가", section(report, 3))
        self.assertIn("해당 없음", section(report, 6))


class 정상3_헷갈리는광고(unittest.TestCase):
    def test_판정(self):
        data, excluded, _, report, warn = run("evals/files/normal-3-tricky-ads")
        self.assertEqual({r["제목"] for r in excluded},
                         {"( 광 고 ) 대표님만 모시는 세미나", "정책자금 안내 드립니다", "Re: 회의 일정 쿠폰 증정 혜택"})
        self.assertIn("광고 시안 검토", section(report, 4))
        self.assertIn("신제품 소식 안내", section(report, 6))
        self.assertNotIn("신제품 소식 안내", "".join(section(report, n) for n in (2, 3, 4, 5)))
        self.assertIn("3,200만원", section(report, 3))
        self.assertEqual(warn, [])


class 예외1_광고만(unittest.TestCase):
    def test_지어내지_않음(self):
        data, excluded, _, report, warn = run("evals/files/exception-1-ads-only")
        self.assertEqual((data["mails"], len(excluded), warn), ([], 2, []))
        self.assertIn("보고할 업무 메일 없음", report)

    def test_메일_0건(self):
        data, excluded, _ = collect_mail.classify([], DAY, [ME])
        self.assertEqual(check_report.check(draft_report.build(data), data, excluded), [])


class 예외2_위험한메일(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.excluded, _, cls.report, cls.warn = run("evals/files/exception-2-unsafe")

    def test_도용과_지시문은_확인필요로(self):
        self.assertEqual(self.data["stats"]["본인 메일"], 0)
        self.assertIn("도용 의심", section(self.report, 6))
        self.assertIn("AI 지시문", section(self.report, 6))
        work = "".join(section(self.report, n) for n in (2, 3, 4, 5))
        self.assertNotIn("비트코인", work)
        self.assertNotIn("자료 요청", work)

    def test_한글_중복_날짜없음(self):
        self.assertIn("최과장", self.report)
        self.assertIn("출장 보고서를 12월 1일까지", self.report)
        self.assertEqual(sum(m["subject"] == "중복 메일 확인 요청" for m in self.data["mails"]), 1)
        self.assertIn("수신일시 불명", section(self.report, 6))

    def test_개인정보_가림(self):
        text = self.report + json.dumps(self.data, ensure_ascii=False)
        for secret in ("900101-1234567", "123-456-789012", "hong@private.example", "02-123-4567", "attacker@evil.example"):
            self.assertNotIn(secret, text)
        self.assertEqual(self.warn, [])


class 점검스크립트(unittest.TestCase):
    """일부러 망가뜨린 보고서를 점검이 잡아내는지 본다."""

    def setUp(self):
        self.data, self.excluded, _, self.report, _ = run("samples/mailbox")

    def broken(self, old, new):
        self.assertIn(old, self.report)
        return " / ".join(check_report.check(self.report.replace(old, new), self.data, self.excluded))

    def test_잡아냄(self):
        self.assertIn("근거가 메일에 없음", self.broken("11. 26.(목)", "12. 3.(목)"))
        self.assertIn("원본에 없는 수치", self.broken("안전교육 이수", "안전교육 이수 및 500만원 절감"))
        self.assertIn("없는 메일 번호", self.broken("안전교육 이수 [M04]", "안전교육 이수 [M99]"))
        self.assertIn("근거 메일 번호가 없음", self.broken("안전교육 이수 [M04]", "안전교육 이수"))
        self.assertIn("개인정보(전화번호)", self.broken("안전교육 이수", "안전교육 이수 010-1111-2222"))
        self.assertIn("광고로 제외한 메일", self.broken("안전교육 이수", "쿠폰 도착! 오늘만 무료체험"))
        self.assertIn("항목 누락", self.broken("## 5. 내일 계획", "## 5. 계획"))
        self.assertIn("건수", self.broken("광고 제외 3건", "광고 제외 1건"))


class 기한계산(unittest.TestCase):
    def test_표현별(self):
        for text, want in {"11월 26일까지": (2026, 11, 26), "11/27까지": (2026, 11, 27), "11. 30.까지": (2026, 11, 30),
                           "2027-01-05까지": (2027, 1, 5), "1월 5일까지": (2027, 1, 5), "내일까지": (2026, 11, 25),
                           "금요일까지": (2026, 11, 27), "월요일까지": (2026, 11, 30), "다음 주 월요일까지": (2026, 11, 30)}.items():
            self.assertEqual(draft_report.find_deadline(text, DAY), dt.date(*want), text)
        for text in ("검토 부탁드립니다", "3.5% 인상", "13월 40일", "1.5배"):
            self.assertIsNone(draft_report.find_deadline(text, DAY), text)


class 본인메일판별(unittest.TestCase):
    def kind(self, sender, to):
        raw = f"From: {sender}\r\nTo: {to}\r\nSubject: t\r\n\r\nb".encode()
        return mc.direction(mc.parse_mail(raw), ["me@gmail.com"])

    def test_주소변형(self):
        self.assertEqual(self.kind("m.e@gmail.com", "me+todo@gmail.com"), "self")
        self.assertEqual(self.kind("me@gmail.com", "other@x.example"), "sent")
        self.assertEqual(self.kind("other@x.example", "me@gmail.com"), "received")
        self.assertEqual(self.kind("me@gmail.com", "Lee, Min <a@x.example>"), "sent")
        self.assertEqual(self.kind('"me@gmail.com" <evil@x.example>', "me@gmail.com"), "received")


class FakeImap(socketserver.StreamRequestHandler):
    """실제 IMAP 문법으로 답하는 시험용 서버. 받은 명령을 기록한다."""
    log, boxes = [], {}

    def handle(self):
        send = lambda b: self.wfile.write(b + b"\r\n")
        send(b"* OK ready")
        for line in self.rfile:
            tag, _, cmd = line.strip().partition(b" ")
            self.log.append(cmd.decode())
            word = cmd.split()[0].upper()
            if word == b"CAPABILITY":
                send(b"* CAPABILITY IMAP4rev1")
            elif word == b"LIST":
                send(b'* LIST (\\HasNoChildren) "/" "INBOX"')
                send(b'* LIST (\\HasNoChildren) "/" "' + mc.encode_folder("내게쓴메일함").encode() + b'"')
            elif word in (b"EXAMINE", b"SELECT"):
                name = cmd.split(b" ", 1)[1].strip(b'"').decode()
                if name not in self.boxes:
                    send(tag + b" NO no such mailbox")
                    continue
                self.box = self.boxes[name]
                send(b"* %d EXISTS" % len(self.box))
            elif word == b"SEARCH":
                send(b"* SEARCH " + b" ".join(b"%d" % (i + 1) for i in range(len(self.box))))
            elif word == b"FETCH":
                n = int(cmd.split()[1])
                raw, internal = self.box[n - 1]
                send(b'* %d FETCH (INTERNALDATE "%s" BODY[] {%d}' % (n, internal, len(raw)))
                self.wfile.write(raw + b")\r\n")
            elif word == b"LOGIN" and b"wrong" in cmd:
                send(tag + b" NO login failed")
                continue
            elif word == b"LOGOUT":
                send(b"* BYE")
                send(tag + b" OK")
                return
            send(tag + b" OK done")


class 메일서버_IMAP(unittest.TestCase):
    def setUp(self):
        at = b"24-Nov-2026 09:00:00 +0900"
        FakeImap.log.clear()
        FakeImap.boxes = {
            "INBOX": [(make_cases.NORMAL_1[0], at), (make_cases.NORMAL_1[2], at),
                      # 세계표준시 23일 16시 = 한국시간 24일 01시. 24일 보고서에 들어가야 한다.
                      (make_cases.mail("새벽 메일", make_cases.BOSS, "공유드립니다\n"), b"23-Nov-2026 16:00:00 +0000"),
                      (make_cases.mail("전날 메일", make_cases.BOSS, "공유드립니다\n"), b"23-Nov-2026 14:00:00 +0000")],
            mc.encode_folder("내게쓴메일함"): [(make_cases.NORMAL_1[4], at)]}
        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), FakeImap)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.original = imaplib.IMAP4_SSL
        imaplib.IMAP4_SSL = imaplib.IMAP4  # 시험 서버는 암호화가 없어 이 시험에서만 바꾼다.
        self.cfg = {"MAIL_HOST": "127.0.0.1", "MAIL_PORT": self.server.server_address[1], "MAIL_USER": ME,
                    "MAIL_PASSWORD": "test", "MAIL_FOLDERS": "INBOX,내게쓴메일함,없는메일함"}

    def tearDown(self):
        imaplib.IMAP4_SSL = self.original
        self.server.shutdown()
        self.server.server_close()

    def test_수집(self):
        warnings = []
        mails = mc.read_imap(self.cfg, DAY, warnings)
        data, excluded, skipped = collect_mail.classify(mails, DAY, [ME])
        self.assertEqual(data["stats"], {"수집": 4, "광고 제외": 1, "받은 업무 메일": 2, "본인 메일": 1, "보낸 메일": 0})
        self.assertEqual((skipped, len(warnings)), (1, 1))
        self.assertIn("새벽 메일", [m["subject"] for m in data["mails"]])

    def test_메일함을_바꾸지_않음(self):
        mc.read_imap(self.cfg, DAY, [])
        words = " ".join(FakeImap.log).upper()
        for bad in ("SELECT ", "STORE", "EXPUNGE", "DELETE", "COPY", "APPEND"):
            self.assertNotIn(bad, words)
        self.assertIn("BODY.PEEK[]", words)
        self.assertIn("SINCE 23-NOV-2026 BEFORE 26-NOV-2026", words)

    def test_메일함_이름과_오류안내(self):
        client = mc.connect(self.cfg)
        self.assertEqual(mc.list_folders(client), ["INBOX", "내게쓴메일함"])
        client.logout()
        with self.assertRaisesRegex(mc.ConfigError, "앱 비밀번호"):
            mc.connect({**self.cfg, "MAIL_PASSWORD": "wrong"})
        with self.assertRaisesRegex(mc.ConfigError, "하나도 열지 못"):
            mc.read_imap({**self.cfg, "MAIL_FOLDERS": "없음"}, DAY, [])
        with self.assertRaisesRegex(mc.ConfigError, "MAIL_PASSWORD"):
            mc.connect({"MAIL_HOST": "x", "MAIL_USER": "y"})


class 파일저장(unittest.TestCase):
    def test_CSV_수식과_HTML_태그(self):
        with tempfile.TemporaryDirectory() as tmp:
            box = Path(tmp) / "box"
            make_cases.save(box, [make_cases.mail("=HYPERLINK(1)", ("광고", "promo@x.example"), "구매하기 수신거부\n", **make_cases.UNSUB),
                                  make_cases.mail("<script>alert(1)</script> 공유", make_cases.BOSS, "공유드립니다\n")])
            with contextlib.redirect_stdout(io.TextIOWrapper(io.BytesIO(), encoding="utf-8")), \
                    contextlib.redirect_stderr(io.TextIOWrapper(io.BytesIO(), encoding="utf-8")):
                self.assertEqual(collect_mail.main(["--eml-dir", str(box), "--date", "2026-11-24", "--me", ME, "--out", tmp]), 0)
                self.assertEqual(draft_report.main([tmp]), 0)
                self.assertEqual(check_report.main([tmp]), 0)
                render_html.main([tmp])
                self.assertEqual(collect_mail.main(["--date", "24일", "--me", ME, "--eml-dir", str(box)]), 2)
            self.assertIn("'=HYPERLINK", (Path(tmp) / "excluded.csv").read_text(encoding="utf-8-sig"))
            self.assertNotIn("<script>", (Path(tmp) / "report.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    unittest.main(verbosity=2)
