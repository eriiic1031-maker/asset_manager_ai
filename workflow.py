"""
결재 흐름 화면 요소 (관리자·현장 담당자 공용)

- 요청 카드: 법인차량 관리 AI의 '예약 승인 / 반려' 카드와 같은 배치
- 처리 대화상자: 승인·반려, 견적, 업체 선정, 입고 검수, 자산 등록, 인수 확인, 사고 조사, 처분 집행·제적
- 신청서: 구매요청, 이동신청, 분실·파손 경위서, 처분 신청
- 자산 상세 대화상자: 기본정보, 감가상각, QR 태그, 변동 이력, 작업
"""
from __future__ import annotations

import html
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import data as d
import ui

ADMIN = "admin"
SITE = "site"


# =========================================================
# 권한: 누가 어떤 단계를 처리하는가
# =========================================================
def actions_for(kind: str, rec: dict, role: str, site: str | None) -> list[str]:
    admin = role == ADMIN
    s = rec["상태"]
    if kind == "pr":
        if s == "요청" and admin:
            return ["approve", "reject"]
        if s == "승인" and admin:
            return ["quotes", "choose"]
        if s == "발주" and (admin or rec["현장"] == site):
            return ["inspect"]
        if s == "검수완료" and admin:
            return ["register"]
    elif kind == "move":
        if s == "요청" and (admin or rec["보내는 현장"] == site):
            return ["approve", "reject"]
        if s == "승인" and (admin or rec["받는 현장"] == site):
            return ["receive"]
    elif kind == "inc":
        if s == "접수" and admin:
            return ["investigate"]
        if s == "조사완료" and admin:
            return ["close"]
    elif kind == "dsp":
        if s == "신청" and admin:
            return ["approve", "reject"]
        if s == "승인" and (admin or rec["현장"] == site):
            return ["execute"]
        if s == "집행완료" and admin:
            return ["derecognize"]
    return []


def related_to_site(kind: str, rec: dict, site: str) -> bool:
    if kind == "move":
        return site in (rec["보내는 현장"], rec["받는 현장"])
    return rec.get("현장") == site


def pending_for(role: str, site: str | None = None) -> dict[str, list[dict]]:
    return {k: [r for r in d.get_requests(k) if actions_for(k, r, role, site)] for k in d.REQUEST_TABLES}


def request_title(kind: str, rec: dict) -> str:
    if kind == "pr":
        return f"{rec['품명']} × {d.to_num(rec['수량'], 0)}"
    if kind == "inc":
        return f"{rec['구분']} · {rec['품명']}"
    tags = [t for t in rec.get("태그번호", "").split(",") if t.strip()]
    return f"{rec['품명']}" + (f" ({len(tags)}개)" if len(tags) > 1 else "")


def request_where(kind: str, rec: dict) -> str:
    if kind == "move":
        return f"{rec['보내는 현장']} → {rec['받는 현장']}"
    return rec.get("현장", "")


def request_who(kind: str, rec: dict) -> str:
    return rec.get("요청자") or rec.get("신고자") or rec.get("신청자") or "-"


def request_detail_line(kind: str, rec: dict) -> str:
    if kind == "pr":
        line = f"예산 {ui.won((d.to_num(rec['예상단가'], 0) or 0) * (d.to_num(rec['수량'], 0) or 0))}"
        if rec["선정업체"]:
            line += f" · 선정 {rec['선정업체']} {ui.won((d.to_num(rec['선정단가'], 0) or 0) * (d.to_num(rec['수량'], 0) or 0))}"
        elif d.pr_quotes(rec):
            line += f" · 견적 {len(d.pr_quotes(rec))}건"
        return line + f" · 사유: {rec['구매사유'][:40]}"
    if kind == "move":
        who = " · ".join(x for x in (rec["받는 부서"], rec["새 사용자"]) if x)
        return f"태그 {rec['태그번호']}" + (f" · 받는 쪽 {who}" if who else "") + f" · 사유: {rec['사유'][:40]}"
    if kind == "inc":
        return f"{rec['태그번호']} · 발생 {ui.fmt_date(rec['발생일'])} {rec['발생장소']} · {rec['경위'][:40]}"
    return f"{rec['태그번호']} · {rec['불용사유']} · 희망 {rec['희망 처분방법']} · 장부가 {ui.won(rec['장부가 합계'])}"


# =========================================================
# 요청 카드
# =========================================================
ACTION_LABELS = {
    "approve": "✅ 승인", "reject": "❌ 반려", "quotes": "💰 견적 입력", "choose": "🏁 업체 선정·발주",
    "inspect": "📦 입고 검수", "register": "🏷️ 자산 등록", "receive": "📥 인수 확인",
    "investigate": "🔎 조사 결과", "close": "🏁 처리·종결", "execute": "🚚 집행 기록", "derecognize": "📕 장부 제적",
}


def render_request_card(kind: str, rec: dict, role: str, site: str | None, actor: str, key: str):
    acts = actions_for(kind, rec, role, site)
    with st.container(border=True):
        a, b, c, e = st.columns([1.1, 2.0, 3.4, 1.7])
        with a:
            st.markdown(f"**{rec['요청번호']}**")
            st.markdown(ui.badge(rec["상태"]), unsafe_allow_html=True)
        with b:
            st.markdown(f"**{request_title(kind, rec)}**")
            st.caption(f"{d.KIND_NAMES[kind]} · {request_where(kind, rec)}")
        with c:
            st.markdown(f"<span class='small-muted'>{html.escape(request_detail_line(kind, rec))}</span>", unsafe_allow_html=True)
            st.markdown(ui.steps_html(kind, rec["상태"]) +
                        f"<div class='small-muted'>{html.escape(request_who(kind, rec))} · {rec['요청일시']}</div>",
                        unsafe_allow_html=True)
        with e:
            if not acts:
                st.caption("처리할 단계가 없습니다" if not d.is_open(kind, rec) else "다른 담당자 처리 차례")
            for act in acts:
                if st.button(ACTION_LABELS[act], key=f"{key}-{rec['요청번호']}-{act}", width="stretch",
                             type="primary" if act not in ("reject",) else "secondary"):
                    open_action(kind, act, rec["요청번호"], actor)
        with st.expander("📄 상세 · 처리이력"):
            show_request_detail(kind, rec)


def show_request_detail(kind: str, rec: dict):
    skip = {"처리이력"}
    rows = [[k, ui.fmt_date(v) if isinstance(v, date) else (f"{v:,}" if isinstance(v, (int, float)) and not isinstance(v, bool) else v)]
            for k, v in rec.items() if k not in skip and v not in ("", None)]
    st.dataframe(pd.DataFrame(rows, columns=["항목", "내용"]), hide_index=True, width="stretch")
    if kind != "pr":
        items = d.request_assets(rec)
        if items:
            st.markdown("**대상 자산**")
            st.dataframe(ui.asset_frame(items), hide_index=True, width="stretch", column_config=ui.ASSET_COLUMN_CONFIG)
    if rec.get("처리이력"):
        st.markdown("**처리이력**")
        st.code(rec["처리이력"], language=None)


def render_request_list(kind: str, role: str, site: str | None, actor: str, key: str, scope_site: str | None = None):
    rows = d.get_requests(kind)
    if scope_site:
        rows = [r for r in rows if related_to_site(kind, r, scope_site)]
    mine = [r for r in rows if actions_for(kind, r, role, site)]
    open_rows = [r for r in rows if d.is_open(kind, r)]
    view = st.radio("목록", [f"처리 대기 ({len(mine)})", f"진행 중 ({len(open_rows)})", f"전체 ({len(rows)})"],
                    horizontal=True, key=f"{key}-filter", label_visibility="collapsed")
    show = mine if view.startswith("처리") else open_rows if view.startswith("진행") else rows
    if not show:
        st.success(f"{'처리할' if view.startswith('처리') else '표시할'} {d.KIND_NAMES[kind]} 건이 없습니다.")
        return
    for rec in show[:60]:
        render_request_card(kind, rec, role, site, actor, key)
    if len(show) > 60:
        st.caption(f"최근 60건만 표시했습니다. 전체는 data/자산요청.xlsx에서 볼 수 있습니다.")


def open_action(kind: str, act: str, no: str, actor: str):
    if act in ("approve", "reject"):
        dlg_decide(kind, no, act == "approve", actor)
    else:
        {"quotes": dlg_pr_quotes, "choose": dlg_pr_choose, "inspect": dlg_pr_inspect, "register": dlg_pr_register,
         "receive": dlg_move_receive, "investigate": dlg_inc_investigate, "close": dlg_inc_close,
         "execute": dlg_dsp_execute, "derecognize": dlg_dsp_derecognize}[act](no, actor)


# =========================================================
# 처리 대화상자
# =========================================================
def _done(message: str):
    ui.flash(message)
    st.rerun()


@st.dialog("결재 처리", width="large")
def dlg_decide(kind: str, no: str, approve: bool, actor: str):
    rec = d.get_request(kind, no)
    word = {"pr": "타당성 승인", "move": "보내기 승인", "dsp": "불용품 판정 승인"}.get(kind, "승인") if approve else "반려"
    st.markdown(f"### {'✅' if approve else '❌'} {rec['요청번호']} {word}")
    st.markdown(f"**{request_title(kind, rec)}** · {request_where(kind, rec)}")
    st.caption(request_detail_line(kind, rec))
    if kind == "pr" and approve:
        word2 = rec["품명"].split()[0] if rec["품명"].split() else rec["품명"]
        idle = [a for a in d.active_assets() if a["상태"] == "유휴" and word2 and word2 in a["품명"]]
        if idle:
            st.warning(f"'{word2}' 유휴 자산이 {len(idle):,}개 있습니다. 재배치로 대체할 수 있는지 먼저 검토하세요.")
            st.dataframe(ui.asset_frame(idle[:200]), hide_index=True, width="stretch", column_config=ui.ASSET_COLUMN_CONFIG)
    label = "위원회 의결 내용" if kind == "dsp" and approve else "검토 의견" if approve else "반려 사유"
    note = st.text_area(label, key=f"decide-note-{no}")
    if st.button(word, type="primary", width="stretch", key=f"decide-go-{no}"):
        fn = {"pr": d.pr_decide, "move": d.transfer_decide, "dsp": d.disposal_decide}[kind]
        if ui.run_action(fn, no, approve, note, actor, success=f"{no} {word} 처리했습니다."):
            st.rerun()


@st.dialog("💰 비교 견적 입력", width="large")
def dlg_pr_quotes(no: str, actor: str):
    rec = d.get_request("pr", no)
    st.markdown(f"**{rec['품명']}** {rec['규격']} × {d.to_num(rec['수량'])} · 예상단가 {ui.won(rec['예상단가'])}")
    st.caption("견적은 최대 3건까지 입력합니다. 2건 이상이어야 업체를 선정할 수 있습니다.")
    quotes = {q["slot"]: q for q in d.pr_quotes(rec)}
    with st.form(f"quotes-{no}"):
        entries = []
        for i in (1, 2, 3):
            q = quotes.get(i, {})
            c1, c2, c3 = st.columns([2, 1.4, 2.6])
            vendor = c1.text_input(f"견적{i} 업체", value=q.get("업체", ""))
            unit = c2.number_input(f"견적{i} 단가(원)", min_value=0, step=10000, value=int(q.get("단가", 0) or 0))
            cond = c3.text_input(f"견적{i} 조건", value=q.get("조건", ""), placeholder="납기, 보증, 설치 포함 등")
            entries.append({"업체": vendor, "단가": unit, "조건": cond})
        if st.form_submit_button("💾 견적 저장", type="primary", width="stretch"):
            if ui.run_action(d.pr_save_quotes, no, entries, actor, success=f"{no} 견적을 저장했습니다."):
                st.rerun()


@st.dialog("🏁 공급업체 선정·발주", width="large")
def dlg_pr_choose(no: str, actor: str):
    rec = d.get_request("pr", no)
    quotes = d.pr_quotes(rec)
    if len(quotes) < 2:
        st.warning("비교견적이 2건 이상 필요합니다. 먼저 '견적 입력'에서 견적을 추가하세요.")
        return
    qty = d.to_num(rec["수량"], 1) or 1
    budget = d.to_num(rec["예상단가"], 0) or 0
    low = min(quotes, key=lambda q: q["단가"])
    table = pd.DataFrame([{"업체": q["업체"], "단가": q["단가"], "합계": q["단가"] * qty,
                           "예산 대비": f"{(q['단가'] / budget - 1) * 100:+.1f}%" if budget else "-",
                           "조건": q["조건"], "비고": "최저가" if q is low else ""} for q in quotes])
    st.dataframe(table, hide_index=True, width="stretch", column_config=ui.money_config("단가", "합계"))
    options = [q["slot"] for q in quotes]
    labels = {q["slot"]: f"{q['업체']} · {ui.won(q['단가'])}" + (" (최저가)" if q is low else "") for q in quotes}
    slot = st.radio("선정 업체", options, index=options.index(low["slot"]), format_func=lambda s: labels[s], key=f"choose-{no}")
    reason = st.text_area("선정 사유", value="최저가 기준 선정" if slot == low["slot"] else "", key=f"choose-reason-{no}-{slot}")
    if st.button("선정하고 발주", type="primary", width="stretch", key=f"choose-go-{no}"):
        if ui.run_action(d.pr_choose_vendor, no, slot, reason, actor,
                         success=f"{no} 발주 단계로 넘겼습니다. 입고되면 {rec['현장']} 담당자가 검수합니다."):
            st.rerun()


@st.dialog("📦 입고 검수", width="large")
def dlg_pr_inspect(no: str, actor: str):
    rec = d.get_request("pr", no)
    qty = int(d.to_num(rec["수량"], 1) or 1)
    st.markdown(f"**{rec['품명']}** {rec['규격']} · 발주 수량 {qty} · {rec['선정업체']}")
    st.caption("규격·수량·파손 여부를 확인합니다. 하나라도 부적합이면 반품·재입고 후 다시 검수합니다.")
    with st.form(f"inspect-{no}"):
        spec_ok = st.checkbox("규격·사양이 발주 내용과 일치합니다")
        received = st.number_input("입고 수량", min_value=0, value=qty, step=1)
        no_damage = st.checkbox("외관 파손·작동 불량이 없습니다")
        serials = st.text_input("시리얼 번호 (쉼표로 구분, 수량 순서대로)")
        note = st.text_area("검수 메모")
        if st.form_submit_button("검수 결과 저장", type="primary", width="stretch"):
            passed = ui.run_action(d.pr_inspect, no, spec_ok, received, no_damage, serials, note, actor)
            if passed is not None:
                _done("검수 합격. 관리자가 자산대장에 등록합니다." if passed is True else
                      "검수 부적합으로 기록했습니다. 재입고 후 다시 검수하세요.")


@st.dialog("🏷️ 자산대장 등록", width="large")
def dlg_pr_register(no: str, actor: str):
    rec = d.get_request("pr", no)
    unit = d.to_num(rec["선정단가"], 0) or 0
    threshold = d.capitalization_threshold()
    account = "소모품" if unit < threshold else (rec["계정과목"] if rec["계정과목"] in d.ACCOUNTS else "비품")
    if unit < threshold:
        st.info(f"단가 {ui.won(unit)} · 자본화 기준금액({ui.won(threshold)}) 미만이라 소모품(비용 처리)을 제안합니다.")
    st.caption(f"{rec['요청번호']} · {rec['선정업체']} · 수량 {d.to_num(rec['수량'])}개 · 시리얼 {rec['검수 시리얼'] or '-'}")
    defaults = {"품명": rec["품명"], "규격": rec["규격"], "계정과목": account, "현장": rec["현장"], "사용자": rec["사용예정자"],
                "취득일자": date.today(), "취득가액": unit, "공급업체": rec["선정업체"]}
    fields = asset_form(f"register-{no}", defaults, submit=f"{d.to_num(rec['수량'])}개 등록하고 태그 발급", show_serial=False)
    if fields is not None:
        tags = ui.run_action(d.pr_register, no, fields, actor)
        if tags:
            st.session_state["new_tags"] = tags
            _done(f"{len(tags)}개 자산을 등록했습니다: {', '.join(tags)}")


@st.dialog("📥 인수 확인", width="large")
def dlg_move_receive(no: str, actor: str):
    rec = d.get_request("move", no)
    st.markdown(f"**{rec['보내는 현장']} → {rec['받는 현장']}** · {rec['받는 부서'] or ''} {rec['새 사용자'] or ''}")
    st.dataframe(ui.asset_frame(d.request_assets(rec)), hide_index=True, width="stretch", column_config=ui.ASSET_COLUMN_CONFIG)
    ok = st.checkbox("실물을 받았고 수량·상태를 확인했습니다", key=f"recv-ok-{no}")
    note = st.text_input("메모", key=f"recv-note-{no}")
    if st.button("인수 완료", type="primary", disabled=not ok, width="stretch", key=f"recv-go-{no}"):
        if ui.run_action(d.transfer_receive, no, note, actor, success=f"{no} 이동을 완료했습니다. 자산대장의 현장이 바뀌었습니다."):
            st.rerun()


@st.dialog("🔎 사고 조사 결과", width="large")
def dlg_inc_investigate(no: str, actor: str):
    rec = d.get_request("inc", no)
    a = d.get_asset(rec["태그번호"])
    st.markdown(f"**{rec['구분']}** · {rec['태그번호']} {rec['품명']} · 장부가 {ui.won(d.book_value(a)) if a else '-'}")
    st.info(rec["경위"])
    options = ["수리", "망실처리", "보험청구 후 망실처리"] if rec["구분"] == "파손" else ["망실처리", "보험청구 후 망실처리", "회수됨(정상 복귀)"]
    with st.form(f"inv-{no}"):
        c1, c2, c3 = st.columns(3)
        intent = c1.selectbox("고의·과실 판단", ["과실 없음", "경과실", "중과실", "고의"])
        liability = c2.selectbox("변상 여부", ["면책", "일부 변상", "전액 변상"])
        comp = c3.number_input("변상 금액(원)", min_value=0, step=10000)
        c1, c2, c3 = st.columns(3)
        action = c1.selectbox("처리 방법", options)
        repair = c2.number_input("수리 견적(원)", min_value=0, step=10000, help="장부가보다 크면 처분 검토 대상에 올라갑니다")
        insurance = c3.text_input("보험사·청구번호")
        opinion = st.text_area("조사 의견", placeholder="내부 규정에 따른 판단 근거")
        if st.form_submit_button("조사 완료", type="primary", width="stretch"):
            fields = {"고의과실": intent, "변상여부": liability, "변상금액": comp, "처리방법": action,
                      "수리견적": repair, "보험청구": insurance, "조사의견": opinion}
            if ui.run_action(d.incident_investigate, no, fields, actor, success=f"{no} 조사 결과를 저장했습니다."):
                st.rerun()


@st.dialog("🏁 처리·종결", width="large")
def dlg_inc_close(no: str, actor: str):
    rec = d.get_request("inc", no)
    a = d.get_asset(rec["태그번호"])
    action = rec["처리방법"]
    st.markdown(f"**{rec['태그번호']} {rec['품명']}** · 처리 방법: **{action}**")
    if a and "망실" in action:
        nbv = d.book_value(a)
        comp = d.to_num(rec["변상금액"], 0) or 0
        st.warning(f"자산대장에서 망실 제적합니다. 장부가 {ui.won(nbv)} − 변상 {ui.won(comp)} = 손실 {ui.won(nbv - comp)}")
    else:
        st.info("자산을 원래 상태로 되돌리고 사고 건을 종결합니다.")
    if st.button("집행하고 종결", type="primary", width="stretch", key=f"close-go-{no}"):
        msg = ui.run_action(d.incident_close, no, actor)
        if msg is not None:
            _done(f"{no} 종결했습니다. {msg if isinstance(msg, str) else ''}".strip())


@st.dialog("🚚 처분 집행", width="large")
def dlg_dsp_execute(no: str, actor: str):
    rec = d.get_request("dsp", no)
    items = d.request_assets(rec)
    wipe = d.needs_secure_wipe(items)
    st.dataframe(ui.asset_frame(items), hide_index=True, width="stretch", column_config=ui.ASSET_COLUMN_CONFIG)
    if wipe:
        st.warning("PC·저장장치가 포함되어 있습니다. 데이터 완전 삭제(보안 파기) 증빙이 있어야 집행할 수 있습니다.")
    methods = ["폐기", "매각", "기증", "사내 경매"]
    with st.form(f"exec-{no}"):
        c1, c2 = st.columns(2)
        method = c1.selectbox("처분 방법", methods, index=methods.index(rec["희망 처분방법"]) if rec["희망 처분방법"] in methods else 0)
        when = c2.date_input("집행일", value=date.today())
        c1, c2 = st.columns(2)
        vendor = c1.text_input("폐기업체 · 매수자 · 기증처")
        proceeds = c2.number_input("처분 금액 합계(원)", min_value=0, step=10000, help="폐기·기증은 0원")
        wiped = cert = False
        if wipe:
            c1, c2 = st.columns(2)
            wiped = c1.checkbox("저장장치 데이터 완전 삭제를 확인했습니다")
            cert = c2.text_input("파기 증명서 번호")
        note = st.text_input("메모")
        if st.form_submit_button("집행 기록", type="primary", width="stretch"):
            if ui.run_action(d.disposal_execute, no, method, when, vendor, proceeds, wiped, cert or "", note, actor,
                             success=f"{no} 집행을 기록했습니다. 관리자가 장부에서 제적합니다."):
                st.rerun()


@st.dialog("📕 장부 제적", width="large")
def dlg_dsp_derecognize(no: str, actor: str):
    rec = d.get_request("dsp", no)
    p = d.disposal_preview(rec)
    rows = [{"태그번호": a["태그번호"], "품명": a["품명"], "취득가액": d.to_num(a["취득가액"], 0), "장부가액": round(n)}
            for a, n in zip(p["items"], p["nbvs"])]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config=ui.money_config("취득가액", "장부가액"))
    c1, c2, c3 = st.columns(3)
    c1.metric("처분 금액", ui.won(p["proceeds"]))
    c2.metric("장부가 합계", ui.won(p["total_nbv"]))
    c3.metric("처분이익" if p["gain_loss"] >= 0 else "처분손실", ui.won(abs(p["gain_loss"])))
    st.caption(f"{rec['처분방법']} · {rec['처분처']} · 집행일 {ui.fmt_date(rec['집행일'])}" + (f" · 파기증명 {rec['파기증명번호']}" if rec["파기증명번호"] else ""))
    if st.button("제적 확정", type="primary", width="stretch", key=f"derec-{no}"):
        gl = ui.run_action(d.disposal_derecognize, no, actor)
        if gl is not None:
            _done(f"{no} 제적했습니다. {'처분이익' if gl >= 0 else '처분손실'} {ui.won(abs(gl))}")


# =========================================================
# 자산 입력 폼 (등록·수정 공용)
# =========================================================
def asset_form(key: str, defaults: dict, submit: str, show_serial: bool = True, show_qty: bool = False,
               sites: list[str] | None = None, show_status: bool = False):
    """st.form 안에서 자산 항목을 입력받아 dict를 돌려줍니다(제출 전에는 None)."""
    sites = sites or d.site_names()
    acc_default = defaults.get("계정과목") if defaults.get("계정과목") in d.ACCOUNTS else "비품"
    with st.form(key):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("품명 *", value=defaults.get("품명", ""))
        spec = c2.text_input("규격·모델", value=defaults.get("규격", ""))
        serial = c3.text_input("시리얼 번호", value=defaults.get("시리얼번호", "")) if show_serial else ""
        c1, c2, c3 = st.columns(3)
        account = c1.selectbox("계정과목 *", d.ACCOUNT_NAMES, index=d.ACCOUNT_NAMES.index(acc_default),
                               format_func=lambda a: f"{a} ({d.ACCOUNTS[a]['cls']})")
        site_default = defaults.get("현장") if defaults.get("현장") in sites else (sites[0] if sites else None)
        site = c2.selectbox("현장 *", sites, index=sites.index(site_default) if site_default in sites else 0)
        dept = c3.text_input("관리부서", value=defaults.get("관리부서", ""))
        c1, c2, c3 = st.columns(3)
        holder = c1.text_input("사용자", value=defaults.get("사용자", ""))
        location = c2.text_input("설치 위치", value=defaults.get("설치위치", ""), placeholder="예: 3층 개발실")
        vendor = c3.text_input("공급업체", value=defaults.get("공급업체", ""))
        c1, c2, c3 = st.columns(3)
        acquired = c1.date_input("취득일자 *", value=d.to_date(defaults.get("취득일자")) or date.today())
        cost = c2.number_input("취득가액(원, 1개 기준) *", min_value=0, step=10000, value=int(d.to_num(defaults.get("취득가액"), 0) or 0))
        qty = c3.number_input("수량", min_value=1, max_value=500, value=1, step=1) if show_qty else 1
        c1, c2, c3 = st.columns(3)
        life = c1.number_input("내용연수(년) · 0이면 계정 기본값", min_value=0, max_value=50, value=int(d.to_num(defaults.get("내용연수"), 0) or 0))
        methods = ["", "정률", "정액"]
        method = c2.selectbox("상각방법", methods, index=methods.index(defaults.get("상각방법")) if defaults.get("상각방법") in methods else 0,
                              format_func=lambda m: m + "법" if m else "계정 기본값")
        residual = c3.number_input("잔존가액(원)", min_value=0, step=1000, value=int(d.to_num(defaults.get("잔존가액"), 0) or 0))
        status = defaults.get("상태") or "사용중"
        if show_status:
            status = st.selectbox("상태", d.ASSET_STATUSES, index=d.ASSET_STATUSES.index(status) if status in d.ASSET_STATUSES else 0)
        memo = st.text_input("비고", value=defaults.get("비고", ""))
        threshold = d.capitalization_threshold()
        st.caption(f"자본화 기준금액 {ui.won(threshold)} 미만은 '소모품'으로 등록하면 취득 시 비용 처리되고 감가상각에서 빠집니다.")
        submitted = st.form_submit_button(submit, type="primary", width="stretch")
    if not submitted:
        return None
    fields = {"품명": name.strip(), "규격": spec.strip(), "시리얼번호": serial.strip(), "계정과목": account, "현장": site,
              "관리부서": dept.strip(), "사용자": holder.strip(), "설치위치": location.strip(), "공급업체": vendor.strip(),
              "취득일자": acquired, "취득가액": cost, "내용연수": life or "", "상각방법": method, "잔존가액": residual,
              "상태": status, "비고": memo.strip()}
    if show_qty:
        fields["_qty"] = qty
    if account != "소모품" and 0 < cost < threshold:
        ui.flash(f"참고: 단가 {ui.won(cost)}은 자본화 기준금액({ui.won(threshold)}) 미만입니다. 소모품으로 바꾸려면 자산 정보에서 수정하세요.", "info")
    return fields


# =========================================================
# 신청서
# =========================================================
def purchase_form(key: str, site_options: list[str], actor: str, defaults: dict | None = None):
    defaults = defaults or {}
    with st.form(key):
        c1, c2, c3 = st.columns(3)
        site = c1.selectbox("요청 현장", site_options,
                            index=site_options.index(defaults["현장"]) if defaults.get("현장") in site_options else 0)
        account = c2.selectbox("예상 계정과목", d.ACCOUNT_NAMES,
                               index=d.ACCOUNT_NAMES.index(defaults["계정과목"]) if defaults.get("계정과목") in d.ACCOUNTS else 0)
        needed = c3.date_input("필요 시점", value=d.to_date(defaults.get("필요일")) or date.today() + timedelta(days=14))
        c1, c2 = st.columns(2)
        item = c1.text_input("품명 *", value=defaults.get("품명", ""))
        spec = c2.text_input("규격·사양", value=defaults.get("규격", ""))
        c1, c2, c3 = st.columns(3)
        qty = c1.number_input("수량 *", min_value=1, value=int(defaults.get("수량") or 1), step=1)
        unit = c2.number_input("예상 단가(원) *", min_value=0, step=10000, value=int(defaults.get("예상단가") or 0))
        user = c3.text_input("사용 예정자", value=defaults.get("사용예정자", ""))
        reason = st.text_area("구매 사유 (타당성) *", value=defaults.get("구매사유", ""),
                              placeholder="필요한 이유, 대체 가능한 유휴 자산 검토 결과 등")
        st.caption(f"예산 합계 {ui.won(qty * unit)} · 관리자가 타당성 검토 → 비교견적 → 업체 선정 후 발주합니다.")
        if st.form_submit_button("🛒 구매요청 제출", type="primary", width="stretch"):
            no = ui.run_action(d.create_purchase_request, {"현장": site, "계정과목": account, "필요일": needed, "품명": item,
                                                           "규격": spec, "수량": qty, "예상단가": unit, "사용예정자": user,
                                                           "구매사유": reason}, actor)
            if no:
                _done(f"구매요청 {no}을(를) 제출했습니다.")


SEARCH_LIMIT = 300


def _search_pool(key: str, candidates: list[dict], preselected: list[str] | None = None) -> list[dict]:
    """후보가 많으면(수천 개) 먼저 검색어로 좁힙니다. 미리 고른 자산은 항상 포함합니다."""
    if len(candidates) <= SEARCH_LIMIT:
        return candidates
    pre = set(preselected or [])
    q = st.text_input(f"🔎 자산 검색 (후보 {len(candidates):,}개)", key=f"{key}-search",
                      placeholder="태그번호·품명·규격·사용자 일부를 입력하세요").strip().lower()
    hits = [a for a in candidates if a["태그번호"] in pre]
    if q:
        hits += [a for a in candidates if a["태그번호"] not in pre and
                 (q in a["태그번호"].lower() or q in a["품명"].lower() or q in a["규격"].lower() or q in a["사용자"].lower())][:SEARCH_LIMIT]
        if not hits:
            st.caption("검색 결과가 없습니다.")
    elif not hits:
        st.caption("검색어를 입력하면 선택할 자산 목록이 나옵니다.")
    elif q == "":
        st.caption(f"선택한 자산 {len(hits)}개만 표시합니다. 더 추가하려면 검색하세요.")
    return hits


def transfer_form(key: str, candidates: list[dict], to_site_options: list[str], actor: str,
                  preselected: list[str] | None = None, default_to: str | None = None):
    if not candidates:
        st.info("이동할 수 있는 자산이 없습니다.")
        return
    candidates = _search_pool(key, candidates, preselected)
    if not candidates:
        return
    labels = {a["태그번호"]: f"{a['태그번호']} · {a['품명']} · {a['현장']}" + (f" · {a['상태']}" if a["상태"] != "사용중" else "")
              for a in candidates}
    with st.form(key):
        tags = st.multiselect("이동할 자산 *", list(labels), default=[t for t in (preselected or []) if t in labels],
                              format_func=lambda t: labels[t], placeholder="태그번호나 품명으로 검색")
        c1, c2, c3 = st.columns(3)
        to_site = c1.selectbox("받는 현장 *", to_site_options,
                               index=to_site_options.index(default_to) if default_to in to_site_options else 0)
        to_dept = c2.text_input("받는 부서")
        to_holder = c3.text_input("새 사용자")
        reason = st.text_area("신청 사유 *", placeholder="예: 신규 입사자 지급, 공사 투입 장비 부족")
        st.caption("보내는 현장 담당자가 승인하고, 받는 현장에서 인수확인하면 자산대장의 현장이 바뀝니다.")
        if st.form_submit_button("🔄 이동 신청", type="primary", width="stretch"):
            nos = ui.run_action(d.create_transfer, tags, to_site, to_dept, to_holder, reason, actor)
            if nos:
                _done(f"이동신청 {', '.join(nos)}을(를) 제출했습니다." + (" (보내는 현장별로 나눠 접수)" if len(nos) > 1 else ""))


def incident_form(key: str, candidates: list[dict], actor: str, preselected: str | None = None, defaults: dict | None = None):
    defaults = defaults or {}
    if not candidates:
        st.info("신고할 수 있는 자산이 없습니다.")
        return
    candidates = _search_pool(key, candidates, [preselected] if preselected else [])
    if not candidates:
        return
    labels = {a["태그번호"]: f"{a['태그번호']} · {a['품명']} · {a['사용자'] or a['관리부서'] or a['현장']}" for a in candidates}
    keys = list(labels)
    with st.form(key):
        c1, c2 = st.columns([3, 1])
        tag = c1.selectbox("대상 자산 *", keys, index=keys.index(preselected) if preselected in keys else 0, format_func=lambda t: labels[t])
        kinds = ["분실", "도난", "파손"]
        kind = c2.selectbox("구분", kinds, index=kinds.index(defaults["구분"]) if defaults.get("구분") in kinds else 0)
        c1, c2, c3 = st.columns(3)
        occurred = c1.date_input("발생일", value=d.to_date(defaults.get("발생일")) or date.today())
        place = c2.text_input("발생 장소", value=defaults.get("발생장소", ""))
        person = c3.text_input("관련자(사용자)")
        statement = st.text_area("경위 *", value=defaults.get("경위", ""), placeholder="언제, 어디서, 어떻게 발생했는지 사실대로 적어 주세요.")
        police = st.text_input("도난 시 경찰 신고 번호")
        if st.form_submit_button("⚠️ 경위서 접수", type="primary", width="stretch"):
            no = ui.run_action(d.create_incident, tag, kind, occurred, place, person, statement, police, actor)
            if no:
                _done(f"경위서 {no}을(를) 접수했습니다. 관리자가 조사합니다.")


def disposal_form(key: str, candidates: list[dict], actor: str, preselected: list[str] | None = None):
    if not candidates:
        st.info("처분 신청할 수 있는 자산이 없습니다.")
        return
    candidates = _search_pool(key, candidates, preselected)
    if not candidates:
        return
    labels = {a["태그번호"]: f"{a['태그번호']} · {a['품명']} · {a['현장']} · 장부가 {ui.won(d.book_value(a))}" for a in candidates}
    with st.form(key):
        tags = st.multiselect("처분할 자산 *", list(labels), default=[t for t in (preselected or []) if t in labels],
                              format_func=lambda t: labels[t])
        c1, c2 = st.columns(2)
        reason = c1.selectbox("불용 사유", ["내용연수 만료", "고장 (수리비 과다)", "노후화", "유휴 장기화", "기타"])
        method = c2.selectbox("희망 처분 방법", ["폐기", "매각", "기증", "사내 경매"])
        detail = st.text_area("상세 사유 *")
        st.caption("불용품 판정 위원회(관리자) 승인 → 집행(폐기·매각·기증) → 장부 제적 순서로 진행합니다. PC·저장장치는 보안 파기 증빙이 필요합니다.")
        if st.form_submit_button("🗑 처분 신청", type="primary", width="stretch"):
            nos = ui.run_action(d.create_disposal, tags, reason, method, detail, actor)
            if nos:
                _done(f"처분 신청 {', '.join(nos)}을(를) 접수했습니다.")


@st.dialog("🔄 자산 이동 신청", width="large")
def dlg_new_transfer(tags: list[str], actor: str, default_to: str | None = None):
    candidates = [a for a in d.active_assets() if a["상태"] != "처분대기"]
    transfer_form("dlg-transfer", candidates, d.site_names(), actor, preselected=tags, default_to=default_to)


@st.dialog("🗑 처분 신청", width="large")
def dlg_new_disposal(tags: list[str], actor: str):
    candidates = [a for a in d.active_assets() if a["상태"] in ("사용중", "유휴", "수리중")]
    disposal_form("dlg-disposal", candidates, actor, preselected=tags)


# =========================================================
# 자산 상세 대화상자
# =========================================================
@st.dialog("🏷️ 자산 상세", width="large")
def asset_dialog(tag: str, role: str, site: str | None, actor: str):
    render_asset_detail(tag, role, site, actor, key="dlg")


def render_asset_detail(tag: str, role: str, site: str | None, actor: str, key: str):
    a = d.get_asset(tag)
    if not a:
        st.error(f"{tag} 자산을 찾을 수 없습니다.")
        return
    info = d.account_info(a)
    dep = d.depreciation(a)
    st.markdown(
        f"<div class='asset-head'><span class='tag'>{html.escape(a['태그번호'])}</span>"
        f"<span class='name'>{html.escape(a['품명'])}</span>{ui.badge(a['상태'])}"
        f"<span class='badge muted'>{html.escape(a['계정과목'])} · {html.escape(info['cls'])}</span></div>",
        unsafe_allow_html=True,
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("현장", a["현장"] or "-")
    c2.metric("사용자", a["사용자"] or "-")
    c3.metric("취득가액", ui.short_won(a["취득가액"]) + "원")
    c4.metric("장부가액", ui.short_won(d.book_value(a)) + "원" if d.is_active(a) else "-")

    admin = role == ADMIN
    own = admin or a["현장"] == site
    tab_names = ["📄 기본정보", "🏷️ QR 태그", "🕘 변동 이력"]
    if d.is_active(a) and actor:
        tab_names.append("🛠 작업")
    if admin:
        tab_names.append("✏️ 정보 수정")
    tabs = st.tabs(tab_names)

    with tabs[0]:
        rows = [["규격", a["규격"]], ["시리얼 번호", a["시리얼번호"]], ["관리부서", a["관리부서"]], ["설치 위치", a["설치위치"]],
                ["공급업체", a["공급업체"]], ["취득일자", ui.fmt_date(a["취득일자"])], ["취득가액", ui.won(a["취득가액"])]]
        if info["cls"] != "소모품":
            life = d.asset_life(a)
            left = d.life_remaining_months(a)
            rows += [["상각", f"{d.asset_method(a)}법 · {life}년 · 잔존가액 {ui.won(a['잔존가액'] or 0)}"],
                     ["경과", f"{min(dep['months'], life * 12)} / {life * 12}개월" + (" · 내용연수 만료" if left is not None and left <= 0 else "")],
                     ["상각누계액", ui.won(dep["accum"])], ["장부가액", ui.won(dep["nbv"]) if d.is_active(a) else "-"],
                     ["이번 달 상각비", ui.won(dep["monthly"])]]
        else:
            rows.append(["회계처리", "취득 시 소모품비로 비용 처리 (감가상각 없음)"])
        if a["수리견적"]:
            rows.append(["수리 견적", ui.won(a["수리견적"])])
        if a["처분일자"]:
            rows.append(["처분", f"{a['처분방법']} · {ui.fmt_date(a['처분일자'])} · 처분금액 {ui.won(a['처분금액'])} · 손익 {ui.won(a['처분손익'])}"])
        for k in ("연결차량번호", "구매요청번호", "등록일시", "비고"):
            if a[k]:
                rows.append([k, a[k]])
        st.dataframe(pd.DataFrame([r for r in rows if r[1] not in ("", None)], columns=["항목", "내용"]),
                     hide_index=True, width="stretch")

    with tabs[1]:
        c1, c2 = st.columns([1, 2])
        try:
            c1.image(ui.qr_png(ui.qr_payload(a["태그번호"]), 8), caption=a["태그번호"], width=200)
            c2.image(ui.label_png(a), caption="실물 부착용 라벨 미리보기", width="stretch")
            c2.download_button("🖼 라벨 이미지(PNG)", ui.label_png(a), file_name=f"자산라벨_{a['태그번호']}.png",
                               mime="image/png", key=f"{key}-png-{tag}", width="stretch")
            with c2:
                ui.label_download([a], key=f"{key}-pdf-{tag}", label="🏷️ 라벨 PDF (A4)")
        except d.DataError as exc:
            st.error(str(exc))
        st.caption(f"QR 내용: {ui.qr_payload(a['태그번호'])}  · 설정에서 'QR 기본주소'를 넣으면 휴대폰으로 스캔해 이 자산 화면을 바로 엽니다.")

    with tabs[2]:
        hist = d.get_history(tag)
        if hist:
            st.dataframe(pd.DataFrame(hist)[["일시", "구분", "내용", "처리자"]], hide_index=True, width="stretch")
        else:
            st.info("변동 이력이 없습니다.")
        related = [(k, r) for k in d.REQUEST_TABLES for r in d.get_requests(k)
                   if tag in (r.get("태그번호") or r.get("등록 태그번호") or "")
                   and tag in [t.strip() for t in (r.get("태그번호") or r.get("등록 태그번호") or "").split(",")]]
        if related:
            st.markdown("**관련 요청**")
            st.dataframe(pd.DataFrame([{"요청번호": r["요청번호"], "종류": d.KIND_NAMES[k], "상태": r["상태"], "일시": r["요청일시"]}
                                       for k, r in related]), hide_index=True, width="stretch")

    if "🛠 작업" in tab_names:
        with tabs[tab_names.index("🛠 작업")]:
            render_asset_actions(a, own, site, actor, key)

    if admin:
        with tabs[tab_names.index("✏️ 정보 수정")]:
            fields = asset_form(f"{key}-edit-{tag}", a, submit="💾 저장", show_status=True)
            if fields is not None:
                if ui.run_action(d.update_asset, tag, fields, actor, success=f"{tag} 정보를 저장했습니다."):
                    st.rerun()


def render_asset_actions(a: dict, own: bool, site: str | None, actor: str, key: str):
    tag = a["태그번호"]
    if not own:
        st.markdown(f"이 자산은 **{a['현장']}** 소속입니다. 우리 현장에서 필요하면 이동을 신청하세요.")
        transfer_form(f"{key}-mv-{tag}", [a], d.site_names(), actor, preselected=[tag], default_to=site)
        return
    choice = st.radio("작업", ["👥 사용자·위치 변경", "🔄 다른 현장으로 이동", "⚠️ 분실·파손 신고", "🗑 처분 신청", "💤 상태 변경"],
                      horizontal=True, key=f"{key}-act-{tag}")
    if choice.startswith("👥"):
        st.caption("입퇴사, 부서 이동, 조직개편, 층간·사옥 이동 때 같은 현장 안의 인수인계를 기록합니다.")
        with st.form(f"{key}-ho-{tag}"):
            c1, c2, c3 = st.columns(3)
            dept = c1.text_input("관리부서", value=a["관리부서"])
            holder = c2.text_input("새 사용자", value=a["사용자"])
            location = c3.text_input("위치", value=a["설치위치"])
            reason = st.selectbox("사유", ["부서 이동", "입사 지급", "퇴사 회수", "조직개편", "층간·사옥 이동", "기타"])
            ok = st.checkbox("인수자와 함께 실물 상태와 수량을 확인했습니다")
            if st.form_submit_button("인수인계 기록", type="primary", width="stretch"):
                if not ok:
                    st.error("인수인계 확인에 체크하세요.")
                elif ui.run_action(d.handover, tag, dept, holder, location, reason, actor, success=f"{tag} 인수인계를 기록했습니다."):
                    st.rerun()
    elif choice.startswith("🔄"):
        others = [s for s in d.site_names() if s != a["현장"]]
        transfer_form(f"{key}-mv2-{tag}", [a], others, actor, preselected=[tag])
    elif choice.startswith("⚠️"):
        incident_form(f"{key}-inc-{tag}", [a], actor, preselected=tag)
    elif choice.startswith("🗑"):
        if a["상태"] not in ("사용중", "유휴", "수리중"):
            st.info(f"'{a['상태']}' 상태에서는 처분 신청할 수 없습니다.")
        else:
            disposal_form(f"{key}-dsp-{tag}", [a], actor, preselected=[tag])
    else:
        options = [s for s in ("사용중", "유휴") if s != a["상태"]]
        if a["상태"] not in ("사용중", "유휴"):
            st.info(f"'{a['상태']}' 상태는 진행 중인 요청이 끝나면 바뀝니다.")
            return
        new = st.radio("바꿀 상태", options, horizontal=True, key=f"{key}-st-{tag}")
        st.caption("유휴로 표시하면 다른 현장의 '유휴 자산' 목록에 올라 재배치 대상이 됩니다.")
        if st.button("상태 변경", type="primary", key=f"{key}-st-go-{tag}"):
            if ui.run_action(d.update_asset, tag, {"상태": new}, actor, "상태 변경", f"{a['상태']} → {new}",
                             success=f"{tag} 상태를 '{new}'(으)로 바꿨습니다."):
                st.rerun()


# =========================================================
# 재물조사 작업 화면 (관리자·현장 담당자 공용)
# =========================================================
def _scan_callback(audit_no: str, key: str, actor: str, site: str | None):
    code = st.session_state.get(key, "")
    if not d.clean_str(code):
        return
    try:
        ok, msg = d.audit_scan(audit_no, code, actor, allowed_site=site)
    except d.DataError as exc:
        ok, msg = False, str(exc)
    st.session_state[f"{key}-msg"] = (ok, msg)
    st.session_state[key] = ""


def render_audit_workspace(audit: dict, role: str, site: str | None, actor: str, key: str):
    audit_no = audit["회차번호"]
    items = d.get_audit_items(audit_no, site if role == SITE else None)
    stats = d.audit_stats(items)
    st.markdown(f"#### 🔍 {audit['회차명']} <span class='small-muted'>· 기준일 {ui.fmt_date(audit['기준일'])} · 대상 {audit['대상']}"
                f"{' · ' + site + ' 자산만 표시' if role == SITE else ''}</span>", unsafe_allow_html=True)
    k = st.columns(5)
    with k[0]:
        ui.kpi("장부 수량", stats["total"], "조사 시작 시점 보유 자산", unit="개")
    with k[1]:
        ui.kpi("실물 확인", stats["found"], f"일치율 {stats['found'] / stats['total'] * 100:.0f}%" if stats["total"] else "-", "ok", "개")
    with k[2]:
        ui.kpi("미발견", stats["missing"], "분실 경위 확인 필요", "crit" if stats["missing"] else "", "개")
    with k[3]:
        ui.kpi("미확인", stats["todo"], "아직 확인하지 않은 자산", "warn" if stats["todo"] else "", "개")
    with k[4]:
        ui.kpi("유휴 판정", stats["idle"], "마감 시 재배치 대상으로 전환", "warn" if stats["idle"] else "", "개")
    if stats["total"]:
        st.progress((stats["found"] + stats["missing"]) / stats["total"], text=f"진행률 {(stats['found'] + stats['missing']) / stats['total'] * 100:.0f}%")

    scan_key = f"{key}-scan"
    st.text_input("📷 QR·바코드 스캔 또는 태그번호 입력 후 Enter", key=scan_key,
                  on_change=_scan_callback, args=(audit_no, scan_key, actor, site if role == SITE else None),
                  placeholder="예: FUR-2026-0001  (USB·블루투스 바코드 스캐너는 그대로 입력됩니다)")
    msg = st.session_state.pop(f"{scan_key}-msg", None)
    if msg:
        (st.success if msg[0] else st.warning)(msg[1])

    c1, c2 = st.columns([3, 2])
    view = c1.radio("보기", ["미확인", "전체", "확인", "미발견", "유휴"], horizontal=True, key=f"{key}-view")
    q = c2.text_input("검색", placeholder="태그번호·품명·위치", key=f"{key}-q").strip().lower()
    shown = [r for r in items if (view == "전체" or (view == "유휴" and r["유휴"] == "Y") or r["결과"] == view)
             and (not q or q in r["태그번호"].lower() or q in r["품명"].lower() or q in r["설치위치"].lower())]
    if not shown:
        st.info("해당하는 자산이 없습니다.")
        return
    shown = ui.paginate(shown, f"{key}-page-{view}", page_size=500)
    df = pd.DataFrame([{"태그번호": r["태그번호"], "품명": r["품명"], "현장": r["현장"], "위치": r["설치위치"],
                        "결과": r["결과"], "유휴": r["유휴"] == "Y", "메모": r["메모"], "확인자": r["확인자"],
                        "확인일시": r["확인일시"]} for r in shown])
    edited = st.data_editor(
        df, hide_index=True, width="stretch", key=f"{key}-editor-{view}-{abs(hash(tuple(r['태그번호'] for r in shown))) % 10**8}",
        disabled=["태그번호", "품명", "현장", "위치", "확인자", "확인일시"],
        column_config={
            "결과": st.column_config.SelectboxColumn("결과", options=["미확인", "확인", "미발견"], required=True),
            "유휴": st.column_config.CheckboxColumn("유휴", help="사용하지 않고 방치된 자산이면 체크"),
            "메모": st.column_config.TextColumn("메모"),
        },
    )
    c1, c2 = st.columns([1, 1])
    if c1.button("💾 표에서 고친 결과 저장", type="primary", width="stretch", key=f"{key}-save"):
        before = {r["태그번호"]: r for r in df.to_dict("records")}
        updates = {}
        for r in edited.to_dict("records"):
            b = before[r["태그번호"]]
            if (r["결과"], bool(r["유휴"]), d.clean_str(r["메모"])) != (b["결과"], bool(b["유휴"]), d.clean_str(b["메모"])):
                updates[r["태그번호"]] = {"결과": r["결과"], "유휴": bool(r["유휴"]), "메모": r["메모"]}
        if not updates:
            st.info("바뀐 내용이 없습니다.")
        else:
            n = ui.run_action(d.audit_mark, audit_no, updates, actor)
            if n is not None:
                ui.flash(f"{n}건의 조사 결과를 저장했습니다.")
                st.rerun()
    if role == SITE:
        c2.caption("마감은 관리자가 합니다. 미발견 자산은 '신청서 작성 → 분실·파손 신고'로 경위서를 제출하세요.")


# =========================================================
# 폐기·처분 자산 목록 (관리자: 전체 / 현장 담당자: 자기 현장)
# =========================================================
CLOSED_VIEW_COLS = ["태그번호", "품명", "규격", "계정과목", "현장", "취득일자", "처분일자", "사용기간", "처분방법",
                    "처분처", "취득가액", "처분금액", "처분손익", "처분요청번호"]


def _closed_row(a: dict) -> dict:
    acq, dis = a["취득일자"], a["처분일자"]
    months = (dis.year - acq.year) * 12 + dis.month - acq.month if acq and dis else None
    return {"태그번호": a["태그번호"], "품명": a["품명"], "규격": a["규격"], "계정과목": a["계정과목"], "현장": a["현장"],
            "취득일자": acq, "처분일자": dis, "사용기간": f"{months // 12}년 {months % 12}개월" if months is not None and months >= 0 else "-",
            "처분방법": a["처분방법"] or a["상태"], "처분처": a["처분처"], "취득가액": a["취득가액"] or 0,
            "처분금액": a["처분금액"] or 0, "처분손익": a["처분손익"] or 0, "처분요청번호": a["처분요청번호"]}


@st.dialog("📄 요청서 상세", width="large")
def dlg_request_detail(kind: str, no: str):
    rec = d.get_request(kind, no)
    if not rec:
        st.info(f"{no} 요청서를 찾을 수 없습니다.")
        return
    st.markdown(f"**{rec['요청번호']}** {ui.badge(rec['상태'])} · {d.KIND_NAMES[kind]} · {request_where(kind, rec)}", unsafe_allow_html=True)
    st.markdown(ui.steps_html(kind, rec["상태"]), unsafe_allow_html=True)
    show_request_detail(kind, rec)


def render_disposed_list(key: str, actor: str, role: str, site: str | None = None):
    """폐기·매각·기증·경매·망실로 장부에서 빠진 자산 목록. 수십만 건도 필터·페이지로 봅니다."""
    base = d.closed_assets()
    if site:
        base = [a for a in base if a["현장"] == site]
    if not base:
        st.info("처분·폐기된 자산이 없습니다.")
        return
    years = sorted({a["처분일자"].year for a in base if a["처분일자"]}, reverse=True)
    c1, c2, c3, c4, c5 = st.columns([1, 2.2, 1.1, 1.1, 1.8])
    year = c1.selectbox("처분연도", ["전체"] + years, key=f"{key}-year")
    methods = c2.multiselect("처분방법", d.DISPOSAL_METHODS, default=d.DISPOSAL_METHODS, key=f"{key}-methods")
    site_f = c3.selectbox("현장", ["전체"] + d.site_names(), key=f"{key}-site") if not site else site
    acc = c4.selectbox("계정과목", ["전체"] + d.ACCOUNT_NAMES, key=f"{key}-acc")
    q = c5.text_input("검색", placeholder="태그번호·품명·처분처·요청번호", key=f"{key}-q").strip().lower()

    b = _closed_bundle(site, year, tuple(methods), site_f, acc, q)
    rows = b["rows"]
    cost, proceeds, gl = b["cost"], b["proceeds"], b["gl"]
    k = st.columns(5)
    with k[0]: ui.kpi("처분 자산", f"{len(rows):,}", f"전체 {len(base):,}개 중", unit="개")
    with k[1]: ui.kpi("취득가액 합계", ui.short_won(cost), ui.won(cost), unit="원")
    with k[2]: ui.kpi("처분금액 합계", ui.short_won(proceeds), "매각·경매 회수액", unit="원")
    with k[3]: ui.kpi("처분손익", ("+" if gl >= 0 else "") + ui.short_won(gl), "처분금액 − 처분 시 장부가", "ok" if gl >= 0 else "crit", "원")
    with k[4]: ui.kpi("폐기 · 망실", f"{b['n_scrap']:,} · {b['n_lost']:,}", "폐기 건수 · 망실 건수", unit="개")

    tab_list, tab_chart, tab_sum = st.tabs(["📋 목록", "📊 연도별 추이", "🧮 방법·현장별 합계"])
    with tab_list:
        if not rows:
            st.info("조건에 맞는 자산이 없습니다.")
        else:
            page = ui.paginate(rows, f"{key}-page", page_size=1000)
            df = pd.DataFrame([_closed_row(a) for a in page], columns=CLOSED_VIEW_COLS)
            ev = st.dataframe(df, hide_index=True, width="stretch", height=420, on_select="rerun", selection_mode="single-row",
                              key=f"{key}-table",
                              column_config={**ui.money_config("취득가액", "처분금액", "처분손익"),
                                             "취득일자": st.column_config.DateColumn("취득일자", format="YYYY-MM-DD"),
                                             "처분일자": st.column_config.DateColumn("처분일자", format="YYYY-MM-DD")})
            sel = [df.iloc[i] for i in ev.selection.rows if i < len(df)]
            c1, c2, c3 = st.columns([1, 1, 2])
            if c1.button("🔍 자산 상세·이력", disabled=not sel, width="stretch", key=f"{key}-detail"):
                asset_dialog(sel[0]["태그번호"], role, site, actor)
            if c2.button("📄 처분 요청서", disabled=not sel or not (sel and sel[0]["처분요청번호"]), width="stretch", key=f"{key}-req"):
                no = sel[0]["처분요청번호"]
                dlg_request_detail("inc" if no.startswith("IN-") else "dsp", no)
            c3.caption("행을 하나 고르면 자산 이력과 처분 요청서(위원회 승인·집행·제적 기록)를 볼 수 있습니다.")
        ui.export_panel(f"{key}-export", f"처분자산_{date.today():%Y%m%d}",
                        lambda: {"처분자산": (CLOSED_VIEW_COLS, [_closed_row(a) for a in rows])}, len(rows))
    with tab_chart:
        counts = b["trend"]
        if counts:
            chart = pd.DataFrame([{"연도": y, "처분방법": m, "건수": n} for (y, m), n in sorted(counts.items())])
            st.bar_chart(chart, x="연도", y="건수", color="처분방법", stack=True, height=340)
            st.caption("연도 필터를 뺀 나머지 조건으로 집계했습니다.")
    with tab_sum:
        summarize = lambda field: b["summary"][field]
        if rows:
            c1, c2 = st.columns(2)
            c1.markdown("**처분방법별**")
            c1.dataframe(summarize("처분방법"), hide_index=True, width="stretch", column_config=ui.money_config("취득가액", "처분금액", "처분손익"))
            c2.markdown("**현장별**")
            c2.dataframe(summarize("현장"), hide_index=True, width="stretch", column_config=ui.money_config("취득가액", "처분금액", "처분손익"))
            st.markdown("**계정과목별**")
            st.dataframe(summarize("계정과목"), hide_index=True, width="stretch", column_config=ui.money_config("취득가액", "처분금액", "처분손익"))


_closed_cache: dict = {}


def _closed_bundle(site, year, methods: tuple, site_f, acc, q) -> dict:
    """필터 결과·합계·추이를 한 번에 계산해 캐시합니다(같은 조건으로 다시 그릴 때 즉시 표시)."""
    key = (d.data_version("assets"), site, year, methods, site_f, acc, q)
    hit = _closed_cache.get(key)
    if hit:
        return hit
    base = d.closed_assets()
    method_set = set(methods)
    rows, trend = [], {}
    agg = {f: {} for f in ("처분방법", "현장", "계정과목")}
    cost = proceeds = gl = n_scrap = n_lost = 0
    for a in base:
        m = a["처분방법"] or a["상태"]
        if m not in method_set:
            continue
        if site and a["현장"] != site:
            continue
        if site_f != "전체" and a["현장"] != site_f:
            continue
        if acc != "전체" and a["계정과목"] != acc:
            continue
        if q and not (q in a["태그번호"].lower() or q in a["품명"].lower() or q in a["처분처"].lower() or q in a["처분요청번호"].lower()):
            continue
        dis = a["처분일자"]
        if dis:
            tk = (str(dis.year), m)
            trend[tk] = trend.get(tk, 0) + 1
        if year != "전체" and (not dis or dis.year != year):
            continue
        rows.append(a)
        c, p, g = a["취득가액"] or 0, a["처분금액"] or 0, a["처분손익"] or 0
        cost, proceeds, gl = cost + c, proceeds + p, gl + g
        n_scrap += m == "폐기"
        n_lost += m == "망실"
        for f, val in (("처분방법", m), ("현장", a["현장"]), ("계정과목", a["계정과목"])):
            gsum = agg[f].setdefault(val, [0, 0, 0, 0])
            gsum[0] += 1
            gsum[1] += c
            gsum[2] += p
            gsum[3] += g
    summary = {f: pd.DataFrame([{f: k2, "건수": v[0], "취득가액": v[1], "처분금액": v[2], "처분손익": v[3]}
                                for k2, v in sorted(groups.items(), key=lambda kv: -kv[1][0])]) for f, groups in agg.items()}
    bundle = {"rows": rows, "trend": trend, "summary": summary, "cost": cost, "proceeds": proceeds, "gl": gl,
              "n_scrap": n_scrap, "n_lost": n_lost}
    if len(_closed_cache) > 12:
        _closed_cache.clear()
    _closed_cache[key] = bundle
    return bundle
