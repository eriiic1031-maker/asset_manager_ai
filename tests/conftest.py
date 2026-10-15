import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import data as d  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, request):
    """모든 테스트는 빈 임시 DB를 씁니다(실제 data 폴더는 건드리지 않음). 화면 테스트는 자체 DB를 씁니다."""
    if "demo_store" in request.fixturenames:
        yield
        return
    d.use_data_dir(tmp_path / "data")
    d.init_storage()
    yield
    d.use_data_dir(tmp_path / "data_closed")


@pytest.fixture()
def store():
    return d


@pytest.fixture()
def one_laptop(store):
    """본사에 노트북 1대를 등록하고 태그번호를 돌려줍니다."""
    tags = store.register_assets({"품명": "노트북", "규격": "LG gram", "계정과목": "비품", "현장": "본사",
                                  "취득일자": store.today().replace(year=store.today().year - 6), "취득가액": 2_000_000},
                                 1, "테스트")
    return tags[0]
