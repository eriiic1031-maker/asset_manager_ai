"""
알림 요약 보내기 (매일 아침 자동 실행용)

    python notify.py            → 관리자 기준 알림을 설정된 메일·웹훅으로 보냅니다
    python notify.py --dry-run  → 보내지 않고 내용만 화면에 출력합니다

Windows 작업 스케줄러 등록 예 (매일 08:30):
    프로그램: C:\\자산관리\\.venv\\Scripts\\python.exe
    인수:     notify.py
    시작 위치: C:\\자산관리
메일 서버·계정·받는 사람, 웹훅 주소는 프로그램의 ⚙️ 설정 → 환경 설정에서 입력합니다.
"""
from __future__ import annotations

import argparse
import sys

import data as d
import ops


def admin_view() -> dict:
    """관리자 역할 기준(모든 현장)으로 알림을 모읍니다. 결재 대기는 단계와 상관없이 진행 중인 요청 전체로 셉니다."""
    return {"아이디": "", "이름": "알림", "역할": ops.ADMIN, "현장": ""}


def collect() -> list[dict]:
    pending = {k: [r for r in d.get_requests(k) if d.is_open(k, r)] for k in d.REQUEST_TABLES}
    return ops.alerts_for(admin_view(), pending)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="자산관리 AI 알림 요약 보내기")
    p.add_argument("--dry-run", action="store_true", help="보내지 않고 내용만 출력")
    args = p.parse_args(argv)
    d.init_storage()
    alerts = collect()
    text = ops.digest_text(alerts)
    if args.dry_run:
        print(text)
        return 0
    done = ops.send_digest(alerts)
    if not done:
        print("메일 서버나 웹훅 주소가 설정되지 않아 보내지 않았습니다. 설정 → 환경 설정을 확인하세요.")
        return 1
    print(" · ".join(done))
    return 0 if not any("실패" in x for x in done) else 2


if __name__ == "__main__":
    sys.exit(main())
