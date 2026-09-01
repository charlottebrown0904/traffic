"""영업소 코드 정규화.

교통량 파일과 도로공사 API 가 같은 영업소를 다르게 적는다.

  파일  영업소코드 = 11   (정수. 변환 과정에서 앞의 0 이 떨어졌다)
  API   unitCode  = "011 "  (문자열. 세 자리로 채우고 뒤에 공백)

이대로 조인하면 100 미만 코드 25개가 통째로 어긋난다. 오류가 아니라 그냥
'짝이 없음' 으로 조용히 빠지므로, 패널이 비어도 이유를 알기 어렵다. 실제로
한 번 그렇게 비었다.

그래서 양쪽을 같은 규칙으로 접는다 — 숫자면 앞의 0 을 떼고, 숫자가 아니면
(합성 데이터의 'TG001' 같은 것) 공백만 정리해 그대로 둔다.
"""
from __future__ import annotations

import pandas as pd


def canon_tollgate_id(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    # 판다스가 결측이 섞인 정수 컬럼을 float 로 읽어오면 2 가 2.0 이 된다.
    # 그대로 문자열로 만들면 '2.0' 이 되어 어느 쪽과도 짝이 맞지 않는다.
    if isinstance(value, (int, float)) and float(value).is_integer():
        value = int(value)
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if not text or text.lower() == "nan":
        return None
    digits = text.lstrip("0") if text.isdigit() else text
    return digits or "0"


def canon_series(col: pd.Series) -> pd.Series:
    return col.map(canon_tollgate_id)
