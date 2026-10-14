"""
AI 자산 요청 분석

법인차량 관리 AI와 같은 방식으로 Ollama가 자연어 요청을 JSON으로 구조화하고,
Python이 날짜·수량·금액·태그번호를 다시 보정합니다. Ollama가 꺼져 있어도
규칙 기반 분석으로 같은 화면을 쓸 수 있습니다.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

import data as d

try:
    import requests
except ImportError:
    requests = None

INTENTS = {
    "purchase": "구매요청",
    "transfer": "이동신청",
    "incident": "분실·파손 신고",
    "disposal": "처분 신청",
    "search": "자산 찾기",
}

ACCOUNT_KEYWORDS = [
    ("소프트웨어", ["소프트웨어", "라이선스", "라이센스", "SW", "프로그램", "ERP", "CAD", "오피스"]),
    ("차량운반구", ["차량", "트럭", "승합", "승용", "화물차", "카니발", "포터", "스타리아"]),
    ("기계장치", ["지게차", "컨베이어", "발전기", "기계", "설비", "프레스", "크레인", "3D 프린터", "3D프린터"]),
    ("공기구비품", ["측량", "레벨기", "토탈스테이션", "공구", "스캐너", "오실로", "계측", "드론", "파렛트", "용접기", "측정"]),
    ("비품", ["노트북", "PC", "컴퓨터", "데스크탑", "모니터", "프린터", "복합기", "책상", "의자", "프로젝터", "태블릿",
              "워크스테이션", "냉장고", "에어컨", "캐비닛", "서버"]),
]
ITEM_WORDS = sorted({w for _, words in ACCOUNT_KEYWORDS for w in words if len(w) >= 2}, key=len, reverse=True)


def guess_account(text: str) -> str:
    for account, words in ACCOUNT_KEYWORDS:
        if any(w.lower() in text.lower() for w in words):
            return account
    return "비품"


def _extract_json(text: str):
    text = d.clean_str(text)
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, flags=re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def call_ollama(prompt: str, settings: dict):
    if requests is None:
        return None, "requests 패키지가 없습니다."
    base = d.clean_str(settings.get("Ollama 주소")) or "http://127.0.0.1:11434"
    model = d.clean_str(settings.get("Ollama 모델")) or "qwen2.5vl:3b"
    try:
        r = requests.post(f"{base}/api/generate", json={"model": model, "prompt": prompt, "stream": False,
                                                          "format": "json", "options": {"temperature": 0.1}}, timeout=90)
        r.raise_for_status()
        result = _extract_json(r.json().get("response", ""))
        return (result, None) if isinstance(result, dict) else (None, "Ollama가 JSON을 반환하지 않았습니다.")
    except requests.exceptions.ConnectionError:
        return None, "Ollama에 연결할 수 없습니다."
    except requests.exceptions.Timeout:
        return None, "Ollama 응답 시간이 초과되었습니다."
    except Exception as exc:
        return None, f"Ollama 오류: {exc}"


# ---------------------------------------------------------
# 규칙 기반 보정
# ---------------------------------------------------------
def find_tags(text: str) -> list[str]:
    return [t.upper() for t in re.findall(r"\b[A-Za-z]{2,3}-\d{4}-\d{3,4}\b", text)]


def find_qty(text: str):
    m = re.search(r"(\d+)\s*(대|개|EA|ea|세트|식|copy|카피|명분|set)", text)
    return int(m.group(1)) if m else None


def find_price(text: str):
    m = re.search(r"(\d+(?:\.\d+)?)\s*억", text)
    if m:
        return int(float(m.group(1)) * 1e8)
    m = re.search(r"(\d+(?:,\d{3})*)\s*만\s*원?", text)
    if m:
        return int(m.group(1).replace(",", "")) * 10000
    m = re.search(r"(\d{1,3}(?:,\d{3})+|\d{5,})\s*원", text)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def find_date(text: str, base: date):
    if "내일" in text:
        return base + timedelta(days=1)
    if "모레" in text:
        return base + timedelta(days=2)
    if "다음주" in text or "다음 주" in text:
        return base - timedelta(days=base.weekday()) + timedelta(days=7 + 4)  # 다음 주 금요일
    if "이번주" in text or "이번 주" in text:
        return base - timedelta(days=base.weekday()) + timedelta(days=4)
    if "다음달" in text or "다음 달" in text:
        y, m = (base.year + 1, 1) if base.month == 12 else (base.year, base.month + 1)
        return date(y, m, 15)
    m = re.search(r"(\d{1,2})월\s*(\d{1,2})일", text)
    if m:
        try:
            target = date(base.year, int(m.group(1)), int(m.group(2)))
            return target if target >= base else date(base.year + 1, target.month, target.day)
        except ValueError:
            return None
    m = re.search(r"(\d+)\s*일\s*(안|이내|내)", text)
    if m:
        return base + timedelta(days=int(m.group(1)))
    return None


def find_item(text: str) -> str:
    for w in ITEM_WORDS:
        if w.lower() in text.lower():
            return w
    m = re.search(r"([가-힣A-Za-z0-9 ]{2,20}?)\s*\d+\s*(대|개|세트|EA)", text)
    return m.group(1).strip() if m else ""


def rule_intent(text: str) -> str:
    if re.search(r"분실|잃어|도난|훔|파손|깨졌|깨짐|고장|부서", text):
        return "incident"
    if re.search(r"폐기|매각|처분|불용|버리|기증", text):
        return "disposal"
    if re.search(r"이동|옮|보내|가져|빌려|재배치|넘겨", text):
        return "transfer"
    if re.search(r"구매|구입|사야|사고|살 |필요|요청|신청|주문", text):
        return "purchase"
    return "search"


def analyze(text: str, site: str, use_ollama: bool = True) -> tuple[dict, str, str | None]:
    """(결과, 분석 방식, 안내 문구)"""
    settings = d.get_settings()
    base = d.today()
    result, source, note = None, "규칙", None
    if use_ollama:
        prompt = f"""
너는 기업 총무팀의 자산관리 요청을 구조화하는 AI다.
오늘 날짜는 {base.isoformat()}이다. 요청자의 현장은 {site}이다.
계정과목은 {', '.join(d.ACCOUNT_NAMES)} 중 하나다.

요청:
{text}

반드시 JSON 하나만 반환해라. 설명이나 마크다운은 쓰지 마라.
{{
  "intent": "purchase|transfer|incident|disposal|search",
  "item": "품명",
  "spec": "규격 또는 빈 문자열",
  "qty": 숫자 또는 null,
  "unit_price": 원 단위 숫자 또는 null,
  "needed_by": "YYYY-MM-DD 또는 null",
  "account": "계정과목",
  "incident_type": "분실|도난|파손 또는 null",
  "reason": "요청 사유를 한 문장으로"
}}
규칙:
- 새로 사야 하면 purchase, 다른 현장 자산을 가져오거나 보내면 transfer, 잃어버리거나 고장·파손이면 incident,
  버리거나 팔거나 불용이면 disposal, 단순히 찾는 것이면 search.
- '노트북 2대'처럼 수량이 있으면 qty에 숫자만 넣는다. '150만원'은 1500000으로 바꾼다.
"""
        result, err = call_ollama(prompt, settings)
        if result:
            source = "Ollama " + (d.clean_str(settings.get("Ollama 모델")) or "")
        else:
            note = f"{err} 규칙 기반으로 분석했습니다."
    result = dict(result or {})
    # Python 보정 (AI가 놓친 부분 또는 Ollama 미사용)
    if result.get("intent") not in INTENTS:
        result["intent"] = rule_intent(text)
    if not d.clean_str(result.get("item")):
        result["item"] = find_item(text)
    qty = find_qty(text)
    if qty:
        result["qty"] = qty
    result["qty"] = int(d.to_num(result.get("qty"), 1) or 1)
    price = find_price(text)
    if price:
        result["unit_price"] = price
    result["unit_price"] = int(d.to_num(result.get("unit_price"), 0) or 0)
    when = find_date(text, base)
    result["needed_by"] = when or d.to_date(result.get("needed_by"))
    if result.get("account") not in d.ACCOUNTS:
        result["account"] = guess_account(f"{result.get('item', '')} {text}")
    threshold = d.capitalization_threshold()
    if result["unit_price"] and result["unit_price"] < threshold and result["account"] != "소프트웨어":
        result["account"] = "소모품"
    if result.get("incident_type") not in ("분실", "도난", "파손"):
        result["incident_type"] = "도난" if re.search(r"도난|훔", text) else "파손" if re.search(r"파손|깨|고장|부서", text) else "분실"
    result["tags"] = find_tags(text)
    result["reason"] = d.clean_str(result.get("reason")) or text.strip()[:120]
    result["spec"] = d.clean_str(result.get("spec"))
    return result, source, note


def match_assets(assets: list[dict], item: str, tags: list[str] | None = None) -> list[dict]:
    """품명·규격에 키워드가 들어간 자산(태그번호가 있으면 그 자산 우선)."""
    tags = [t.upper() for t in (tags or [])]
    if tags:
        hit = [a for a in assets if a["태그번호"].upper() in tags]
        if hit:
            return hit
    item = d.clean_str(item)
    if not item:
        return []
    words = [w for w in re.split(r"\s+", item) if len(w) >= 2] or [item]
    return [a for a in assets if any(w.lower() in f"{a['품명']} {a['규격']}".lower() for w in words)]
