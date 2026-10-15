"""
업무 문서 PDF (구매요청서 · 물품 검수조서 · 불용품 처분 결의서 · 퇴사 자산 반납 확인서)

A4 세로, 결재란 포함. 한글 글꼴은 ui.py와 같은 목록에서 찾습니다(맑은 고딕·나눔고딕·Noto CJK).
"""
from __future__ import annotations

import io
import re

from PIL import Image, ImageDraw

import data as d
import ui

W, H = 1240, 1754          # A4 150dpi
M = 80                     # 여백
LINE = (60, 60, 60)
SHADE = (235, 240, 247)


class _Doc:
    def __init__(self, title: str, doc_no: str):
        self.pages: list[Image.Image] = []
        self.title, self.doc_no = title, doc_no
        self.f_title, self.f_h, self.f, self.f_s = ui._font(46, True), ui._font(26, True), ui._font(22), ui._font(18)
        self._new_page()

    def _new_page(self):
        self.img = Image.new("RGB", (W, H), "white")
        self.dr = ImageDraw.Draw(self.img)
        self.pages.append(self.img)
        self.y = M
        company = d.clean_str(d.get_settings().get("회사명"))
        self.dr.text((M, H - M + 20), f"{company + ' · ' if company else ''}자산관리 AI · {self.doc_no} · {len(self.pages)}쪽",
                     font=self.f_s, fill=(120, 120, 120))

    def need(self, h: int):
        if self.y + h > H - M - 20:
            self._new_page()

    def header(self, approvals: list[tuple[str, str, str]]):
        """제목 + 오른쪽 결재란. approvals: [(직위, 이름, 날짜)]"""
        company = d.clean_str(d.get_settings().get("회사명"))
        if company:
            self.dr.text((M, self.y), company, font=self.f, fill=(90, 90, 90))
        self.dr.text((M, self.y + 40), self.title, font=self.f_title, fill="black")
        self.dr.text((M, self.y + 110), f"문서번호 {self.doc_no}   ·   출력일 {d.today()}", font=self.f_s, fill=(90, 90, 90))
        if approvals:
            cw, ch1, ch2 = 130, 40, 90
            x0 = W - M - cw * len(approvals) - 40
            self.dr.rectangle([x0, self.y, x0 + 40, self.y + ch1 + ch2], outline=LINE, width=2, fill=SHADE)
            for i, ch in enumerate("결재"):
                self.dr.text((x0 + 9, self.y + 25 + i * 40), ch, font=self.f, fill="black")
            for i, (role, name, when) in enumerate(approvals):
                x = x0 + 40 + i * cw
                self.dr.rectangle([x, self.y, x + cw, self.y + ch1], outline=LINE, width=2, fill=SHADE)
                self.dr.rectangle([x, self.y + ch1, x + cw, self.y + ch1 + ch2], outline=LINE, width=2)
                self._center(role, x, self.y + 8, cw, self.f_s)
                if name:
                    self._center(name, x, self.y + ch1 + 18, cw, self.f)
                    self._center(when, x, self.y + ch1 + 56, cw, self.f_s, (90, 90, 90))
        self.y += 170

    def _center(self, text, x, y, w, font, fill="black"):
        text = ui._fit(self.dr, text, font, w - 8)
        tw = self.dr.textlength(text, font=font)
        self.dr.text((x + (w - tw) / 2, y), text, font=font, fill=fill)

    def heading(self, text: str):
        self.need(70)
        self.y += 14
        self.dr.text((M, self.y), text, font=self.f_h, fill=(20, 50, 100))
        self.y += 44

    def grid(self, pairs: list[tuple[str, str]], cols: int = 2):
        """항목-내용 표 (cols쌍/행)."""
        lw = 170
        cw = (W - 2 * M) // cols
        for i in range(0, len(pairs), cols):
            self.need(52)
            for j, (k, v) in enumerate(pairs[i:i + cols]):
                x = M + j * cw
                self.dr.rectangle([x, self.y, x + lw, self.y + 50], outline=LINE, width=1, fill=SHADE)
                self.dr.rectangle([x + lw, self.y, x + cw, self.y + 50], outline=LINE, width=1)
                self.dr.text((x + 12, self.y + 13), ui._fit(self.dr, k, self.f, lw - 20), font=self.f, fill="black")
                self.dr.text((x + lw + 12, self.y + 13), ui._fit(self.dr, d.clean_str(v) or "-", self.f, cw - lw - 20),
                             font=self.f, fill="black")
            self.y += 50

    def paragraph(self, text: str):
        text = d.clean_str(text) or "-"
        maxw = W - 2 * M - 24
        lines = []
        for raw in text.split("\n"):
            cur = ""
            for ch in raw:
                if self.dr.textlength(cur + ch, font=self.f) > maxw:
                    lines.append(cur)
                    cur = ch
                else:
                    cur += ch
            lines.append(cur)
        h = 24 + 34 * len(lines)
        self.need(min(h, 600))
        self.dr.rectangle([M, self.y, W - M, self.y + h], outline=LINE, width=1)
        for i, line in enumerate(lines):
            if self.y + 12 + i * 34 > H - M - 50:
                break
            self.dr.text((M + 12, self.y + 12 + i * 34), line, font=self.f, fill="black")
        self.y += h + 6

    def table(self, cols: list[tuple[str, float]], rows: list[list]):
        """cols: [(제목, 너비 비율)]"""
        total = sum(w for _, w in cols)
        widths = [(W - 2 * M) * w / total for _, w in cols]

        def draw_header():
            x = M
            for (name, _), w in zip(cols, widths):
                self.dr.rectangle([x, self.y, x + w, self.y + 44], outline=LINE, width=1, fill=SHADE)
                self._center(name, x, self.y + 11, w, self.f_s)
                x += w
            self.y += 44
        draw_header()
        for r in rows:
            if self.y + 42 > H - M - 20:
                self._new_page()
                draw_header()
            x = M
            for v, w in zip(r, widths):
                self.dr.rectangle([x, self.y, x + w, self.y + 42], outline=LINE, width=1)
                text = f"{v:,}" if isinstance(v, (int, float)) and not isinstance(v, bool) else d.clean_str(v)
                font = self.f_s
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    tw = self.dr.textlength(text, font=font)
                    self.dr.text((x + w - tw - 10, self.y + 11), text, font=font, fill="black")
                else:
                    self.dr.text((x + 8, self.y + 11), ui._fit(self.dr, text, font, w - 14), font=font, fill="black")
                x += w
            self.y += 42

    def signatures(self, roles: list[str]):
        self.need(150)
        self.y += 20
        cw = (W - 2 * M) // len(roles)
        for i, role in enumerate(roles):
            x = M + i * cw
            self.dr.text((x + 10, self.y), f"{role}", font=self.f, fill="black")
            self.dr.text((x + 10, self.y + 60), "성명 ____________  (서명)", font=self.f_s, fill=(80, 80, 80))
        self.y += 120

    def pdf(self) -> bytes:
        buf = io.BytesIO()
        self.pages[0].save(buf, format="PDF", save_all=True, append_images=self.pages[1:], resolution=150)
        return buf.getvalue()


_APPROVE_RE = re.compile(r"^\[(?P<when>[^\]]+)\] (?:\d+차|최종) 승인\((?P<role>[^)]+)\)[^·]*· (?P<who>[^·]+)")


def _approvals_from_log(rec: dict) -> dict[str, tuple[str, str]]:
    out = {}
    for line in d.clean_str(rec.get("처리이력")).split("\n"):
        m = _APPROVE_RE.match(line.strip())
        if m:
            out[m.group("role")] = (m.group("who").strip().split("(")[0], m.group("when")[:10])
    return out


def _who(s: str) -> str:
    return d.clean_str(s).replace(d.SAMPLE_MARK, "").strip().split("(")[0]


def purchase_request_pdf(rec: dict) -> bytes:
    doc = _Doc("구 매 요 청 서", rec["요청번호"])
    signed = _approvals_from_log(rec)
    approvals = [("요청자", _who(rec["요청자"]), rec["요청일시"][:10])]
    approvals += [(lv, *signed.get(lv, ("", ""))) for lv in d.pr_line(rec)]
    doc.header(approvals)
    qty = int(d.to_num(rec["수량"], 0) or 0)
    unit = d.to_num(rec["예상단가"], 0) or 0
    doc.heading("1. 요청 내용")
    doc.grid([("요청 현장", rec["현장"]), ("요청일", rec["요청일시"][:10]), ("품명", rec["품명"]), ("규격", rec["규격"]),
              ("수량", f"{qty:,}"), ("예상 단가", ui.won(unit)), ("예산 합계", ui.won(qty * unit)), ("필요 시점", ui.fmt_date(rec["필요일"])),
              ("계정과목", rec["계정과목"]), ("사용 예정자", rec["사용예정자"])])
    doc.heading("2. 구매 사유 (타당성)")
    doc.paragraph(rec["구매사유"])
    quotes = d.pr_quotes(rec)
    if quotes:
        doc.heading("3. 비교 견적")
        doc.table([("업체", 3), ("단가", 2), ("합계", 2), ("조건", 4), ("선정", 1)],
                  [[q["업체"], round(q["단가"]), round(q["단가"] * qty), q["조건"], "○" if q["업체"] == rec["선정업체"] else ""] for q in quotes])
        if rec["선정사유"]:
            doc.grid([("선정 업체", rec["선정업체"]), ("선정 사유", rec["선정사유"])])
    if rec["검토의견"]:
        doc.heading("4. 검토 의견")
        doc.paragraph(rec["검토의견"])
    return doc.pdf()


def inspection_pdf(rec: dict) -> bytes:
    doc = _Doc("물 품 검 수 조 서", rec["요청번호"])
    doc.header([("검수자", _who(rec["검수자"]), rec["검수일시"][:10]), ("입회자", "", ""), ("자산관리자", "", "")])
    doc.heading("1. 발주 내용")
    doc.grid([("구매요청번호", rec["요청번호"]), ("요청 현장", rec["현장"]), ("품명", rec["품명"]), ("규격", rec["규격"]),
              ("발주 수량", f"{int(d.to_num(rec['수량'], 0) or 0):,}"), ("공급업체", rec["선정업체"]),
              ("단가", ui.won(rec["선정단가"])), ("발주일", d.clean_str(rec["발주일시"])[:10])])
    doc.heading("2. 검수 결과")
    doc.grid([("규격 일치", rec["검수 규격"]), ("파손 여부", rec["검수 파손"]), ("이번 입고 수량", f"{int(d.to_num(rec['검수 입고수량'], 0) or 0):,}"),
              ("누적 등록 수량", f"{int(d.to_num(rec['입고누계'], 0) or 0):,}"), ("검수일", d.clean_str(rec["검수일시"])[:10]),
              ("판정", "합격" if rec["상태"] in ("검수완료", "등록완료") or rec["입고누계"] else "부적합")])
    doc.heading("3. 시리얼 번호 · 검수 메모")
    doc.paragraph(f"시리얼: {rec['검수 시리얼'] or '-'}\n메모: {rec['검수 메모'] or '-'}")
    tags = [t.strip() for t in d.clean_str(rec["등록 태그번호"]).split(",") if t.strip()]
    if tags:
        doc.heading("4. 등록된 자산")
        doc.table([("태그번호", 2), ("품명", 3), ("시리얼", 2), ("현장", 2)],
                  [[t, (d.get_asset(t) or {}).get("품명", ""), (d.get_asset(t) or {}).get("시리얼번호", ""),
                    (d.get_asset(t) or {}).get("현장", "")] for t in tags])
    doc.signatures(["검수자", "입회자", "공급업체 확인"])
    return doc.pdf()


def disposal_pdf(rec: dict) -> bytes:
    doc = _Doc("불 용 품 처 분 결 의 서", rec["요청번호"])
    votes = d.dsp_votes(rec["요청번호"])
    approvals = [("신청자", _who(rec["신청자"]), rec["요청일시"][:10])]
    approvals += [(f"위원 {v['위원명']}", v["결과"], v["일시"][:10]) for v in votes[:4]]
    doc.header(approvals)
    items = d.request_assets(rec)
    doc.heading("1. 처분 신청")
    doc.grid([("현장", rec["현장"]), ("신청일", rec["요청일시"][:10]), ("불용 사유", rec["불용사유"]), ("희망 처분 방법", rec["희망 처분방법"]),
              ("대상 자산", f"{len(items):,}개"), ("장부가 합계", ui.won(rec["장부가 합계"]))])
    doc.paragraph(rec["상세사유"])
    doc.heading("2. 대상 자산")
    doc.table([("태그번호", 2), ("품명", 3), ("취득일", 2), ("취득가액", 2), ("장부가액", 2)],
              [[a["태그번호"], a["품명"], ui.fmt_date(a["취득일자"]), round(a["취득가액"] or 0),
                round(d.depreciation(a, d.to_date(rec["집행일"]) or d.today())["nbv"])] for a in items[:200]])
    doc.heading("3. 위원회 의결")
    if votes:
        doc.table([("위원", 2), ("결과", 1), ("의견", 5), ("일시", 2)], [[v["위원명"], v["결과"], v["의견"], v["일시"]] for v in votes])
    doc.paragraph(rec["위원회 의견"] or "심의 중")
    if rec["처분방법"]:
        doc.heading("4. 집행 · 제적")
        doc.grid([("처분 방법", rec["처분방법"]), ("집행일", ui.fmt_date(rec["집행일"])), ("처분처", rec["처분처"]),
                  ("처분 금액", ui.won(rec["처분금액"])), ("보안 파기", rec["보안파기 확인"] or "-"), ("파기증명번호", rec["파기증명번호"]),
                  ("처분손익", ui.won(rec["처분손익"]) if rec["처분손익"] not in (None, "") else "-"), ("상태", rec["상태"])])
    return doc.pdf()


def return_pdf(ret: dict) -> bytes:
    doc = _Doc("퇴 사 자 산 반 납 확 인 서", ret["회수번호"])
    doc.header([("퇴사자", ret["이름"], ""), ("현장 담당", "", ""), ("자산관리자", "", "")])
    doc.heading("1. 퇴사자 정보")
    doc.grid([("사번", ret["사번"]), ("이름", ret["이름"]), ("현장", ret["현장"]), ("부서", ret["부서"]),
              ("퇴사일", ui.fmt_date(ret["퇴사일"])), ("상태", ret["상태"])])
    doc.heading("2. 보유 자산 반납 내역")
    from ops import return_items  # 순환 참조 방지
    doc.table([("태그번호", 2), ("품명", 3), ("결과", 1), ("인계자", 2), ("처리일시", 2)],
              [[i["태그번호"], i["품명"], i["결과"], i["인계자"], i["처리일시"]] for i in return_items(ret["회수번호"])])
    doc.signatures(["퇴사자", "현장 담당", "자산관리자"])
    return doc.pdf()
