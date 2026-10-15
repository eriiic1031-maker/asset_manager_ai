"""
현장 · 직원 화면 + QR 스캔 화면

- 현장 홈 (현장책임자·현장담당): 우리 현장 KPI, 처리할 일, 알림, 신청 현황
- 내 자산 (모든 사용자): 내가 쓰는 자산·라이선스, 내 대여, 내가 낸 신청
- AI 요청·신청서: 자연어 요청 → 유휴 자산 재배치 / 구매요청 / 경위서 / 처분 신청
- QR 화면 (?tag=태그번호): 사용자를 고르기 전에는 기본 정보만, 고르면 상세·조사 확인·신고
"""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st

import ai
import auth
import data as d
import ops
import ui
import workflow as wf
from auth import ADMIN, SITE_ROLES, STAFF


# ---------------------------------------------------------
# 현장 홈
# ---------------------------------------------------------
def site_home(u: dict):
    site = u["현장"]
    st.title(f"👷 {site} 자산관리")
    st.caption(f"{u['이름']}님({u['역할']}) · 우리 현장 자산을 관리하고, 필요한 자산은 다른 현장 유휴 자산 이동이나 구매요청으로 신청합니다.")
    mine = d.get_assets(site, include_closed=False)
    pending = wf.pending_for(u)
    rentals = wf.pending_rentals(u)
    todo = [(k, r) for k in d.REQUEST_TABLES for r in pending[k]]
    import pages_ops
    alerts = pages_ops.all_alerts(u)

    k = st.columns(6)
    with k[0]: ui.kpi("보유 자산", f"{len(mine):,}", site, unit="개")
    with k[1]: ui.kpi("장부가액", ui.short_won(sum(d.book_value(a) for a in mine)), "오늘 기준", unit="원")
    idle = sum(1 for a in mine if a["상태"] == "유휴")
    with k[2]: ui.kpi("유휴", idle, "다른 현장에 재배치 가능", "warn" if idle else "", "개")
    with k[3]: ui.kpi("내용연수 만료", sum(1 for a in mine if (d.life_remaining_months(a) or 1) <= 0), "처분 검토", unit="개")
    with k[4]: ui.kpi("내 처리 대기", len(todo) + len(rentals), "결재·인수·검수·경위서·대여", "warn" if todo or rentals else "", "건")
    with k[5]: ui.kpi("예산 잔액", ui.short_won(ops.budget_status(d.today().year, site)[0]["잔액"]), f"{d.today().year}년 · 결재 중 포함", unit="원")

    if todo or rentals:
        st.markdown("### 📌 처리할 일")
        for kind, rec in todo[:30]:
            wf.render_request_card(kind, rec, u, key="todo")
        if rentals:
            pages_ops.rental_cards(rentals, u, key="todo-rt")
    else:
        st.success("지금 처리할 결재·인수·검수가 없습니다.")

    tabs = st.tabs([f"🔔 알림 ({len(alerts)})", "📋 신청 현황", "🗑 처분 이력"])
    with tabs[0]:
        pages_ops.alert_center(alerts, u, key="site-alert")
    with tabs[1]:
        st.caption("우리 현장과 관련된 모든 요청입니다. 처리할 차례가 되면 위 '처리할 일'에 나타납니다.")
        icons = {"pr": "🛒", "move": "🔄", "inc": "⚠️", "dsp": "🗑"}
        sub = st.tabs([f"{icons[k]} {d.KIND_NAMES[k]}" for k in d.REQUEST_TABLES])
        for tab, kind in zip(sub, d.REQUEST_TABLES):
            with tab:
                wf.render_request_list(kind, u, key=f"status-{kind}", scope_site=site)
    with tabs[2]:
        st.caption(f"{site}에서 폐기·매각·기증·경매·망실로 장부에서 빠진 자산입니다.")
        wf.render_disposed_list(f"site-disposed-{site}", u, site)


# ---------------------------------------------------------
# 내 자산 (모든 사용자)
# ---------------------------------------------------------
def my_assets(u: dict) -> list[dict]:
    name, site = u.get("이름"), u.get("현장")
    emp_nos = {e["사번"] for e in ops.get_employees() if e["이름"] == name and (not site or e["현장"] == site)}
    return [a for a in d.active_assets() if (a["사용자사번"] and a["사용자사번"] in emp_nos)
            or (not a["사용자사번"] and a["사용자"] == name and (not site or a["현장"] == site))]


def my_requests(u: dict) -> list[tuple[str, dict]]:
    me = auth.actor(u)
    return [(k, r) for k in d.REQUEST_TABLES for r in d.get_requests(k)
            if me in (r.get("요청자"), r.get("신고자"), r.get("신청자"))]


def my_page(u: dict):
    st.title("🙋 내 자산")
    st.caption("내가 쓰는 회사 자산과 소프트웨어, 빌린 공용 장비, 내가 낸 신청을 한 곳에서 봅니다. "
               "잃어버리거나 고장 나면 자산을 골라 '상세 · 신고'에서 바로 신고하세요.")
    assets = my_assets(u)
    lic = [x for x in d.load("license_assign") if x["상태"] == "사용중" and x["사용자"] == u["이름"]
           and (not u.get("현장") or not x["현장"] or x["현장"] == u["현장"])]
    rentals = [r for r in d.load("rentals") if r["신청자"] == u["아이디"]]
    reqs = my_requests(u)
    k = st.columns(4)
    with k[0]: ui.kpi("내 자산", len(assets), "내가 사용자로 등록된 자산", unit="개")
    with k[1]: ui.kpi("소프트웨어", len(lic), "할당된 라이선스", unit="개")
    open_r = [r for r in rentals if r["상태"] in ops.RENTAL_OPEN]
    with k[2]: ui.kpi("대여 중·예약", len(open_r), "공용 장비", "warn" if any(r["상태"] == "대여중" for r in open_r) else "", "건")
    with k[3]: ui.kpi("진행 중인 신청", sum(1 for kd, r in reqs if d.is_open(kd, r)), f"전체 {len(reqs)}건", unit="건")

    tabs = st.tabs(["💻 내 자산", "🧰 내 대여", "📝 내 신청", "🛒 구매 요청하기"])
    with tabs[0]:
        if not assets:
            st.info("내 이름으로 등록된 자산이 없습니다. 받은 장비가 목록에 없으면 현장 담당자에게 알려 주세요.")
        else:
            df = ui.asset_frame(assets)
            ev = st.dataframe(df, hide_index=True, width="stretch", column_config=ui.ASSET_COLUMN_CONFIG,
                              on_select="rerun", selection_mode="single-row", key="my-assets-table")
            sel = [df.iloc[i]["태그번호"] for i in ev.selection.rows if i < len(df)]
            if st.button("🔍 상세 · 신고", disabled=not sel, key="my-asset-detail"):
                wf.asset_dialog(sel[0], u)
        if lic:
            st.markdown("**💿 내 소프트웨어**")
            st.dataframe(pd.DataFrame([{"소프트웨어": (d.lookup("licenses", x["라이선스번호"]) or {}).get("소프트웨어명", ""),
                                        "설치 PC": x["PC태그"], "할당일": x["할당일"]} for x in lic]), hide_index=True, width="stretch")
    with tabs[1]:
        import pages_ops
        if not rentals:
            st.info("빌린 장비가 없습니다. '🧰 장비 대여' 메뉴에서 공용 장비를 빌릴 수 있습니다.")
        else:
            pages_ops.rental_cards(sorted(rentals, key=lambda r: r["신청일시"], reverse=True)[:30], u, key="my-rt")
    with tabs[2]:
        if not reqs:
            st.info("낸 신청이 없습니다.")
        for kind, rec in sorted(reqs, key=lambda kr: kr[1]["요청일시"], reverse=True)[:40]:
            wf.render_request_card(kind, rec, u, key="my-req")
    with tabs[3]:
        if not u.get("현장"):
            st.info("소속 현장이 없는 계정은 결재함의 '구매요청 작성'을 이용하세요.")
        else:
            wf.purchase_form("my-pr", [u["현장"]], u, defaults={"현장": u["현장"]})


# ---------------------------------------------------------
# AI 요청 · 신청서
# ---------------------------------------------------------
def request_page(u: dict):
    st.title("🤖 AI 요청 · 신청서")
    if u.get("역할") == ADMIN or not u.get("현장"):
        sites = d.site_names()
        site = st.selectbox("요청 현장", sites, key="req-site") if sites else None
    else:
        site = u["현장"]
    if not site:
        st.warning("등록된 현장이 없습니다.")
        return
    tabs = st.tabs(["🤖 AI 자연어 요청", "📝 신청서 직접 작성"])
    with tabs[0]:
        ai_tab(site, u)
    with tabs[1]:
        forms_tab(site, u)


def ai_tab(site: str, u: dict):
    st.caption("Ollama가 요청을 분석하고 Python이 다시 확인합니다. 새로 사기 전에 다른 현장의 유휴 자산부터 찾아 드립니다.")
    example = "다음주까지 신규 입사자 2명이 쓸 노트북 2대가 필요해. 한 대에 180만원 정도로 생각하고 있어"
    text = st.text_area("요청을 자연어로 입력하세요", height=100, placeholder=example, key="ai_text")
    c1, c2 = st.columns([3, 1])
    use_ollama = c2.toggle("Ollama 사용", value=not d.ON_CLOUD, key="ai_use_ollama", help="끄면 규칙 기반으로 바로 분석합니다")
    if c1.button("🤖 AI 분석하기", type="primary", width="stretch"):
        if not text.strip():
            st.warning("요청 내용을 입력하세요.")
        else:
            with st.spinner("요청을 분석하고 있습니다..."):
                result, source, note = ai.analyze(text, site, use_ollama)
            st.session_state["ai_result"] = {"result": result, "source": source, "note": note, "text": text, "site": site}
            st.rerun()

    saved = st.session_state.get("ai_result")
    if not saved or saved.get("site") != site:
        st.caption("예: '평택 현장 지게차가 부족해서 다른 현장 남는 거 있으면 가져오고 싶어', 'FUR-2024-0003 노트북을 잃어버렸어', '고장난 프로젝터 폐기하고 싶어'")
        return
    r, source = saved["result"], saved["source"]
    if saved["note"]:
        st.info(saved["note"])
    st.divider()
    st.markdown(f"### ① AI가 해석한 요청 <span class='small-muted'>· {html.escape(source)} 분석</span>", unsafe_allow_html=True)
    m = st.columns(6)
    m[0].metric("요청 종류", ai.INTENTS[r["intent"]])
    m[1].metric("품명", r["item"] or "미확인")
    m[2].metric("수량", f"{r['qty']}개")
    m[3].metric("예상 단가", ui.short_won(r["unit_price"]) + "원" if r["unit_price"] else "-")
    m[4].metric("필요 시점", ui.fmt_date(r["needed_by"]))
    m[5].metric("계정과목", r["account"])

    staff = u.get("역할") == STAFF
    others = [a for a in d.active_assets() if a["현장"] != site]
    mine = my_assets(u) if staff else d.get_assets(site, include_closed=False)
    intent = r["intent"]

    if intent in ("purchase", "transfer", "search"):
        idle_hits = [a for a in ai.match_assets(others, r["item"], r["tags"]) if a["상태"] == "유휴"]
        all_hits = ai.match_assets(others, r["item"], r["tags"])
        st.markdown("### ② 재배치 가능한 자산 (구매 전 확인)")
        hits = idle_hits or (all_hits if intent != "purchase" else [])
        if hits:
            saving = sum(r["unit_price"] or d.book_value(a) for a in hits[: r["qty"]])
            st.success(f"다른 현장에 {'유휴 ' if idle_hits else ''}'{r['item']}' {len(hits)}개가 있습니다." +
                       (f" 재배치하면 약 {ui.won(saving)}의 구매 비용을 줄일 수 있습니다." if idle_hits and r["unit_price"] else ""))
            st.dataframe(ui.asset_frame(hits), hide_index=True, width="stretch", column_config=ui.ASSET_COLUMN_CONFIG)
            if staff:
                st.caption("이동 신청은 현장 담당자가 합니다. 담당자에게 위 자산을 알려 주세요.")
            else:
                st.markdown("### ③ 이동 신청")
                wf.transfer_form("ai-transfer", hits, [site], u, preselected=[a["태그번호"] for a in idle_hits[: r["qty"]]], default_to=site)
        else:
            st.caption(f"다른 현장에 재배치할 수 있는 유휴 '{r['item'] or '자산'}'이(가) 없습니다.")
        if intent == "purchase" or not hits:
            st.markdown(f"### {'④' if hits and not staff else '③'} 구매요청서 (AI가 미리 채움)")
            wf.purchase_form("ai-pr", [site], u, defaults={
                "현장": site, "계정과목": r["account"], "품명": r["item"], "규격": r["spec"], "수량": r["qty"],
                "예상단가": r["unit_price"], "필요일": r["needed_by"], "구매사유": r["reason"]})
    elif intent == "incident":
        st.markdown("### ② 대상 자산 확인")
        hits = ai.match_assets(mine, r["item"], r["tags"]) or mine
        st.caption(("내 자산" if staff else "우리 현장 자산") + " 중 요청과 맞는 자산을 먼저 보여 줍니다. 다르면 목록에서 바꾸세요.")
        st.markdown("### ③ 분실·파손 경위서 (AI가 미리 채움)")
        wf.incident_form("ai-inc", hits, u, preselected=hits[0]["태그번호"] if hits else None,
                         defaults={"구분": r["incident_type"], "경위": r["reason"], "발생일": d.today()})
    elif intent == "disposal":
        if staff:
            st.info("처분 신청은 현장 담당자가 합니다. 고장이라면 '분실·파손 신고'로 알려 주세요.")
        else:
            st.markdown("### ② 처분 대상 확인")
            pool = [a for a in mine if a["상태"] in ("사용중", "유휴", "수리중")]
            matched = ai.match_assets(pool, r["item"], r["tags"])
            st.markdown("### ③ 처분 신청")
            wf.disposal_form("ai-dsp", matched or pool, u, preselected=[a["태그번호"] for a in matched[:r["qty"]]])
    if st.button("다시 입력", key="ai-reset"):
        st.session_state.pop("ai_result", None)
        st.rerun()


def forms_tab(site: str, u: dict):
    staff = u.get("역할") == STAFF
    if staff:
        options = ["🛒 구매요청", "⚠️ 분실·파손 신고 (내 자산)"]
    else:
        options = ["🛒 구매요청", "🔄 이동신청 (다른 현장 자산 받기)", "📤 이동신청 (우리 자산 보내기)", "⚠️ 분실·파손 신고", "🗑 처분 신청"]
    kind = st.radio("신청서", options, horizontal=True, key="form-kind")
    mine = my_assets(u) if staff else d.get_assets(site, include_closed=False)
    if kind.startswith("🛒"):
        wf.purchase_form("site-pr", [site], u, defaults={"현장": site})
    elif kind.startswith("🔄"):
        others = [a for a in d.active_assets() if a["현장"] != site and a["상태"] != "처분대기"]
        wf.transfer_form("site-mv-in", others, [site], u, default_to=site)
    elif kind.startswith("📤"):
        wf.transfer_form("site-mv-out", [a for a in mine if a["상태"] != "처분대기"], [s for s in d.site_names() if s != site], u)
    elif kind.startswith("⚠️"):
        wf.incident_form("site-inc", mine, u)
    else:
        candidates = [a for a in mine if a["상태"] in ("사용중", "유휴", "수리중")]
        hints = d.disposal_candidates(site)
        only = st.toggle(f"처분 검토 대상만 보기 (내용연수 만료·수리비 과다 등 {len(hints):,}개)", value=bool(hints), key="dsp-only-hints")
        wf.disposal_form("site-dsp", hints if only and hints else candidates, u)


# ---------------------------------------------------------
# QR 스캔 화면 (?tag=태그번호)
# ---------------------------------------------------------
def qr_page(tag: str, u: dict | None):
    a = d.get_asset(tag)
    st.title("🏷️ 자산 확인")
    if st.button("← 전체 화면으로"):
        st.query_params.clear()
        st.rerun()
    if not a:
        st.error(f"'{tag}' 태그의 자산을 찾을 수 없습니다. 라벨의 태그번호를 확인하세요.")
        return
    if not u:
        # 사용자 선택 전: 습득·반납 안내에 필요한 정보만 보여 줍니다(사용자 이름·금액은 숨김).
        site = next((s for s in d.get_sites() if s["현장명"] == a["현장"]), {})
        company = d.clean_str(d.get_settings().get("회사명"))
        st.markdown(f"<div class='asset-head'><span class='tag'>{html.escape(a['태그번호'])}</span>"
                    f"<span class='name'>{html.escape(a['품명'])}</span>{ui.badge(a['상태'])}</div>", unsafe_allow_html=True)
        st.write(f"{company + ' ' if company else ''}{a['현장']} 소속 자산입니다.")
        if site.get("담당자 연락처"):
            st.info(f"이 물건을 습득하셨다면 {a['현장']} 자산 담당자({site.get('담당자', '')}, {site['담당자 연락처']})에게 연락 부탁드립니다.")
        st.caption("직원은 아래에서 본인을 고르면 상세 정보 확인, 재물조사 확인, 분실·파손 신고를 할 수 있습니다.")
        auth.choose_screen(compact=True)
        return

    audit = d.open_audit()
    if audit:
        item = next((r for r in d.get_audit_items(audit["회차번호"]) if r["태그번호"] == a["태그번호"]), None)
        if item:
            with st.container(border=True):
                st.markdown(f"**🔍 {html.escape(audit['회차명'])}** · 현재 결과: {ui.badge(item['결과'])}", unsafe_allow_html=True)
                if item["결과"] != "확인":
                    if not wf.manages(u, a["현장"]):
                        st.caption(f"{a['현장']} 담당자가 확인할 자산입니다.")
                    elif st.button("✅ 실물 확인 처리", type="primary", width="stretch"):
                        if ui.run_action(d.audit_mark, audit["회차번호"], {a["태그번호"]: {"결과": "확인"}}, auth.actor(u),
                                         success=f"{a['태그번호']} 실물 확인을 기록했습니다."):
                            st.rerun()
    wf.render_asset_detail(a["태그번호"], u, key="qr")


# 다른 모듈에서 쓰는 역할 상수
__all__ = ["site_home", "my_page", "request_page", "qr_page", "SITE_ROLES"]
