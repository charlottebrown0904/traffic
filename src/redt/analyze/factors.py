"""미래 가치 인자 — 네 사건을 **함께 넣어 각각의 몫을 가른다**.

2026-09-14 지시. 처음에 나는 'IC → 산업단지 → 공장 → 인구는 한 사건의 네
이름이니 합치자' 고 적었다. 틀린 말이었다. 고속도로 없이 공장이 들어오고,
IC 없는 산업단지가 있고, 넷이 한꺼번에 오기도 하고 둘만 오기도 한다 —
각기 다른 계획으로 **독립적으로** 움직인다.

상관이 있다는 것과 같은 사건이라는 것은 다르다. 상관은 **합쳐서 없애는
것이 아니라 함께 넣어서 가르는 것**이다. 넷을 한 회귀에 같이 넣으면
계수는 '다른 셋을 붙든 채' 그 하나의 몫이 된다 (편효과). 그리고 같이
일어났을 때만 생기는 몫은 **교차항**이 따로 잡는다.

    ln(P) = α + Σ β_k·D_k + Σ γ_jk·D_j·D_k + 읍면동FE + 연도FE

    미래 가치 배율 = exp( Σ β_k·D_k + Σ γ_jk·D_j·D_k )

      · IC 만            → exp(β_ic)
      · 산단만           → exp(β_ind)
      · IC + 산단        → exp(β_ic + β_ind + γ_ic,ind)
        γ < 0 이면 겹치는 몫(둘을 그냥 곱하면 과대) — 그만큼 깎인다
        γ > 0 이면 같이 와야 생기는 몫 — 그만큼 더해진다

**γ 를 추정할 수 있느냐는 우리가 정하지 않는다. 표본이 정한다.** 열여섯
조합 중 관측이 얇은 칸은 교차항을 세울 수 없다. 그래서 추정보다 먼저
**조합 칸을 센다** (`cells`). 이것이 '산출 준비' 의 첫 걸음이고, 이 표를
보고서야 어떤 교차항을 넣을지 말할 수 있다.

단위는 **읍·면·동 × 연도** 다. 필지 단위로 하면 같은 동네가 수천 번
들어와 표준오차가 거짓으로 작아지고, 시군구 단위로 하면 IC 하나가 시
전체를 처치한 것이 된다. 읍면동이 사건의 거리 감쇠(0.5~5km)와 맞는 크기다.
"""
from __future__ import annotations

import math

import pandas as pd

# 사건별 거리 — 그 사건이 값에 닿는 범위. 우리 밴드 실측(0-1·1-3·3-5km)과
# 문헌의 역세권(500m) 통념에서 잡았다. 인구는 거리가 아니라 그 시군구 값이다.
TREATMENTS = [
    ("ic",  "IC 신설",   5.0),
    ("ind", "산업단지",  3.0),
    ("hsg", "택지지구",  3.0),
    ("pop", "인구 증가", None),
]
TREAT_KEYS = [k for k, _n, _r in TREATMENTS]
TREAT_NAME = {k: n for k, n, _r in TREATMENTS}

# 사건이 값에 반영되기 **시작하는** 시점. 지정·발표가 나면 완공 전부터
# 값이 움직이므로 LEAD_YEARS 만큼 앞당겨 켠다.
#
# **켠 뒤에는 끄지 않는다.** 처음에는 (-2, +5) 창으로 두었는데 그러면 2015년에
# 뚫린 IC 가 2022년 필지에는 없는 것이 된다 — 그 IC 는 여전히 거기 있다.
# 값의 수준 이동은 영구적이고, '몇 년에 걸쳐 반영되는가' 는 창이 아니라
# 상대연도별 계수(이벤트 스터디)가 답할 질문이다.
LEAD_YEARS = 2

# 인구는 이분법이 어색하지만, 다른 셋과 같은 표에 놓으려면 같은 모양이어야
# 한다. '그 해 그 시군구의 5년 인구 증가율이 전국 상위 4분의 1' 을 1 로 둔다.
POP_TOP_Q = 0.75
POP_WINDOW = 5


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def near(events: pd.DataFrame, lat: float, lon: float, radius_km: float) -> pd.DataFrame:
    """그 자리에서 radius 안에 든 사건. 위경도 상자로 먼저 거르고 거리로 확인.

    상자만 쓰면 모서리가 반경 밖인데도 들어온다 — 전국을 돌리면 그 차이가
    수천 건이다. 그래서 상자는 **빨리 거르는 용도**이고 판정은 거리가 한다.
    """
    if events.empty:
        return events
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(math.cos(math.radians(lat)), 0.2))
    box = events[(events["lat"].between(lat - dlat, lat + dlat))
                 & (events["lon"].between(lon - dlon, lon + dlon))]
    if box.empty:
        return box
    d = box.apply(lambda r: haversine_km(lat, lon, r["lat"], r["lon"]), axis=1)
    return box[d <= radius_km]


def panel(trades: pd.DataFrame, min_n: int = 3) -> pd.DataFrame:
    """거래 → 읍·면·동 × 연도 패널. 값은 중앙 ln 단가.

    중앙값을 쓰는 까닭: 한 동네에 큰 거래 한 건이 섞이면 평균이 통째로
    끌려간다. 그리고 셀에 min_n 건이 안 되면 버린다 — 한두 건짜리 중앙값은
    중앙값이 아니다.
    """
    need = {"umd_cd", "deal_year", "price_per_m2", "lat", "lon"}
    if trades.empty or not need.issubset(trades.columns):
        return pd.DataFrame()
    t = trades[trades["price_per_m2"] > 0].copy()
    t["ln_price"] = t["price_per_m2"].map(math.log)
    g = t.groupby(["umd_cd", "deal_year"])
    out = g.agg(ln_price=("ln_price", "median"), n=("price_per_m2", "size"),
                lat=("lat", "median"), lon=("lon", "median"),
                sigungu_cd=("sigungu_cd", "first")).reset_index()
    return out[out["n"] >= min_n].rename(columns={"deal_year": "year"})


def mark(pan: pd.DataFrame, events: dict, pop: pd.DataFrame | None = None) -> pd.DataFrame:
    """패널에 사건 표시 D_k 를 붙인다. events 는 {키: 사건표}.

    사건표에는 lat·lon·year 가 있어야 한다 (year 는 지정연도 또는 개통연도).
    """
    if pan.empty:
        return pan
    df = pan.copy()
    radius = {k: r for k, _n, r in TREATMENTS}
    for key, _name, rad in TREATMENTS:
        if rad is None:
            continue
        ev = events.get(key)
        if ev is None or len(ev) == 0:
            df[f"d_{key}"] = 0
            continue
        ev = pd.DataFrame(ev).dropna(subset=["lat", "lon", "year"])
        flags = []
        for row in df.itertuples(index=False):
            hit = near(ev, row.lat, row.lon, radius[key])
            on = 0
            if not hit.empty:
                # 이미 있었거나 곧 온다 — 한 번 켜지면 계속 켜져 있다.
                on = int((hit["year"] <= row.year + LEAD_YEARS).any())
            flags.append(on)
        df[f"d_{key}"] = flags
    # 인구는 거리가 아니라 그 시군구의 증가율이다.
    if pop is not None and not pop.empty:
        df = df.merge(pop[["sigungu_cd", "year", "d_pop"]],
                      on=["sigungu_cd", "year"], how="left")
        df["d_pop"] = df["d_pop"].fillna(0).astype(int)
    else:
        df["d_pop"] = 0
    return df


def pop_flags(region_year: pd.DataFrame) -> pd.DataFrame:
    """시군구 인구 → '최근 POP_WINDOW 년 증가율이 전국 상위 4분의 1' 표시."""
    if region_year.empty:
        return pd.DataFrame(columns=["sigungu_cd", "year", "d_pop"])
    p = region_year[region_year["metric"] == "population"].copy()
    if p.empty:
        return pd.DataFrame(columns=["sigungu_cd", "year", "d_pop"])
    p = p.sort_values(["sigungu_cd", "year"])
    p["base"] = p.groupby("sigungu_cd")["value"].shift(POP_WINDOW)
    p["growth"] = (p["value"] - p["base"]) / p["base"]
    p = p.dropna(subset=["growth"])
    out = []
    for year, blk in p.groupby("year"):
        cut = blk["growth"].quantile(POP_TOP_Q)
        blk = blk.assign(d_pop=(blk["growth"] >= cut).astype(int))
        out.append(blk[["sigungu_cd", "year", "d_pop"]])
    return pd.concat(out, ignore_index=True) if out else \
        pd.DataFrame(columns=["sigungu_cd", "year", "d_pop"])


def cells(df: pd.DataFrame) -> pd.DataFrame:
    """열여섯 조합이 각각 몇 칸인가. **추정보다 이 표가 먼저다.**

    어떤 조합이 얇으면 그 교차항은 못 세운다. 못 세우는 것을 세우면 계수가
    표본 몇 개에 휘둘리고, 그 숫자가 화면으로 나간다.
    """
    cols = [f"d_{k}" for k in TREAT_KEYS]
    if df.empty or not set(cols).issubset(df.columns):
        return pd.DataFrame()
    g = (df.groupby(cols)
         .agg(셀=("ln_price", "size"), 읍면동=("umd_cd", "nunique"),
              거래=("n", "sum"))
         .reset_index())
    g["조합"] = g.apply(
        lambda r: " + ".join(TREAT_NAME[k] for k in TREAT_KEYS if r[f"d_{k}"])
        or "없음", axis=1)
    g["사건수"] = g[cols].sum(axis=1)
    return g.sort_values(["사건수", "셀"], ascending=[True, False])


# 교차항을 세우려면 그 조합에 이만큼은 있어야 한다. 근거는 검정력이 아니라
# 신중함이다 — 읍면동 50곳 아래에서는 계수가 한두 동네에 끌려간다.
MIN_CELL_UMD = 50


def formula(df: pd.DataFrame, pairs: bool = True) -> str:
    """추정식. **셀 수가 받쳐 주는 교차항만 넣는다.**"""
    cols = [f"d_{k}" for k in TREAT_KEYS]
    have = [c for c in cols if c in df.columns and df[c].nunique() > 1]
    terms = list(have)
    if pairs:
        c = cells(df)
        for i, a in enumerate(have):
            for b in have[i + 1:]:
                both = c[(c[a] == 1) & (c[b] == 1)]
                if not both.empty and both["읍면동"].sum() >= MIN_CELL_UMD:
                    terms.append(f"{a}:{b}")
    fe = []
    if df["umd_cd"].nunique() > 1:
        fe.append("C(umd_cd)")
    if df["year"].nunique() > 1:
        fe.append("C(year)")
    return "ln_price ~ " + " + ".join(terms + fe)


def estimate(df: pd.DataFrame, pairs: bool = True):
    """읍면동FE · 연도FE 를 둔 이원고정효과. 표준오차는 시군구로 묶는다."""
    import statsmodels.formula.api as smf              # noqa: PLC0415
    data = df.dropna(subset=["ln_price", "umd_cd", "year"]).copy()
    if data.empty:
        return None
    res = smf.ols(formula(data, pairs), data=data)
    groups = data["sigungu_cd"].fillna("?")
    return res.fit(cov_type="cluster", cov_kwds={"groups": groups})


def multipliers(fit) -> pd.DataFrame:
    """계수 → 조합별 배율. 화면에 쓸 모양 그대로.

    하나만 온 경우와 같이 온 경우를 **따로** 적는다 — 그것이 이 설계의 요지다.
    """
    if fit is None:
        return pd.DataFrame()
    b = fit.params
    rows = []
    for k in TREAT_KEYS:
        key = f"d_{k}"
        if key in b:
            rows.append({"조합": TREAT_NAME[k], "배율": round(math.exp(b[key]), 3),
                         "p": round(float(fit.pvalues[key]), 3)})
    for i, a in enumerate(TREAT_KEYS):
        for c in TREAT_KEYS[i + 1:]:
            ka, kc = f"d_{a}", f"d_{c}"
            inter = f"{ka}:{kc}"
            if ka in b and kc in b and inter in b:
                tot = b[ka] + b[kc] + b[inter]
                rows.append({"조합": f"{TREAT_NAME[a]} + {TREAT_NAME[c]}",
                             "배율": round(math.exp(tot), 3),
                             "p": round(float(fit.pvalues[inter]), 3),
                             "겹친 몫": round(math.exp(b[inter]), 3)})
    return pd.DataFrame(rows)


# 개발사건을 갈래로 나누는 말. **칸이 아니라 갈래를 봐야 한다.**
#
# 2026-09-14. 첫 실행에서 산단·택지 조합이 **한 칸도** 안 나왔다. 사건이
# 없는 줄 알았는데 그게 아니었다. zones_housing.csv 189건은 모두 좌표가
# 있는 도시개발사업인데, 적재기가 type 칸에 넣은 것이 bizMthSeNm —
# 수용 · 환지 · 수용+환지, 즉 **땅을 어떻게 확보하는가** 였다. 사업의
# 갈래가 아니다. 그래서 '택지|주택|도시개발' 로 훑으면 하나도 안 걸린다.
#
# 연속지적도에서 배운 것과 같은 종류의 일이다: **0 은 소리를 내야 한다.**
# 갈래를 파일 이름(source)까지 함께 보고 정하고, 어느 갈래가 비었는지
# 부르는 쪽이 반드시 말하게 한다.
ZONE_MATCH = {
    "ind": "산업단지|산단|농공|industrial",
    "hsg": "택지|주택|도시개발|신도시|housing|residential",
}


def split_zones(zones: pd.DataFrame) -> dict:
    """zone_event → {갈래: 사건표}. type 과 source 를 **함께** 본다.

    적재기는 유형 칸이 없으면 파일 이름을 type 에 넣고, 있으면 그 칸을
    그대로 넣는다. 그 칸이 갈래가 아닐 수도 있으므로(수용·환지) 파일
    이름도 같이 훑는다. 둘 중 하나만 걸려도 그 갈래다.
    """
    out = {}
    if zones is None or len(zones) == 0:
        return {k: pd.DataFrame() for k in ZONE_MATCH}
    z = pd.DataFrame(zones)
    tag = (z.get("type", pd.Series("", index=z.index)).astype("string").fillna("")
           + " " +
           z.get("source", pd.Series("", index=z.index)).astype("string").fillna(""))
    for key, pat in ZONE_MATCH.items():
        out[key] = z[tag.str.contains(pat, case=False, na=False)]
    return out
