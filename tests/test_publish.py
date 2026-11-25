"""업로드 스크립트 자동 시험. 내 PC의 시험 서버(Code.gs 그대로 실행)에 실제로 올려 본다.

사용법: python tests/test_publish.py     (Node.js 필요)
"""
import contextlib
import datetime as dt
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT / "agent"
sys.path.insert(0, str(AGENT / "scripts"))
sys.path.insert(0, str(AGENT))
import publish_diary as pub
import join_team
import run_daily

BASE = dt.date(2026, 11, 24)
SAMPLE = AGENT / "samples" / "result"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class 변환(unittest.TestCase):
    def setUp(self):
        self.p = pub.load_day(SAMPLE)

    def test_항목수와_칸(self):
        kinds = [i["kind"] for i in self.p["items"]]
        self.assertEqual({k: kinds.count(k) for k in set(kinds)}, {"한 일": 3, "공유": 1, "할 일": 5, "계획": 2})
        self.assertEqual(len(self.p["day"]["core"]), 3)
        self.assertEqual(self.p["day"]["author"], "홍길동(가상)")

    def test_할일_기한과_근거(self):
        todo = [i for i in self.p["items"] if i["kind"] == "할 일"]
        self.assertEqual([t["due"] for t in todo], ["2026-11-24", "2026-11-26", "2026-11-27", "2026-11-30", ""])
        self.assertEqual((todo[0]["who"], todo[0]["priority"], todo[0]["refs"]), ("대성오토 구매팀", "긴급", "[M02]"))

    def test_해당없음은_기록하지_않음(self):
        self.assertNotIn("해당 없음", json.dumps(self.p, ensure_ascii=False))

    def test_해를_넘기는_기한(self):
        self.assertEqual(pub.iso_due("1. 5.(화)", dt.date(2026, 12, 28)), "2027-01-05")
        self.assertEqual(pub.iso_due("12. 30.(수)", dt.date(2027, 1, 4)), "2026-12-30")
        self.assertEqual(pub.iso_due("미정", BASE), "")

    def test_메일원문과_광고는_올리지_않음(self):
        text = json.dumps(self.p, ensure_ascii=False)
        for secret in ("promo@officemall.example", "사무용품 최대", "안녕하세요"):
            self.assertNotIn(secret, text)

    def test_아래줄은_윗항목에_붙음(self):
        self.assertEqual(pub.bullets("□ 가\n  ○ 나\n  - 다\n□ 라"), ["가 나 다", "라"])


class 막아야_하는_것(unittest.TestCase):
    def test_점검경고가_있으면_올리지_않음(self):
        with tempfile.TemporaryDirectory() as tmp:
            for n in ("report.md", "mails.json", "excluded.csv"):
                shutil.copy(SAMPLE / n, tmp)
            f = Path(tmp) / "report.md"
            f.write_text(f.read_text(encoding="utf-8").replace("안전교육 이수함", "안전교육 이수함 010-1234-5678"), encoding="utf-8")
            with self.assertRaisesRegex(pub.UploadError, "점검 경고"):
                pub.load_day(tmp)

    def test_열쇠는_구글_웹앱으로만(self):
        pub.check_url("https://script.google.com/macros/s/abc/exec")
        for bad in ("https://evil.example/exec", "http://script.google.com/macros/s/a/exec", "https://script.google.com.evil.example/exec",
                    "https://script.google.com/macros/s/a/dev", "https://script.google.com@evil.example/exec", "file:///exec"):
            with self.assertRaises(pub.UploadError, msg=bad):
                pub.check_url(bad)

    def test_샘플은_실제_다이어리에_자동으로_올리지_않음(self):
        with contextlib.redirect_stderr(io.TextIOWrapper(io.BytesIO(), encoding="utf-8")):
            self.assertEqual(run_daily.main(["--sample", "--upload"]), 2)


class 실제업로드(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.server = subprocess.Popen(["node", str(ROOT / "tests" / "local_server.js"), str(cls.port)], stdout=subprocess.PIPE)
        cls.server.stdout.readline()
        cls.url = f"http://127.0.0.1:{cls.port}/exec"
        os.environ["DIARY_URL"], os.environ["DIARY_TOKEN"] = cls.url, "T01.upload-test"

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.wait()
        cls.server.stdout.close()
        del os.environ["DIARY_URL"], os.environ["DIARY_TOKEN"]

    def call(self, fn, *args):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/call", data=json.dumps([fn, args]).encode())
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    def quiet(self, argv):
        out, err = io.TextIOWrapper(io.BytesIO(), encoding="utf-8"), io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = pub.main(argv)
        out.seek(0), err.seek(0)
        return code, out.read() + err.read()

    def test_올리고_검색까지(self):
        self.assertEqual(self.quiet(["--ping"])[0], 0)
        self.assertEqual(self.quiet([str(SAMPLE)])[0], 0)
        code, text = self.quiet([str(SAMPLE)])
        self.assertIn("이전 11건 교체", text)
        s = self.call("apiLogin", "T01-lead-test")["session"]
        day = self.call("apiOpen", s, "", "2026-11-24")
        self.assertEqual((len(day["items"]), day["day"]["stats"]["수집"]), (11, 11))
        found = self.call("apiSearch", s, {"keyword": "한빛", "from": "2026-11-01", "to": "2026-11-30"})
        self.assertEqual(found["total"], 2)  # 핵심 1 + 한 일 1

    def test_열쇠가_틀리면(self):
        os.environ["DIARY_TOKEN"] = "wrong"
        try:
            code, text = self.quiet([str(SAMPLE)])
        finally:
            os.environ["DIARY_TOKEN"] = "T01.upload-test"
        self.assertEqual(code, 1)
        self.assertIn("열쇠가 맞지 않거나", text)

    def test_로그인화면이_돌아오면_안내(self):
        with self.assertRaisesRegex(pub.UploadError, "모든 사용자"):
            pub.send(f"http://127.0.0.1:{self.port}/", {})

    def test_팀원이_같은_DB에_올림(self):
        self.quiet([str(SAMPLE)])
        os.environ["DIARY_TOKEN"] = "T02.upload-test"
        try:
            code, text = self.quiet([str(SAMPLE)])
        finally:
            os.environ["DIARY_TOKEN"] = "T01.upload-test"
        self.assertIn("김민지 2026-11-24", text)
        s = self.call("apiLogin", "T01-lead-test")["session"]
        team = self.call("apiTeam", s, "2026-11-23", "2026-11-27")
        self.assertEqual([(m["name"], m["done"]) for m in team["members"]], [("홍길동", 3), ("김민지", 3)])

    def test_바쁘면_다시_시도(self):
        calls, real = [], pub.send

        def twice_busy(url, body, timeout=60):
            calls.append(1)
            if len(calls) < 3:
                raise pub.UploadError("BUSY: 저장 중")
            return {"ok": True}

        def always_busy(url, body, timeout=60):
            raise pub.UploadError("BUSY: 저장 중")
        try:
            with contextlib.redirect_stdout(io.TextIOWrapper(io.BytesIO(), encoding="utf-8")):
                pub.send = twice_busy
                self.assertTrue(pub.send_retry("u", {}, (0, 0))["ok"])
                pub.send = always_busy
                with self.assertRaisesRegex(pub.UploadError, "^저장 중"):
                    pub.send_retry("u", {}, (0, 0))
        finally:
            pub.send = real

    def join(self, answers, secrets, path):
        a, s = iter(answers), iter(secrets)
        out, err = io.TextIOWrapper(io.BytesIO(), encoding="utf-8"), io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = join_team.main(path, lambda q: next(a), lambda q: next(s))
        out.seek(0), err.seek(0)
        return code, out.read() + err.read()

    def test_팀원_처음설정(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            answers = ["https://evil.example/exec", self.url, "imap.gmail.com", "kim@mycompany.example", "", "", "mycompany.example", "김민지"]
            code, text = self.join(answers, ["T02.upload-test\r\n", "app-password"], env)
            self.assertEqual(code, 0, text)
            self.assertIn("김민지 님으로", text)
            self.assertNotIn("upload-test", text)
            self.assertNotIn("app-password", text)
            v = join_team.read_values(env)
            self.assertEqual((v["DIARY_TOKEN"], v["MAIL_FOLDERS"], v["REPORT_AUTHOR"]), ("T02.upload-test", "INBOX", "김민지"))
            code, _ = self.join([""] * 7, ["", ""], env)          # 다시 실행해 Enter 만 눌러도 값이 남는다
            self.assertEqual((code, join_team.read_values(env)), (0, v))

    def test_열쇠가_틀리면_저장하지_않음(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            code, text = self.join([self.url] + [""] * 6, ["T02.wrong", ""], env)
            self.assertEqual((code, env.exists()), (1, False))

    def test_연결_안됨(self):
        with self.assertRaisesRegex(pub.UploadError, "연결하지 못"):
            pub.send(f"http://127.0.0.1:{free_port()}/exec", {}, timeout=3)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    unittest.main(verbosity=2)
