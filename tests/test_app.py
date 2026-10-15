"""화면 실행 테스트: 역할별로 모든 메뉴가 오류 없이 열리는지 확인합니다 (Streamlit AppTest)."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import data as d

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "app.py")

# 메뉴 화면 하나만 그리는 작은 실행 파일 (app.py의 메뉴 표에서 함수를 찾아 실행)
HARNESS = f'''
import sys
sys.path.insert(0, {str(ROOT)!r})
import streamlit as st
import app, auth, ui
u = auth.get_user(st.session_state["uid"])
app.build_pages(u)
key = st.session_state["key"]
fn = app.home_function(u) if key == "home" else next(m[4] for m in app.MENU if m[1] == key)
ui.show_flash()
fn(u)
'''


@pytest.fixture(scope="module")
def demo_store(tmp_path_factory):
    d.use_data_dir(tmp_path_factory.mktemp("app") / "data")
    d.init_storage()
    d.create_sample_data(active_count=400, closed_count=2000)
    yield d


def _ok(at):
    assert not at.exception, [e.value for e in at.exception]
    return at


def run_app(state=None, tag=None):
    at = AppTest.from_file(APP, default_timeout=120)
    for k, v in (state or {}).items():
        at.session_state[k] = v
    if tag:
        at.query_params["tag"] = tag
    at.run()
    return _ok(at)


def run_menu(uid, key):
    at = AppTest.from_string(HARNESS, default_timeout=120)
    at.session_state["uid"] = uid
    at.session_state["key"] = key
    at.run()
    return _ok(at)


def _cases():
    import app
    out = []
    import auth
    for uid, _, role, *_ in [("admin", "", auth.ADMIN)] + auth.DEMO_USERS:
        out.append((uid, "home"))
        out += [(uid, m[1]) for m in app.MENU if role in m[5]]
    return out


def test_choose_screen_without_login(demo_store):
    at = run_app()
    assert any("김재열" in b.label for b in at.button)  # 비밀번호 없이 사람을 고르는 버튼


def test_pick_user_opens_dashboard(demo_store):
    at = run_app()
    next(b for b in at.button if "김재열" in b.label).click().run()
    _ok(at)
    assert at.session_state["user_id"] == "admin"


@pytest.mark.parametrize("uid,key", _cases())
def test_every_menu_opens_for_each_role(demo_store, uid, key):
    run_menu(uid, key)


def test_qr_page_opens(demo_store):
    tag = d.active_assets()[0]["태그번호"]
    run_app(tag=tag)                          # 사용자 선택 전: 기본 정보 + 사람 고르기
    run_app({"user_id": "site"}, tag=tag)     # 현장 담당자로 열기
