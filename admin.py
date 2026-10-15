"""
관리 화면 (관리자 · 임원 · 재무 · 현장)

법인차량 관리 AI의 관리자 화면 구성을 따릅니다.
제목·기준일 → KPI 카드 → 탭으로 나눈 현황표 → 관리 탭 → 승인/반려 카드.
메뉴는 app.py가 역할에 맞게 왼쪽에 보여 주고, 각 화면은 지금 고른 사용자(u)로 권한을 확인합니다.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

import auth
import data as d
import ops
import ui
import workflow as wf
from auth import ADMIN, EXEC, FIN, SITE_ROLES

LIVE_REFRESH_SECONDS = 15
ON_CLOUD = d.ON_CLOUD  # 공개 데모(Streamlit Community Cloud)에서 실행 중인지


def live_refresh_fragment(func):
    fragment = getattr(st, "fragment", None)
    if fragment is None:
        return func
    return fragment(run_every=f"{LIVE_REFRESH_SECONDS}s")(func)


def is_site_role(u: dict) -> bool:
    return u.get("역할") in SITE_ROLES


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
def dashboard_body(u: dict):
    assets = d.active_assets()
    cost = sum(a["취득가액"] or 0 for a in assets)
    nbv = sum(d.book_value(a) for a in assets)
    pending = wf.pending_for(u)
    pending_n = sum(len(v) for v in pending.values()) + len(wf.pending_rentals(u))
    expired = sum(1 for a in assets if (d.life_remaining_months(a) or 1) <= 0)
    idle = sum(1 for a in assets if a["상태"] == "유휴")
    closed_n = len(d.closed_assets())
    alerts = ops.alerts_for(u, pending)
    crit = sum(1 for a in alerts if a["심각도"] == "crit")

    k = st.columns(4) + st.columns(4)[:3]  # 7개 카드를 두 줄(4 + 3)로
    with k[0]: ui.kpi("보유 자산", f"{len(assets):,}", f"{len(d.site_names())}개 현장·부서", unit="개")
    with k[1]: ui.kpi("취득가액", ui.short_won(cost), ui.won(cost), unit="원")
    with k[2]: ui.kpi("장부가액", ui.short_won(nbv), f"상각누계 {ui.short_won(cost - nbv)}원", unit="원")
    with k[3]: ui.kpi("내 결재 대기", pending_n, "승인·투표·견적·등록·제적", "warn" if pending_n else "", "건")
    with k[4]: ui.kpi("긴급 알림", crit, f"전체 알림 {len(alerts)}건", "crit" if crit else "", "건")
    with k[5]: ui.kpi("내용연수 만료 · 유휴", f"{expired:,} · {idle:,}", "처분 검토 · 재배치 대상", "warn" if expired or idle else "", "개")
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
                           file_name=f"현장별_{criterion}_현황_{d.today():%Y%m%d}.xlsx", width="stretch")
        by_site = {}
        for a in assets:
            by_site[a["현장"]] = by_site.get(a["현장"], 0) + 1
        for site in d.site_names():
            st.caption(f"{site}: {by_site.get(site, 0):,}개")

    c1, c2 = st.columns([1.3, 1])
    with c1:
        st.markdown("## 🔔 알림")
        ui.alert_list(alerts, key="dash-alert", limit=8)
        ui.page_button("🔔 알림 전체 보기", "alerts", key="dash-alerts-all")
    with c2:
        st.markdown(f"## 💰 {d.today().year}년 예산")
        rows = [b for b in ops.budget_status(d.today().year) if b["예산"]]
        if rows:
            df = pd.DataFrame(rows)[["현장", "예산", "집행", "결재 중", "잔액", "집행률(%)"]]
            st.dataframe(df, hide_index=True, width="stretch", column_config=ui.money_config("예산", "집행", "결재 중", "잔액"))
        else:
            st.caption("등록된 예산이 없습니다. '💰 예산' 메뉴에서 현장별 연간 예산을 입력하세요.")

    st.markdown("## ⏳ 내 처리 대기")
    cols = st.columns(5)
    for col, kind in zip(cols, d.REQUEST_TABLES):
        with col:
            st.markdown(f"<div class='todo-card'><div class='small-muted'>{d.KIND_NAMES[kind]}</div><b>{len(pending[kind])}</b>건</div>",
                        unsafe_allow_html=True)
    with cols[4]:
        st.markdown(f"<div class='todo-card'><div class='small-muted'>장비 대여</div><b>{len(wf.pending_rentals(u))}</b>건</div>",
                    unsafe_allow_html=True)
    if pending_n:
        ui.page_button("✅ 결재함으로 이동", "inbox", key="dash-inbox", type="primary")

    st.markdown("## 🕘 최근 변동 이력")
    hist = d.get_history(limit=12)
    if hist:
        df = pd.DataFrame(hist)[["일시", "태그번호", "구분", "내용", "처리자"]]
        df["처리자"] = df["처리자"].str.replace(d.SAMPLE_MARK + " ", "", regex=False)
        st.dataframe(df, hide_index=True, width="stretch")
    else:
        st.caption("아직 이력이 없습니다.")


def dashboard(u: dict):
    st.title("🏷️ 자산관리 AI")
    st.caption(f"기준일: {d.today():%Y-%m-%d} · {u['이름']}님({u['역할']}) · 장부가액은 오늘 기준 감가상각을 반영합니다 · "
               f"{LIVE_REFRESH_SECONDS}초마다 자동 갱신")
    dashboard_body(u)


# =========================================================
# 자산대장
# =========================================================
def ledger(u: dict):
    site_role = is_site_role(u)
    st.title("📋 자산대장" if not site_role else f"📋 {u['현장']} 자산대장")
    st.caption("행을 선택하면 상세·작업, 이동·처분 신청, 일괄 수정, QR 라벨 출력을 할 수 있습니다. 목록은 1,000개씩 나눠 보여 줍니다.")
    sites = d.site_names()
    c1, c2, c3, c4 = st.columns([1.2, 1.2, 1.2, 2.4])
    if site_role:
        site = c1.selectbox("현장", [u["현장"], "다른 현장 유휴 자산"], key="ledger_site_scoped")
    else:
        site = c1.selectbox("현장", ["전체"] + sites, key="ledger_site")
    account = c2.selectbox("계정과목", ["전체"] + d.ACCOUNT_NAMES, key="ledger_acc")
    status = c3.selectbox("상태", ["보유 자산", "전체"] + d.ASSET_STATUSES + ["공용 장비"], key="ledger_status")
    query = c4.text_input("검색", placeholder="태그번호·품명·규격·시리얼·사용자", key="ledger_q").strip().lower()

    if site == "다른 현장 유휴 자산":
        assets = [a for a in d.active_assets() if a["상태"] == "유휴" and a["현장"] != u["현장"]]
    else:
        assets = d.active_assets() if status in ("보유 자산", "공용 장비") else d.get_assets()
        if site != "전체":
            assets = [a for a in assets if a["현장"] == site]
    if status == "공용 장비":
        assets = [a for a in assets if a["공용"] == "Y"]
    elif status not in ("보유 자산", "전체"):
        assets = [a for a in assets if a["상태"] == status]
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

    sel_assets = [a for a in page if a["태그번호"] in selected]
    can_manage = bool(sel_assets) and all(wf.manages(u, a["현장"]) for a in sel_assets)
    can_request = u.get("역할") in (ADMIN,) + SITE_ROLES
    c1, c2, c3, c4, c5 = st.columns(5)
    if c1.button("🔍 상세 · 작업", disabled=len(selected) != 1, width="stretch"):
        wf.asset_dialog(selected[0], u)
    if can_request and c2.button("🔄 이동 신청", disabled=not selected, width="stretch",
                                 help="다른 현장 자산을 고르면 우리 현장으로 받는 신청이 됩니다"):
        wf.dlg_new_transfer(selected, u, default_to=u.get("현장") if site_role and not can_manage else None)
    if c3.button("🗑 처분 신청", disabled=not can_manage, width="stretch", help="관리 권한이 있는 자산만 신청할 수 있습니다"):
        wf.dlg_new_disposal(selected, u)
    if c4.button("✏️ 일괄 수정", disabled=not can_manage, width="stretch", help="부서·사용자·위치·상태·공용·보증일·세무 상각 등을 한 번에"):
        wf.dlg_bulk_edit(selected, u)
    with c5:
        targets = sel_assets or assets
        if st.button(f"🏷️ QR 라벨 ({len(targets):,}개)", width="stretch", key="ledger-label-make",
                     help=f"선택한 자산, 선택이 없으면 검색 결과 전체(최대 {ui.LABEL_MAX}개)"):
            st.session_state["ledger_label_tags"] = [a["태그번호"] for a in targets]
        if st.session_state.get("ledger_label_tags"):
            label_assets = [a for a in (d.get_asset(t) for t in st.session_state["ledger_label_tags"]) if a]
            ui.label_download(label_assets, key="ledger-label-dl", label="⬇️ 라벨 PDF 받기")

    cols = ["태그번호", "품명", "규격", "시리얼번호", "계정과목", "자산구분", "현장", "관리부서", "사용자", "사용자사번", "설치위치",
            "취득일자", "취득가액", "내용연수", "상각방법", "세무 내용연수", "세무 상각방법", "장부가액", "상태", "공용", "보증만료일",
            "공급업체", "처분일자", "처분방법", "처분금액", "처분손익", "연결차량번호", "비고"]
    ui.export_panel("ledger-export", f"자산대장_{d.today():%Y%m%d}",
                    lambda: {"자산대장": (cols, [{**a, "장부가액": round(d.book_value(a))} for a in assets])}, len(assets))


# =========================================================
# 자산 등록
# =========================================================
def register(u: dict):
    actor = auth.actor(u)
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
                                  "설치위치": "3층", "취득일자": d.today(), "취득가액": 1890000, "내용연수": 5,
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
        vehicle_sync(u)


def vehicle_sync(u: dict):
    actor = auth.actor(u)
    st.markdown("#### 🚗 법인차량 관리 프로그램 연동")
    st.caption("차량목록.xlsx의 '구매' 차량(임원용)은 차량운반구 자산으로, '렌트' 차량(업무용)은 렌탈·리스 계약으로 등록합니다. "
               "최근정비일은 점검 기록으로, 운행일지.xlsx의 월별 주행거리는 차량 자산 상세에 표시됩니다.")
    with st.container(border=True):
        c1, c2 = st.columns([3, 1.3])
        c1.markdown("**차량목록.xlsx 샘플 양식**  \n법인차량 관리 프로그램과 같은 20개 열(차량번호 ~ 차량 구매 비용)에 구매·렌트 예시 4대와 작성 안내 시트가 들어 있습니다. "
                    "법인차량 프로그램의 차량목록.xlsx로 그대로 써도 됩니다.")
        c2.download_button("📄 차량목록 샘플 양식 받기", d.vehicle_template_bytes(), file_name="차량목록_샘플양식.xlsx",
                           width="stretch", type="primary")
    settings = d.get_settings()
    c1, c2 = st.columns([4, 1])
    path = c1.text_input("차량목록.xlsx 경로", value=settings.get("차량목록 경로", ""),
                         placeholder=r"예: C:\법인차량관리\차량목록.xlsx", key="veh-path", disabled=ON_CLOUD)
    if c2.button("경로 저장", width="stretch", disabled=ON_CLOUD):
        if ui.run_action(d.save_settings, {"차량목록 경로": path}, success="차량목록 경로를 저장했습니다."):
            st.rerun()
    up = st.file_uploader("또는 차량목록.xlsx 파일 올리기", type=["xlsx"], key="veh-upload")
    source = up if up is not None else (None if ON_CLOUD else (path.strip() or None))
    vehicles = []
    if not source:
        st.info("경로를 입력하거나 파일을 올리면 미리보기가 나옵니다.")
    else:
        try:
            vehicles = d.read_vehicle_file(source)
        except d.DataError as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(f"차량목록을 읽지 못했습니다: {exc}")
    if vehicles:
        owned = [v for v in vehicles if d.clean_str(v.get("구분")) == "구매"]
        linked = {a["연결차량번호"] for a in d.get_assets() if a["연결차량번호"]}
        leased = {x["연결차량번호"] for x in d.load("leases") if x["연결차량번호"]}
        k = st.columns(4)
        with k[0]: ui.kpi("차량 전체", len(vehicles), "차량목록 기준", unit="대")
        with k[1]: ui.kpi("구매(임원용)", len(owned), "자산 등록 대상", unit="대")
        with k[2]: ui.kpi("렌트(업무용)", len(vehicles) - len(owned), f"렌탈 계약 연동 {sum(1 for v in vehicles if d.clean_str(v.get('차량번호')) in leased)}대", unit="대")
        with k[3]: ui.kpi("이미 연동됨", sum(1 for v in owned if d.clean_str(v.get("차량번호")) in linked), "다시 동기화하면 현장·사용자·상태 갱신", unit="대")
        preview = pd.DataFrame([{"차량번호": d.clean_str(v.get("차량번호")), "구분": d.clean_str(v.get("구분")), "차종": d.clean_str(v.get("차종")),
                                 "현장": d.clean_str(v.get("현장")), "사용자": d.clean_str(v.get("사용자")), "상태": d.clean_str(v.get("상태")),
                                 "구매일": d.to_date(v.get("차량 구매일")), "구매 비용": d.to_num(v.get("차량 구매 비용"), 0),
                                 "연동": "연동됨" if d.clean_str(v.get("차량번호")) in linked | leased else "신규"} for v in vehicles])
        st.dataframe(preview, hide_index=True, width="stretch", column_config=ui.money_config("구매 비용"))
        if st.button("🔄 자산대장·렌탈 계약·정비 기록 동기화", type="primary"):
            result = ui.run_action(d.sync_vehicles, vehicles, actor)
            if result:
                extra = ui.run_action(ops.sync_vehicle_extras, vehicles, actor) or {"leases": 0, "maint": 0}
                msg = (f"자산 신규 {len(result['added'])}대 · 갱신 {len(result['updated'])}대 · "
                       f"렌탈 계약 신규 {extra['leases']}건 · 정비 기록 {extra['maint']}건")
                if result["new_sites"]:
                    msg += f" · 새 현장 추가: {', '.join(result['new_sites'])}"
                ui.flash(msg)
                st.rerun()

    st.markdown("#### 🛣 운행일지 연동 (월별 주행거리)")
    st.caption("법인차량 프로그램의 운행일지.xlsx '월별요약' 시트(차량번호, 01월 KM ~ 12월 KM)를 읽어 차량 자산 상세의 '🚗 차량 운행' 탭에 보여 줍니다.")
    c1, c2, c3 = st.columns([3, 1, 1])
    km_path = c1.text_input("운행일지.xlsx 경로", value=settings.get("운행일지 경로", ""), key="km-path", disabled=ON_CLOUD,
                            placeholder=r"예: C:\법인차량관리\운행일지.xlsx")
    year = c2.number_input("연도", min_value=2000, max_value=2100, value=d.today().year, key="km-year")
    km_up = st.file_uploader("또는 운행일지.xlsx 올리기", type=["xlsx"], key="km-upload")
    if c3.button("📥 불러오기", width="stretch", key="km-go"):
        src = km_up if km_up is not None else (None if ON_CLOUD else km_path.strip() or None)
        if not src:
            st.warning("경로를 입력하거나 파일을 올리세요.")
        else:
            if not ON_CLOUD and km_path.strip():
                d.save_settings({"운행일지 경로": km_path.strip()})
            n = ui.run_action(ops.import_vehicle_km, src, int(year))
            if n is not None:
                ui.flash(f"차량 {n}대의 {int(year)}년 월별 주행거리를 불러왔습니다.")
                st.rerun()


# =========================================================
# 결재함
# =========================================================
ICONS = {"pr": "🛒", "move": "🔄", "inc": "⚠️", "dsp": "🗑"}


def inbox(u: dict):
    st.title("✅ 결재함")
    st.caption("구매요청 단계별 결재 → 견적 → 발주 → 검수(부분 입고) → 등록 / 이동 승인·인수 / 경위서·사고 조사·종결 / "
               "처분 위원회 투표·입찰·집행·제적 / 장비 대여 승인·인계·반납을 처리합니다.")
    pending = wf.pending_for(u)
    rentals = wf.pending_rentals(u)
    scope = u["현장"] if is_site_role(u) else None
    names = [f"{ICONS[k]} {d.KIND_NAMES[k]} ({len(pending[k])})" for k in d.REQUEST_TABLES] + [f"🧰 장비 대여 ({len(rentals)})"]
    tabs = st.tabs(names)
    for tab, kind in zip(tabs, d.REQUEST_TABLES):
        with tab:
            if kind == "pr" and u.get("역할") in (ADMIN,) + SITE_ROLES:
                with st.expander("📝 구매요청 작성"):
                    wf.purchase_form("inbox-pr-form", [u["현장"]] if scope else d.site_names(), u, defaults={"현장": scope} if scope else None)
            wf.render_request_list(kind, u, key=f"inbox-{kind}", scope_site=scope)
    with tabs[-1]:
        import pages_ops
        pages_ops.rental_cards(rentals, u, key="inbox-rt")


# =========================================================
# 재물조사
# =========================================================
def audit(u: dict):
    actor = auth.actor(u)
    st.title("🔍 재물조사")
    st.caption("장부상 수량과 실물이 일치하는지 확인합니다. 바코드 스캐너·카메라로 QR을 읽거나 표에서 결과를 고릅니다. "
               "마감하면 미발견 자산은 현장에 분실 경위서가 자동 요청되고, 차이 보고서를 내려받을 수 있습니다.")
    current = d.open_audit()
    admin = wf.is_admin(u)
    if current and (admin or current["대상"] in ("전체", u.get("현장"))):
        wf.render_audit_workspace(current, u, key="audit-ws")
        if admin:
            st.divider()
            with st.container(border=True):
                st.markdown("**🏁 조사 마감**")
                st.caption("유휴로 체크한 '사용중' 자산은 '유휴'로 바뀌어 재배치 대상에 오르고, 결과가 자산 이력에 남습니다.")
                req = st.checkbox("미발견 자산은 현장 담당자에게 분실 경위서를 요청합니다", value=True, key="audit-req")
                ok = st.checkbox("조사 결과를 확인했고 마감합니다", key="audit-close-ok")
                if st.button("조사 마감", type="primary", disabled=not ok):
                    with st.spinner("마감하는 중입니다..."):
                        stats = ui.run_action(d.close_audit, current["회차번호"], actor, req)
                    if stats:
                        ui.flash(f"재물조사를 마감했습니다. 확인 {stats['found']:,} · 미발견 {stats['missing']:,} · 유휴 {stats['idle']:,}"
                                 + (f" · 경위서 요청 {stats['requested']:,}건" if stats.get("requested") else ""))
                        st.rerun()
    elif current:
        st.info(f"진행 중인 조사({current['회차명']})는 {current['대상']} 대상입니다.")
    elif admin:
        with st.container(border=True):
            st.markdown("**새 재물조사 시작**")
            with st.form("audit-start"):
                c1, c2, c3 = st.columns([2, 1, 1])
                name = c1.text_input("회차 이름", value=f"{d.today().year} {'상반기' if d.today().month <= 6 else '하반기'} 정기 재물조사")
                base = c2.date_input("기준일", value=d.today())
                scope = c3.selectbox("대상", ["전체"] + d.site_names())
                if st.form_submit_button("🔍 조사 시작", type="primary", width="stretch"):
                    no = ui.run_action(d.start_audit, name, base, scope, actor)
                    if no:
                        ui.flash(f"{no} 재물조사를 시작했습니다. 현장 담당자 화면에서도 스캔·확인할 수 있습니다.")
                        st.rerun()
    else:
        st.info("지금 진행 중인 재물조사가 없습니다. 관리자가 조사를 시작하면 여기서 우리 현장 자산을 확인합니다.")

    audits = [a for a in d.get_audits() if a["상태"] == "완료"]
    if audits:
        st.markdown("### 📚 지난 조사 · 차이 보고서")
        df = pd.DataFrame(audits)[["회차번호", "회차명", "기준일", "대상", "장부수량", "확인", "미발견", "유휴", "마감일시"]]
        st.dataframe(df, hide_index=True, width="stretch")
        pick = st.selectbox("보고서 볼 회차", [a["회차번호"] for a in audits],
                            format_func=lambda n: next(f"{a['회차번호']} · {a['회차명']}" for a in audits if a["회차번호"] == n))
        wf.render_audit_report(pick, key=f"audit-rep-{pick}")


# =========================================================
# 감가상각 · 결산
# =========================================================
def depreciation(u: dict):
    can_close = u.get("역할") in (ADMIN, FIN)
    st.title("📉 감가상각 · 결산")
    st.caption("세법·회계기준에 따라 정액법·정률법으로 월할 상각합니다. 정률법 상각률은 잔존가치 5% 기준(5년 0.451), "
               "내용연수가 끝나면 유형자산은 비망가액 1,000원을 남깁니다. 소모품은 취득 시 비용 처리되어 제외됩니다. "
               "자본적 지출은 원가에 더해 따로 상각합니다.")
    today = d.today()
    c1, c2, c3, c4 = st.columns(4)
    year = c1.selectbox("연도", list(range(today.year, today.year - 10, -1)), key="dep_year")
    month = c2.selectbox("결산월", list(range(1, 13)), index=today.month - 1 if year == today.year else 11, key="dep_month",
                         format_func=lambda m: f"{m}월")
    site = c3.selectbox("현장", ["전체"] + d.site_names(), key="dep_site")
    basis = c4.radio("기준", ["회계", "세무"], horizontal=True, key="dep_basis",
                     help="세무: 자산별 '세무 내용연수·상각방법'(비우면 회계와 같음)으로 계산한 세법 상각한도")
    site_arg = None if site == "전체" else site
    with st.spinner("감가상각을 계산하는 중입니다..."):
        rows = d.depreciation_schedule(year, month, site_arg, basis)
    key = f"{year}-{month:02d}"
    closed = d.lookup("closings", key)

    total = lambda k: sum(r[k] for r in rows)  # noqa: E731
    k = st.columns(5)
    with k[0]: ui.kpi("상각 대상", f"{len(rows):,}", "소모품 제외 · 당기 처분분 포함", unit="개")
    with k[1]: ui.kpi("기초 장부가", ui.short_won(total("기초 장부가")), f"{year - 1}년 말", unit="원")
    with k[2]: ui.kpi(f"당기 상각비 (1~{month}월)", ui.short_won(total("당기 상각비")), ui.won(total("당기 상각비")), unit="원")
    with k[3]: ui.kpi("상각누계액", ui.short_won(total("상각누계액")), f"{key} 말 · {basis} 기준", unit="원")
    with k[4]: ui.kpi("기말 장부가", ui.short_won(total("기말 장부가")), "마감됨" if closed else "미마감", "ok" if closed else "", "원")

    money = ui.money_config("취득가액", "기초장부가", "당기취득", "당기상각비", "월상각비", "상각누계액", "기말장부가",
                            "기초 장부가", "당기 취득", "당기 상각비", "월 상각비", "기말 장부가", "회계 상각비", "세법 상각한도",
                            "상각부인액", "시인부족액", "상각비")
    tabs = st.tabs(["계정과목별", "현장별", "자산별 명세", f"{year}년 월별 상각비", "⚖️ 세무조정", "🔮 3년 예측"])
    if not rows:
        with tabs[0]:
            st.info("상각 대상 자산이 없습니다.")
    else:
        df = pd.DataFrame(rows)
        by_acc = df.groupby("계정과목", sort=False).agg(자산수=("태그번호", "count"), 취득가액=("취득가액", "sum"),
                                                       기초장부가=("기초 장부가", "sum"), 당기취득=("당기 취득", "sum"),
                                                       당기상각비=("당기 상각비", "sum"), 월상각비=("월 상각비", "sum"),
                                                       상각누계액=("상각누계액", "sum"), 기말장부가=("기말 장부가", "sum")).reset_index()
        by_site = df.groupby("현장", sort=False).agg(자산수=("태그번호", "count"), 취득가액=("취득가액", "sum"),
                                                   당기상각비=("당기 상각비", "sum"), 기말장부가=("기말 장부가", "sum")).reset_index()
        with tabs[0]:
            st.dataframe(by_acc.round(0), hide_index=True, width="stretch", column_config=money)
        with tabs[1]:
            st.dataframe(by_site.round(0), hide_index=True, width="stretch", column_config=money)
        with tabs[2]:
            page = ui.paginate(rows, f"dep_page_{key}_{site}_{basis}")
            st.dataframe(pd.DataFrame(page).round(0), hide_index=True, width="stretch", column_config=money, height=420)
        with tabs[3]:
            if st.toggle("월별 상각비 계산하기", key="dep_monthly", help="자산이 많으면 몇 초 걸립니다"):
                monthly = []
                for m in range(1, 13):
                    if date(year, m, 1) > today:
                        break
                    sched = d.depreciation_schedule(year, m, site_arg, basis)
                    monthly.append({"월": f"{m:02d}월", "상각비(백만원)": round(sum(r["월 상각비"] for r in sched) / 1e6, 1)})
                if monthly:
                    st.bar_chart(pd.DataFrame(monthly), x="월", y="상각비(백만원)", height=300)
        detail_cols = list(rows[0].keys())
        acc_cols = list(by_acc.columns)
        site_cols = list(by_site.columns)
        ui.export_panel(f"dep-export-{key}-{site}-{basis}", f"고정자산명세서_{basis}_{key}",
                        lambda: {"고정자산명세": (detail_cols, [{k2: (round(v) if isinstance(v, float) else v) for k2, v in r.items()} for r in rows]),
                                 "계정과목별": (acc_cols, by_acc.round(0).to_dict("records")),
                                 "현장별": (site_cols, by_site.round(0).to_dict("records"))}, len(rows))
    with tabs[4]:
        st.caption("회계 상각비가 세법 상각한도보다 크면 '상각부인액'(손금불산입), 작으면 '시인부족액'입니다. "
                   "자산 정보의 '세무 내용연수·상각방법'이 회계와 다른 자산만 나옵니다.")
        if st.toggle("세무조정 계산하기", key="dep_tax"):
            adj = d.tax_adjustment(year, month, site_arg)
            if not adj:
                st.success("회계와 세무 상각비가 다른 자산이 없습니다.")
            else:
                c1, c2 = st.columns(2)
                c1.metric("상각부인액 합계", ui.won(sum(r["상각부인액"] for r in adj)))
                c2.metric("시인부족액 합계", ui.won(sum(r["시인부족액"] for r in adj)))
                st.dataframe(pd.DataFrame(adj), hide_index=True, width="stretch", column_config=money)
                st.download_button("📥 세무조정 명세 엑셀", d.rows_to_xlsx({"세무조정": (list(adj[0].keys()), adj)}),
                                   file_name=f"감가상각_세무조정_{key}.xlsx", key="dep-tax-dl")
    with tabs[5]:
        st.caption("지금 보유한 자산만으로 계산한 앞으로 3년의 연도별 감가상각비입니다(새로 살 자산은 빠집니다). 예산·손익 계획에 씁니다.")
        if st.toggle("예측 계산하기", key="dep_fc"):
            fc = d.depreciation_forecast(3)
            if site_arg:
                fc = [r for r in fc if r["현장"] == site_arg]
            if fc:
                fdf = pd.DataFrame(fc)
                pivot = fdf.pivot_table(index="계정과목", columns="연도", values="상각비", aggfunc="sum", fill_value=0)
                pivot.columns = [f"{c}년" for c in pivot.columns]
                pivot = pivot.reset_index()
                st.dataframe(pivot, hide_index=True, width="stretch", column_config=ui.money_config(*[c for c in pivot.columns if c != "계정과목"]))
                chart = fdf.groupby(["연도", "계정과목"], as_index=False)["상각비"].sum()
                chart["상각비(백만원)"] = (chart["상각비"] / 1e6).round(1)
                chart["연도"] = chart["연도"].astype(str)
                st.bar_chart(chart, x="연도", y="상각비(백만원)", color="계정과목", stack=True, height=300)
                st.download_button("📥 예측 엑셀", d.rows_to_xlsx({"감가상각 예측": (list(fc[0].keys()), fc)}),
                                   file_name=f"감가상각_3년예측_{today:%Y%m%d}.xlsx", key="dep-fc-dl")

    st.divider()
    st.markdown("### 🔒 결산 마감")
    if closed:
        st.success(f"{key} 결산이 {closed['마감일시']}에 마감되었습니다 ({closed['마감자']}).")
    elif can_close:
        st.caption("재무팀과 결산할 때 마감하면 그 시점의 고정자산 명세(전체 현장·회계 기준)가 별도로 보관됩니다. "
                   "ERP에 올릴 분개는 '🧾 회계 분개' 메뉴에서 받습니다.")
        ok = st.checkbox(f"{key} 고정자산 명세를 확인했습니다", key="close-ok")
        if st.button(f"🔒 {key} 결산 마감", type="primary", disabled=not ok):
            with st.spinner("마감 명세를 저장하는 중입니다..."):
                if ui.run_action(d.close_period, year, month, auth.actor(u), success=f"{key} 결산을 마감했습니다."):
                    st.rerun()
    else:
        st.caption("결산 마감은 관리자·재무 담당자가 합니다.")
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
def disposal_and_idle(u: dict):
    st.title("♻️ 처분 검토 · 유휴 자산")
    st.caption("이미 폐기·매각된 자산은 '🗑 폐기·처분 자산' 메뉴에서 봅니다.")
    candidates = d.disposal_candidates()
    idle = [a for a in d.active_assets() if a["상태"] == "유휴"]
    tabs = st.tabs([f"♻️ 처분 검토 대상 ({len(candidates):,})", f"💤 유휴 자산 재배치 ({len(idle):,})"])
    with tabs[0]:
        st.caption("내용연수가 지났거나, 누적 수리비·수리 견적이 장부가보다 크거나, 유휴 상태로 만료가 1년 안에 오는 자산입니다.")
        if not candidates:
            st.success("지금은 처분 검토 대상이 없습니다.")
        else:
            c1, c2 = st.columns(2)
            site = c1.selectbox("현장", ["전체"] + d.site_names(), key="cand-site")
            acc = c2.selectbox("계정과목", ["전체"] + d.ACCOUNT_NAMES, key="cand-acc")
            rows = [a for a in candidates if (site == "전체" or a["현장"] == site) and (acc == "전체" or a["계정과목"] == acc)]
            page = ui.paginate(rows, f"cand-page-{site}-{acc}", page_size=500)
            extra = ["검토사유"] + (["누적 수리비"] if any("누적 수리비" in a for a in page) else [])
            df = ui.asset_frame(page, extra=extra)
            ev = st.dataframe(df, hide_index=True, width="stretch", column_config={**ui.ASSET_COLUMN_CONFIG, **ui.money_config("누적 수리비")},
                              on_select="rerun", selection_mode="multi-row", key=f"cand-table-{site}-{acc}")
            sel = [df.iloc[i]["태그번호"] for i in ev.selection.rows if i < len(df)]
            if st.button(f"🗑 선택한 {len(sel)}개 처분 신청", type="primary", disabled=not sel):
                wf.dlg_new_disposal(sel, u)
    with tabs[1]:
        st.caption("재물조사·퇴사 회수·현장 담당자가 유휴로 표시한 자산입니다. 필요한 현장으로 재배치하면 구매 비용을 줄일 수 있습니다.")
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
                wf.dlg_new_transfer(sel, u)


def disposed(u: dict):
    site = u["현장"] if is_site_role(u) else None
    st.title("🗑 폐기·처분 자산" + (f" · {site}" if site else ""))
    st.caption("폐기·매각·기증·사내 경매·망실로 장부에서 제적된 자산입니다. 처분일자 최신 순이며, 연도·방법·현장으로 걸러 볼 수 있습니다.")
    wf.render_disposed_list("disposed", u, site)


# =========================================================
# 설정
# =========================================================
NUM_SETTINGS = {"자본화 기준금액", "결재 기준1", "결재 기준2", "위원회 정족수", "알림 기준일", "메일 포트"}
SECRET_SETTINGS = {"메일 비밀번호"}
CLOUD_HIDDEN = {"메일 서버", "메일 포트", "메일 계정", "메일 비밀번호", "알림 받는 메일", "웹훅 주소", "차량목록 경로", "운행일지 경로"}


def settings(u: dict):
    st.title("⚙️ 설정")
    tabs = st.tabs(["🏢 현장·부서", "👤 사용자·역할", "🔧 환경 설정", "💾 데이터"])
    with tabs[0]:
        settings_sites(u)
    with tabs[1]:
        settings_users(u)
    with tabs[2]:
        settings_env(u)
    with tabs[3]:
        settings_data(u)


def settings_sites(u: dict):
    actor = auth.actor(u)
    st.caption("행을 추가·수정한 뒤 저장하세요. 보유 자산이 남아 있는 현장은 삭제할 수 없습니다. "
               "현장 담당자는 '👤 사용자·역할' 탭에서 등록합니다.")
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

    with st.expander("✏️ 현장 이름 바꾸기 (자산·요청·재물조사 기록까지 함께 변경)"):
        st.caption("위 표에서 이름을 직접 고치면 '삭제 후 새로 추가'로 처리되어 자산이 있는 현장은 바뀌지 않습니다. 이름을 바꿀 때는 여기를 쓰세요.")
        with st.form("rename-site"):
            c1, c2 = st.columns(2)
            old = c1.selectbox("현재 이름", d.site_names())
            new_name = c2.text_input("새 이름")
            if st.form_submit_button("이름 바꾸기", type="primary"):
                n = ui.run_action(d.rename_site, old, new_name, actor)
                if n is not None:
                    for usr in auth.get_users():
                        if usr["현장"] == old:
                            d.upsert("users", [dict(usr, 현장=new_name.strip())])
                    ui.flash(f"'{old}' → '{new_name.strip()}'(으)로 바꿨습니다. 자산 {n:,}개에 반영했습니다.")
                    st.rerun()


def settings_users(u: dict):
    actor = auth.actor(u)
    st.caption("로그인 없이 쓰는 프로그램입니다. 여기에 등록한 사람이 첫 화면과 사이드바의 '사용자 바꾸기' 목록에 나오고, "
               "고른 사람의 역할에 따라 메뉴와 권한이 달라집니다. '위원'은 불용품 판정 위원회에서 처분 신청에 투표합니다.")
    st.dataframe(pd.DataFrame([{"역할": r, "할 수 있는 일": desc} for r, desc in auth.ROLE_DESC.items()]), hide_index=True, width="stretch")
    users = auth.get_users()
    view = pd.DataFrame([{k: usr[k] for k in ("아이디", "이름", "역할", "현장", "부서", "이메일", "연락처", "위원", "활성")}
                         for usr in users])
    st.dataframe(view, hide_index=True, width="stretch")

    sites = d.site_names()
    c1, c2 = st.columns(2)
    with c1:
        with st.container(border=True):
            st.markdown("**➕ 새 사용자**")
            with st.form("user-new", clear_on_submit=True):
                a1, a2 = st.columns(2)
                name = a1.text_input("이름")
                role = a2.selectbox("역할", auth.ROLES, index=auth.ROLES.index(auth.SITE))
                a1, a2 = st.columns(2)
                site = a1.selectbox("소속 현장", [""] + sites, help="현장책임자·현장담당·직원은 꼭 고르세요")
                dept = a2.text_input("부서")
                a1, a2 = st.columns(2)
                email = a1.text_input("이메일 (알림용)")
                phone = a2.text_input("연락처")
                member = st.checkbox("불용품 판정 위원회 위원")
                if st.form_submit_button("사용자 추가", type="primary", width="stretch"):
                    if ui.run_action(auth.save_user, {"이름": name, "역할": role, "현장": site, "부서": dept, "이메일": email,
                                                      "연락처": phone, "위원": "Y" if member else ""}, actor,
                                     success=f"'{name.strip()}' 사용자를 추가했습니다."):
                        st.rerun()
    with c2:
        with st.container(border=True):
            st.markdown("**✏️ 사용자 수정**")
            if not users:
                st.caption("사용자가 없습니다.")
                return
            pick = st.selectbox("사용자", [usr["아이디"] for usr in users],
                                format_func=lambda x: next(auth.label(v) for v in users if v["아이디"] == x),
                                key="user-pick")
            cur = auth.get_user(pick)
            with st.form(f"user-edit-{pick}"):
                a1, a2 = st.columns(2)
                name = a1.text_input("이름", value=cur["이름"])
                role = a2.selectbox("역할", auth.ROLES, index=auth.ROLES.index(cur["역할"]) if cur["역할"] in auth.ROLES else 0)
                a1, a2 = st.columns(2)
                opts = [""] + sites
                site = a1.selectbox("소속 현장", opts, index=opts.index(cur["현장"]) if cur["현장"] in opts else 0)
                dept = a2.text_input("부서", value=cur["부서"])
                a1, a2 = st.columns(2)
                email = a1.text_input("이메일", value=cur["이메일"])
                phone = a2.text_input("연락처", value=cur["연락처"])
                a1, a2 = st.columns(2)
                member = a1.checkbox("위원회 위원", value=cur["위원"] == "Y")
                active = a2.checkbox("사용 중 (끄면 선택 목록에서 숨김)", value=cur["활성"] == "Y")
                if st.form_submit_button("💾 저장", type="primary", width="stretch"):
                    if ui.run_action(auth.save_user, {"이름": name, "역할": role, "현장": site, "부서": dept,
                                                      "이메일": email, "연락처": phone, "위원": "Y" if member else "",
                                                      "활성": "Y" if active else "N"}, actor, pick, success="저장했습니다."):
                        st.rerun()


def settings_env(u: dict):
    values = d.get_settings()
    if ON_CLOUD:
        st.info("공개 데모에서는 메일·웹훅·파일 경로 설정을 숨깁니다(다른 방문자가 서버로 메일을 보내지 못하게).")
    with st.form("settings-form"):
        new = {}
        for key, (_, desc) in d.DEFAULT_SETTINGS.items():
            if ON_CLOUD and key in CLOUD_HIDDEN:
                continue
            if key in SECRET_SETTINGS:
                entered = st.text_input(key, value="", type="password", help=desc,
                                        placeholder="저장됨 · 바꿀 때만 입력" if values.get(key) else "")
                if entered:
                    new[key] = entered
            else:
                new[key] = st.text_input(key, value=values.get(key, ""), help=desc)
        if st.form_submit_button("💾 설정 저장", type="primary"):
            bad = [k for k in NUM_SETTINGS if k in new and d.to_num(new[k]) is None]
            if bad:
                st.error(f"{', '.join(bad)}은(는) 숫자로 입력하세요.")
            elif ui.run_action(d.save_settings, new, success="설정을 저장했습니다."):
                st.rerun()
    if not ON_CLOUD:
        st.markdown("#### 📨 알림 보내기 시험")
        st.caption("메일·웹훅 설정을 저장한 뒤 시험해 보세요. 매일 아침 자동으로 보내려면 README의 'Windows 작업 스케줄러' 안내대로 "
                   "`python notify.py`를 등록하세요.")
        c1, c2 = st.columns(2)
        if c1.button("✉️ 시험 메일 보내기", width="stretch"):
            ui.run_action(ops.send_email, "[자산관리 AI] 시험 메일", "자산관리 AI 알림 메일 설정이 잘 되었습니다.",
                          success="시험 메일을 보냈습니다.")
            ui.show_flash()
        if c2.button("💬 시험 웹훅 보내기", width="stretch"):
            ui.run_action(ops.send_webhook, "[자산관리 AI] 웹훅 알림 설정이 잘 되었습니다.", success="웹훅을 보냈습니다.")
            ui.show_flash()


def settings_data(u: dict):
    actor = auth.actor(u)
    st.markdown("#### 💾 데이터 내보내기 · 백업")
    st.caption(f"데이터는 {d.DB_FILE.parent.name}/{d.DB_FILE.name} 한 파일(SQLite)에 저장되고, 첨부파일은 data/attachments 폴더에 저장됩니다. "
               "엑셀이 필요하면 아래에서 표를 골라 내보내세요.")
    labels = {t: f"{spec['label']} ({d.table_count(t):,}행)" for t, spec in d.TABLES.items()}
    table = st.selectbox("내보낼 표", list(labels), format_func=lambda t: labels[t], key="export-table")
    cols = list(d.TABLES[table]["cols"])
    ui.export_panel(f"table-export-{table}", f"{d.TABLES[table]['label']}_{d.today():%Y%m%d}",
                    lambda: {d.TABLES[table]["label"]: (cols, d.table_rows(table))}, d.table_count(table))
    if not ON_CLOUD:
        c1, c2 = st.columns([1, 2])
        if c1.button("🗄 DB 백업 파일 만들기", width="stretch"):
            with st.spinner("백업 파일을 만드는 중입니다..."):
                st.session_state["db-backup"] = d.backup_db_bytes()
        if st.session_state.get("db-backup"):
            blob = st.session_state["db-backup"]
            c2.download_button(f"⬇️ 자산관리_백업_{d.today():%Y%m%d}.db ({len(blob) / 1e6:.0f}MB)", blob,
                               file_name=f"자산관리_백업_{d.today():%Y%m%d}.db", width="stretch")
        st.caption("복원하려면 프로그램을 끈 뒤 백업 파일 이름을 '자산관리.db'로 바꿔 data 폴더에 덮어쓰세요. 첨부파일은 data/attachments 폴더를 따로 복사하세요.")

    st.markdown("#### 🧪 예시 데이터")
    c1, c2 = st.columns([2, 1])
    if ON_CLOUD:
        c1.info("공개 데모입니다. 다른 방문자가 데이터를 많이 바꿔 놓았다면 처음 상태로 되돌릴 수 있습니다 (체험용 사용자도 다시 만들어집니다).")
        if c2.button("🔄 데모 데이터 초기화", width="stretch"):
            with st.spinner("데모 데이터를 다시 만드는 중입니다..."):
                d.clear_sample_data()
                d.create_sample_data("데모", active_count=d.DEMO_SAMPLE[0], closed_count=d.DEMO_SAMPLE[1])
            ui.flash("데모 데이터를 처음 상태로 되돌렸습니다.")
            st.rerun()
        return
    if d.has_sample_data():
        c1.info(f"예시 데이터가 들어 있습니다 (보유 {sum(1 for a in d.active_assets() if d.SAMPLE_MARK in a['비고']):,}개 · "
                f"처분 {sum(1 for a in d.closed_assets() if d.SAMPLE_MARK in a['비고']):,}개). 실제 운영 전에 삭제하세요. "
                "체험용 사용자(김자산·박전무·최재무·이현장·정담당·한직원)도 함께 지워집니다.")
        if u.get("비고") == d.SAMPLE_MARK:
            c1.warning("지금 체험용 사용자로 쓰고 있습니다. 삭제하면 사용자 선택 화면으로 돌아갑니다.")
        if c2.button("🧹 예시 데이터 삭제", width="stretch"):
            with st.spinner("예시 데이터를 지우는 중입니다..."):
                n = ui.run_action(d.clear_sample_data)
            if n is not None:
                ui.flash(f"예시 자산 {n:,}개와 관련 요청·조사·이력·직원·업체·체험 사용자를 삭제했습니다.")
                st.rerun()
    else:
        sizes = {"작게 (체험용)": d.DEMO_SAMPLE, "크게 (대량 데이터 확인용)": d.FULL_SAMPLE}
        size = c1.radio("예시 데이터 크기", list(sizes), index=1, horizontal=True, key="sample-size")
        active_n, closed_n = sizes[size]
        c1.caption(f"보유 자산 {active_n:,}개(현장 4곳), 처분 자산 {closed_n:,}개, 진행 중인 구매·이동·사고·처분 요청과 재물조사, "
                   "직원·공급업체·예산·점검 계획·라이선스·렌탈·장비 대여 예시와 역할별 체험용 사용자 6명을 만듭니다. "
                   "모든 예시에 [예시]가 붙습니다."
                   + (" 30~60초 걸립니다." if closed_n > 50000 else " 몇 초면 끝납니다."))
        if c2.button("🧪 예시 데이터 만들기", width="stretch", type="primary"):
            bar = st.progress(0.0, text="준비하는 중")
            result = ui.run_action(d.create_sample_data, actor, active_count=active_n, closed_count=closed_n,
                                   progress=lambda p, t: bar.progress(min(1.0, p), text=t))
            if result:
                ui.flash(f"예시 데이터를 만들었습니다: 보유 자산 {result['active']:,}개 · 처분 자산 {result['closed']:,}개 · 처분 요청서 {result['dsp']:,}건")
                st.rerun()


# 임원·재무 상수는 app.py의 메뉴 구성에서 씁니다.
READ_ONLY_ROLES = (EXEC, FIN)
