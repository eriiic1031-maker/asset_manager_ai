"""데이터 계층(감가상각·결재 흐름·보안) 테스트.  실행: pytest -q"""
from datetime import date, datetime

import pytest

import data as d


# ---------------------------------------------------------------- 감가상각
def asset(**kw):
    base = {"태그번호": "T-1", "계정과목": "비품", "취득가액": 1_000_000, "취득일자": date(2025, 1, 1),
            "내용연수": 5, "상각방법": "정률", "잔존가액": 0, "상태": "사용중"}
    base.update(kw)
    return base


def test_declining_balance_uses_tax_rate():
    # 5년 정률법 상각률 = 1 - 0.05^(1/5) ≈ 0.451 → 1년 상각비 약 450,720원
    dep = d.depreciation(asset(), date(2025, 12, 31))
    assert dep["months"] == 12
    assert dep["accum"] == pytest.approx(1_000_000 * (1 - 0.05 ** 0.2), abs=1)


def test_straight_line_monthly():
    dep = d.depreciation(asset(상각방법="정액"), date(2025, 12, 31))
    assert dep["accum"] == pytest.approx(200_000)
    assert dep["monthly"] == pytest.approx(200_000 / 12)


def test_end_of_life_keeps_memo_value():
    dep = d.depreciation(asset(), date(2031, 1, 31))
    assert dep["nbv"] == 1000  # 비망가액


def test_intangible_goes_to_zero():
    dep = d.depreciation(asset(계정과목="소프트웨어", 상각방법="정액"), date(2031, 1, 31))
    assert dep["nbv"] == 0


def test_consumable_is_expensed_immediately():
    dep = d.depreciation(asset(계정과목="소모품", 내용연수=0), date(2025, 1, 31))
    assert dep["nbv"] == 0


def test_today_uses_korea_time():
    assert d.today() == datetime.now(d.KST).date()


# ---------------------------------------------------------------- 구매 → 등록
def test_purchase_flow_registers_assets_with_serials(store):
    no = store.create_purchase_request({"현장": "평택", "품명": "노트북", "계정과목": "비품", "수량": 2,
                                        "예상단가": 1_800_000, "구매사유": "신규 입사자"}, "요청자")
    store.pr_decide(no, True, "", "현장책임자")  # 360만원 → 현장책임자 → 자산관리자 2단계
    assert store.get_request("pr", no)["상태"] == "요청"
    store.pr_decide(no, True, "승인", "관리자")
    with pytest.raises(d.DataError):  # 비교견적 1건으로는 선정 불가
        store.pr_save_quotes(no, [{"업체": "A", "단가": 1_700_000}], "관리자")
        store.pr_choose_vendor(no, 1, "최저가", "관리자")
    store.pr_save_quotes(no, [{"업체": "A", "단가": 1_700_000}, {"업체": "B", "단가": 1_750_000}], "관리자")
    store.pr_choose_vendor(no, 1, "최저가", "관리자")
    assert store.pr_inspect(no, True, 3, True, "", "수량 초과", "현장") is False  # 남은 수량보다 많으면 불합격
    assert store.pr_inspect(no, True, 2, True, "S1, S2", "", "현장") is True
    tags = store.pr_register(no, {"품명": "노트북", "계정과목": "비품", "현장": "평택",
                                  "취득일자": store.today(), "취득가액": 1_700_000}, "관리자")
    assert len(tags) == 2
    assert [store.get_asset(t)["시리얼번호"] for t in tags] == ["S1", "S2"]
    assert store.get_request("pr", no)["상태"] == "등록완료"


# ---------------------------------------------------------------- 이동
def test_transfer_needs_sender_approval_then_receipt(store, one_laptop):
    [no] = store.create_transfer([one_laptop], "평택", "설계팀", "홍길동", "신규 입사자", "평택 담당")
    with pytest.raises(d.DataError):  # 승인 전에는 인수 불가
        store.transfer_receive(no, "", "평택 담당")
    store.transfer_decide(no, True, "", "본사 담당")
    store.transfer_receive(no, "", "평택 담당")
    a = store.get_asset(one_laptop)
    assert (a["현장"], a["사용자"]) == ("평택", "홍길동")
    assert any(h["구분"] == "현장 이동" for h in store.get_history(one_laptop))


def test_transfer_to_same_site_is_rejected(store, one_laptop):
    with pytest.raises(d.DataError):
        store.create_transfer([one_laptop], "본사", "", "", "사유", "x")


# ---------------------------------------------------------------- 처분
def test_disposal_requires_secure_wipe_for_pc_and_books_gain(store, one_laptop):
    [no] = store.create_disposal([one_laptop], "내용연수 만료", "매각", "노후", "본사 담당")
    assert store.get_asset(one_laptop)["상태"] == "처분대기"
    store.disposal_decide(no, True, "불용 판정", "위원회")
    with pytest.raises(d.DataError):  # 노트북은 보안 파기 증빙 필수
        store.disposal_execute(no, "매각", store.today(), "중고상", 100_000, False, "", "", "본사 담당")
    store.disposal_execute(no, "매각", store.today(), "중고상", 100_000, True, "WIPE-1", "", "본사 담당")
    gain = store.disposal_derecognize(no, "관리자")
    a = store.get_asset(one_laptop)
    assert a["상태"] == "처분완료" and a["처분처"] == "중고상"
    assert gain == pytest.approx(100_000 - 1000)  # 6년 지난 노트북 장부가 = 비망가액 1,000원
    assert a in store.closed_assets()


def test_cannot_dispose_while_transfer_is_open(store, one_laptop):
    store.create_transfer([one_laptop], "평택", "", "", "사유", "x")
    with pytest.raises(d.DataError):
        store.create_disposal([one_laptop], "노후화", "폐기", "사유", "x")


def test_loss_incident_writes_off_asset(store, one_laptop):
    no = store.create_incident(one_laptop, "분실", store.today(), "현장", "", "출장 중 분실", "", "본사 담당")
    store.incident_investigate(no, {"고의과실": "경과실", "변상여부": "면책", "처리방법": "망실처리", "조사의견": "분실 확인"}, "관리자")
    store.incident_close(no, "관리자")
    assert store.get_asset(one_laptop)["상태"] == "망실"


# ---------------------------------------------------------------- 재물조사
def test_audit_scan_and_close_marks_idle(store, one_laptop):
    no = store.start_audit("정기", store.today(), "전체", "관리자")
    ok, _ = store.audit_scan(no, f"http://host/?tag={one_laptop}", "본사 담당")  # QR 주소 형태도 인식
    assert ok
    ok, msg = store.audit_scan(no, one_laptop, "평택 담당", allowed_site="평택")
    assert not ok and "담당 현장" in msg
    store.audit_mark(no, {one_laptop: {"결과": "확인", "유휴": True}}, "본사 담당")
    stats = store.close_audit(no, "관리자")
    assert stats["found"] == 1 and store.get_asset(one_laptop)["상태"] == "유휴"


# ---------------------------------------------------------------- 설정·보안
def test_export_blocks_spreadsheet_formula_injection():
    csv_text = d.rows_to_csv(["품명"], [{"품명": "=HYPERLINK(\"x\")"}]).decode("utf-8-sig")
    assert "'=HYPERLINK" in csv_text


def test_rename_site_moves_assets(store, one_laptop):
    store.rename_site("본사", "서울 본사", "관리자")
    assert "서울 본사" in store.site_names() and "본사" not in store.site_names()
    assert store.get_asset(one_laptop)["현장"] == "서울 본사"


def test_site_with_assets_cannot_be_deleted(store, one_laptop):
    rows = [s for s in store.get_sites() if s["현장명"] != "본사"]
    with pytest.raises(d.DataError):
        store.save_sites(rows)


# ---------------------------------------------------------------- 예시 데이터
def test_sample_data_create_and_clear(store, one_laptop):
    result = store.create_sample_data(active_count=300, closed_count=1500)
    assert result["active"] == 300 and result["closed"] == 1500
    assert len(store.closed_assets()) >= 1500
    store.clear_sample_data()
    assert [a["태그번호"] for a in store.get_assets()] == [one_laptop]  # 직접 등록한 자산은 남음
