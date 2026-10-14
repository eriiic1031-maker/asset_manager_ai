"""
현장 담당자 페이지 + QR 스캔 화면

법인차량 관리 AI의 사용자 페이지처럼 이름을 입력해 사용합니다.
현장 담당자는 자기 현장 자산을 보유·관리하고, 다른 현장 자산이 필요하면 이동을 신청합니다.
"""
from __future__ import annotations

import html
from datetime import date

import pandas as pd
import streamlit as st

import ai
import data as d
import ui
import workflow as wf


def render(site: str, name: str):
    actor = f"{name}({site})" if name else ""
    st.title(f"👤 {site} 자산관리")
    st.caption("우리 현장 자산을 관리하고, 필요한 자산은 구매요청이나 다른 현장 유휴 자산 이동으로 신청합니다.")
    if not name:
        st.info("왼쪽에서 담당 현장을 고르고 이름을 입력하세요. 이름이 있어야 신청·승인·검수를 할 수 있습니다.")

    mine = d.get_assets(site, include_closed=False)
    pending = wf.pending_for(wf.SITE, site) if name else {k: [] for k in d.REQUEST_TABLES}
    todo = [(k, r) for k in d.REQUEST_TABLES for r in pending[k]]

    k = st.columns(5)
    with k[0]: ui.kpi("보유 자산", len(mine), site, unit="개")
    with k[1]: ui.kpi("장부가액", ui.short_won(sum(d.book_value(a) for a in mine)), "오늘 기준", unit="원")
    with k[2]: ui.kpi("유휴", sum(1 for a in mine if a["상태"] == "유휴"), "다른 현장에 재배치 가능", "warn" if any(a["상태"] == "유휴" for a in mine) else "", "개")
    with k[3]: ui.kpi("내용연수 만료", sum(1 for a in mine if (d.life_remaining_months(a) or 1) <= 0), "처분 검토", unit="개")
    with k[4]: ui.kpi("내 처리 대기", len(todo), "이동 승인·인수·검수·집행", "warn" if todo else "", "건")

    if todo:
        st.markdown("### 🔔 처리할 일")
        for kind, rec in todo:
            wf.render_request_card(kind, rec, wf.SITE, site, actor, key="todo")

    audit = d.open_audit()
    tab_names = ["🤖 AI 요청", "📦 우리 현장 자산", "🔄 다른 현장 유휴 자산", "📝 신청서 작성", "📋 신청 현황", "🗑 처분 이력"]
    if audit and (audit["대상"] in ("전체", site)):
        tab_names.append("🔍 재물조사")
    tabs = st.tabs(tab_names)
    with tabs[0]:
        ai_tab(site, actor)
    with tabs[1]:
        my_assets_tab(site, actor, mine)
    with tabs[2]:
        idle_tab(site, actor)
    with tabs[3]:
        forms_tab(site, actor, mine)
    with tabs[4]:
        status_tab(site, actor)
    with tabs[5]:
        st.caption(f"{site}에서 폐기·매각·기증·경매·망실로 장부에서 빠진 자산입니다.")
        wf.render_disposed_list(f"site-disposed-{site}", actor, wf.SITE, site)
    if len(tabs) > 6:
        with tabs[6]:
            if not name:
                st.info("이름을 입력하면 재물조사 결과를 입력할 수 있습니다.")
            else:
                wf.render_audit_workspace(audit, wf.SITE, site, actor, key=f"site-audit-{site}")


# ---------------------------------------------------------
# AI 요청
# ---------------------------------------------------------
def ai_tab(site: str, actor: str):
    st.markdown("### 🤖 AI 자연어 자산 요청")
    st.caption("Ollama가 요청을 분석하고 Python이 다시 확인합니다. 새로 사기 전에 다른 현장의 유휴 자산부터 찾아 드립니다.")
    if not actor:
        st.warning("먼저 왼쪽에서 이름을 입력하세요.")
        return
    example = "다음주까지 신규 입사자 2명이 쓸 노트북 2대가 필요해. 한 대에 180만원 정도로 생각하고 있어"
    text = st.text_area("요청을 자연어로 입력하세요", height=100, placeholder=example, key="ai_text")
    c1, c2 = st.columns([3, 1])
    use_ollama = c2.toggle("Ollama 사용", value=True, key="ai_use_ollama", help="끄면 규칙 기반으로 바로 분석합니다")
    if c1.button("🤖 AI 분석하기", type="primary", width="stretch"):
        if not text.strip():
            st.warning("요청 내용을 입력하세요.")
        else:
            with st.spinner("요청을 분석하고 있습니다..."):
                result, source, note = ai.analyze(text, site, use_ollama)
            st.session_state["ai_result"] = {"result": result, "source": source, "note": note, "text": text}
            st.rerun()

    saved = st.session_state.get("ai_result")
    if not saved:
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

    others = [a for a in d.active_assets() if a["현장"] != site]
    mine = d.get_assets(site, include_closed=False)
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
            st.markdown("### ③ 이동 신청")
            wf.transfer_form("ai-transfer", hits, [site], actor, preselected=[a["태그번호"] for a in idle_hits[: r["qty"]]], default_to=site)
        else:
            st.caption(f"다른 현장에 재배치할 수 있는 유휴 '{r['item'] or '자산'}'이(가) 없습니다.")
        if intent == "purchase" or not hits:
            st.markdown(f"### {'④' if hits else '③'} 구매요청서 (AI가 미리 채움)")
            wf.purchase_form("ai-pr", [site], actor, defaults={
                "현장": site, "계정과목": r["account"], "품명": r["item"], "규격": r["spec"], "수량": r["qty"],
                "예상단가": r["unit_price"], "필요일": r["needed_by"], "구매사유": r["reason"]})
    elif intent == "incident":
        st.markdown("### ② 대상 자산 확인")
        hits = ai.match_assets(mine, r["item"], r["tags"]) or mine
        st.caption("우리 현장 자산 중 요청과 맞는 자산을 먼저 보여 줍니다. 다르면 목록에서 바꾸세요.")
        st.markdown("### ③ 분실·파손 경위서 (AI가 미리 채움)")
        wf.incident_form("ai-inc", hits, actor, preselected=hits[0]["태그번호"] if hits else None,
                         defaults={"구분": r["incident_type"], "경위": r["reason"], "발생일": date.today()})
    elif intent == "disposal":
        st.markdown("### ② 처분 대상 확인")
        pool = [a for a in mine if a["상태"] in ("사용중", "유휴", "수리중")]
        hits = ai.match_assets(pool, r["item"], r["tags"]) or pool
        st.markdown("### ③ 처분 신청")
        wf.disposal_form("ai-dsp", hits, actor, preselected=[a["태그번호"] for a in hits[:r["qty"]]] if ai.match_assets(pool, r["item"], r["tags"]) else [])
    if st.button("다시 입력", key="ai-reset"):
        st.session_state.pop("ai_result", None)
        st.rerun()


# ---------------------------------------------------------
# 우리 현장 자산
# ---------------------------------------------------------
def my_assets_tab(site: str, actor: str, mine: list[dict]):
    c1, c2 = st.columns([2, 1])
    query = c1.text_input("검색", placeholder="태그번호·품명·사용자", key="my-q").strip().lower()
    status = c2.selectbox("상태", ["전체"] + [s for s in d.ASSET_STATUSES if s not in d.CLOSED_STATUSES], key="my-status")
    rows = [a for a in mine if (status == "전체" or a["상태"] == status)
            and (not query or any(query in str(a[k]).lower() for k in ("태그번호", "품명", "규격", "사용자", "관리부서")))]
    if not rows:
        st.info("우리 현장에 해당하는 자산이 없습니다.")
        return
    page = ui.paginate(rows, f"my-page-{site}-{status}-{query}")
    df = ui.asset_frame(page)
    ev = st.dataframe(df, hide_index=True, width="stretch", column_config=ui.ASSET_COLUMN_CONFIG,
                      on_select="rerun", selection_mode="multi-row", key=f"my-table-{site}")
    sel = [df.iloc[i]["태그번호"] for i in ev.selection.rows if i < len(df)]
    c1, c2 = st.columns(2)
    if c1.button("🔍 상세 · 작업", disabled=len(sel) != 1, width="stretch", key="my-detail"):
        wf.asset_dialog(sel[0], wf.SITE, site, actor)
    with c2:
        targets = [a for a in page if a["태그번호"] in sel] or rows
        if st.button(f"🏷️ QR 라벨 ({len(targets):,}개)", width="stretch", key="my-label"):
            st.session_state["my_label_tags"] = [a["태그번호"] for a in targets]
        if st.session_state.get("my_label_tags"):
            ui.label_download([a for a in (d.get_asset(t) for t in st.session_state["my_label_tags"]) if a], key="my-label-dl", label="⬇️ 라벨 PDF 받기")
    export_cols = ui.ASSET_VIEW_COLS + ["시리얼번호", "공급업체", "비고"]
    ui.export_panel(f"my-export-{site}", f"{site}_자산_{date.today():%Y%m%d}",
                    lambda: {site: (export_cols, [{**a, "장부가액": round(d.book_value(a))} for a in rows])}, len(rows))


def idle_tab(site: str, actor: str):
    st.caption("다른 현장에서 쓰지 않는 자산입니다. 필요하면 이동을 신청하세요. 보내는 현장이 승인하면 받아서 인수확인합니다.")
    idle = [a for a in d.active_assets() if a["상태"] == "유휴" and a["현장"] != site]
    if not idle:
        st.success("지금은 다른 현장의 유휴 자산이 없습니다.")
        return
    c1, c2 = st.columns(2)
    acc = c1.selectbox("계정과목", ["전체"] + d.ACCOUNT_NAMES, key="idle-acc")
    q = c2.text_input("검색", placeholder="품명·규격", key="idle-q").strip().lower()
    idle = [a for a in idle if (acc == "전체" or a["계정과목"] == acc) and (not q or q in a["품명"].lower() or q in a["규격"].lower())]
    if not idle:
        st.info("조건에 맞는 유휴 자산이 없습니다.")
        return
    page = ui.paginate(idle, f"idle-page-{acc}-{q}", page_size=500)
    df = ui.asset_frame(page)
    ev = st.dataframe(df, hide_index=True, width="stretch", column_config=ui.ASSET_COLUMN_CONFIG,
                      on_select="rerun", selection_mode="multi-row", key=f"idle-others-{acc}-{q}")
    sel = [df.iloc[i]["태그번호"] for i in ev.selection.rows if i < len(df)]
    if st.button(f"🔄 선택한 {len(sel)}개 우리 현장으로 이동 신청", type="primary", disabled=not sel or not actor):
        wf.dlg_new_transfer(sel, actor, default_to=site)


def forms_tab(site: str, actor: str, mine: list[dict]):
    if not actor:
        st.warning("이름을 입력하면 신청서를 작성할 수 있습니다.")
        return
    kind = st.radio("신청서", ["🛒 구매요청", "🔄 이동신청 (다른 현장 자산 받기)", "📤 이동신청 (우리 자산 보내기)",
                             "⚠️ 분실·파손 신고", "🗑 처분 신청"], horizontal=True, key="form-kind")
    if kind.startswith("🛒"):
        wf.purchase_form("site-pr", [site], actor, defaults={"현장": site})
    elif kind.startswith("🔄"):
        others = [a for a in d.active_assets() if a["현장"] != site and a["상태"] != "처분대기"]
        wf.transfer_form("site-mv-in", others, [site], actor, default_to=site)
    elif kind.startswith("📤"):
        wf.transfer_form("site-mv-out", [a for a in mine if a["상태"] != "처분대기"], [s for s in d.site_names() if s != site], actor)
    elif kind.startswith("⚠️"):
        wf.incident_form("site-inc", mine, actor)
    else:
        candidates = [a for a in mine if a["상태"] in ("사용중", "유휴", "수리중")]
        hints = d.disposal_candidates(site)
        only = st.toggle(f"처분 검토 대상만 보기 (내용연수 만료 등 {len(hints):,}개)", value=bool(hints), key="dsp-only-hints")
        wf.disposal_form("site-dsp", hints if only and hints else candidates, actor)


def status_tab(site: str, actor: str):
    st.caption("우리 현장과 관련된 모든 요청입니다. 처리할 차례가 되면 위 '처리할 일'에 나타납니다.")
    icons = {"pr": "🛒", "move": "🔄", "inc": "⚠️", "dsp": "🗑"}
    tabs = st.tabs([f"{icons[k]} {d.KIND_NAMES[k]}" for k in d.REQUEST_TABLES])
    for tab, kind in zip(tabs, d.REQUEST_TABLES):
        with tab:
            wf.render_request_list(kind, wf.SITE, site, actor, key=f"status-{kind}", scope_site=site)


# ---------------------------------------------------------
# QR 스캔 화면 (?tag=태그번호)
# ---------------------------------------------------------
def qr_page(tag: str):
    a = d.get_asset(tag)
    st.title("🏷️ 자산 확인")
    if st.button("← 전체 화면으로"):
        st.query_params.clear()
        st.rerun()
    if not a:
        st.error(f"'{tag}' 태그의 자산을 찾을 수 없습니다. 라벨의 태그번호를 확인하세요.")
        return
    c1, c2 = st.columns(2)
    sites = d.site_names()
    site = c1.selectbox("내 현장", sites, index=sites.index(a["현장"]) if a["현장"] in sites else 0, key="qr_site")
    name = c2.text_input("이름", key="qr_name", placeholder="확인·신고하려면 입력")
    actor = f"{name}({site})" if name else ""

    audit = d.open_audit()
    if audit and actor:
        item = next((r for r in d.get_audit_items(audit["회차번호"]) if r["태그번호"] == a["태그번호"]), None)
        if item:
            with st.container(border=True):
                st.markdown(f"**🔍 {audit['회차명']}** · 현재 결과: {ui.badge(item['결과'])}", unsafe_allow_html=True)
                if item["결과"] != "확인":
                    if a["현장"] != site:
                        st.caption(f"{a['현장']} 담당자가 확인할 자산입니다.")
                    elif st.button("✅ 실물 확인 처리", type="primary", width="stretch"):
                        if ui.run_action(d.audit_mark, audit["회차번호"], {a["태그번호"]: {"결과": "확인"}}, actor,
                                         success=f"{a['태그번호']} 실물 확인을 기록했습니다."):
                            st.rerun()
    role = wf.SITE
    wf.render_asset_detail(a["태그번호"], role, site, actor, key="qr")
