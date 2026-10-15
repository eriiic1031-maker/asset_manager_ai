"""
카메라 사진에서 QR 코드 읽기

재물조사 화면의 '📷 카메라로 스캔'에서 st.camera_input으로 찍은 사진을 받아
QR 안의 글자(태그번호 또는 '...?tag=태그번호' 주소)를 돌려줍니다.
OpenCV(opencv-python-headless)가 없으면 None을 돌려주고, 화면에서 안내 문구를 보여 줍니다.
"""
from __future__ import annotations

import io

try:
    import cv2
    import numpy as np
except ImportError:  # requirements 설치 전
    cv2 = None
    np = None


def available() -> bool:
    return cv2 is not None


def decode(image_bytes: bytes) -> str | None:
    """사진 bytes → QR 글자. 못 읽으면 None."""
    if cv2 is None or not image_bytes:
        return None
    try:
        from PIL import Image, ImageOps
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes))).convert("RGB")
        arr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    except Exception:
        return None
    detector = cv2.QRCodeDetector()
    gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
    # 원본 → 흑백 → 대비 보정 → 확대 순서로 시도 (휴대폰 사진은 흐리거나 작게 찍히는 경우가 많습니다)
    candidates = [arr, gray, cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]]
    h, w = gray.shape[:2]
    if max(h, w) < 1200:
        candidates.append(cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC))
    for img in candidates:
        try:
            text, _, _ = detector.detectAndDecode(img)
        except cv2.error:
            continue
        if text:
            return text.strip()
    return None
