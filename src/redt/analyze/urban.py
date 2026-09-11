"""여섯째 축 '주변 이용' — 법정동리 도시용지 비율과 그 검증.

docs/six-axes-method.md §4·§5. 관의 세 평가 체계(감정평가 환경조건 ·
토지가격비준표 · 토지적성평가 도시용지비율)가 공통으로 쓰는 요인 중
우리 레이더에 없던 것이다.

## 정의 (토지적성평가의 지역특성 지표와 같다)

    도시용지 비율 = 법정동리 안에서 이용상황이 주거·상업·업무·주상·공업인
                   필지 면적 ÷ (그것 + 농지 + 임야 면적)

도로·하천·공공용지·묘지처럼 값이 매겨지지 않는 땅은 분모에서 뺀다 —
넣으면 큰 하천 하나가 리 전체의 비율을 끌어내린다. 면적 가중이 적성평가의
정의다. 필지 수 기준도 함께 내 둔다(작은 필지가 촘촘한 취락이 큰 임야 한
필지에 묻히는 것을 보기 위해).

법정동리 = PNU 앞 10자리. `parcel` 표는 거래에 붙은 필지만이 아니라
훑은 칸의 필지 **전부(434만)** 를 갖고 있어서 이 집계는 DB 한 번이다.

## 검증 — 축으로 올리기 전에 (§5-2)

도로·형상·지세·용도지역·지목군·면적·연도·시군구를 통제한 헤도닉에
도시용지 비율을 넣어, **10%p 당 +3% 이상 · p<0.05 · 시도별 부호가 2/3
이상 일치** 이면 채택한다. 이 문턱 아래면 축이 아니라 주석으로 둔다.
결과는 data/processed/urban_check.json 에 남고, 내보내기(export-web)는
그 파일이 '채택' 일 때만 parcelstats.json 에 urban 을 싣는다 — 검증
안 된 축이 화면에 나가는 길을 코드로 막는다.
"""
from __future__ import annotations

import datetime as dt
import json
import math

import numpy as np
import pandas as pd

from ..config import PROCESSED
from ..usage import road_grade
from ..valuation import use_group, zone_group

RESULT = PROCESSED / "urban_check.json"

# 이용상황 → 세 갈래. 토지특성의 lad_use_sittn_nm 값이 이렇게 온다
# (단독·연립·아파트·주거나지·주거기타·상업용·업무용·상업나지·주상용·
#  공업용·공업나지·전·답·과수원·전기타·답기타·조림·자연림·토지임야·
#  목장용지·도로·하천·공원·공공용지·종교용지·묘지 …).
URBAN_KEYS = ("주거", "단독", "연립", "아파트", "다세대", "상업", "업무", "주상", "공업", "공장", "창고")
FARM_KEYS = ("전", "답", "과수", "목장", "농")
FOREST_KEYS = ("임야", "자연림", "조림", "토지임야", "임")

URBAN_CASE = f"""
    CASE
      WHEN {" OR ".join(f"use_situation LIKE '%{k}%'" for k in URBAN_KEYS)} THEN 'urban'
      WHEN {" OR ".join(f"use_situation LIKE '%{k}%'" for k in FOREST_KEYS)} THEN 'forest'
      WHEN {" OR ".join(f"use_situation LIKE '%{k}%'" for k in FARM_KEYS)} THEN 'farm'
      ELSE NULL
    END
"""

# 채택 문턱 (docs/six-axes-method.md §5-2)
MIN_EFFECT = 0.03          # 10%p 당 +3%
MAX_P = 0.05
MIN_SIDO_N = 5000
MIN_SIDO_AGREE = 2 / 3
MIN_UMD_PARCELS = 20       # 이보다 적은 동리의 비율은 우연이다


def umd_share(con) -> pd.DataFrame:
    """법정동리별 도시용지 비율. (umd, sigungu_cd, n, urban_area, urban_cnt)"""
    df = con.execute(f"""
        WITH c AS (
            SELECT substr(pnu, 1, 10) AS umd,
                   substr(pnu, 1, 5)  AS sigungu_cd,
                   {URBAN_CASE} AS cls,
                   coalesce(area_m2, 0) AS area
            FROM parcel
            WHERE pnu IS NOT NULL AND length(pnu) >= 10
        )
        SELECT umd, sigungu_cd,
               count(*) AS n,
               sum(CASE WHEN cls = 'urban' THEN area ELSE 0 END)
                 / nullif(sum(area), 0) AS urban_area,
               sum(CASE WHEN cls = 'urban' THEN 1 ELSE 0 END) * 1.0
                 / count(*) AS urban_cnt,
               sum(CASE WHEN cls = 'farm' THEN area ELSE 0 END)
                 / nullif(sum(area), 0) AS farm_area
        FROM c
        WHERE cls IS NOT NULL
        GROUP BY 1, 2
        HAVING count(*) >= {MIN_UMD_PARCELS}
    """).fetchdf()
    return df


def _quantiles(values, k: int = 10) -> list[float]:
    v = sorted(float(x) for x in values if x is not None and not math.isnan(x))
    if not v:
        return []
    n = len(v)
    return [round(v[min(n - 1, max(0, int(round(q / k * (n - 1)))))], 4)
            for q in range(k + 1)]


def for_web(con) -> dict:
    """화면용. 동리별 값과 시군구별 분위 경계 — parcelstats.json 의 urban."""
    df = umd_share(con)
    umd = {str(r.umd): round(float(r.urban_area), 4)
           for r in df.itertuples(index=False) if r.urban_area is not None}
    q = {}
    for code, g in df.groupby("sigungu_cd"):
        vals = [float(x) for x in g["urban_area"].dropna()]
        # 동리가 다섯도 안 되는 시군구는 분위가 서지 않는다 — 시도로 물러난다.
        if len(vals) >= 5:
            q[str(code)] = _quantiles(vals)
    q_sido = {}
    for code, g in df.assign(sido=df["sigungu_cd"].str[:2]).groupby("sido"):
        q_sido[str(code)] = _quantiles([float(x) for x in g["urban_area"].dropna()])
    return {"umd": umd, "q": q, "q_sido": q_sido, "min_parcels": MIN_UMD_PARCELS,
            "definition": "법정동리 안 주거·상업·공업 이용상황 필지의 면적 비율 (농지·임야 대비)"}


_ELIGIBLE_WHERE = """
        FROM trade t
        JOIN trade_parcel tp ON tp.trade_id = t.trade_id
        JOIN parcel pc ON pc.pnu = tp.pnu
        WHERE t.kind = 'land'
          AND NOT coalesce(t.is_cancelled, FALSE)
          AND t.price_per_m2 > 0 AND pc.area_m2 > 0
          AND t.deal_year >= {since_year}
"""


def eligible(con, since_year: int) -> int:
    """표본 상한을 걸기 전, 조건에 드는 거래 수. 표본이 상한보다 적게
    나오면 이 수가 이유를 말한다 — 조인이 얇은지, 연도가 좁은지."""
    return int(con.execute("SELECT count(*) " + _ELIGIBLE_WHERE.format(since_year=since_year))
               .fetchone()[0])


def _sample(con, since_year: int, limit: int) -> pd.DataFrame:
    # 표본은 **조건을 다 건 뒤에** 뽑는다. USING SAMPLE 을 WHERE 뒤에 그냥
    # 붙였더니 조인 결과에서 먼저 뽑고 연도를 걸러, 상한 15만에 2021년
    # 이후는 2.9만, 2016년 이후는 7.6만만 남았다 (run 1·2 실측). 부분
    # 질의로 감싸면 걸러진 것에서 뽑는다.
    return con.execute(f"""
        SELECT * FROM (
            SELECT t.trade_id, t.sigungu_cd, t.deal_year, t.price_per_m2, t.land_use,
                   pc.pnu, pc.jimok, pc.use_situation, pc.road_side, pc.shape, pc.slope,
                   pc.area_m2
            {_ELIGIBLE_WHERE.format(since_year=since_year)}
        ) USING SAMPLE {limit} ROWS
    """).fetchdf()


def check(con, since_year: int | None = None, limit: int = 150_000) -> dict:
    """헤도닉 검증. 결과 dict 를 돌려주고 저장은 하지 않는다."""
    import statsmodels.formula.api as smf

    since_year = since_year or dt.date.today().year - 5
    share = umd_share(con)[["umd", "urban_area", "urban_cnt", "n"]]
    n_eligible = eligible(con, since_year)
    df = _sample(con, since_year, limit)
    if df.empty:
        return {"adopted": False, "reason": "표본 없음 — 필지가 붙은 거래가 없다", "n": 0,
                "eligible": n_eligible}
    n_sampled = int(len(df))
    df["umd"] = df["pnu"].str.slice(0, 10)
    df = df.merge(share, on="umd", how="inner")
    n_with_share = int(len(df))
    df["grp"] = df["land_use"].map(zone_group)
    df["ug"] = [use_group(j, u) for j, u in zip(df["jimok"], df["use_situation"])]
    df["road_g"] = df["road_side"].map(road_grade)
    from ..parcelscore import shape_grade, slope_grade
    df["shape_g"] = df["shape"].map(shape_grade)
    df["slope_g"] = df["slope"].map(slope_grade)
    df = df.dropna(subset=["grp", "ug", "road_g", "urban_area"])
    df["shape_g"] = df["shape_g"].fillna(-1)
    df["slope_g"] = df["slope_g"].fillna(-1)
    df["urban10"] = df["urban_area"] * 10.0          # 10%p 단위
    df["lp"] = np.log(df["price_per_m2"])
    df["la"] = np.log(df["area_m2"])
    df["sido"] = df["sigungu_cd"].astype(str).str[:2]
    if len(df) < 1000:
        return {"adopted": False, "reason": f"표본 {len(df)}건 — 너무 얇다", "n": int(len(df))}

    def fit(sub: pd.DataFrame) -> dict:
        fe = " + C(deal_year)" + (" + C(sigungu_cd)" if sub["sigungu_cd"].nunique() > 1 else "")
        formula = ("lp ~ urban10 + C(road_g) + C(shape_g) + C(slope_g) + C(grp) + C(ug)"
                   " + la" + fe)
        m = smf.ols(formula, data=sub).fit(cov_type="HC1")
        b = float(m.params["urban10"])
        return {"n": int(m.nobs), "coef": round(b, 5),
                "effect_pct": round((math.exp(b) - 1) * 100, 2),
                "se": round(float(m.bse["urban10"]), 5),
                "p": round(float(m.pvalues["urban10"]), 5),
                "r2": round(float(m.rsquared), 3)}

    national = fit(df)
    # 시도별. 문턱(MIN_SIDO_N) 아래도 **적되 세지는 않는다** — 한 시도만
    # 문턱을 넘으면 '부호 일치 100%' 가 사실상 검사가 아니라는 것을
    # 읽는 사람이 알아야 한다.
    by_sido = {}
    for code, g in df.groupby("sido"):
        if len(g) >= 1000:
            by_sido[str(code)] = {**fit(g), "counted": bool(len(g) >= MIN_SIDO_N)}
    counted = {k: v for k, v in by_sido.items() if v["counted"]}
    agree = [v for v in counted.values() if v["coef"] > 0]
    agree_ratio = len(agree) / len(counted) if counted else 0.0
    agree_all = (sum(1 for v in by_sido.values() if v["coef"] > 0) / len(by_sido)
                 if by_sido else 0.0)

    # 통제 없이 본 원값도 남긴다 — 통제가 얼마나 먹었는지 보이도록.
    raw_corr = float(np.corrcoef(df["urban10"], df["lp"])[0, 1])

    adopted = (national["effect_pct"] / 100 >= MIN_EFFECT and national["p"] < MAX_P
               and (not counted or agree_ratio >= MIN_SIDO_AGREE))
    reasons = []
    if national["effect_pct"] / 100 < MIN_EFFECT:
        reasons.append(f"효과 {national['effect_pct']}% < {MIN_EFFECT * 100:.0f}%")
    if national["p"] >= MAX_P:
        reasons.append(f"p {national['p']} ≥ {MAX_P}")
    if counted and agree_ratio < MIN_SIDO_AGREE:
        reasons.append(f"시도 부호 일치 {agree_ratio:.0%} < {MIN_SIDO_AGREE:.0%}")
    caveats = []
    if len(counted) < 2:
        caveats.append(f"문턱({MIN_SIDO_N}건)을 넘는 시도가 {len(counted)}곳뿐 — 시도 일치 검사는 사실상 안 된 것")
    if n_sampled < limit and n_eligible <= limit:
        caveats.append(f"조건에 드는 거래가 {n_eligible:,}건이라 상한({limit:,})보다 적다")
    return {
        "adopted": bool(adopted),
        "reason": "채택 — 세 문턱을 다 넘었다" if adopted else " · ".join(reasons),
        "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "since_year": since_year,
        "n": int(len(df)),
        "counts": {"eligible": n_eligible, "sampled": n_sampled,
                   "with_share": n_with_share, "used": int(len(df))},
        "caveats": caveats,
        "umd_with_share": int(share.shape[0]),
        "raw_corr": round(raw_corr, 4),
        "national": national,
        "by_sido": by_sido,
        "sido_agree": round(agree_ratio, 3),
        "sido_counted": len(counted),
        "sido_agree_all": round(agree_all, 3),
        "thresholds": {"min_effect_per_10pp": MIN_EFFECT, "max_p": MAX_P,
                       "min_sido_agree": MIN_SIDO_AGREE, "min_sido_n": MIN_SIDO_N},
        "formula": "log(단가) ~ 도시용지비율×10 + 도로접면 + 형상 + 지세 + 용도지역군 + 지목군"
                   " + log(면적) + 연도 + 시군구 (HC1)",
    }


def save(result: dict) -> None:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")


def load() -> dict | None:
    if not RESULT.exists():
        return None
    try:
        return json.loads(RESULT.read_text(encoding="utf-8"))
    except ValueError:
        return None


def adopted() -> bool:
    r = load()
    return bool(r and r.get("adopted"))


def report(result: dict) -> str:
    """사람이 읽는 요약 (CLI · 워크플로 요약 · docs 에 그대로 붙인다)."""
    lines = [f"주변 이용 축 검증 — {'채택' if result.get('adopted') else '보류'}: {result.get('reason')}"]
    if "national" in result:
        n = result["national"]
        lines.append(f"  전국  n={n['n']:,}  도시용지 10%p 당 {n['effect_pct']:+.2f}%"
                     f"  (se {n['se']}, p {n['p']}, R² {n['r2']})  통제 전 상관 {result['raw_corr']}")
        lines.append(f"  법정동리 {result['umd_with_share']:,}곳 · {result['since_year']}년 이후 표본")
        c = result.get("counts") or {}
        if c:
            lines.append(f"  거래 조건에 듦 {c['eligible']:,} → 표본 {c['sampled']:,}"
                         f" → 동리 비율 붙음 {c['with_share']:,} → 회귀 {c['used']:,}")
        for code, v in sorted(result.get("by_sido", {}).items()):
            tag = "" if v.get("counted", True) else "  (문턱 미만 · 참고)"
            lines.append(f"  시도 {code}  n={v['n']:,}  {v['effect_pct']:+.2f}%  p {v['p']}{tag}")
        lines.append(f"  시도 부호 일치 {result['sido_agree']:.0%}"
                     f" (문턱 넘는 시도 {result.get('sido_counted', '?')}곳"
                     f" · 참고 포함 {result.get('sido_agree_all', 0):.0%})")
        for w in result.get("caveats") or []:
            lines.append(f"  ! {w}")
    return "\n".join(lines)
