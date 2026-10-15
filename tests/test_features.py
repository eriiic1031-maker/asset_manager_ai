"""확장 기능 테스트: 결재선·예산·부분 입고·대여·점검·퇴사 회수·라이선스·렌탈·자본적 지출·세무·분개·위원회·입찰·조사."""
from datetime import timedelta

import pytest

import data as d
import ops


def _pr(store, qty, unit, site="평택"):
    return store.create_purchase_request({"현장": site, "품명": "장비", "계정과목": "공기구비품", "수량": qty,
                                          "예상단가": unit, "구매사유": "필요"}, "요청자")


def _to_order(store, no):
    while store.get_request("pr", no)["상태"] == "요청":
        store.pr_decide(no, True, "", "결재자")
    store.pr_save_quotes(no, [{"업체": "A", "단가": 100}, {"업체": "B", "단가": 120}], "관리자")
    store.pr_choose_vendor(no, 1, "최저가", "관리자")


def test_approval_line_by_amount(store):
    assert d.approval_line(500_000) == ["현장책임자"]
    assert d.approval_line(5_000_000) == ["현장책임자", "자산관리자"]
    assert d.approval_line(50_000_000) == ["현장책임자", "자산관리자", "임원"]
    no = _pr(store, 10, 2_000_000)
    for level in ("현장책임자", "자산관리자", "임원"):
        assert d.pr_current_level(store.get_request("pr", no)) == level
        store.pr_decide(no, True, "", level)
    assert store.get_request("pr", no)["상태"] == "승인"


def test_budget_check_warns_when_over(store):
    ops.save_budgets(store.today().year, {"평택": 5_000_000}, "재무")
    _pr(store, 2, 2_000_000)
    chk = ops.budget_check("평택", 2_000_000)
    assert chk["결재 중"] == 4_000_000 and chk["초과"]


def test_partial_receipt_then_rest(store):
    no = _pr(store, 3, 100)
    _to_order(store, no)
    assert store.pr_inspect(no, True, 2, True, "S1,S2", "", "현장") is True
    tags = store.pr_register(no, {"품명": "장비", "계정과목": "공기구비품", "현장": "평택", "취득일자": store.today(), "취득가액": 100}, "관리자")
    rec = store.get_request("pr", no)
    assert len(tags) == 2 and rec["상태"] == "발주" and d.pr_remaining(rec) == 1
    assert store.pr_inspect(no, True, 2, True, "", "", "현장") is False  # 남은 수량보다 많으면 불합격
    assert store.pr_inspect(no, True, 1, True, "S3", "", "현장") is True
    store.pr_register(no, {"품명": "장비", "계정과목": "공기구비품", "현장": "평택", "취득일자": store.today(), "취득가액": 100}, "관리자")
    assert store.get_request("pr", no)["상태"] == "등록완료"


def test_rental_flow_and_conflict(store, one_laptop):
    store.update_asset(one_laptop, {"공용": "Y"}, "관리자")
    t = store.today()
    no = ops.create_rental(one_laptop, t, t + timedelta(days=2), "발표", "staff", "한직원", "설계팀", "한직원")
    with pytest.raises(d.DataError):  # 겹치는 기간
        ops.create_rental(one_laptop, t + timedelta(days=1), t + timedelta(days=3), "회의", "x", "x", "", "x")
    with pytest.raises(d.DataError):  # 최대 기간 초과
        ops.create_rental(one_laptop, t + timedelta(days=10), t + timedelta(days=60), "장기", "x", "x", "", "x")
    ops.rental_decide(no, True, "", "담당")
    ops.rental_handout(no, "담당")
    ops.rental_return(no, "정상", "", "담당")
    assert d.lookup("rentals", no)["상태"] == "반납완료"


def test_maintenance_plan_advances_and_repairs_trigger_disposal(store, one_laptop):
    t = store.today()
    pno = ops.save_plan({"태그번호": one_laptop, "점검명": "정기점검", "구분": "정기점검", "주기개월": 6,
                         "최근점검일": t - timedelta(days=200)}, "관리자")
    assert any(p["계획번호"] == pno for p in ops.plans_due(30))
    d.add_maint_log({"태그번호": one_laptop, "일자": t, "구분": "정기점검", "내용": "점검", "계획번호": pno}, "관리자")
    assert d.lookup("maint_plans", pno)["다음점검일"] > t
    d.add_maint_log({"태그번호": one_laptop, "일자": t, "구분": "수리", "내용": "메인보드", "비용": 500_000}, "관리자")
    assert d.repair_costs()[one_laptop] == 500_000
    assert any(a["태그번호"] == one_laptop for a in d.disposal_candidates())


def test_offboarding_returns_assets_and_releases_licenses(store, one_laptop):
    emp = ops.save_employee({"이름": "홍길동", "현장": "본사", "부서": "설계팀"}, "관리자")
    store.update_asset(one_laptop, {"사용자": "홍길동", "사용자사번": emp}, "관리자")
    lic = ops.save_license({"소프트웨어명": "CAD", "보유수량": 1}, "관리자")
    ops.assign_license(lic, "홍길동", emp, "설계팀", "본사", "", "관리자")
    with pytest.raises(d.DataError):  # 수량 초과
        ops.assign_license(lic, "김철수", "", "설계팀", "본사", "", "관리자")
    no = ops.start_return(emp, store.today(), "관리자")
    assert ops.process_return_item(no, one_laptop, "회수", "", "", "관리자") is True
    a = store.get_asset(one_laptop)
    assert a["상태"] == "유휴" and a["사용자"] == ""
    assert ops.license_used(lic) == 0 and d.lookup("employees", emp)["상태"] == "퇴사"


def test_lease_expiry(store):
    ops.save_lease({"품명": "복합기", "현장": "본사", "시작일": store.today() - timedelta(days=300),
                    "종료일": store.today() + timedelta(days=20), "월요금": 150_000}, "재무")
    assert len(ops.leases_expiring(30)) == 1 and ops.lease_monthly_cost() == 150_000


def test_capex_raises_cost_and_tax_basis_differs(store):
    [tag] = store.register_assets({"품명": "굴착기", "계정과목": "기계장치", "현장": "평택", "취득일자": store.today().replace(month=1, day=1),
                                   "취득가액": 100_000_000, "상각방법": "정액", "내용연수": 5,
                                   "세무 내용연수": 8, "세무 상각방법": "정액"}, 1, "관리자")
    a = store.get_asset(tag)
    before = d.depreciation(a)["cost"]
    ops.add_capex(tag, store.today(), "엔진 오버홀", 20_000_000, 2, "관리자")
    assert d.depreciation(store.get_asset(tag))["cost"] == before + 20_000_000
    y, m = store.today().year, store.today().month
    adj = d.tax_adjustment(y, m)
    assert adj and adj[0]["상각부인액"] > 0  # 회계 5년 > 세무 8년이면 회계 상각이 더 큼
    assert sum(r["상각비"] for r in d.depreciation_forecast(3)) > 0


def test_journal_is_balanced(store, one_laptop):
    t = store.today()
    store.register_assets({"품명": "모니터", "계정과목": "비품", "현장": "본사", "취득일자": t.replace(day=1),
                           "취득가액": 3_000_000}, 1, "테스트")
    rows = ops.journal_entries(t.year, t.month)
    debit = sum(r["금액"] for r in rows if r["차대"] == "차변")
    credit = sum(r["금액"] for r in rows if r["차대"] == "대변")
    assert rows and debit == credit


def test_committee_votes_and_bids(store, one_laptop):
    store.save_settings({"위원회 정족수": "2"})
    [no] = store.create_disposal([one_laptop], "내용연수 만료", "매각", "노후", "담당")
    assert d.cast_votes(no, [{"위원": "a", "위원명": "가", "결과": "찬성"}], "관리자") == "진행중"
    assert d.cast_votes(no, [{"위원": "b", "위원명": "나", "결과": "찬성"}], "관리자") == "승인"
    d.dsp_save_bids(no, [{"매수자": "X", "금액": 300_000}, {"매수자": "Y", "금액": 250_000}], "관리자")
    d.dsp_award(no, 1, "관리자")
    rec = store.get_request("dsp", no)
    assert rec["상태"] == "승인" and rec["낙찰자"] == "X"


def test_audit_missing_requests_statement_and_report(store, one_laptop):
    no = store.start_audit("정기", store.today(), "전체", "관리자")
    store.audit_mark(no, {one_laptop: {"결과": "미발견"}}, "담당")
    stats = store.close_audit(no, "관리자")
    assert stats["requested"] == 1
    inc = [r for r in store.get_requests("inc") if r["태그번호"] == one_laptop]
    assert inc and inc[0]["상태"] == "경위요청"
    store.submit_statement(inc[0]["요청번호"], "분실", store.today(), "현장", "", "이사 중 분실", "", "담당")
    assert store.get_request("inc", inc[0]["요청번호"])["상태"] == "접수"
    rep = store.audit_report(no)
    assert rep["total"]["missing"] == 1 and rep["missing"]


def test_alerts_and_digest(store, one_laptop):
    store.update_asset(one_laptop, {"보증만료일": store.today() + timedelta(days=5)}, "관리자")
    alerts = ops.alerts_for({"아이디": "admin", "역할": ops.ADMIN, "현장": ""}, {})
    assert any(a["분류"] == "보증" for a in alerts)
    assert "보증" in ops.digest_text(alerts)


def test_qr_decode_roundtrip():
    import qrscan
    import ui
    if not qrscan.available():
        pytest.skip("opencv 미설치")
    assert qrscan.decode(ui.qr_png("http://h:8501/?tag=FUR-2026-0001")) .endswith("FUR-2026-0001")


def test_users_without_password(store):
    import auth
    auth.ensure_default_admin()
    [admin] = auth.get_users()
    assert admin["역할"] == auth.ADMIN and "비밀번호" not in admin
    uid = auth.save_user({"이름": "정담당", "역할": auth.SITE, "현장": "평택"}, "관리자")
    assert auth.get_user(uid)["현장"] == "평택"
    with pytest.raises(d.DataError):  # 현장 역할은 현장 필수
        auth.save_user({"이름": "무소속", "역할": auth.STAFF}, "관리자")
    with pytest.raises(d.DataError):  # 마지막 관리자는 막을 수 없음
        auth.save_user({"활성": "N"}, "관리자", admin["아이디"])
    auth.save_user({"위원": "Y"}, "관리자", uid)
    assert [m["아이디"] for m in auth.committee_members()] == [admin["아이디"], uid]


def test_alerts_point_to_where_they_are_handled(store, one_laptop):
    import workflow as wf
    store.update_asset(one_laptop, {"보증만료일": store.today() + timedelta(days=5)}, "관리자")
    no = store.create_purchase_request({"현장": "평택", "품명": "장비", "계정과목": "공기구비품", "수량": 1,
                                        "예상단가": 100_000, "구매사유": "필요"}, "요청자")
    u = {"아이디": "admin", "이름": "관리자", "역할": ops.ADMIN, "현장": "", "위원": "Y"}
    alerts = ops.alerts_for(u, wf.pending_for(u))
    assert ("req", "pr", no) in [a["대상"] for a in alerts]          # 결재 대기는 한 건씩 바로 처리
    assert ("asset", one_laptop) in [a["대상"] for a in alerts]
    summary = ops.alerts_for(u, wf.pending_for(u), detail=False)     # 메일 요약은 종류별 한 줄
    assert any(a["분류"] == "결재" and "1건" in a["제목"] for a in summary)
