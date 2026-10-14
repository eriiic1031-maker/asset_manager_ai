"""
관리자 페이지

법인차량 관리 AI의 관리자 화면 구성을 따릅니다.
제목·기준일 → KPI 카드 → 탭으로 나눈 현황표 → 관리 탭 → 승인/반려 카드.
자산관리는 화면이 많아 왼쪽 사이드바에서 관리자 메뉴를 고릅니다.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

import data as d
import ui
import workflow as wf

MENU = ["📊 대시보드", "📋 자산대장", "➕ 자산 등록", "✅ 결재함", "🔍 재물조사", "📉 감가상각·결산",
        "♻️ 처분 검토·유휴", "🗑 폐기·처분 자산", "⚙️ 설정"]
LIVE_REFRESH_SECONDS = 10


def live_refresh_fragment(func):
    fragment = getattr(st, "fragment", None)
    if fragment is None:
        return func
    return fragment(run_every=f"{LIVE_REFRESH_SECONDS}s")(func)


def render(actor: str):
    menu = st.session_state.get("admin_menu", MENU[0])
    if menu not in MENU:
        menu = MENU[0]
    {
        MENU[0]: dashboard, MENU[1]: ledger, MENU[2]: register, MENU[3]: inbox, MENU[4]: audit,
        MENU[5]: depreciation, MENU[6]: disposal_and_idle, MENU[7]: disposed, MENU[8]: settings,
    }[menu](actor)


def goto(menu: str):
    st.session_state["_goto_menu"] = menu
    st.rerun()


# =========================================================
# 대시보드
# =========================================================
def _life_bucket(a: dict) -> str:
    left = d.life_remaining_months(a)
    if left is None:
        return "해당 없음(소모품)"
    if left <= 0:
        return "만료"
    return "1년 이내 만료" if left <= 12 else "잔여 1년 초과"


CRITERIA = {
    "계정과목": (lambda a: a["계정과목"], lambda assets: d.ACCOUNT_NAMES),
    "자산구분": (lambda a: d.account_info(a)["cls"], lambda assets: d.CLASSES),
    "상태": (lambda a: a["상태"], lambda assets: [s for s in d.ASSET_STATUSES if s not in d.CLOSED_STATUSES]),
    "내용연수": (_life_bucket, lambda assets: ["잔여 1년 초과", "1년 이내 만료", "만료", "해당 없음(소모품)"]),
    "취득연도": (lambda a: str(a["취득일자"].year) if a["취득일자"] else "미상",
             lambda assets: sorted({str(a["취득일자"].year) for a in assets if a["취득일자"]})),
}


def site_matrix(assets: list[dict], criterion: str, basis: str):
    key_fn, values_fn = CRITERIA[criterion]
    values = values_fn(assets)
    amount = (lambda a: a["취득가액"] or 0) if basis == "취득가액" else d.book_value
    sites = d.site_names()
    site_info = {s["현장명"]: s for s in d.get_sites()}
    # 한 번만 훑어서 (현장, 구분) 별 개수·금액을 모읍니다.
    cnt: dict[tuple, int] = {}
    amt: dict[tuple, float] = {}
    for a in assets:
        k = (a["현장"], key_fn(a))
        cnt[k] = cnt.get(k, 0) + 1
        amt[k] = amt.get(k, 0) + amount(a)
    table, long_rows, cnt_rows, amt_rows = [], [], [], []
    for site in sites + ["합계"]:
        row, crow, arow = {"현장": site}, {"현장": site}, {"현장": site}
        tn = ta = 0
        for v in values:
            n = sum(cnt.get((s, v), 0) for s in sites) if site == "합계" else cnt.get((site, v), 0)
            m = sum(amt.get((s, v), 0) for s in sites) if site == "합계" else amt.get((site, v), 0)
            row[v] = f"{n:,}개 · {ui.short_won(m)}" if n else "·"
            crow[v], arow[v] = n, round(m)
            tn, ta = tn + n, ta + m
            if site != "합계" and m:
                long_rows.append({"현장": site, "구분": v, "금액(백만원)": round(m / 1e6, 1)})
        row["합계"] = f"{tn:,}개 · {ui.short_won(ta)}"
        crow["합계"], arow["합계"] = tn, round(ta)
        row["담당자"] = site_info.get(site, {}).get("담당자", "") if site != "합계" else ""
        table.append(row)
        cnt_rows.append(crow)
        amt_rows.append(arow)
    cols = ["현장", "담당자"] + values + ["합계"]
    return pd.DataFrame(table)[cols], pd.DataFrame(long_rows), pd.DataFrame(cnt_rows), pd.DataFrame(amt_rows)


@live_refresh_fragment
def dashboard_body(actor: str):
    assets = d.active_assets()
    cost = sum(a["취득가액"] or 0 for a in assets)
    nbv = sum(d.book_value(a) for a in assets)
    pending = wf.pending_for(wf.ADMIN)
    pending_n = sum(len(v) for v in pending.values())
    expired = sum(1 for a in assets if (d.life_remaining_months(a) or 1) <= 0)
    idle = sum(1 for a in assets if a["상태"] == "유휴")
    closed_n = len(d.closed_assets())

    k = st.columns(7)
    with k[0]: ui.kpi("보유 자산", f"{len(assets):,}", f"{len(d.site_names())}개 현장·부서", unit="개")
    with k[1]: ui.kpi("취득가액", ui.short_won(cost), ui.won(cost), unit="원")
    with k[2]: ui.kpi("장부가액", ui.short_won(nbv), f"상각누계 {ui.short_won(cost - nbv)}원", unit="원")
    with k[3]: ui.kpi("결재 대기", pending_n, "승인·견적·등록·제적", "warn" if pending_n else "", "건")
    with k[4]: ui.kpi("내용연수 만료", f"{expired:,}", "처분 검토 대상", "warn" if expired else "", "개")
    with k[5]: ui.kpi("유휴 자산", f"{idle:,}", "재배치 대상", "warn" if idle else "", "개")
    with k[6]: ui.kpi("폐기·처분 누계", f"{closed_n:,}", "장부에서 제적된 자산", "", "개")

    st.markdown("## 🏢 현장별 자산 현황")
    c1, c2 = st.columns([3, 1.4])
    criterion = c1.radio("집계 기준", list(CRITERIA), horizontal=True, key="dash_criterion")
    basis = c2.radio("금액 기준", ["취득가액", "장부가액"], horizontal=True, key="dash_basis")
    if not assets:
        st.info("등록된 자산이 없습니다. '➕ 자산 등록'에서 자산을 등록하거나 설정에서 예시 데이터를 만들어 보세요.")
        return
    table, long_df, cnt_df, amt_df = site_matrix(assets, criterion, basis)
    st.dataframe(table, hide_index=True, width="stretch")
    st.caption(f"셀 = 개수 · {basis}. 망실·처분완료 자산은 제외됩니다 (🗑 폐기·처분 자산 메뉴에서 따로 봅니다).")
    c1, c2 = st.columns([3, 1])
    with c1:
        if not long_df.empty:
            st.bar_chart(long_df, x="현장", y="금액(백만원)", color="구분", stack=True, height=320)
    with c2:
        st.download_button("📥 현황표 엑셀", ui.excel_bytes({f"{criterion}_개수": cnt_df, f"{criterion}_{basis}": amt_df}),
                           file_name=f"현장별_{criterion}_현황_{date.today():%Y%m%d}.xlsx", width="stretch")
        by_site = {}
        for a in assets:
            by_site[a["현장"]] = by_site.get(a["현장"], 0) + 1
        for site in d.site_names():
            st.caption(f"{site}: {by_site.get(site, 0):,}개")

    st.markdown("## ⏳ 처리 대기")
    cols = st.columns(4)
    for col, kind in zip(cols, d.REQUEST_TABLES):
        with col:
            st.markdown(f"<div class='todo-card'><div class='small-muted'>{d.KIND_NAMES[kind]}</div><b>{len(pending[kind])}</b>건</div>",
                        unsafe_allow_html=True)
    if pending_n and st.button("✅ 결재함으로 이동", type="primary", key="dash-inbox"):
        goto("✅ 결재함")

    st.markdown("## 🕘 최근 변동 이력")
    hist = d.get_history(limit=12)
    if hist:
        st.dataframe(pd.DataFrame(hist)[["일시", "태그번호", "구분", "내용", "처리자"]], hide_index=True, width="stretch")
    else:
        st.caption("아직 이력이 없습니다.")


def dashboard(actor: str):
    st.title("🏷️ 자산관리 AI")
    st.caption(f"기준일: {date.today():%Y-%m-%d} · 장부가액은 오늘 기준 감가상각을 반영합니다 · {LIVE_REFRESH_SECONDS}초마다 자동 갱신")
    dashboard_body(actor)


# =========================================================
# 자산대장
# =========================================================
def ledger(actor: str):
    st.title("📋 자산대장")
    st.caption("행을 선택하면 상세·편집, 이동·처분 신청, QR 라벨 출력을 할 수 있습니다. 목록은 1,000개씩 나눠 보여 줍니다.")
    sites = d.site_names()
    c1, c2, c3, c4 = st.columns([1.2, 1.2, 1.2, 2.4])
    site = c1.selectbox("현장", ["전체"] + sites, key="ledger_site")
    account = c2.selectbox("계정과목", ["전체"] + d.ACCOUNT_NAMES, key="ledger_acc")
    status = c3.selectbox("상태", ["보유 자산", "전체"] + d.ASSET_STATUSES, key="ledger_status")
    query = c4.text_input("검색", placeholder="태그번호·품명·규격·시리얼·사용자", key="ledger_q").strip().lower()

    assets = d.active_assets() if status == "보유 자산" else d.get_assets()
    if status not in ("보유 자산", "전체"):
        assets = [a for a in assets if a["상태"] == status]
    if site != "전체":
        assets = [a for a in assets if a["현장"] == site]
    if account != "전체":
        assets = [a for a in assets if a["계정과목"] == account]
    if query:
        assets = [a for a in assets if any(query in str(a[k]).lower() for k in ("태그번호", "품명", "규격", "시리얼번호", "사용자", "관리부서", "설치위치"))]

    total_cost = sum(a["취득가액"] or 0 for a in assets)
    st.markdown(f"**{len(assets):,}개** · 취득가액 {ui.won(total_cost)} · 장부가액 {ui.won(sum(d.book_value(a) for a in assets))}")
    if not assets:
        st.info("조건에 맞는 자산이 없습니다.")
        return
    page = ui.paginate(assets, f"ledger_page_{site}_{account}_{status}_{query}")
    df = ui.asset_frame(page)
    event = st.dataframe(df, hide_index=True, width="stretch", column_config=ui.ASSET_COLUMN_CONFIG,
                         on_select="rerun", selection_mode="multi-row", key=f"ledger_table_{site}_{account}_{status}", height=430)
    selected = [df.iloc[i]["태그번호"] for i in event.selection.rows if i < len(df)]
    st.caption(f"선택 {len(selected)}개" if selected else "표 왼쪽 칸을 눌러 자산을 선택하세요.")

    c1, c2, c3, c4 = st.columns(4)
    if c1.button("🔍 상세 / 편집", disabled=len(selected) != 1, width="stretch"):
        wf.asset_dialog(selected[0], wf.ADMIN, None, actor)
    if c2.button("🔄 이동 신청", disabled=not selected, width="stretch"):
        wf.dlg_new_transfer(selected, actor)
    if c3.button("🗑 처분 신청", disabled=not selected, width="stretch"):
        wf.dlg_new_disposal(selected, actor)
    with c4:
        targets = [a for a in page if a["태그번호"] in selected] if selected else assets
        if st.button(f"🏷️ QR 라벨 ({len(targets):,}개)", width="stretch", key="ledger-label-make",
                     help=f"선택한 자산, 선택이 없으면 검색 결과 전체(최대 {ui.LABEL_MAX}개)"):
            st.session_state["ledger_label_tags"] = [a["태그번호"] for a in targets]
        if st.session_state.get("ledger_label_tags"):
            label_assets = [a for a in (d.get_asset(t) for t in st.session_state["ledger_label_tags"]) if a]
            ui.label_download(label_assets, key="ledger-label-dl", label="⬇️ 라벨 PDF 받기")

    cols = ["태그번호", "품명", "규격", "시리얼번호", "계정과목", "자산구분", "현장", "관리부서", "사용자", "설치위치",
            "취득일자", "취득가액", "내용연수", "상각방법", "장부가액", "상태", "공급업체", "처분일자", "처분방법", "처분금액",
            "처분손익", "연결차량번호", "비고"]
    ui.export_panel("ledger-export", f"자산대장_{date.today():%Y%m%d}",
                    lambda: {"자산대장": (cols, [{**a, "장부가액": round(d.book_value(a))} for a in assets])}, len(assets))


# =========================================================
# 자산 등록
# =========================================================
def register(actor: str):
    st.title("➕ 자산 등록")
    st.caption("기존 보유 자산을 대장에 올리거나, 엑셀로 한꺼번에 등록합니다. 새로 사는 자산은 구매요청 → 검수 후 결재함에서 등록됩니다.")
    new_tags = st.session_state.get("new_tags")
    if new_tags:
        with st.container(border=True):
            st.success(f"방금 등록한 자산 {len(new_tags)}개: {', '.join(new_tags[:10])}{' …' if len(new_tags) > 10 else ''}")
            c1, c2 = st.columns([2, 1])
            with c1:
                ui.label_download([a for a in (d.get_asset(t) for t in new_tags[:ui.LABEL_MAX]) if a], key="new-tags-label")
            if c2.button("닫기", width="stretch", key="new-tags-close"):
                st.session_state.pop("new_tags", None)
                st.rerun()

    tabs = st.tabs(["✍️ 개별 등록", "📤 엑셀 일괄 등록", "🚗 법인차량 연동"])
    with tabs[0]:
        if not d.site_names():
            st.warning("먼저 설정에서 현장을 등록하세요.")
        else:
            fields = wf.asset_form("register-form", {}, submit="💾 등록하고 태그 발급", show_qty=True)
            if fields is not None:
                qty = fields.pop("_qty", 1)
                tags = ui.run_action(d.register_assets, fields, qty, actor)
                if tags:
                    st.session_state["new_tags"] = tags
                    ui.flash(f"{len(tags)}개 자산을 등록했습니다.")
                    st.rerun()

    with tabs[1]:
        st.markdown("#### 1. 양식 내려받기")
        template = pd.DataFrame([{"품명": "노트북", "규격": "LG gram 16", "시리얼번호": "SN123456", "계정과목": "비품",
                                  "현장": (d.site_names() or ["본사"])[0], "관리부서": "경영지원팀", "사용자": "홍길동",
                                  "설치위치": "3층", "취득일자": date.today(), "취득가액": 1890000, "내용연수": 5,
                                  "상각방법": "정률", "잔존가액": 0, "공급업체": "OO상사", "상태": "사용중", "비고": ""}],
                                columns=d.IMPORT_TEMPLATE_COLS)
        guide = pd.DataFrame({"항목": ["계정과목", "현장", "상태", "상각방법", "내용연수", "취득일자"],
                              "입력 값": [", ".join(d.ACCOUNT_NAMES), ", ".join(d.site_names()), "사용중, 유휴, 수리중",
                                        "정률 또는 정액 (비우면 계정 기본값)", "숫자(년). 비우면 계정 기본값", "YYYY-MM-DD"]})
        st.download_button("📄 일괄 등록 양식(xlsx)", ui.excel_bytes({"자산등록": template, "입력안내": guide}),
                           file_name="자산_일괄등록_양식.xlsx")
        st.markdown("#### 2. 작성한 파일 올리기")
        up = st.file_uploader("자산 일괄등록 엑셀", type=["xlsx"], key="import-upload")
        if up is not None:
            try:
                rows = d.read_upload_rows(up)
            except Exception as exc:
                st.error(f"파일을 읽지 못했습니다: {exc}")
                rows = []
            rows = [r for r in rows if d.clean_str(r.get("품명"))]
            if rows:
                st.dataframe(pd.DataFrame(rows[:1000]), hide_index=True, width="stretch")
                if len(rows) > 1000:
                    st.caption(f"미리보기는 1,000행까지 보여 줍니다 (전체 {len(rows):,}행).")
                if st.button(f"📥 {len(rows):,}개 등록", type="primary", key="import-go"):
                    with st.spinner("등록하는 중입니다..."):
                        result = ui.run_action(d.import_assets_from_rows, rows, actor)
                    if result:
                        tags, errors = result
                        if errors:
                            st.error(f"등록하지 않았습니다. 아래 {len(errors):,}개 행을 고친 뒤 다시 올려 주세요.")
                            for e in errors[:50]:
                                st.write("• " + e)
                        else:
                            st.session_state["new_tags"] = tags
                            ui.flash(f"{len(tags):,}개 자산을 일괄 등록했습니다.")
                            st.rerun()
            else:
                st.warning("'품명'이 들어 있는 행이 없습니다. 양식의 첫 행 머리글을 그대로 두세요.")

    with tabs[2]:
        vehicle_sync(actor)


def vehicle_sync(actor: str):
    st.markdown("#### 🚗 법인차량 관리 프로그램 연동")
    st.caption("차량목록.xlsx의 '구매' 차량(임원용)을 차량운반구 자산으로 등록·갱신합니다. 렌트 차량은 회사 소유가 아니므로 자산대장에 넣지 않습니다.")
    with st.container(border=True):
        c1, c2 = st.columns([3, 1.3])
        c1.markdown("**차량목록.xlsx 샘플 양식**  \n법인차량 관리 프로그램과 같은 20개 열(차량번호 ~ 차량 구매 비용)에 구매·렌트 예시 4대와 작성 안내 시트가 들어 있습니다. "
                    "법인차량 프로그램의 차량목록.xlsx로 그대로 써도 됩니다.")
        c2.download_button("📄 차량목록 샘플 양식 받기", d.vehicle_template_bytes(), file_name="차량목록_샘플양식.xlsx",
                           width="stretch", type="primary")
    settings = d.get_settings()
    c1, c2 = st.columns([4, 1])
    path = c1.text_input("차량목록.xlsx 경로", value=settings.get("차량목록 경로", ""),
                         placeholder=r"예: C:\법인차량관리\차량목록.xlsx", key="veh-path")
    if c2.button("경로 저장", width="stretch"):
        if ui.run_action(d.save_settings, {"차량목록 경로": path}, success="차량목록 경로를 저장했습니다."):
            st.rerun()
    up = st.file_uploader("또는 차량목록.xlsx 파일 올리기", type=["xlsx"], key="veh-upload")
    source = up if up is not None else (path.strip() or None)
    if not source:
        st.info("경로를 입력하거나 파일을 올리면 미리보기가 나옵니다.")
        return
    try:
        vehicles = d.read_vehicle_file(source)
    except d.DataError as exc:
        st.error(str(exc))
        return
    except Exception as exc:
        st.error(f"차량목록을 읽지 못했습니다: {exc}")
        return
    owned = [v for v in vehicles if d.clean_str(v.get("구분")) == "구매"]
    linked = {a["연결차량번호"] for a in d.get_assets() if a["연결차량번호"]}
    k = st.columns(4)
    with k[0]: ui.kpi("차량 전체", len(vehicles), "차량목록 기준", unit="대")
    with k[1]: ui.kpi("구매(임원용)", len(owned), "자산 등록 대상", unit="대")
    with k[2]: ui.kpi("렌트(업무용)", len(vehicles) - len(owned), "자산 아님 · 제외", unit="대")
    with k[3]: ui.kpi("이미 연동됨", sum(1 for v in owned if d.clean_str(v.get("차량번호")) in linked), "다시 동기화하면 현장·사용자·상태 갱신", unit="대")
    preview = pd.DataFrame([{"차량번호": d.clean_str(v.get("차량번호")), "차종": d.clean_str(v.get("차종")), "현장": d.clean_str(v.get("현장")),
                             "사용자": d.clean_str(v.get("사용자")), "상태": d.clean_str(v.get("상태")),
                             "구매일": d.to_date(v.get("차량 구매일")), "구매 비용": d.to_num(v.get("차량 구매 비용"), 0),
                             "연동": "연동됨" if d.clean_str(v.get("차량번호")) in linked else "신규"} for v in owned])
    if not preview.empty:
        st.dataframe(preview, hide_index=True, width="stretch", column_config=ui.money_config("구매 비용"))
    if st.button("🔄 구매 차량을 자산대장에 동기화", type="primary", disabled=not owned):
        result = ui.run_action(d.sync_vehicles, vehicles, actor)
        if result:
            msg = f"신규 등록 {len(result['added'])}대 · 갱신 {len(result['updated'])}대 · 렌트 제외 {result['rent']}대"
            if result["new_sites"]:
                msg += f" · 새 현장 추가: {', '.join(result['new_sites'])}"
            ui.flash(msg)
            st.rerun()


# =========================================================
# 결재함
# =========================================================
def inbox(actor: str):
    st.title("✅ 결재함")
    st.caption("구매요청 → 견적 → 발주 → 검수 → 등록 / 이동 승인·인수 / 사고 조사·종결 / 처분 승인·집행·제적을 처리합니다.")
    pending = wf.pending_for(wf.ADMIN)
    icons = {"pr": "🛒", "move": "🔄", "inc": "⚠️", "dsp": "🗑"}
    tabs = st.tabs([f"{icons[k]} {d.KIND_NAMES[k]} ({len(pending[k])})" for k in d.REQUEST_TABLES])
    for tab, kind in zip(tabs, d.REQUEST_TABLES):
        with tab:
            if kind == "pr":
                with st.expander("📝 관리자가 직접 구매요청 작성"):
                    wf.purchase_form("admin-pr-form", d.site_names(), actor)
            wf.render_request_list(kind, wf.ADMIN, None, actor, key=f"inbox-{kind}")


# =========================================================
# 재물조사
# =========================================================
def audit(actor: str):
    st.title("🔍 재물조사")
    st.caption("장부상 수량과 실물이 일치하는지 확인합니다. 통상 연 1회 정기 조사를 하고, 필요할 때 수시 조사를 합니다.")
    current = d.open_audit()
    if current:
        wf.render_audit_workspace(current, wf.ADMIN, None, actor, key="admin-audit")
        st.divider()
        with st.container(border=True):
            st.markdown("**🏁 조사 마감**")
            st.caption("마감하면 유휴로 체크한 '사용중' 자산은 '유휴'로 바뀌어 재배치 대상에 오르고, 결과가 자산 이력에 남습니다. 미확인 자산은 결과 없이 남습니다.")
            ok = st.checkbox("조사 결과를 확인했고 마감합니다", key="audit-close-ok")
            if st.button("조사 마감", type="primary", disabled=not ok):
                with st.spinner("마감하는 중입니다..."):
                    stats = ui.run_action(d.close_audit, current["회차번호"], actor)
                if stats:
                    ui.flash(f"재물조사를 마감했습니다. 확인 {stats['found']:,} · 미발견 {stats['missing']:,} · 유휴 {stats['idle']:,}")
                    st.rerun()
    else:
        with st.container(border=True):
            st.markdown("**새 재물조사 시작**")
            with st.form("audit-start"):
                c1, c2, c3 = st.columns([2, 1, 1])
                name = c1.text_input("회차 이름", value=f"{date.today().year} {'상반기' if date.today().month <= 6 else '하반기'} 정기 재물조사")
                base = c2.date_input("기준일", value=date.today())
                scope = c3.selectbox("대상", ["전체"] + d.site_names())
                if st.form_submit_button("🔍 조사 시작", type="primary", width="stretch"):
                    no = ui.run_action(d.start_audit, name, base, scope, actor)
                    if no:
                        ui.flash(f"{no} 재물조사를 시작했습니다. 현장 담당자 화면에서도 스캔·확인할 수 있습니다.")
                        st.rerun()
    audits = [a for a in d.get_audits() if a["상태"] == "완료"]
    if audits:
        st.markdown("### 📚 지난 조사")
        df = pd.DataFrame(audits)[["회차번호", "회차명", "기준일", "대상", "장부수량", "확인", "미발견", "유휴", "마감일시"]]
        st.dataframe(df, hide_index=True, width="stretch")
        pick = st.selectbox("결과 내려받기", [a["회차번호"] for a in audits],
                            format_func=lambda n: next(f"{a['회차번호']} · {a['회차명']}" for a in audits if a["회차번호"] == n))
        cols = d.TABLES["audit_items"]["cols"]
        ui.export_panel(f"audit-export-{pick}", f"재물조사_{pick}", lambda: {"조사결과": (cols, d.get_audit_items(pick))},
                        next(a["장부수량"] for a in audits if a["회차번호"] == pick) or 0)


# =========================================================
# 감가상각 · 결산
# =========================================================
def depreciation(actor: str):
    st.title("📉 감가상각 · 결산")
    st.caption("세법·회계기준에 따라 정액법·정률법으로 월할 상각합니다. 정률법 상각률은 잔존가치 5% 기준(5년 0.451), "
               "내용연수가 끝나면 유형자산은 비망가액 1,000원을 남깁니다. 소모품은 취득 시 비용 처리되어 제외됩니다.")
    today = date.today()
    c1, c2, c3 = st.columns(3)
    year = c1.selectbox("연도", list(range(today.year, today.year - 10, -1)), key="dep_year")
    month = c2.selectbox("결산월", list(range(1, 13)), index=today.month - 1 if year == today.year else 11, key="dep_month",
                         format_func=lambda m: f"{m}월")
    site = c3.selectbox("현장", ["전체"] + d.site_names(), key="dep_site")
    with st.spinner("감가상각을 계산하는 중입니다..."):
        rows = d.depreciation_schedule(year, month, None if site == "전체" else site)
    key = f"{year}-{month:02d}"
    closed = d.lookup("closings", key)

    total = lambda k: sum(r[k] for r in rows)
    k = st.columns(5)
    with k[0]: ui.kpi("상각 대상", f"{len(rows):,}", "소모품 제외 · 당기 처분분 포함", unit="개")
    with k[1]: ui.kpi("기초 장부가", ui.short_won(total("기초 장부가")), f"{year - 1}년 말", unit="원")
    with k[2]: ui.kpi(f"당기 상각비 (1~{month}월)", ui.short_won(total("당기 상각비")), ui.won(total("당기 상각비")), unit="원")
    with k[3]: ui.kpi("상각누계액", ui.short_won(total("상각누계액")), f"{key} 말", unit="원")
    with k[4]: ui.kpi("기말 장부가", ui.short_won(total("기말 장부가")), "마감됨" if closed else "미마감", "ok" if closed else "", "원")

    if not rows:
        st.info("상각 대상 자산이 없습니다.")
    else:
        df = pd.DataFrame(rows)
        by_acc = df.groupby("계정과목", sort=False).agg(자산수=("태그번호", "count"), 취득가액=("취득가액", "sum"),
                                                       기초장부가=("기초 장부가", "sum"), 당기취득=("당기 취득", "sum"),
                                                       당기상각비=("당기 상각비", "sum"), 월상각비=("월 상각비", "sum"),
                                                       상각누계액=("상각누계액", "sum"), 기말장부가=("기말 장부가", "sum")).reset_index()
        by_site = df.groupby("현장", sort=False).agg(자산수=("태그번호", "count"), 취득가액=("취득가액", "sum"),
                                                   당기상각비=("당기 상각비", "sum"), 기말장부가=("기말 장부가", "sum")).reset_index()
        money = ui.money_config("취득가액", "기초장부가", "당기취득", "당기상각비", "월상각비", "상각누계액", "기말장부가",
                                "기초 장부가", "당기 취득", "당기 상각비", "월 상각비", "기말 장부가")
        tabs = st.tabs(["계정과목별", "현장별", "자산별 명세", f"{year}년 월별 상각비"])
        with tabs[0]:
            st.dataframe(by_acc.round(0), hide_index=True, width="stretch", column_config=money)
        with tabs[1]:
            st.dataframe(by_site.round(0), hide_index=True, width="stretch", column_config=money)
        with tabs[2]:
            page = ui.paginate(rows, f"dep_page_{key}_{site}")
            st.dataframe(pd.DataFrame(page).round(0), hide_index=True, width="stretch", column_config=money, height=420)
        with tabs[3]:
            if st.toggle("월별 상각비 계산하기", key="dep_monthly", help="자산이 많으면 몇 초 걸립니다"):
                monthly = []
                for m in range(1, 13):
                    if date(year, m, 1) > today:
                        break
                    sched = d.depreciation_schedule(year, m, None if site == "전체" else site)
                    monthly.append({"월": f"{m:02d}월", "상각비(백만원)": round(sum(r["월 상각비"] for r in sched) / 1e6, 1)})
                if monthly:
                    st.bar_chart(pd.DataFrame(monthly), x="월", y="상각비(백만원)", height=300)
        detail_cols = list(rows[0].keys())
        acc_cols = list(by_acc.columns)
        site_cols = list(by_site.columns)
        ui.export_panel(f"dep-export-{key}-{site}", f"고정자산명세서_{key}",
                        lambda: {"고정자산명세": (detail_cols, [{k2: (round(v) if isinstance(v, float) else v) for k2, v in r.items()} for r in rows]),
                                 "계정과목별": (acc_cols, by_acc.round(0).to_dict("records")),
                                 "현장별": (site_cols, by_site.round(0).to_dict("records"))}, len(rows))

    st.divider()
    st.markdown("### 🔒 결산 마감")
    if closed:
        st.success(f"{key} 결산이 {closed['마감일시']}에 마감되었습니다 ({closed['마감자']}).")
    else:
        st.caption("재무팀과 결산할 때 마감하면 그 시점의 고정자산 명세(전체 현장 기준)가 별도로 보관됩니다.")
        ok = st.checkbox(f"{key} 고정자산 명세를 확인했습니다", key="close-ok")
        if st.button(f"🔒 {key} 결산 마감", type="primary", disabled=not ok):
            with st.spinner("마감 명세를 저장하는 중입니다..."):
                if ui.run_action(d.close_period, year, month, actor, success=f"{key} 결산을 마감했습니다."):
                    st.rerun()
    closings = d.get_closings()
    if closings:
        st.dataframe(pd.DataFrame(closings), hide_index=True, width="stretch",
                     column_config=ui.money_config("취득가액", "당기상각비", "상각누계액", "장부가액"))
        pick = st.selectbox("마감 명세 내려받기", [c["결산월"] for c in closings], key="closing-pick")
        cols = d.TABLES["closing_items"]["cols"]
        count = next(c["자산수"] for c in closings if c["결산월"] == pick) or 0
        ui.export_panel(f"closing-export-{pick}", f"결산마감명세_{pick}", lambda: {f"{pick} 명세": (cols, d.closing_items(pick))}, count)


# =========================================================
# 처분 검토 · 유휴 자산
# =========================================================
def disposal_and_idle(actor: str):
    st.title("♻️ 처분 검토 · 유휴 자산")
    st.caption("이미 폐기·매각된 자산은 '🗑 폐기·처분 자산' 메뉴에서 봅니다.")
    candidates = d.disposal_candidates()
    idle = [a for a in d.active_assets() if a["상태"] == "유휴"]
    tabs = st.tabs([f"♻️ 처분 검토 대상 ({len(candidates):,})", f"💤 유휴 자산 재배치 ({len(idle):,})"])
    with tabs[0]:
        st.caption("내용연수가 지났거나, 수리비가 장부가보다 크거나, 유휴 상태로 만료가 1년 안에 오는 자산입니다.")
        if not candidates:
            st.success("지금은 처분 검토 대상이 없습니다.")
        else:
            c1, c2 = st.columns(2)
            site = c1.selectbox("현장", ["전체"] + d.site_names(), key="cand-site")
            acc = c2.selectbox("계정과목", ["전체"] + d.ACCOUNT_NAMES, key="cand-acc")
            rows = [a for a in candidates if (site == "전체" or a["현장"] == site) and (acc == "전체" or a["계정과목"] == acc)]
            page = ui.paginate(rows, f"cand-page-{site}-{acc}", page_size=500)
            df = ui.asset_frame(page, extra=["검토사유"])
            ev = st.dataframe(df, hide_index=True, width="stretch", column_config=ui.ASSET_COLUMN_CONFIG,
                              on_select="rerun", selection_mode="multi-row", key=f"cand-table-{site}-{acc}")
            sel = [df.iloc[i]["태그번호"] for i in ev.selection.rows if i < len(df)]
            if st.button(f"🗑 선택한 {len(sel)}개 처분 신청", type="primary", disabled=not sel):
                wf.dlg_new_disposal(sel, actor)
    with tabs[1]:
        st.caption("재물조사나 현장 담당자가 유휴로 표시한 자산입니다. 필요한 현장으로 재배치하면 구매 비용을 줄일 수 있습니다.")
        if not idle:
            st.success("유휴 자산이 없습니다.")
        else:
            st.caption(f"유휴 자산 장부가 합계 {ui.won(sum(d.book_value(a) for a in idle))}")
            page = ui.paginate(idle, "idle-page", page_size=500)
            df = ui.asset_frame(page)
            ev = st.dataframe(df, hide_index=True, width="stretch", column_config=ui.ASSET_COLUMN_CONFIG,
                              on_select="rerun", selection_mode="multi-row", key="idle-table")
            sel = [df.iloc[i]["태그번호"] for i in ev.selection.rows if i < len(df)]
            if st.button(f"🔄 선택한 {len(sel)}개 재배치(이동 신청)", type="primary", disabled=not sel):
                wf.dlg_new_transfer(sel, actor)


def disposed(actor: str):
    st.title("🗑 폐기·처분 자산")
    st.caption("폐기·매각·기증·사내 경매·망실로 장부에서 제적된 자산입니다. 처분일자 최신 순이며, 연도·방법·현장으로 걸러 볼 수 있습니다.")
    wf.render_disposed_list("admin-disposed", actor, wf.ADMIN)


# =========================================================
# 설정
# =========================================================
def settings(actor: str):
    st.title("⚙️ 설정")
    st.markdown("### 🏢 현장·부서와 자산 담당자")
    st.caption("행을 추가·수정한 뒤 저장하세요. 보유 자산이 남아 있는 현장은 삭제할 수 없습니다. 담당자는 현장 담당자 화면에서 자기 현장을 고르고 이름을 입력해 사용합니다.")
    sites = d.get_sites()
    cols = d.TABLES["sites"]["cols"]
    df = pd.DataFrame(sites, columns=cols) if sites else pd.DataFrame(columns=cols)
    counts = {}
    for a in d.active_assets():
        counts[a["현장"]] = counts.get(a["현장"], 0) + 1
    df["보유 자산"] = df["현장명"].map(lambda s: counts.get(s, 0))
    edited = st.data_editor(df, num_rows="dynamic", hide_index=True, width="stretch", key="sites-editor",
                            disabled=["보유 자산"],
                            column_config={"구분": st.column_config.SelectboxColumn("구분", options=["본사", "현장", "지사", "부서"]),
                                           "표시순서": st.column_config.NumberColumn("표시순서", step=1)})
    if st.button("💾 현장 목록 저장", type="primary"):
        rows = [{k: v for k, v in r.items() if k != "보유 자산"} for r in edited.to_dict("records") if d.clean_str(r.get("현장명"))]
        if ui.run_action(d.save_sites, rows, success="현장 목록을 저장했습니다."):
            st.rerun()

    st.markdown("### 🔧 환경 설정")
    values = d.get_settings()
    with st.form("settings-form"):
        new = {}
        for key, (_, desc) in d.DEFAULT_SETTINGS.items():
            if key == "관리자 PIN":
                new[key] = st.text_input(key, value=values.get(key, ""), type="password", help=desc)
            else:
                new[key] = st.text_input(key, value=values.get(key, ""), help=desc)
        if st.form_submit_button("💾 설정 저장", type="primary"):
            if d.to_num(new["자본화 기준금액"]) is None:
                st.error("자본화 기준금액은 숫자로 입력하세요.")
            elif ui.run_action(d.save_settings, new, success="설정을 저장했습니다."):
                st.rerun()

    st.markdown("### 💾 데이터 내보내기 · 백업")
    st.caption(f"데이터는 {d.DB_FILE} 한 파일(SQLite)에 저장됩니다. 보유·처분 자산이 수십만 개여도 빠르게 저장·조회하기 위해서입니다. "
               "엑셀이 필요하면 아래에서 표를 골라 내보내세요.")
    labels = {t: f"{spec['label']} ({d.table_count(t):,}행)" for t, spec in d.TABLES.items()}
    table = st.selectbox("내보낼 표", list(labels), format_func=lambda t: labels[t], key="export-table")
    ui.export_panel(f"table-export-{table}", f"{d.TABLES[table]['label']}_{date.today():%Y%m%d}",
                    lambda: {d.TABLES[table]["label"]: (d.TABLES[table]["cols"], d.table_rows(table))}, d.table_count(table))
    c1, c2 = st.columns([1, 2])
    if c1.button("🗄 DB 백업 파일 만들기", width="stretch"):
        with st.spinner("백업 파일을 만드는 중입니다..."):
            st.session_state["db-backup"] = d.backup_db_bytes()
    if st.session_state.get("db-backup"):
        blob = st.session_state["db-backup"]
        c2.download_button(f"⬇️ 자산관리_백업_{date.today():%Y%m%d}.db ({len(blob) / 1e6:.0f}MB)", blob,
                           file_name=f"자산관리_백업_{date.today():%Y%m%d}.db", width="stretch")
    st.caption("복원하려면 프로그램을 끈 뒤 백업 파일 이름을 '자산관리.db'로 바꿔 data 폴더에 덮어쓰세요.")

    st.markdown("### 🧪 예시 데이터")
    c1, c2 = st.columns([2, 1])
    if d.has_sample_data():
        c1.info(f"예시 데이터가 들어 있습니다 (보유 {sum(1 for a in d.active_assets() if d.SAMPLE_MARK in a['비고']):,}개 · "
                f"처분 {sum(1 for a in d.closed_assets() if d.SAMPLE_MARK in a['비고']):,}개). 실제 운영 전에 삭제하세요.")
        if c2.button("🧹 예시 데이터 삭제", width="stretch"):
            with st.spinner("예시 데이터를 지우는 중입니다..."):
                n = ui.run_action(d.clear_sample_data)
            if n is not None:
                ui.flash(f"예시 자산 {n:,}개와 관련 요청·조사·이력을 삭제했습니다.")
                st.rerun()
    else:
        c1.caption("보유 자산 약 2만 개(현장 4곳), 폐기·매각·기증·경매·망실로 처분된 자산 약 18만 개와 처분 요청서, "
                   "진행 중인 구매·이동·사고·처분 요청과 재물조사를 만듭니다. 모든 예시 자산 비고에 [예시]가 붙습니다. 20~40초 걸립니다.")
        if c2.button("🧪 예시 데이터 만들기", width="stretch", type="primary"):
            bar = st.progress(0.0, text="준비하는 중")
            result = ui.run_action(d.create_sample_data, actor, progress=lambda p, t: bar.progress(min(1.0, p), text=t))
            if result:
                ui.flash(f"예시 데이터를 만들었습니다: 보유 자산 {result['active']:,}개 · 처분 자산 {result['closed']:,}개 · 처분 요청서 {result['dsp']:,}건")
                st.rerun()
