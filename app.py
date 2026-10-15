"""
자산관리 AI - 실행 파일

    streamlit run app.py

로그인 없이 "누구로 사용할지"를 고르면, 그 사람의 역할에 따라 왼쪽 메뉴가 달라집니다.
- 관리자     : 모든 메뉴 (자산 등록·결재·재물조사·처분·설정)
- 임원       : 대시보드, 고액 구매 최종 결재, 감가상각·예산·분석 열람
- 재무       : 감가상각·결산, 회계 분개, 예산, 라이선스, 렌탈·리스, 공급업체, 분석, 처분 위원회 투표
- 현장책임자 : 우리 현장 홈, 구매요청 1차 결재, 이동·검수·대여·재물조사·퇴사 회수
- 현장담당   : 현장책임자와 같고 구매 결재만 없음
- 직원       : 내 자산, 장비 대여, 구매 요청, 분실·파손 신고
QR 스캔 화면: http://주소:8501/?tag=태그번호
데이터는 data/자산관리.db (SQLite)에 저장되고, 화면에서 엑셀·CSV로 내보낼 수 있습니다.
"""
import streamlit as st

st.set_page_config(page_title="자산관리 AI", page_icon="🏷️", layout="wide")

import admin  # noqa: E402
import auth  # noqa: E402
import data as d  # noqa: E402
import ops  # noqa: E402
import pages_fin  # noqa: E402
import pages_ops  # noqa: E402
import ui  # noqa: E402
import user  # noqa: E402
import workflow as wf  # noqa: E402
from auth import ADMIN, EXEC, FIN, LEAD, SITE, STAFF  # noqa: E402

ALL = (ADMIN, EXEC, FIN, LEAD, SITE, STAFF)
SITE_R = (LEAD, SITE)

# (구역, 키, 제목, 아이콘, 함수, 볼 수 있는 역할)
MENU = [
    ("홈", "alerts", "알림", "🔔", pages_ops.alerts_page, ALL),
    ("홈", "my", "내 자산", "🙋", user.my_page, (ADMIN, EXEC, FIN, LEAD, SITE)),
    ("자산", "ledger", "자산대장", "📋", admin.ledger, (ADMIN, EXEC, FIN) + SITE_R),
    ("자산", "register", "자산 등록", "➕", admin.register, (ADMIN,)),
    ("자산", "request", "AI 요청·신청서", "🤖", user.request_page, (ADMIN, STAFF) + SITE_R),
    ("자산", "rental", "장비 대여", "🧰", pages_ops.rental_page, ALL),
    ("자산", "audit", "재물조사", "🔍", admin.audit, (ADMIN,) + SITE_R),
    ("자산", "maint", "점검·수리·보증", "🔧", pages_ops.maint_page, (ADMIN,) + SITE_R),
    ("자산", "people", "직원·퇴사 회수", "👥", pages_ops.people_page, (ADMIN,) + SITE_R),
    ("결재", "inbox", "결재함", "✅", admin.inbox, (ADMIN, EXEC, FIN) + SITE_R),
    ("처분", "disposal", "처분 검토·유휴", "♻️", admin.disposal_and_idle, (ADMIN,)),
    ("처분", "disposed", "폐기·처분 자산", "🗑", admin.disposed, (ADMIN, EXEC, FIN) + SITE_R),
    ("구매·재무", "vendor", "공급업체", "🏪", pages_ops.vendor_page, (ADMIN, FIN)),
    ("구매·재무", "budget", "예산", "💰", pages_ops.budget_page, (ADMIN, EXEC, FIN)),
    ("구매·재무", "license", "소프트웨어 라이선스", "💿", pages_ops.license_page, (ADMIN, FIN)),
    ("구매·재무", "lease", "렌탈·리스", "📑", pages_ops.lease_page, (ADMIN, FIN) + SITE_R),
    ("구매·재무", "dep", "감가상각·결산", "📉", admin.depreciation, (ADMIN, EXEC, FIN)),
    ("구매·재무", "journal", "회계 분개", "🧾", pages_fin.journal_page, (ADMIN, FIN)),
    ("구매·재무", "analytics", "분석", "📈", pages_fin.analytics_page, (ADMIN, EXEC, FIN)),
    ("관리", "settings", "설정", "⚙️", admin.settings, (ADMIN,)),
]


def home_function(u: dict):
    role = u.get("역할")
    if role in SITE_R:
        return user.site_home
    if role == STAFF:
        return user.my_page
    return admin.dashboard


def _page(fn, u: dict, key: str, title: str, icon: str, default: bool = False):
    def run():
        fn(u)
    run.__name__ = f"page_{key}"
    return st.Page(run, title=title, icon=icon, url_path=key, default=default)


def build_pages(u: dict) -> dict[str, list]:
    role = u.get("역할")
    pending = wf.pending_for(u)
    n_pending = sum(len(v) for v in pending.values()) + len(wf.pending_rentals(u))
    sections: dict[str, list] = {"홈": []}
    ui.PAGES.clear()
    home = _page(home_function(u), u, "home", "홈" if role in (STAFF,) + SITE_R else "대시보드", "🏠", default=True)
    sections["홈"].append(home)
    ui.PAGES["home"] = home
    for section, key, title, icon, fn, roles in MENU:
        if role not in roles:
            continue
        if key == "inbox" and n_pending:
            title = f"{title} ({n_pending})"
        page = _page(fn, u, key, title, icon)
        sections.setdefault(section, []).append(page)
        ui.PAGES[key] = page
    return sections


def sidebar(u: dict):
    with st.sidebar:
        st.divider()
        auth.sidebar_box(u)
        alerts = ops.alerts_for(u, wf.pending_for(u))
        crit = sum(1 for a in alerts if a["심각도"] == "crit")
        if alerts:
            st.caption(f"🔔 알림 {len(alerts)}건" + (f" · 🔴 긴급 {crit}건" if crit else ""))
        st.divider()
        assets = d.active_assets()
        st.caption(f"보유 자산 {len(assets):,}개 · 폐기·처분 누계 {len(d.closed_assets()):,}개")
        st.caption(f"데이터: {d.DATA_DIR.name}/{d.DB_FILE.name}")


def prepare_storage():
    try:
        d.init_storage()
        if not d.is_loaded("assets"):
            with st.spinner("자산 데이터를 불러오는 중입니다 (프로그램을 켠 뒤 처음 한 번만, 20만 건 기준 수 초)..."):
                d.active_assets()
                d.closed_assets()
        if d.ON_CLOUD and not st.session_state.get("_demo_checked"):
            st.session_state["_demo_checked"] = True
            with st.spinner("체험용 예시 데이터를 준비하는 중입니다..."):
                d.seed_demo_if_empty()
                if not auth.has_any_user():
                    auth.seed_demo_users()
        auth.ensure_default_admin()
    except d.DataError as exc:
        st.error(str(exc))
        st.stop()


def demo_banner():
    if d.ON_CLOUD:
        st.info("🧪 **공개 데모**입니다. 예시 데이터로 자유롭게 눌러 보세요. 서버가 다시 시작되면 데이터는 처음 상태로 돌아갑니다. "
                "AI 요청은 Ollama 대신 규칙 기반으로 분석합니다.", icon=None)


def main():
    ui.inject_css()
    prepare_storage()

    tag = st.query_params.get("tag")
    u = auth.current_user()
    if tag:
        demo_banner()
        ui.show_flash()
        user.qr_page(tag, u)
        return
    if not u:
        demo_banner()
        auth.choose_screen()
        return

    nav = st.navigation(build_pages(u))
    sidebar(u)
    demo_banner()
    ui.show_flash()
    nav.run()


if __name__ == "__main__":
    main()
