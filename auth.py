"""
사용자 · 역할 (로그인 없음)

법인차량 관리 AI처럼 비밀번호 없이 쓰는 사내용 프로그램입니다.
관리자가 ⚙️ 설정 → 👤 사용자·역할 에 사람을 등록해 두면, 처음 화면에서 "누구로 사용할지"를 고르고
사이드바에서 언제든 다른 사람으로 바꿀 수 있습니다. 고른 사람의 역할에 따라 메뉴와 권한이 달라집니다.

역할 6가지
- 관리자     : 자산 등록·결재·설정 등 모든 기능 (총무)
- 임원       : 고액 구매 최종 승인, 현황·분석 열람
- 재무       : 감가상각·결산·분개·예산·렌탈리스 관리, 현황 열람
- 현장책임자 : 자기 현장의 1차 결재(구매), 현장 담당 업무
- 현장담당   : 자기 현장 자산 관리, 이동·검수·대여 처리
- 직원       : 내 자산 확인, 장비 대여 신청, 분실 신고, 구매 요청
"""
from __future__ import annotations

import streamlit as st

import data as d

ADMIN, EXEC, FIN, LEAD, SITE, STAFF = "관리자", "임원", "재무", "현장책임자", "현장담당", "직원"
ROLES = [ADMIN, EXEC, FIN, LEAD, SITE, STAFF]
ROLE_DESC = {
    ADMIN: "자산 등록·결재·설정 등 모든 기능",
    EXEC: "고액 구매 최종 승인, 현황·분석 열람",
    FIN: "감가상각·결산·분개·예산·렌탈리스",
    LEAD: "자기 현장 1차 결재 + 현장 담당 업무",
    SITE: "자기 현장 자산 관리, 이동·검수·대여 처리",
    STAFF: "내 자산, 장비 대여 신청, 분실 신고, 구매 요청",
}
ROLE_ICON = {ADMIN: "🛡️", EXEC: "👔", FIN: "💰", LEAD: "🏗️", SITE: "🧰", STAFF: "🙋"}
SITE_ROLES = (LEAD, SITE)
NEEDS_SITE = SITE_ROLES + (STAFF,)
SESSION_KEY = "user_id"


# =========================================================
# 사용자 명부
# =========================================================
def get_users(active_only: bool = False) -> list[dict]:
    order = {s: i for i, s in enumerate(d.site_names())}
    rows = sorted(d.load("users"), key=lambda u: (ROLES.index(u["역할"]) if u["역할"] in ROLES else 9,
                                                   order.get(u["현장"], -1), u["이름"]))
    return [u for u in rows if u["활성"] == "Y"] if active_only else rows


def get_user(user_id: str) -> dict | None:
    return d.lookup("users", d.clean_str(user_id))


def has_any_user() -> bool:
    return bool(d.load("users"))


def _next_id() -> str:
    nums = [int(u["아이디"][1:]) for u in d.load("users") if u["아이디"][:1] == "u" and u["아이디"][1:].isdigit()]
    return f"u{(max(nums) if nums else 0) + 1:04d}"


def _check(rec: dict):
    if not d.clean_str(rec.get("이름")):
        raise d.DataError("이름을 입력하세요.")
    if rec.get("역할") not in ROLES:
        raise d.DataError("역할을 고르세요.")
    if rec["역할"] in NEEDS_SITE and rec.get("현장") not in d.site_names():
        raise d.DataError("현장책임자·현장담당·직원은 소속 현장을 골라야 합니다.")


def save_user(fields: dict, actor: str, uid: str | None = None) -> str:
    """사람을 등록(uid 없음)하거나 고칩니다. 아이디는 자동으로 붙습니다(u0001…)."""
    cur = get_user(uid) if uid else None
    if uid and not cur:
        raise d.DataError("사용자를 찾을 수 없습니다.")
    rec = dict(cur) if cur else {c: "" for c in d.TABLES["users"]["cols"]}
    rec.update({k: (d.clean_str(v) if isinstance(v, str) else v) for k, v in fields.items()
                if k in rec and k != "아이디"})
    if rec["역할"] not in NEEDS_SITE and rec["역할"] in ROLES and not rec.get("현장"):
        rec["현장"] = ""
    _check(rec)
    if cur and cur["역할"] == ADMIN and (rec["역할"] != ADMIN or rec["활성"] != "Y"):
        if not [u for u in get_users(True) if u["역할"] == ADMIN and u["아이디"] != uid]:
            raise d.DataError("관리자는 한 명 이상 남아 있어야 합니다.")
    if not cur:
        rec.update({"아이디": _next_id(), "활성": rec.get("활성") or "Y", "생성일시": d.now_text()})
    d.upsert("users", [rec])
    if not cur:
        d.add_history("-", "사용자 등록", f"{rec['이름']} ({rec['역할']}{', ' + rec['현장'] if rec['현장'] else ''})", actor)
    return rec["아이디"]


ADMIN_ID, ADMIN_NAME, ADMIN_DEPT = "admin", "김재열", "총무"


def ensure_default_admin() -> None:
    """관리자(김재열)가 없으면 만듭니다. 예시 데이터를 지워도 남는 실제 관리자입니다."""
    cur = get_user(ADMIN_ID)
    if cur:
        # 이전 버전의 기본 관리자(김자산 · 자산관리팀) → 총무 김재열로 바꿈
        if cur["이름"] == "김자산" or cur["비고"] == d.SAMPLE_MARK or cur["부서"] == "자산관리팀":
            d.upsert("users", [dict(cur, 이름=ADMIN_NAME, 부서=ADMIN_DEPT, 비고="")])
        return
    if any(u["역할"] == ADMIN for u in get_users(True)):
        return
    rec = {c: "" for c in d.TABLES["users"]["cols"]}
    rec.update({"아이디": ADMIN_ID, "이름": ADMIN_NAME, "역할": ADMIN, "부서": ADMIN_DEPT, "위원": "Y", "활성": "Y",
                "생성일시": d.now_text()})
    d.upsert("users", [rec])


def committee_members() -> list[dict]:
    return [u for u in get_users(True) if u["위원"] == "Y"]


def site_users(site: str, roles=SITE_ROLES) -> list[dict]:
    return [u for u in get_users(True) if u["현장"] == site and u["역할"] in roles]


DEMO_USERS = [
    # 아이디, 이름, 역할, 현장 인덱스(None=소속 현장 없음), 부서, 위원
    ("exec", "박전무", EXEC, None, "경영진", "Y"),
    ("finance", "최재무", FIN, None, "재무팀", "Y"),
    ("lead", "이현장", LEAD, 1, "공무팀", ""),
    ("site", "정담당", SITE, 1, "공무팀", ""),
    ("staff", "한직원", STAFF, 1, "설계팀", ""),
]


def seed_demo_users() -> list[str]:
    """관리자(김재열) + 역할별 체험용 사용자 5명을 만듭니다. 체험용은 비고에 [예시]가 붙어 예시 데이터와 함께 지워집니다."""
    ensure_default_admin()
    sites = d.site_names() or ["본사"]
    made = []
    for uid, name, role, si, dept, member in DEMO_USERS:
        if get_user(uid):
            continue
        site = sites[min(si, len(sites) - 1)] if si is not None else ""
        rec = {c: "" for c in d.TABLES["users"]["cols"]}
        rec.update({"아이디": uid, "이름": name, "역할": role, "현장": site, "부서": dept, "위원": member, "활성": "Y",
                    "생성일시": d.now_text(), "비고": d.SAMPLE_MARK})
        d.upsert("users", [rec])
        made.append(uid)
    return made


# =========================================================
# 세션 / 화면
# =========================================================
def label(u: dict) -> str:
    return f"{ROLE_ICON.get(u['역할'], '👤')} {u['이름']} · {u['역할']}" + (f" ({u['현장']})" if u.get("현장") else "")


def current_user() -> dict | None:
    uid = st.session_state.get(SESSION_KEY)
    if not uid:
        return None
    u = get_user(uid)
    if not u or u["활성"] != "Y":
        st.session_state.pop(SESSION_KEY, None)
        return None
    return dict(u)


def use_as(uid: str):
    st.session_state[SESSION_KEY] = uid
    st.rerun()


def actor(u: dict) -> str:
    return f"{u['이름']}({u['현장'] or u['역할']})"


def switch_user():
    """사용자 바꾸기: 세션을 비우고 사람 고르는 화면으로 돌아갑니다."""
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.rerun()


def choose_screen(compact: bool = False):
    """누구로 사용할지 고르는 화면 (비밀번호 없음)."""
    if not compact:
        st.title("🏷️ 자산관리 AI")
        st.caption("현장·부서별 자산을 구매부터 처분까지 관리합니다. 누구로 사용할지 고르세요. "
                   "역할(관리자·임원·재무·현장책임자·현장담당·직원)에 따라 보이는 메뉴와 할 수 있는 일이 달라집니다.")
    users = get_users(True)
    roles = [r for r in ROLES if any(u["역할"] == r for u in users)]
    tabs = st.tabs([f"{ROLE_ICON[r]} {r}" for r in roles])
    for tab, role in zip(tabs, roles):
        with tab:
            st.caption(ROLE_DESC[role])
            group = [u for u in users if u["역할"] == role]
            cols = st.columns(3)
            for i, u in enumerate(group):
                text = f"{u['이름']}" + (f" · {u['현장']}" if u["현장"] else "") + (f" · {u['부서']}" if u["부서"] else "")
                if cols[i % 3].button(text, key=f"pick-{u['아이디']}", width="stretch"):
                    use_as(u["아이디"])
    st.caption("명부에 없는 사람은 관리자가 ⚙️ 설정 → 👤 사용자·역할 에서 추가합니다.")


def sidebar_box(u: dict):
    """사이드바: 지금 사용자 + 다른 사람으로 바꾸기."""
    users = get_users(True)
    ids = [x["아이디"] for x in users]
    names = {x["아이디"]: label(x) for x in users}
    with st.container(border=True):
        st.markdown(f"**{label(u)}**" + (f"  \n<span class='small-muted'>{u['부서']}</span>" if u.get("부서") else ""),
                    unsafe_allow_html=True)
        pick = st.selectbox("사용자 바꾸기", ids, index=ids.index(u["아이디"]) if u["아이디"] in ids else 0,
                            format_func=lambda x: names.get(x, x), key="sidebar-user-pick")
    if pick != u["아이디"]:
        for k in list(st.session_state.keys()):
            del st.session_state[k]  # 다른 사람의 화면 상태(선택·필터)가 섞이지 않게 비웁니다
        use_as(pick)
