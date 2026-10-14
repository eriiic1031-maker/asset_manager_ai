"""
자산관리 AI - 실행 파일

    streamlit run app.py

화면 구성
- 관리자 페이지 (admin.py): 대시보드, 자산대장, 자산 등록, 결재함, 재물조사, 감가상각·결산, 처분·유휴, 설정
- 현장 담당자 페이지 (user.py): AI 요청, 우리 현장 자산, 유휴 자산, 신청서, 신청 현황, 재물조사
- QR 스캔 화면: http://주소:8502/?tag=태그번호
데이터는 data 폴더의 엑셀 파일에 저장됩니다 (data.py).
"""
import streamlit as st

st.set_page_config(page_title="자산관리 AI", page_icon="🏷️", layout="wide")

import admin  # noqa: E402
import data as d  # noqa: E402
import ui  # noqa: E402
import user  # noqa: E402

PAGES = ["관리자 페이지", "현장 담당자 페이지"]


def sidebar_summary():
    assets = d.active_assets()
    counts = {}
    for a in assets:
        counts[a["현장"]] = counts.get(a["현장"], 0) + 1
    st.divider()
    st.markdown("**자산 현황**")
    st.write(f"보유 자산 {len(assets):,}개")
    for site in d.site_names():
        st.write(f"· {site} {counts.get(site, 0):,}개")
    st.write(f"폐기·처분 누계 {len(d.closed_assets()):,}개")
    settings = d.get_settings()
    st.caption(f"Ollama: {settings.get('Ollama 모델')}")
    st.caption(f"데이터: {d.DATA_DIR.name}/{d.DB_FILE.name}")


def admin_gate() -> bool:
    pin = d.clean_str(d.get_settings().get("관리자 PIN"))
    if not pin or st.session_state.get("admin_ok"):
        return True
    st.title("🔒 관리자 페이지")
    entered = st.text_input("관리자 PIN", type="password")
    if st.button("확인", type="primary"):
        if entered == pin:
            st.session_state["admin_ok"] = True
            st.rerun()
        st.error("PIN이 맞지 않습니다.")
    return False


def main():
    ui.inject_css()
    try:
        d.init_storage()
        if not d.is_loaded("assets"):
            with st.spinner("자산 데이터를 불러오는 중입니다 (프로그램을 켠 뒤 처음 한 번만, 20만 건 기준 수 초)..."):
                d.active_assets()
                d.closed_assets()
    except d.DataError as exc:
        st.error(str(exc))
        st.stop()

    # 대시보드 버튼 등에서 요청한 메뉴 이동은 위젯을 그리기 전에 반영
    if "_goto_menu" in st.session_state:
        st.session_state["main_page"] = PAGES[0]
        st.session_state["admin_menu"] = st.session_state.pop("_goto_menu")

    tag = st.query_params.get("tag")

    with st.sidebar:
        st.header("🏷️ 자산관리 AI")
        page = st.radio("메뉴", PAGES, key="main_page")
        if page == PAGES[0]:
            st.radio("관리자 메뉴", admin.MENU, key="admin_menu")
            actor = d.clean_str(d.get_settings().get("관리자명")) or "자산관리자"
            st.caption(f"처리자: {actor} (설정에서 변경)")
        else:
            sites = d.site_names()
            site = st.selectbox("담당 현장", sites, key="user_site") if sites else None
            name = st.text_input("담당자 이름", placeholder="예: 홍길동", key="user_name").strip()
            if site:
                info = next((s for s in d.get_sites() if s["현장명"] == site), {})
                if info.get("담당자"):
                    st.caption(f"등록된 자산 담당자: {info['담당자']} {info.get('담당자 연락처', '')}")
        sidebar_summary()

    ui.show_flash()

    if tag:
        user.qr_page(tag)
        return
    if page == PAGES[0]:
        if admin_gate():
            admin.render(actor)
    else:
        if not d.site_names():
            st.warning("등록된 현장이 없습니다. 관리자 페이지 → 설정에서 현장을 추가하세요.")
            return
        user.render(site, name)


if __name__ == "__main__":
    main()
