"""
운영 화면: 장비 대여 · 점검·수리 · 직원·퇴사 회수 · 라이선스 · 렌탈·리스 · 공급업체 · 예산 · 알림

데이터 처리는 ops.py, 화면 공용 요소는 ui.py / workflow.py를 씁니다.
"""
from __future__ import annotations

import html
from datetime import timedelta

import pandas as pd
import streamlit as st

import auth
import data as d
import docs_pdf
import ops
import ui
import workflow as wf
from auth import ADMIN, EXEC, FIN, SITE_ROLES, STAFF


def _scope(u: dict) -> str | None:
    """현장 역할이면 자기 현장, 나머지는 전체(None)."""
    return u["현장"] if u.get("역할") in SITE_ROLES else None


def _clean(text: str) -> str:
    return d.clean_str(text).replace(d.SAMPLE_MARK, "").strip()


def _steps(flow: list[str], status: str) -> str:
    if status in (d.REJECTED, "취소"):
        return f'<div class="steps"><span class="done">{flow[0]}</span><em>›</em><span class="stop">{status}</span></div>'
    idx = flow.index(status) if status in flow else 0
    parts = []
    for i, s in enumerate(flow):
        cls = "done" if i < idx or (i == idx == len(flow) - 1) else "now" if i == idx else ""
        parts.append(f'<span class="{cls}">{s}</span>')
    return '<div class="steps">' + "<em>›</em>".join(parts) + "</div>"


# =========================================================
# 🧰 장비 대여
# =========================================================
def rental_cards(rows: list[dict], u: dict, key: str):
    if not rows:
        st.success("처리할 대여 건이 없습니다.")
        return
    for r in rows:
        acts = wf.rental_actions(r, u)
        own = r["신청자"] == u.get("아이디")
        late = r["상태"] == "대여중" and r["반납예정일"] and r["반납예정일"] < d.today()
        with st.container(border=True):
            a, b, c, e = st.columns([1.1, 2.0, 3.4, 1.7])
            with a:
                st.markdown(f"**{r['대여번호']}**")
                st.markdown(ui.badge("반려" if r["상태"] == "취소" else r["상태"]), unsafe_allow_html=True)
            with b:
                st.markdown(f"**{html.escape(r['품명'])}**")
                st.caption(f"{r['태그번호']} · {r['현장']}")
            with c:
                st.markdown(f"<span class='small-muted'>{html.escape(_clean(r['신청자명']))} · {html.escape(r['부서'])} · "
                            f"{ui.fmt_date(r['시작일'])} ~ {ui.fmt_date(r['반납예정일'])} · {html.escape(r['사용목적'][:40])}</span>"
                            + (" <span class='badge rejected'>반납 지연</span>" if late else ""), unsafe_allow_html=True)
                st.markdown(_steps(ops.RENTAL_FLOW, r["상태"]), unsafe_allow_html=True)
            with e:
                labels = {"r_approve": "✅ 승인", "r_reject": "❌ 반려", "r_handout": "📤 장비 인계", "r_return": "📥 반납 확인"}
                for act in acts:
                    if st.button(labels[act], key=f"{key}-{r['대여번호']}-{act}", width="stretch",
                                 type="secondary" if act == "r_reject" else "primary"):
                        dlg_rental(r["대여번호"], act, u)
                if own and r["상태"] in ("신청", "승인") and st.button("신청 취소", key=f"{key}-{r['대여번호']}-cancel", width="stretch"):
                    if ui.run_action(ops.rental_cancel, r["대여번호"], auth.actor(u), success=f"{r['대여번호']} 신청을 취소했습니다."):
                        st.rerun()
                if not acts and not (own and r["상태"] in ("신청", "승인")):
                    st.caption("처리할 단계가 없습니다" if r["상태"] not in ops.RENTAL_OPEN else "담당자 처리 차례")


@st.dialog("🧰 장비 대여 처리")
def dlg_rental(no: str, act: str, u: dict):
    r = d.lookup("rentals", no)
    if not r:
        st.error("대여 신청을 찾을 수 없습니다.")
        return
    actor = auth.actor(u)
    st.markdown(f"**{no}** · {html.escape(r['품명'])} ({r['태그번호']}) · {html.escape(_clean(r['신청자명']))} · "
                f"{ui.fmt_date(r['시작일'])} ~ {ui.fmt_date(r['반납예정일'])}")
    st.caption(f"사용 목적: {r['사용목적']}")
    if act in ("r_approve", "r_reject"):
        note = st.text_area("의견" + (" (반려 사유 필수)" if act == "r_reject" else ""))
        if st.button("승인" if act == "r_approve" else "반려", type="primary", width="stretch"):
            if ui.run_action(ops.rental_decide, no, act == "r_approve", note, actor):
                ui.flash(f"{no} {'승인' if act == 'r_approve' else '반려'}했습니다.")
                st.rerun()
    elif act == "r_handout":
        st.caption("장비를 신청자에게 넘겨줄 때 누릅니다. 이때부터 '대여중'이 되고 자산 이력에 남습니다.")
        ok = st.checkbox("신청자와 함께 장비 상태·구성품을 확인했습니다")
        if st.button("인계 완료", type="primary", width="stretch", disabled=not ok):
            if ui.run_action(ops.rental_handout, no, actor):
                ui.flash(f"{no} 장비를 인계했습니다.")
                st.rerun()
    else:
        cond = st.radio("반납 상태", ["정상", "구성품 누락", "파손"], horizontal=True)
        note = st.text_input("메모", placeholder="예: 충전기 누락, 화면 긁힘")
        if cond == "파손":
            st.warning("파손이면 반납 후 '⚠️ 분실·파손 신고'로 경위서를 접수하세요(수리·변상 검토).")
        if st.button("반납 확인", type="primary", width="stretch"):
            if ui.run_action(ops.rental_return, no, cond, note, actor):
                ui.flash(f"{no} 반납을 확인했습니다." + (" 파손 신고를 이어서 접수하세요." if cond == "파손" else ""))
                st.rerun()


def _calendar(assets: list[dict], days: int = 14) -> pd.DataFrame:
    """공용 장비 × 날짜 예약표 (법인차량 관리 AI의 배차 달력처럼)."""
    start = d.today()
    dates = [start + timedelta(days=i) for i in range(days)]
    by_tag: dict[str, list[dict]] = {}
    for r in d.load("rentals"):
        if r["상태"] in ops.RENTAL_OPEN and r["시작일"] and r["반납예정일"]:
            by_tag.setdefault(r["태그번호"], []).append(r)
    rows = []
    for a in assets:
        row = {"장비": f"{a['품명']} ({a['태그번호']})", "현장": a["현장"]}
        for day in dates:
            hit = next((r for r in by_tag.get(a["태그번호"], []) if r["시작일"] <= day <= r["반납예정일"]), None)
            mark = {"신청": "⏳", "승인": "✅", "대여중": "🔵"}.get(hit["상태"], "") if hit else ""
            row[f"{day.month}/{day.day}({'월화수목금토일'[day.weekday()]})"] = f"{mark}{_clean(hit['신청자명'])}" if hit else ""
        rows.append(row)
    return pd.DataFrame(rows)


def rental_page(u: dict):
    st.title("🧰 공용 장비 대여")
    st.caption("측량기·빔프로젝터·카메라·노트북처럼 여러 사람이 돌려 쓰는 공용 장비를 빌리고 반납합니다. "
               f"신청 → 현장 담당자 승인 → 장비 인계(대여중) → 반납 확인 순서이며, 한 번에 최대 {ops.MAX_RENTAL_DAYS}일까지 빌릴 수 있습니다.")
    scope = _scope(u)
    sites = d.site_names()
    pool_all = ops.rentable_assets()
    k = st.columns(4)
    rentals = ops.get_rentals(scope)
    with k[0]: ui.kpi("공용 장비", len(pool_all if not scope else [a for a in pool_all if a["현장"] == scope]), scope or "전체 현장", unit="대")
    with k[1]: ui.kpi("대여 중", sum(1 for r in rentals if r["상태"] == "대여중"), "지금 빌려 간 장비", unit="건")
    with k[2]: ui.kpi("승인 대기", sum(1 for r in rentals if r["상태"] == "신청"), "현장 담당자 승인", "warn" if any(r["상태"] == "신청" for r in rentals) else "", "건")
    overdue = ops.overdue_rentals(scope)
    with k[3]: ui.kpi("반납 지연", len(overdue), "반납 예정일 지남", "crit" if overdue else "", "건")

    tabs = st.tabs(["📅 예약 현황", "📝 대여 신청", f"✅ 처리할 대여 ({len(wf.pending_rentals(u)) + sum(1 for r in d.load('rentals') if r['상태'] == '대여중' and 'r_return' in wf.rental_actions(r, u))})", "📋 전체 대여 기록"])
    with tabs[0]:
        c1, c2, c3 = st.columns([1.2, 1, 2])
        site = c1.selectbox("현장", ["전체"] + sites, index=(sites.index(u["현장"]) + 1) if u.get("현장") in sites else 0, key="rt-cal-site")
        days = c2.selectbox("기간", [7, 14, 21, 28], index=1, key="rt-cal-days", format_func=lambda x: f"{x}일")
        q = c3.text_input("장비 검색", key="rt-cal-q", placeholder="품명·태그번호").strip().lower()
        pool = [a for a in pool_all if (site == "전체" or a["현장"] == site) and (not q or q in a["품명"].lower() or q in a["태그번호"].lower())]
        if not pool:
            st.info("대여할 수 있는 공용 장비가 없습니다. 자산 상세 → 🛠 작업 → 상태 변경(또는 일괄 수정)에서 '공용 장비'로 지정하세요.")
        else:
            st.dataframe(_calendar(pool[:80], days), hide_index=True, width="stretch", height=min(40 + 35 * len(pool[:80]), 560))
            st.caption("⏳ 승인 대기 · ✅ 승인(인계 전) · 🔵 대여 중" + (f" · 장비가 많아 80대까지만 표시했습니다 (전체 {len(pool):,}대)" if len(pool) > 80 else ""))
    with tabs[1]:
        if not pool_all:
            st.info("대여할 수 있는 공용 장비가 없습니다.")
        else:
            c1, c2 = st.columns([1, 3])
            site = c1.selectbox("장비가 있는 현장", sites, index=sites.index(u["현장"]) if u.get("현장") in sites else 0, key="rt-new-site")
            cand = [a for a in pool_all if a["현장"] == site]
            if not cand:
                st.info(f"{site}에는 공용 장비가 없습니다.")
            else:
                labels = {a["태그번호"]: f"{a['품명']} · {a['규격']} ({a['태그번호']})" for a in cand}
                with st.form("rt-new"):
                    tag = st.selectbox("장비 *", list(labels), format_func=lambda t: labels[t])
                    c1, c2 = st.columns(2)
                    start = c1.date_input("대여 시작일 *", value=d.today())
                    end = c2.date_input("반납 예정일 *", value=d.today() + timedelta(days=2))
                    purpose = st.text_input("사용 목적 *", placeholder="예: 3공구 측량, 고객사 발표")
                    if st.form_submit_button("🧰 대여 신청", type="primary", width="stretch"):
                        no = ui.run_action(ops.create_rental, tag, start, end, purpose, u["아이디"], u["이름"], u.get("부서", ""), auth.actor(u))
                        if no:
                            ui.flash(f"대여 신청 {no}을(를) 접수했습니다. {site} 담당자가 승인하면 장비를 받아 가세요.")
                            st.rerun()
    with tabs[2]:
        rows = [r for r in d.load("rentals") if wf.rental_actions(r, u)]
        rental_cards(sorted(rows, key=lambda r: r["시작일"] or d.today()), u, key="rt-todo")
    with tabs[3]:
        rows = rentals if u.get("역할") in (ADMIN,) + SITE_ROLES else [r for r in rentals if r["신청자"] == u["아이디"]]
        if not rows:
            st.info("대여 기록이 없습니다.")
        else:
            cols = ["대여번호", "상태", "태그번호", "품명", "현장", "신청자명", "부서", "시작일", "반납예정일", "사용목적", "반납일시", "반납상태"]
            df = pd.DataFrame(rows)[cols]
            df["신청자명"] = df["신청자명"].map(_clean)
            st.dataframe(df, hide_index=True, width="stretch")
            st.download_button("📥 대여 기록 엑셀", d.rows_to_xlsx({"장비대여": (cols, rows)}), file_name=f"장비대여_{d.today():%Y%m%d}.xlsx")


# =========================================================
# 🔧 점검 · 수리 · 보증
# =========================================================
MT_GUIDE = """
**이렇게 운영합니다**

1. **점검 계획 등록** — 소방설비·크레인·계측기처럼 정기적으로 점검·검사·검교정을 받아야 하는 자산에
   '➕ 점검 계획 등록'으로 주기(예: 12개월)와 최근 점검일을 넣습니다. 다음 점검일이 자동으로 정해집니다.
2. **지연·임박 확인** — 위 카드의 **[목록 보기]** 를 누르면 처리할 목록이 나옵니다. 사이드바 🔔 알림에도 뜹니다.
3. **점검하고 완료 기록** — 점검을 마치면 그 줄의 **✅ 점검 완료** 를 눌러 점검일·결과·비용을 넣습니다.
   다음 점검일이 주기만큼 자동으로 넘어가 목록에서 빠집니다. 여러 건을 같은 날 정상 완료했다면 체크 후 **일괄 완료**.
   업체 일정 등으로 미뤄야 하면 **📅 일정 변경** (사유가 이력에 남습니다).
4. **이상이 있으면 수리** — 결과가 '조치 필요·불합격'이면 자산이 **수리중**으로 바뀌어 '수리 중' 목록에 올라갑니다.
   수리가 끝나면 **🔧 수리 완료** 를 눌러 비용을 기록하면 다시 사용중이 됩니다.
5. **보증 관리** — 보증 만료가 다가오면 무상 수리를 받거나(**🔧 보증 수리**), 연장 보증을 샀다면 **🛡 보증 연장** 으로 만료일을 바꿉니다.

누적 수리비가 장부가보다 크면 ♻️ 처분 검토 대상에 자동으로 올라갑니다.
"""


@st.dialog("✅ 점검 완료 기록", width="large")
def dlg_plan_done(pno: str, u: dict):
    p = d.lookup("maint_plans", pno)
    a = d.get_asset(p["태그번호"]) if p else None
    if not p or not a:
        st.error("점검 계획을 찾을 수 없습니다.")
        return
    st.markdown(f"**{html.escape(p['점검명'])}** · {html.escape(a['품명'])} ({a['태그번호']}) · {a['현장']} · "
                f"예정일 {ui.fmt_date(p['다음점검일'])} · {p['주기개월']}개월마다")
    if not wf.manages(u, a["현장"]):
        st.info(f"{a['현장']} 담당자가 기록합니다.")
        return
    vendors = [""] + ops.vendor_names()
    c1, c2, c3 = st.columns(3)
    when = c1.date_input("점검일", value=d.today(), key=f"pd-when-{pno}")
    result = c2.selectbox("결과", ["정상", "조치 필요", "불합격"], key=f"pd-res-{pno}")
    cost = c3.number_input("비용(원)", min_value=0, step=10000, key=f"pd-cost-{pno}")
    content = st.text_input("내용", value=p["점검명"], key=f"pd-txt-{pno}")
    vendor = st.selectbox("업체", vendors, index=vendors.index(p["담당업체"]) if p["담당업체"] in vendors else 0, key=f"pd-v-{pno}", format_func=lambda x: x or "(선택 안 함)")
    repair = False
    if result != "정상":
        repair = st.checkbox("자산을 '수리중'으로 바꾸기 (수리가 끝나면 🔧 수리 완료로 되돌립니다)", value=True, key=f"pd-rep-{pno}")
    st.caption(f"저장하면 다음 점검일이 {ui.fmt_date(d._shift_months_exact(when, int(p['주기개월'] or 12)))}(으)로 바뀝니다.")
    if st.button("✅ 점검 완료 기록", type="primary", width="stretch", key=f"pd-go-{pno}"):
        if ui.run_action(ops.complete_plan, pno, when, result, cost, content, vendor, auth.actor(u), repair,
                         success=f"{a['품명']} {p['점검명']} 완료를 기록했습니다. 다음 점검일이 갱신되었습니다."):
            st.rerun()


@st.dialog("✅ 일괄 점검 완료", width="large")
def dlg_plan_bulk(pnos: list[str], u: dict):
    plans = [p for p in (d.lookup("maint_plans", n) for n in pnos) if p]
    st.markdown(f"선택한 **{len(plans)}건**을 같은 날 **정상** 완료로 기록합니다. 비용·이상이 있는 건은 한 건씩 기록하세요.")
    st.dataframe(pd.DataFrame(plans)[["계획번호", "점검명", "태그번호", "다음점검일", "담당업체"]], hide_index=True, width="stretch")
    when = st.date_input("점검일", value=d.today(), key="pb-when")
    if st.button(f"✅ {len(plans)}건 완료 기록", type="primary", width="stretch"):
        n = ui.run_action(ops.complete_plans_bulk, [p["계획번호"] for p in plans], when, auth.actor(u))
        if n:
            for k in [k for k in st.session_state if str(k).startswith("mt-pick-")]:
                del st.session_state[k]
            ui.flash(f"{n}건 점검 완료를 기록했습니다.")
            st.rerun()


@st.dialog("📅 점검 일정 변경")
def dlg_postpone(pno: str, u: dict):
    p = d.lookup("maint_plans", pno)
    if not p:
        st.error("점검 계획을 찾을 수 없습니다.")
        return
    st.markdown(f"**{html.escape(p['점검명'])}** · {p['태그번호']} · 지금 예정일 {ui.fmt_date(p['다음점검일'])}")
    new = st.date_input("새 점검일", value=d.today() + timedelta(days=14), key=f"pp-date-{pno}")
    reason = st.text_input("사유 *", placeholder="예: 업체 일정, 장비 가동 중", key=f"pp-why-{pno}")
    if st.button("일정 변경", type="primary", width="stretch", key=f"pp-go-{pno}"):
        if ui.run_action(ops.postpone_plan, pno, new, reason, auth.actor(u), success="점검 일정을 바꿨습니다."):
            st.rerun()


@st.dialog("🔧 수리 기록", width="large")
def dlg_repair(tag: str, u: dict, warranty: bool = False):
    a = d.get_asset(tag)
    if not a:
        st.error("자산을 찾을 수 없습니다.")
        return
    st.markdown(f"**{html.escape(a['품명'])}** ({tag}) · {a['현장']} · 지금 상태 {ui.badge(a['상태'])}"
                + (f" · 보증 만료 {ui.fmt_date(a['보증만료일'])}" if a["보증만료일"] else ""), unsafe_allow_html=True)
    vendors = [""] + ops.vendor_names()
    c1, c2 = st.columns(2)
    when = c1.date_input("수리일", value=d.today(), key=f"rp-when-{tag}")
    vendor = c2.selectbox("수리 업체", vendors, key=f"rp-v-{tag}", format_func=lambda x: x or "(선택 안 함)")
    content = st.text_input("수리 내용 *", placeholder="예: 유압 실린더 교체", key=f"rp-txt-{tag}")
    c1, c2 = st.columns(2)
    warranty = c1.checkbox("보증(무상) 수리", value=warranty, key=f"rp-w-{tag}")
    cost = c2.number_input("비용(원)", min_value=0, step=10000, key=f"rp-cost-{tag}", disabled=warranty)
    status = st.radio("수리 상태", ["수리 완료 (사용중으로 복귀)", "수리 진행 중 (수리중으로 표시)"],
                      index=0 if a["상태"] == "수리중" else 1, horizontal=True, key=f"rp-st-{tag}")
    if st.button("🔧 수리 기록", type="primary", width="stretch", key=f"rp-go-{tag}"):
        if ui.run_action(ops.record_repair, tag, when, content, vendor, cost, status.startswith("수리 완료"), auth.actor(u), warranty,
                         success="수리 기록을 남겼습니다."):
            st.rerun()


@st.dialog("🛡 보증 연장")
def dlg_warranty(tag: str, u: dict):
    a = d.get_asset(tag)
    if not a:
        st.error("자산을 찾을 수 없습니다.")
        return
    st.markdown(f"**{html.escape(a['품명'])}** ({tag}) · 지금 보증 만료 {ui.fmt_date(a['보증만료일'])}")
    base = a["보증만료일"] or d.today()
    new = st.date_input("새 보증 만료일", value=d._shift_months_exact(base, 12), key=f"wr-date-{tag}")
    note = st.text_input("메모", placeholder="예: 연장 보증 1년 구매, 계약번호", key=f"wr-note-{tag}")
    if st.button("🛡 연장", type="primary", width="stretch", key=f"wr-go-{tag}"):
        if ui.run_action(ops.extend_warranty, tag, new, note, auth.actor(u), success="보증 만료일을 바꿨습니다."):
            st.rerun()


@st.dialog("➕ 점검 계획 등록", width="large")
def dlg_new_plan(u: dict):
    scope = _scope(u)
    q = st.text_input("자산 찾기 (태그번호·품명·규격)", key="np-q", placeholder="예: 지게차, MCH-2023").strip().lower()
    pool = [a for a in d.active_assets() if (not scope or a["현장"] == scope)
            and (not q or q in a["태그번호"].lower() or q in a["품명"].lower() or q in a["규격"].lower())]
    if not q:
        pool = [a for a in pool if a["계정과목"] in ("기계장치", "공기구비품", "차량운반구")]
    pool = pool[:200]
    if not pool:
        st.info("찾는 자산이 없습니다.")
        return
    tag = st.selectbox("자산", [a["태그번호"] for a in pool], key="np-tag",
                       format_func=lambda t: next(f"{t} · {a['품명']} · {a['현장']}" for a in pool if a["태그번호"] == t))
    c1, c2 = st.columns(2)
    name = c1.text_input("점검명 *", placeholder="예: 지게차 안전검사", key="np-name")
    kind = c2.selectbox("구분", ["정기점검", "법정검사", "검교정"], key="np-kind")
    c1, c2, c3 = st.columns(3)
    months = c1.number_input("주기(개월)", min_value=1, max_value=120, value=12, key="np-m")
    last = c2.date_input("최근 점검일", value=d.today(), key="np-last")
    vendor = c3.selectbox("담당 업체", [""] + ops.vendor_names(), key="np-v", format_func=lambda x: x or "(선택 안 함)")
    st.caption(f"다음 점검일: {ui.fmt_date(d._shift_months_exact(last, int(months)))}")
    if st.button("계획 등록", type="primary", width="stretch", key="np-go"):
        if ui.run_action(ops.save_plan, {"태그번호": tag, "점검명": name, "구분": kind, "주기개월": months,
                                         "최근점검일": last, "담당업체": vendor}, auth.actor(u), success="점검 계획을 등록했습니다."):
            st.rerun()


def _row_buttons(btns: list[tuple], key: str):
    for i, (col, (label, fn, primary)) in enumerate(zip(st.columns(len(btns)), btns)):
        if col.button(label, key=f"{key}-{i}", width="stretch", type="primary" if primary else "secondary"):
            fn()


def _search(rows: list[dict], key: str, fields=("태그번호", "품명", "현장")) -> list[dict]:
    q = st.text_input("검색", key=key, placeholder="태그번호·품명·현장·점검명", label_visibility="collapsed").strip().lower()
    return [r for r in rows if not q or any(q in str(r.get(f, "")).lower() for f in fields)]


def _plan_list(rows: list[dict], u: dict, key: str):
    rows = _search(rows, f"{key}-q", ("태그번호", "품명", "현장", "점검명", "담당업체"))
    if not rows:
        st.success("처리할 점검이 없습니다.")
        return
    mine = [p for p in rows if wf.manages(u, p["현장"])]
    picked = [p["계획번호"] for p in mine if st.session_state.get(f"mt-pick-{p['계획번호']}")]
    c1, c2 = st.columns([3, 1.4])
    c1.caption(f"{len(rows)}건 · 줄마다 버튼으로 처리하거나, 왼쪽을 체크해 같은 날 정상 완료한 건을 한 번에 기록합니다.")
    if c2.button(f"✅ 선택 {len(picked)}건 일괄 완료", disabled=not picked, width="stretch", key=f"{key}-bulk"):
        dlg_plan_bulk(picked, u)
    for p in ui.paginate(rows, key, 20):
        can = wf.manages(u, p["현장"])
        with st.container(border=True):
            c0, c1, c2 = st.columns([0.3, 3.2, 2.6], vertical_alignment="center")
            if can:
                c0.checkbox("선택", key=f"mt-pick-{p['계획번호']}", label_visibility="collapsed")
            late = p["남은 일수"] < 0
            c1.markdown(f"{'🔴' if late else '🟡'} **{html.escape(p['품명'])} · {html.escape(p['점검명'])}** "
                        f"<span class='badge {'rejected' if late else 'pending'}'>{'지연 ' + str(-p['남은 일수']) + '일' if late else str(p['남은 일수']) + '일 남음'}</span>"
                        f"<br><span class='small-muted'>{p['태그번호']} · {p['현장']} · {p['구분']} · 예정일 {ui.fmt_date(p['다음점검일'])} · "
                        f"{p['주기개월']}개월마다 · {html.escape(p['담당업체'] or '업체 미지정')}</span>", unsafe_allow_html=True)
            with c2:
                if can:
                    _row_buttons([("✅ 점검 완료", lambda p=p: dlg_plan_done(p["계획번호"], u), True),
                                  ("📅 일정 변경", lambda p=p: dlg_postpone(p["계획번호"], u), False),
                                  ("🔍 자산", lambda p=p: wf.asset_dialog(p["태그번호"], u), False)], f"{key}-{p['계획번호']}")
                else:
                    st.caption(f"{p['현장']} 담당자 처리")


def maint_page(u: dict):
    st.title("🔧 정기 점검 · 수리 · 보증")
    scope = _scope(u)
    days = d.setting_num("알림 기준일", 30)
    due = ops.plans_due(days, scope)
    late = [p for p in due if p["상태"] == "지연"]
    soon = [p for p in due if p["상태"] == "임박"]
    warr = ops.warranty_expiring(days, scope)
    fixing = ops.repairing_assets(scope)
    logs = [r for r in d.load("maint_logs") if not scope or (d.get_asset(r["태그번호"]) or {}).get("현장") == scope]
    year_cost = sum(r["비용"] or 0 for r in logs if r["일자"] and r["일자"].year == d.today().year)

    g1, g2 = st.columns([5, 1.4])
    with g1.expander("📖 사용 방법 — 점검 계획 → 점검 완료 기록 → 이상 시 수리 → 보증 관리", expanded=not st.session_state.get("mt-view")):
        st.markdown(MT_GUIDE)
    if u.get("역할") in (ADMIN,) + SITE_ROLES and g2.button("➕ 점검 계획 등록", type="primary", width="stretch"):
        dlg_new_plan(u)

    views = {"late": "🔴 점검 지연", "soon": "🟡 점검 임박", "fix": "🔧 수리 중", "warr": "🛡 보증 만료 임박",
             "plans": "🗓 점검 계획 전체", "logs": "🧾 점검·수리 기록", "top": "💸 수리비 많은 자산"}
    cards = [("late", "점검 지연", len(late), "예정일이 지난 점검", "crit" if late else "", "건"),
             ("soon", "점검 임박", len(soon), f"{days}일 안 예정", "warn" if soon else "", "건"),
             ("fix", "수리 중", len(fixing), "수리 완료 기록 대기", "warn" if fixing else "", "개"),
             ("warr", "보증 만료 임박", len(warr), f"{days}일 안", "warn" if warr else "", "개")]
    cols = st.columns(5)
    for col, (v, title, n, cap, tone, unit) in zip(cols, cards):
        with col:
            ui.kpi(title, n, cap, tone, unit)
            if st.button("목록 보기 ›", key=f"mt-card-{v}", width="stretch", type="primary" if st.session_state.get("mt-view") == v else "secondary"):
                st.session_state["mt-view"] = v
                st.rerun()
    with cols[4]:
        ui.kpi(f"{d.today().year}년 점검·수리비", ui.short_won(year_cost), ui.won(year_cost), unit="원")
        if st.button("기록 보기 ›", key="mt-card-logs", width="stretch"):
            st.session_state["mt-view"] = "logs"
            st.rerun()

    if st.session_state.get("mt-view") not in views:
        st.session_state["mt-view"] = "late" if late else "soon" if soon else "plans"
    view = st.segmented_control("보기", list(views), format_func=views.get, key="mt-view", label_visibility="collapsed") or "late"

    if view == "late":
        _plan_list(late, u, "mt-late")
    elif view == "soon":
        _plan_list(soon, u, "mt-soon")
    elif view == "fix":
        rows = _search(fixing, "mt-fix-q")
        if not rows:
            st.success("수리 중인 자산이 없습니다.")
        for a in ui.paginate(rows, "mt-fix", 20):
            last = next((r for r in sorted(ops.logs_for(a["태그번호"]), key=lambda r: r["일자"] or d.today(), reverse=True)), None)
            with st.container(border=True):
                c1, c2 = st.columns([3.5, 2.6], vertical_alignment="center")
                c1.markdown(f"🔧 **{html.escape(a['품명'])}** · {a['태그번호']} · {a['현장']}"
                            + (f"<br><span class='small-muted'>최근: {ui.fmt_date(last['일자'])} {html.escape(last['구분'])} · {html.escape(last['내용'])}</span>" if last else ""),
                            unsafe_allow_html=True)
                with c2:
                    if wf.manages(u, a["현장"]):
                        _row_buttons([("🔧 수리 완료", lambda a=a: dlg_repair(a["태그번호"], u), True),
                                      ("🔍 자산", lambda a=a: wf.asset_dialog(a["태그번호"], u), False)], f"mt-fix-{a['태그번호']}")
    elif view == "warr":
        rows = _search(warr, "mt-warr-q")
        if not rows:
            st.success(f"{days}일 안에 보증이 끝나는 자산이 없습니다.")
        for a in ui.paginate(rows, "mt-warr", 20):
            left = (a["보증만료일"] - d.today()).days
            with st.container(border=True):
                c1, c2 = st.columns([3.2, 2.9], vertical_alignment="center")
                c1.markdown(f"🛡 **{html.escape(a['품명'])}** · {a['태그번호']} · {a['현장']}"
                            f"<br><span class='small-muted'>보증 만료 {ui.fmt_date(a['보증만료일'])} ({left}일 남음) · "
                            f"{html.escape(a.get('공급업체') or a.get('구매처') or '')}</span>", unsafe_allow_html=True)
                with c2:
                    if wf.manages(u, a["현장"]):
                        _row_buttons([("🔧 보증 수리", lambda a=a: dlg_repair(a["태그번호"], u, True), True),
                                      ("🛡 보증 연장", lambda a=a: dlg_warranty(a["태그번호"], u), False),
                                      ("🔍 자산", lambda a=a: wf.asset_dialog(a["태그번호"], u), False)], f"mt-warr-{a['태그번호']}")
        st.caption("보증이 끝나기 전에 점검을 받아 무상 수리를 신청하세요. 연장 보증을 샀다면 '보증 연장'으로 만료일을 바꿉니다.")
    elif view == "plans":
        plans = []
        for p in d.load("maint_plans"):
            a = d.get_asset(p["태그번호"])
            if p["활성"] == "Y" and a and d.is_active(a) and (not scope or a["현장"] == scope):
                plans.append({**p, "품명": a["품명"], "현장": a["현장"],
                              "남은 일수": (p["다음점검일"] - d.today()).days if p["다음점검일"] else 0})
        plans.sort(key=lambda p: p["다음점검일"] or d.today())
        st.caption(f"등록된 점검 계획 {len(plans):,}건 (보유 자산 기준). 새 자산은 오른쪽 위 '➕ 점검 계획 등록'으로 추가합니다.")
        _plan_list(plans, u, "mt-all")
    elif view == "logs":
        c1, c2 = st.columns([1, 2])
        kind = c1.selectbox("구분", ["전체"] + ops.MAINT_KINDS, key="mt-log-kind")
        q = c2.text_input("검색", key="mt-log-q", placeholder="태그번호·내용·업체").strip().lower()
        rows = sorted([r for r in logs if (kind == "전체" or r["구분"] == kind)
                       and (not q or q in r["태그번호"].lower() or q in r["내용"].lower() or q in r["업체"].lower())],
                      key=lambda r: r["일자"] or d.today(), reverse=True)
        if not rows:
            st.info("기록이 없습니다.")
        else:
            cols = ["기록번호", "일자", "구분", "태그번호", "내용", "업체", "비용", "결과", "등록자"]
            df = pd.DataFrame(ui.paginate(rows, f"mt-log-{kind}-{q}", 500))[cols]
            df["등록자"] = df["등록자"].map(_clean)
            st.dataframe(df, hide_index=True, width="stretch", column_config=ui.money_config("비용"))
            st.caption(f"{len(rows):,}건 · 비용 합계 {ui.won(sum(r['비용'] or 0 for r in rows))}")
            st.download_button("📥 기록 엑셀", d.rows_to_xlsx({"점검수리기록": (cols, rows)}), file_name=f"점검수리기록_{d.today():%Y%m%d}.xlsx")
    else:
        top = [r for r in ops.top_repairs(50) if not scope or r["현장"] == scope][:20]
        if not top:
            st.info("수리 기록이 없습니다.")
        else:
            st.caption("누적 수리비가 장부가보다 크면 '♻️ 처분 검토' 대상에 자동으로 올라갑니다.")
            df = pd.DataFrame(top)
            df["수리비/장부가"] = df.apply(lambda r: f"{r['누적 수리비'] / r['장부가']:.1f}배" if r["장부가"] else "-", axis=1)
            st.dataframe(df, hide_index=True, width="stretch", column_config=ui.money_config("누적 수리비", "장부가"))


# =========================================================
# 👥 직원 · 퇴사 회수
# =========================================================
EMP_TEMPLATE_COLS = ["사번", "이름", "현장", "부서", "직급", "이메일", "연락처", "입사일"]


def people_page(u: dict):
    st.title("👥 직원별 보유 자산 · 퇴사 회수")
    st.caption("누가 어떤 자산을 가지고 있는지 보고, 퇴사·휴직 때 자산과 소프트웨어를 빠짐없이 회수합니다. "
               "회수 → 유휴(재배치 대상), 인계 → 다른 직원, 분실 → 경위서 요청으로 처리하며, 모두 끝나면 라이선스가 자동 해제됩니다.")
    scope = _scope(u)
    actor = auth.actor(u)
    returns = ops.get_returns(scope)
    open_returns = [r for r in returns if r["상태"] == "진행중"]
    tabs = st.tabs(["👤 직원별 보유 현황", f"📦 퇴사 회수 ({len(open_returns)})", "➕ 직원 등록·가져오기"])
    with tabs[0]:
        rows = ops.holders_summary(scope)
        c1, c2, c3 = st.columns([1, 1, 2])
        status = c1.selectbox("상태", ["재직", "퇴사예정", "퇴사", "전체"], key="pp-status")
        site = c2.selectbox("현장", ["전체"] + d.site_names(), key="pp-site") if not scope else scope
        q = c3.text_input("검색", key="pp-q", placeholder="이름·사번·부서").strip().lower()
        rows = [e for e in rows if (status == "전체" or e["상태"] == status) and (site == "전체" or e["현장"] == site)
                and (not q or q in e["이름"].lower() or q in e["사번"].lower() or q in e["부서"].lower())]
        if not rows:
            st.info("직원이 없습니다. '➕ 직원 등록·가져오기'에서 등록하세요.")
        else:
            df = pd.DataFrame(rows)[["사번", "이름", "현장", "부서", "직급", "상태", "보유 자산", "취득가액", "입사일", "퇴사일"]]
            ev = st.dataframe(df, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                              key=f"pp-table-{status}-{site}", column_config=ui.money_config("취득가액"), height=380)
            sel = [df.iloc[i]["사번"] for i in ev.selection.rows if i < len(df)]
            if sel:
                emp = d.lookup("employees", sel[0])
                assets = ops.employee_assets(emp)
                lic = ops.employee_licenses(emp)
                st.markdown(f"#### {html.escape(emp['이름'])} ({emp['사번']} · {emp['부서']}) — 자산 {len(assets)}개 · 소프트웨어 {len(lic)}개")
                if assets:
                    st.dataframe(ui.asset_frame(assets), hide_index=True, width="stretch", column_config=ui.ASSET_COLUMN_CONFIG)
                if lic:
                    st.dataframe(pd.DataFrame([{"소프트웨어": (d.lookup("licenses", x["라이선스번호"]) or {}).get("소프트웨어명", ""),
                                                "PC": x["PC태그"], "할당일": x["할당일"]} for x in lic]), hide_index=True, width="stretch")
                if emp["상태"] == "재직" and wf.manages(u, emp["현장"]):
                    with st.form(f"pp-ret-{emp['사번']}"):
                        st.markdown("**🚪 퇴사 회수 시작**")
                        retire = st.date_input("퇴사(예정)일", value=d.today() + timedelta(days=7))
                        if st.form_submit_button("회수 체크리스트 만들기", type="primary"):
                            no = ui.run_action(ops.start_return, emp["사번"], retire, actor)
                            if no:
                                ui.flash(f"{emp['이름']} 퇴사 회수 {no}을(를) 시작했습니다." if assets else f"{emp['이름']}님은 회수할 자산이 없어 바로 퇴사 처리했습니다.")
                                st.rerun()
    with tabs[1]:
        if not returns:
            st.info("퇴사 회수 건이 없습니다. '직원별 보유 현황'에서 직원을 골라 시작하세요.")
        for r in returns[:30]:
            items = ops.return_items(r["회수번호"])
            left = [i for i in items if i["결과"] == "미처리"]
            with st.expander(f"{'🟡' if r['상태'] == '진행중' else '✅'} {r['회수번호']} · {r['이름']} ({r['현장']} {r['부서']}) · 퇴사일 {ui.fmt_date(r['퇴사일'])} · "
                             f"{len(items) - len(left)}/{len(items)} 처리", expanded=r["상태"] == "진행중" and len(open_returns) <= 3):
                if items:
                    st.dataframe(pd.DataFrame(items)[["태그번호", "품명", "결과", "인계자", "메모", "처리일시"]], hide_index=True, width="stretch")
                st.download_button("📄 회수 확인서 PDF", docs_pdf.return_pdf(r), file_name=f"자산회수확인서_{r['회수번호']}.pdf",
                                   mime="application/pdf", key=f"pp-pdf-{r['회수번호']}")
                if left and wf.manages(u, r["현장"]):
                    with st.form(f"pp-item-{r['회수번호']}"):
                        c1, c2 = st.columns([2, 1])
                        tag = c1.selectbox("자산", [i["태그번호"] for i in left],
                                           format_func=lambda t: next(f"{t} · {i['품명']}" for i in left if i["태그번호"] == t))
                        result = c2.radio("처리", ["회수", "인계", "분실"], horizontal=True)
                        c1, c2 = st.columns(2)
                        to = c1.text_input("인계받을 직원 (인계일 때)")
                        memo = c2.text_input("메모", placeholder="예: 충전기 포함 회수")
                        if st.form_submit_button("처리", type="primary"):
                            done = ui.run_action(ops.process_return_item, r["회수번호"], tag, result, to, memo, actor)
                            if done is not None:
                                ui.flash(f"{tag} {result} 처리했습니다." + (" 모든 자산 처리를 마쳐 퇴사 회수를 완료했습니다(라이선스 해제)." if done is True and len(left) == 1 else ""))
                                st.rerun()
    with tabs[2]:
        if u.get("역할") not in (ADMIN,) + SITE_ROLES:
            st.info("직원 등록은 관리자·현장 담당자가 합니다.")
            return
        sites = [scope] if scope else d.site_names()
        with st.form("pp-new", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            name = c1.text_input("이름 *")
            site = c2.selectbox("현장 *", sites)
            dept = c3.text_input("부서")
            c1, c2, c3 = st.columns(3)
            no = c1.text_input("사번 (비우면 자동)")
            rank = c2.text_input("직급")
            joined = c3.date_input("입사일", value=d.today())
            c1, c2 = st.columns(2)
            email = c1.text_input("이메일")
            phone = c2.text_input("연락처")
            if st.form_submit_button("직원 등록", type="primary"):
                got = ui.run_action(ops.save_employee, {"사번": no, "이름": name, "현장": site, "부서": dept, "직급": rank,
                                                        "입사일": joined, "이메일": email, "연락처": phone}, actor)
                if got:
                    ui.flash(f"{name} ({got}) 직원을 등록했습니다.")
                    st.rerun()
        st.markdown("**📤 엑셀로 한꺼번에 가져오기** (인사 시스템에서 내려받은 명단)")
        st.download_button("📄 직원 명단 양식", ui.excel_bytes({"직원": pd.DataFrame([{"사번": "E2026001", "이름": "홍길동", "현장": sites[0] if sites else "",
                                                                                     "부서": "공무팀", "직급": "대리", "이메일": "", "연락처": "", "입사일": d.today()}],
                                                                                   columns=EMP_TEMPLATE_COLS)}), file_name="직원명단_양식.xlsx")
        up = st.file_uploader("직원 명단 엑셀", type=["xlsx"], key="pp-up")
        if up is not None:
            try:
                rows = d.read_upload_rows(up)
            except Exception as exc:
                st.error(f"파일을 읽지 못했습니다: {exc}")
                rows = []
            if scope:
                rows = [r for r in rows if d.clean_str(r.get("현장")) == scope]
            if rows:
                st.dataframe(pd.DataFrame(rows[:300]), hide_index=True, width="stretch")
                if st.button(f"📥 {len(rows):,}명 가져오기", type="primary", key="pp-import"):
                    res = ui.run_action(ops.import_employees, rows, actor)
                    if res:
                        n, errors = res
                        if errors:
                            st.error("가져오지 않았습니다. 아래 행을 고쳐 주세요.")
                            for e in errors[:30]:
                                st.write("• " + e)
                        else:
                            ui.flash(f"직원 {n:,}명을 등록·갱신했습니다.")
                            st.rerun()


# =========================================================
# 💿 소프트웨어 라이선스
# =========================================================
def license_page(u: dict):
    st.title("💿 소프트웨어 라이선스")
    st.caption("CAD·오피스·설계 프로그램처럼 사용자 수로 사는 소프트웨어의 보유 수량, 누가 쓰는지, 만료·갱신일을 관리합니다. "
               "보유보다 많이 쓰면(초과 사용) 감사 위험이 있어 알림을 보냅니다.")
    actor = auth.actor(u)
    usage = ops.license_usage()
    k = st.columns(4)
    with k[0]: ui.kpi("라이선스", len(usage), "등록된 소프트웨어", unit="종")
    with k[1]: ui.kpi("사용 / 보유", f"{sum(x['사용'] for x in usage):,} / {sum(int(x['보유수량'] or 0) for x in usage):,}", "사용자 수 기준", unit="")
    exp = ops.licenses_expiring()
    with k[2]: ui.kpi("만료 임박", len(exp), f"{d.setting_num('알림 기준일', 30) * 2}일 안", "warn" if exp else "", "건")
    cost = sum(x["갱신비용"] or 0 for x in exp)
    with k[3]: ui.kpi("임박 갱신비", ui.short_won(cost), ui.won(cost), unit="원")

    tabs = st.tabs(["📋 현황", "👤 할당 · 해제", "➕ 등록 · 수정"])
    with tabs[0]:
        if not usage:
            st.info("등록된 라이선스가 없습니다.")
        else:
            df = pd.DataFrame(usage)[["라이선스번호", "소프트웨어명", "에디션", "유형", "보유수량", "사용", "남음", "사용률(%)", "만료일", "만료까지(일)", "갱신비용", "공급업체", "상태"]]
            st.dataframe(df, hide_index=True, width="stretch", column_config={
                **ui.money_config("갱신비용"),
                "사용률(%)": st.column_config.ProgressColumn("사용률", min_value=0, max_value=100, format="%.0f%%")})
            st.download_button("📥 라이선스 현황 엑셀", d.rows_to_xlsx({
                "라이선스": (list(df.columns), df.to_dict("records")),
                "할당": (d.TABLES["license_assign"]["cols"], d.load("license_assign"))}), file_name=f"라이선스_{d.today():%Y%m%d}.xlsx")
    with tabs[1]:
        active = [x for x in usage if x["상태"] == "사용"]
        if not active:
            st.info("사용 중인 라이선스가 없습니다.")
        else:
            no = st.selectbox("라이선스", [x["라이선스번호"] for x in active],
                              format_func=lambda n: next(f"{x['소프트웨어명']} {x['에디션']} · 사용 {x['사용']}/{int(x['보유수량'])}" for x in active if x["라이선스번호"] == n),
                              key="lc-pick")
            assigned = [x for x in d.load("license_assign") if x["라이선스번호"] == no and x["상태"] == "사용중"]
            if assigned:
                df = pd.DataFrame(assigned)[["할당번호", "사용자", "사번", "부서", "현장", "PC태그", "할당일"]]
                ev = st.dataframe(df, hide_index=True, width="stretch", on_select="rerun", selection_mode="multi-row", key=f"lc-as-{no}")
                sel = [df.iloc[i]["할당번호"] for i in ev.selection.rows if i < len(df)]
                if st.button(f"선택한 {len(sel)}명 해제", disabled=not sel, key="lc-release"):
                    for aid in sel:
                        ops.release_license(aid, actor, "관리자 해제")
                    ui.flash(f"{len(sel)}명의 라이선스를 해제했습니다.")
                    st.rerun()
            emps = [e for e in ops.get_employees(status="재직")]
            with st.form(f"lc-assign-{no}"):
                labels = {"": "직접 입력"} | {e["사번"]: f"{e['이름']} ({e['현장']} {e['부서']} · {e['사번']})" for e in emps[:3000]}
                c1, c2 = st.columns(2)
                pick = c1.selectbox("직원", list(labels), format_func=lambda k2: labels[k2])
                name = c2.text_input("사용자 (직접 입력)")
                c1, c2 = st.columns(2)
                pc = c1.text_input("설치 PC 태그번호 (선택)")
                dept = c2.text_input("부서 (직접 입력 시)")
                if st.form_submit_button("할당", type="primary"):
                    emp = next((e for e in emps if e["사번"] == pick), None)
                    if ui.run_action(ops.assign_license, no, emp["이름"] if emp else name, emp["사번"] if emp else "",
                                     emp["부서"] if emp else dept, emp["현장"] if emp else "", pc, actor, success="할당했습니다."):
                        st.rerun()
    with tabs[2]:
        cur_no = st.selectbox("수정할 라이선스", [""] + [x["라이선스번호"] for x in usage],
                              format_func=lambda n: "새로 등록" if not n else next(f"{x['소프트웨어명']} ({n})" for x in usage if x["라이선스번호"] == n),
                              key="lc-edit-pick")
        cur = d.lookup("licenses", cur_no) or {}
        with st.form(f"lc-form-{cur_no}"):
            c1, c2, c3 = st.columns(3)
            name = c1.text_input("소프트웨어명 *", value=cur.get("소프트웨어명", ""))
            edition = c2.text_input("에디션", value=cur.get("에디션", ""))
            types = ["구독(연간)", "구독(월간)", "영구", "사이트"]
            kind = c3.selectbox("유형", types, index=types.index(cur["유형"]) if cur.get("유형") in types else 0)
            c1, c2, c3 = st.columns(3)
            qty = c1.number_input("보유 수량 *", min_value=1, value=int(cur.get("보유수량") or 1))
            contract = c2.date_input("계약일", value=cur.get("계약일") or d.today())
            expire = c3.date_input("만료일 (영구면 비움)", value=cur.get("만료일"))
            c1, c2, c3 = st.columns(3)
            renew = c1.number_input("갱신 비용(원)", min_value=0, step=100000, value=int(cur.get("갱신비용") or 0))
            vendors = [""] + ops.vendor_names()
            vendor = c2.selectbox("공급업체", vendors, index=vendors.index(cur["공급업체"]) if cur.get("공급업체") in vendors else 0)
            status = c3.selectbox("상태", ["사용", "해지"], index=1 if cur.get("상태") == "해지" else 0)
            memo = st.text_input("비고", value=cur.get("비고", ""))
            if st.form_submit_button("💾 저장", type="primary"):
                got = ui.run_action(ops.save_license, {"라이선스번호": cur_no, "소프트웨어명": name, "에디션": edition, "유형": kind,
                                                       "보유수량": qty, "계약일": contract, "만료일": expire, "갱신비용": renew,
                                                       "공급업체": vendor, "상태": status, "비고": memo}, actor)
                if got:
                    ui.flash(f"{name} 라이선스를 저장했습니다 ({got}).")
                    st.rerun()


# =========================================================
# 📑 렌탈 · 리스
# =========================================================
def lease_page(u: dict):
    st.title("📑 렌탈 · 리스 계약")
    st.caption("회사 소유가 아닌 렌탈·리스 장비(업무용 렌트 차량, 복합기, 정수기, 장비 리스)는 자산대장에 넣지 않고 계약으로 관리합니다. "
               "만료 전에 연장·반납을 결정하도록 알림을 보냅니다.")
    scope = _scope(u)
    can_edit = u.get("역할") in (ADMIN, FIN)
    leases = ops.get_leases(scope)
    active = [x for x in leases if x["상태"] == "사용중"]
    exp = ops.leases_expiring(site=scope)
    k = st.columns(4)
    with k[0]: ui.kpi("사용 중 계약", len(active), scope or "전체 현장", unit="건")
    with k[1]: ui.kpi("월 비용", ui.short_won(ops.lease_monthly_cost(scope)), "사용 중 계약 합계", unit="원")
    with k[2]: ui.kpi("연 환산", ui.short_won(ops.lease_monthly_cost(scope) * 12), "", unit="원")
    with k[3]: ui.kpi("만료 임박", len(exp), f"{d.setting_num('알림 기준일', 30) * 2}일 안", "warn" if exp else "", "건")
    if leases:
        cols = ["계약번호", "구분", "품명", "규격", "현장", "업체", "시작일", "종료일", "월요금", "보증금", "자동연장", "담당", "상태", "연결차량번호", "비고"]
        st.dataframe(pd.DataFrame(leases)[cols], hide_index=True, width="stretch", column_config=ui.money_config("월요금", "보증금"))
        st.download_button("📥 계약 목록 엑셀", d.rows_to_xlsx({"렌탈리스": (cols, leases)}), file_name=f"렌탈리스_{d.today():%Y%m%d}.xlsx")
    else:
        st.info("등록된 계약이 없습니다.")
    if not can_edit:
        return
    st.markdown("### ➕ 계약 등록 · 수정")
    pick = st.selectbox("수정할 계약", [""] + [x["계약번호"] for x in leases],
                        format_func=lambda n: "새로 등록" if not n else next(f"{x['품명']} · {x['현장']} ({n})" for x in leases if x["계약번호"] == n),
                        key="ls-pick")
    cur = d.lookup("leases", pick) or {}
    with st.form(f"ls-form-{pick}"):
        c1, c2, c3 = st.columns(3)
        kinds = ["렌탈", "운용리스", "금융리스"]
        kind = c1.selectbox("구분", kinds, index=kinds.index(cur["구분"]) if cur.get("구분") in kinds else 0,
                            help="금융리스는 회계상 자산(사용권자산)으로 잡는 경우가 많으니 재무팀과 확인하세요")
        name = c2.text_input("품명 *", value=cur.get("품명", ""))
        spec = c3.text_input("규격", value=cur.get("규격", ""))
        c1, c2, c3 = st.columns(3)
        sites = d.site_names()
        site = c1.selectbox("현장 *", sites, index=sites.index(cur["현장"]) if cur.get("현장") in sites else 0)
        vendor = c2.text_input("업체", value=cur.get("업체", ""))
        manager = c3.text_input("담당", value=cur.get("담당", ""))
        c1, c2, c3, c4 = st.columns(4)
        start = c1.date_input("시작일", value=cur.get("시작일") or d.today())
        end = c2.date_input("종료일", value=cur.get("종료일"))
        monthly = c3.number_input("월 요금(원)", min_value=0, step=10000, value=int(cur.get("월요금") or 0))
        deposit = c4.number_input("보증금(원)", min_value=0, step=100000, value=int(cur.get("보증금") or 0))
        c1, c2 = st.columns(2)
        auto = c1.checkbox("자동 연장", value=cur.get("자동연장") == "Y")
        status = c2.selectbox("상태", ["사용중", "반납", "해지"], index=["사용중", "반납", "해지"].index(cur["상태"]) if cur.get("상태") in ("사용중", "반납", "해지") else 0)
        memo = st.text_input("비고", value=cur.get("비고", ""))
        if st.form_submit_button("💾 저장", type="primary"):
            got = ui.run_action(ops.save_lease, {"계약번호": pick, "구분": kind, "품명": name, "규격": spec, "현장": site, "업체": vendor,
                                                 "담당": manager, "시작일": start, "종료일": end, "월요금": monthly, "보증금": deposit,
                                                 "자동연장": "Y" if auto else "", "상태": status, "비고": memo,
                                                 "연결차량번호": cur.get("연결차량번호", "")}, auth.actor(u))
            if got:
                ui.flash(f"계약 {got}을(를) 저장했습니다.")
                st.rerun()


# =========================================================
# 🏪 공급업체
# =========================================================
def vendor_page(u: dict):
    st.title("🏪 공급업체")
    st.caption("견적·발주에 쓰는 업체를 등록하고, 업체별 견적 참여·선정·거래금액·평균 납기·검수 불합격을 비교합니다. "
               "구매요청의 견적 입력과 자산 등록에서 이 목록을 고릅니다.")
    stats = ops.vendor_stats()
    if stats:
        st.dataframe(pd.DataFrame(stats), hide_index=True, width="stretch", column_config=ui.money_config("거래금액"))
    else:
        st.info("등록된 업체가 없습니다.")
    if u.get("역할") not in (ADMIN, FIN):
        return
    st.markdown("### ➕ 업체 등록 · 수정")
    known = sorted(v["업체명"] for v in d.load("vendors"))
    pick = st.selectbox("수정할 업체", [""] + known, format_func=lambda n: n or "새로 등록", key="vd-pick")
    cur = d.lookup("vendors", pick) or {}
    with st.form(f"vd-form-{pick}"):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("업체명 *", value=cur.get("업체명", ""), disabled=bool(pick))
        biz = c2.text_input("사업자번호", value=cur.get("사업자번호", ""))
        items = c3.text_input("취급 품목", value=cur.get("취급품목", ""), placeholder="예: PC·노트북, 측량장비")
        c1, c2, c3 = st.columns(3)
        person = c1.text_input("담당자", value=cur.get("담당자", ""))
        phone = c2.text_input("연락처", value=cur.get("연락처", ""))
        email = c3.text_input("이메일", value=cur.get("이메일", ""))
        c1, c2 = st.columns([3, 1])
        addr = c1.text_input("주소", value=cur.get("주소", ""))
        status = c2.selectbox("상태", ["거래중", "거래중지"], index=1 if cur.get("상태") == "거래중지" else 0)
        memo = st.text_input("비고", value=cur.get("비고", ""))
        if st.form_submit_button("💾 저장", type="primary"):
            if ui.run_action(ops.save_vendor, {"업체명": pick or name, "사업자번호": biz, "취급품목": items, "담당자": person, "연락처": phone,
                                               "이메일": email, "주소": addr, "상태": status, "비고": memo}, auth.actor(u), pick or None,
                             success="업체를 저장했습니다."):
                st.rerun()


# =========================================================
# 💰 예산
# =========================================================
def budget_page(u: dict):
    st.title("💰 현장별 자산 구매 예산")
    st.caption("현장별 연간 자산 구매 예산을 정하면, 구매요청을 낼 때·결재할 때 잔액이 함께 보이고 초과하면 경고합니다. "
               "집행 = 발주·검수·등록 완료 금액, 결재 중 = 요청·승인 단계 금액입니다.")
    can_edit = u.get("역할") in (ADMIN, FIN)
    year = st.selectbox("연도", list(range(d.today().year + 1, d.today().year - 5, -1)), index=1, key="bg-year")
    rows = ops.budget_status(year)
    df = pd.DataFrame(rows)
    total = {k: sum(r[k] for r in rows) for k in ("예산", "집행", "결재 중", "잔액")}
    k = st.columns(4)
    with k[0]: ui.kpi("예산", ui.short_won(total["예산"]), ui.won(total["예산"]), unit="원")
    with k[1]: ui.kpi("집행", ui.short_won(total["집행"]), f"{total['집행'] / total['예산'] * 100:.0f}%" if total["예산"] else "-", unit="원")
    with k[2]: ui.kpi("결재 중", ui.short_won(total["결재 중"]), "요청·승인 단계", unit="원")
    with k[3]: ui.kpi("잔액", ui.short_won(total["잔액"]), "", "crit" if total["잔액"] < 0 else "ok", "원")
    if can_edit:
        edited = st.data_editor(df[["현장", "예산", "집행", "결재 중", "잔액", "집행률(%)"]], hide_index=True, width="stretch",
                                disabled=["현장", "집행", "결재 중", "잔액", "집행률(%)"], key=f"bg-edit-{year}",
                                column_config={**ui.money_config("집행", "결재 중", "잔액"),
                                               "예산": st.column_config.NumberColumn("예산(원)", min_value=0, step=1_000_000, format="%,d")})
        if st.button("💾 예산 저장", type="primary"):
            if ui.run_action(ops.save_budgets, year, {r["현장"]: r["예산"] for r in edited.to_dict("records")}, auth.actor(u),
                             success=f"{year}년 예산을 저장했습니다."):
                st.rerun()
    else:
        st.dataframe(df, hide_index=True, width="stretch", column_config=ui.money_config("예산", "집행", "결재 중", "잔액"))
    chart = df[df["예산"] > 0]
    if not chart.empty:
        long = pd.concat([pd.DataFrame({"현장": chart["현장"], "구분": k2, "금액(백만원)": (chart[k2] / 1e6).round(1)})
                          for k2 in ("집행", "결재 중")])
        st.bar_chart(long, x="현장", y="금액(백만원)", color="구분", stack=True, height=280)
    st.markdown("**구매요청 내역**")
    prs = [r for r in d.load("pr") if r["요청일시"].startswith(str(year)) and r["상태"] != d.REJECTED]
    if prs:
        st.dataframe(pd.DataFrame([{"요청번호": r["요청번호"], "현장": r["현장"], "품명": r["품명"], "상태": r["상태"], "금액": d.pr_amount(r),
                                    "요청일시": r["요청일시"]} for r in sorted(prs, key=lambda r: r["요청일시"], reverse=True)]),
                     hide_index=True, width="stretch", column_config=ui.money_config("금액"))


# =========================================================
# 🔔 알림
# =========================================================
def all_alerts(u: dict) -> list[dict]:
    """지금 사용자의 알림 전체 (결재·대여 대기는 한 건씩)."""
    return ops.alerts_for(u, wf.pending_for(u), rentals=wf.pending_rentals(u))


@st.dialog("👥 퇴사 자산 회수", width="large")
def dlg_return(rno: str, u: dict):
    r = d.lookup("returns", rno)
    if not r:
        st.error("퇴사 회수 건을 찾을 수 없습니다.")
        return
    items = ops.return_items(rno)
    left = [i for i in items if i["결과"] == "미처리"]
    st.markdown(f"**{rno}** · {html.escape(r['이름'])} ({r['현장']} {r['부서']}) · 퇴사일 {ui.fmt_date(r['퇴사일'])} · "
                f"{len(items) - len(left)}/{len(items)} 처리")
    if items:
        st.dataframe(pd.DataFrame(items)[["태그번호", "품명", "결과", "인계자", "메모"]], hide_index=True, width="stretch")
    if not left:
        st.success("모든 자산을 처리했습니다.")
        return
    if not wf.manages(u, r["현장"]):
        st.info(f"{r['현장']} 담당자가 처리합니다.")
        return
    with st.form(f"dlg-ret-{rno}"):
        c1, c2 = st.columns([2, 1])
        tag = c1.selectbox("자산", [i["태그번호"] for i in left],
                           format_func=lambda t: next(f"{t} · {i['품명']}" for i in left if i["태그번호"] == t))
        result = c2.radio("처리", ["회수", "인계", "분실"], horizontal=True)
        c1, c2 = st.columns(2)
        to = c1.text_input("인계받을 직원 (인계일 때)")
        memo = c2.text_input("메모", placeholder="예: 충전기 포함 회수")
        if st.form_submit_button("처리", type="primary", width="stretch"):
            done = ui.run_action(ops.process_return_item, rno, tag, result, to, memo, auth.actor(u))
            if done is not None:
                ui.flash(f"{tag} {result} 처리했습니다." + (" 퇴사 회수를 모두 마쳤습니다." if len(left) == 1 else ""))
                st.rerun()


RENTAL_LABELS = {"r_approve": "✅ 승인", "r_reject": "❌ 반려", "r_handout": "📤 인계", "r_return": "📥 반납 확인"}


def alert_actions(a: dict, u: dict, key: str):
    """알림 한 건의 처리 버튼 (누르면 그 자리에서 처리 창이 열립니다)."""
    kind, *ref = a["대상"]
    btns = []  # (라벨, 실행 함수, 강조 여부)
    if kind == "req":
        rkind, no = ref
        rec = d.get_request(rkind, no)
        for act in (wf.actions_for(rkind, rec, u) if rec else []):
            btns.append((wf.ACTION_LABELS[act], lambda act=act: wf.open_action(rkind, act, no, u), act != "reject"))
        if rec:
            btns.append(("📄 상세", lambda: wf.dlg_request_detail(rkind, no, u), False))
    elif kind == "rental":
        r = d.lookup("rentals", ref[0])
        for act in (wf.rental_actions(r, u) if r else []):
            btns.append((RENTAL_LABELS[act], lambda act=act: dlg_rental(ref[0], act, u), act != "r_reject"))
    elif kind == "plan":
        btns.append(("✅ 점검 완료", lambda: dlg_plan_done(ref[0], u), True))
    elif kind == "return":
        btns.append(("📥 회수 처리", lambda: dlg_return(ref[0], u), True))
    elif kind == "asset":
        btns.append(("🔍 자산 보기", lambda: wf.asset_dialog(ref[0], u), False))
    elif ref and ref[0] in ui.PAGES:
        btns.append(("➡️ 바로가기", lambda: ui.goto(ref[0]), False))
    if not btns:
        st.caption("처리됨")
        return
    for i, (col, (label, fn, primary)) in enumerate(zip(st.columns(len(btns)), btns)):
        if col.button(label, key=f"{key}-{i}", width="stretch", type="primary" if primary else "secondary"):
            fn()


def alert_center(alerts: list[dict], u: dict, key: str, per_group: int = 30, expand_first: bool = False):
    """알림을 종류별로 묶어 건수와 함께 보여 줍니다. 종류를 펼치면 한 건씩 처리 버튼이 나옵니다."""
    if not alerts:
        st.success("확인할 알림이 없습니다.")
        return
    groups: dict[str, list[dict]] = {}
    for a in alerts:
        groups.setdefault(a["분류"], []).append(a)
    order = {"crit": 0, "warn": 1, "info": 2}
    names = sorted(groups, key=lambda g: (min(order[a["심각도"]] for a in groups[g]), -len(groups[g])))
    for gi, g in enumerate(names):
        rows = groups[g]
        crit = sum(1 for a in rows if a["심각도"] == "crit")
        icon = ui.ALERT_ICON[min((a["심각도"] for a in rows), key=order.get)]
        with st.expander(f"{icon} **{g}** · {len(rows)}건" + (f" (긴급 {crit})" if crit else ""),
                         expanded=expand_first and gi == 0 and len(names) > 1 or len(names) == 1):
            for i, a in enumerate(rows[:per_group]):
                c1, c2 = st.columns([3, 2.4], vertical_alignment="center")
                c1.markdown(f"{ui.ALERT_ICON[a['심각도']]} **{html.escape(_clean(a['제목']))}**"
                            + (f"  \n<span class='small-muted'>{html.escape(_clean(str(a['내용'])))}</span>" if a["내용"] else ""),
                            unsafe_allow_html=True)
                with c2:
                    alert_actions(a, u, f"{key}-{g}-{i}")
            if len(rows) > per_group:
                st.caption(f"… 외 {len(rows) - per_group}건 · 나머지는 해당 메뉴에서 처리하세요.")
                menu = rows[0].get("메뉴")
                if menu in ui.PAGES and st.button("➡️ 전체 보기", key=f"{key}-{g}-all"):
                    ui.goto(menu)


def alerts_page(u: dict):
    st.title("🔔 알림")
    st.caption("결재 대기, 반납 지연, 점검·보증·라이선스·계약 만료, 예산 초과, 경위서 요청, 퇴사 회수처럼 챙겨야 할 일을 모았습니다. "
               "종류를 펼쳐 한 건씩 바로 처리하세요.")
    alerts = all_alerts(u)
    crit_n = sum(1 for a in alerts if a["심각도"] == "crit")
    levels = {"all": f"전체 {len(alerts)}건", "crit": f"🔴 긴급 {crit_n}건"}
    want = st.session_state.pop("al-want", None)  # 사이드바 '알림'·'긴급' 버튼을 누르고 왔을 때
    if want is not None:
        st.session_state["al-level"] = ["all", "crit"][want]
    if st.session_state.get("al-level") not in levels:
        st.session_state["al-level"] = "all"
    c1, c2 = st.columns([2, 3])
    level = c1.segmented_control("보기", list(levels), format_func=levels.get, key="al-level",
                                 label_visibility="collapsed") or "all"
    shown = [a for a in alerts if a["심각도"] == "crit"] if level == "crit" else alerts
    cats = sorted({a["분류"] for a in shown})
    pick = c2.multiselect("분류", cats, placeholder="분류 골라 보기 (비우면 전체)", key="al-cats", label_visibility="collapsed")
    if pick:
        shown = [a for a in shown if a["분류"] in pick]
    st.caption("종류를 누르면 목록이 펼쳐지고, 각 건의 버튼으로 바로 처리합니다.")
    alert_center(shown, u, key="al")
    if u.get("역할") != ADMIN:
        return
    st.divider()
    st.markdown("### 📨 메일 · 메신저로 보내기")
    st.caption("설정의 메일·웹훅(Slack·Teams·Discord)으로 관리자 기준 알림 요약을 보냅니다. 매일 자동으로 보내려면 "
               "Windows 작업 스케줄러에 `python notify.py`를 등록하세요 (README 참고).")
    summary = ops.alerts_for(u, wf.pending_for(u), detail=False)
    with st.expander("보낼 내용 미리보기"):
        st.code(ops.digest_text(summary), language=None)
    if st.button("📨 지금 보내기", type="primary", disabled=d.ON_CLOUD, help="공개 데모에서는 보내지 않습니다" if d.ON_CLOUD else None):
        done = ops.send_digest(summary)
        if done:
            st.success(" · ".join(done))
        else:
            st.warning("메일 서버나 웹훅 주소가 설정되지 않았습니다. ⚙️ 설정 → 환경 설정에서 입력하세요.")
    log = d.table_rows("notify_log")[-20:]
    if log:
        st.dataframe(pd.DataFrame(log[::-1]), hide_index=True, width="stretch")


# 역할 상수(다른 모듈에서 메뉴 구성에 사용)
VIEW_ROLES = (ADMIN, EXEC, FIN)
_ = (STAFF,)
