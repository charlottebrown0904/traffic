"""세 가설을 한 자리에서 판정한다.

  H1  IC 가 새로 뚫리면 주변 지가는 오른다.
  H2  IC 통행량(특히 화물)이 늘면 주변 지가는 오른다.
  H3  주변 인구·산업단지·택지지구가 늘면 지가는 오른다.

왜 셋을 따로 돌리면 안 되는가
-----------------------------
H3 는 세 번째 질문이면서 **동시에 H1·H2 의 교란**이다. IC 가 뚫린 그 해에
옆에 산업단지가 지정됐다면, 산단이 만든 상승을 IC 공으로 돌리게 된다.
세 가설을 따로 돌려 각각 '유의함' 을 얻으면, 같은 상승을 세 번 세는 것이다.

그래서 H1·H2 를 **H3 통제를 넣기 전과 후로 나란히** 보고한다. 통제를 넣자
계수가 사라지면 그건 IC 효과가 아니었다는 뜻이고, 그렇게 쓴다.

각 가설의 판정 기준
-------------------
가설마다 '무엇을 보면 참이라고 할 수 있는가' 를 미리 정해 둔다. 결과를
보고 기준을 고르면 무엇이든 증명할 수 있다.

  H1  이중차분 교차항이 유의(p<0.05)하고 양수 · 개통 **전** 계수는 유의하지
      않을 것(평행추세) · H3 통제 후에도 살아남을 것
  H2  영향범위 밴드에서 β 가 유의하고 양수 · **위약 밴드(5-10km)에서는
      유의하지 않을 것** · H3 통제 후에도 살아남을 것
  H3  산단 지정 이벤트의 교차항 또는 인구 증가율 계수가 유의하고 양수일 것

셋 중 하나라도 표본이 모자라면 '기각' 이 아니라 '아직 모름' 이다. 이 둘을
섞으면 안 된다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

# 판정에 쓰는 기준. 결과를 보고 고치지 않는다.
ALPHA = 0.05
MIN_OBS = 50
MIN_CLUSTERS = 10


class Verdict:
    SUPPORT = "지지"
    REJECT = "기각"
    UNKNOWN = "아직 모름"
    CONFOUNDED = "교란 — IC 효과로 볼 수 없음"
    # 수준 비교(H4·H5)는 서로 다른 장소를 견준다. 관계가 있어도 인과가
    # 아니다. '지지' 와 같은 칸에 넣으면 읽는 사람이 구별할 방법이 없어서
    # 판정 이름 자체를 다르게 둔다.
    CORRELATED = "관계 있음 (상관 · 인과 아님)"


def _fit(data: pd.DataFrame, formula: str, cluster: str):
    return smf.ols(formula, data=data).fit(
        cov_type="cluster", cov_kwds={"groups": data[cluster]})


# 최소 탐지 가능 효과(MDE). 표준오차 하나로 계산한다.
#
#   MDE ≈ (z(1-α/2) + z(검정력)) × se = (1.96 + 0.84) × se
#
# 뜻은 이렇다. **이 표본으로는 MDE 보다 작은 효과는 있어도 못 찾는다.**
# 계수가 0.1 로 나왔고 MDE 가 0.35 면, "효과가 0.1" 이 아니라 "0.35 미만이면
# 뭐든 이렇게 보인다" 는 뜻이다. 이 한 줄이 없으면 표본이 작아서 못 잡은
# 것을 '효과 없음' 으로 읽는다 — 공장이 정확히 그 처지다.
MDE_K = 2.80


def _row(model, term: str, label: str, n: int, clusters: int) -> dict:
    if model is None or term not in model.params:
        return {"항": label, "n": n, "영업소": clusters, "beta": np.nan,
                "se": np.nan, "p": np.nan, "mde": np.nan}
    se = float(model.bse[term])
    return {"항": label, "n": n, "영업소": clusters,
            "beta": float(model.params[term]), "se": se,
            "p": float(model.pvalues[term]), "mde": MDE_K * se}


# ────────────────────────────────────────────────────────────────
# H3 통제 만들기
# ────────────────────────────────────────────────────────────────

def region_controls(region: pd.DataFrame) -> pd.DataFrame:
    """시군구×연도 지표를 **변화율**로 바꾼다.

    수준(인구 몇 명)은 시군구 고정효과에 흡수된다. 변화가 통제로 쓸모 있다.
    """
    if region is None or region.empty:
        return pd.DataFrame(columns=["sigungu_cd", "year"])
    wide = (region.pivot_table(index=["sigungu_cd", "year"], columns="metric",
                               values="value", aggfunc="first")
            .reset_index().sort_values(["sigungu_cd", "year"]))
    for col in [c for c in wide.columns if c not in ("sigungu_cd", "year")]:
        ln = np.log(wide[col].where(wide[col] > 0))
        wide[f"d_ln_{col}"] = ln.groupby(wide["sigungu_cd"]).diff()
    return wide


def zone_pressure(zones: pd.DataFrame, links: pd.DataFrame,
                  years: list[int], kinds: tuple[str, ...] = ()) -> pd.DataFrame:
    """영업소×연도별 '그 해까지 주변에 지정된 개발면적'.

    누적으로 두는 데 이유가 있다. 산단은 지정된 해에만 영향을 주고 사라지지
    않는다. 지정 이후로 계속 그 자리에 있으므로 누적 면적이 '개발 압력' 이다.
    변화량은 회귀에서 diff 로 만들어진다.
    """
    cols = ["tollgate_id", "year", "zone_area_km2", "zone_n"]
    if zones is None or zones.empty or links is None or links.empty:
        return pd.DataFrame(columns=cols)

    z = zones.dropna(subset=["designated_date"]).copy()
    if kinds:
        z = z[z["type"].isin(kinds)]
    if z.empty:
        return pd.DataFrame(columns=cols)
    z["open_year"] = pd.to_datetime(z["designated_date"], errors="coerce").dt.year
    z = z.dropna(subset=["open_year"])

    joined = links.merge(z[["zone_id", "open_year", "area_m2"]], on="zone_id", how="inner")
    rows = []
    for tid, grp in joined.groupby("tollgate_id"):
        for year in years:
            active = grp[grp["open_year"] <= year]
            rows.append({"tollgate_id": tid, "year": year,
                         "zone_area_km2": float(active["area_m2"].sum()) / 1e6,
                         "zone_n": int(len(active))})
    return pd.DataFrame(rows, columns=cols)


def attach_controls(panel: pd.DataFrame, region: pd.DataFrame | None,
                    pressure: pd.DataFrame | None) -> tuple[pd.DataFrame, list[str]]:
    """패널에 H3 통제를 붙이고, 실제로 쓸 수 있는 통제 이름을 함께 돌려준다.

    붙였다고 쓸 수 있는 게 아니다. 결측이 많으면 그 통제를 넣는 순간 표본이
    반으로 줄어 계수가 통제 때문에 변한 것인지 표본이 바뀌어서인지 알 수
    없게 된다. 그래서 결측률을 보고 쓸 것만 고른다.
    """
    out = panel.copy()
    usable: list[str] = []

    ctrl = region_controls(region) if region is not None else pd.DataFrame()
    if not ctrl.empty:
        keep = ["sigungu_cd", "year"] + [c for c in ctrl.columns if c.startswith("d_ln_")]

        # **붙기 전에 열쇠가 맞는지 본다.** KOSIS 의 지역코드는 법정동
        # 코드와 다른 체계다(부산 KOSIS 21 vs 법정동 26). 다른 체계끼리
        # 조인하면 예외가 아니라 전부 결측이 되고, 아래 결측률 검사가
        # "결측 100%" 라고만 말한다. 그것은 '자료가 드물다' 로 읽히지만
        # 사실은 '열쇠가 틀렸다' 이고, 고치는 방법이 전혀 다르다.
        # 자료를 더 모아도 영원히 안 붙는다.
        hit = out["sigungu_cd"].astype(str).isin(
            set(ctrl["sigungu_cd"].astype(str)))
        share = float(hit.mean()) if len(out) else 0.0
        if share < 0.05:
            pv = sorted(set(out["sigungu_cd"].astype(str)))[:3]
            cv = sorted(set(ctrl["sigungu_cd"].astype(str)))[:3]
            print(f"  ⚠ 시군구 코드가 서로 안 맞습니다 (겹침 {share:.1%}) — "
                  f"자료가 없는 게 아니라 **코드 체계가 다릅니다**")
            print(f"      패널 쪽 예: {pv}")
            print(f"      지역 쪽 예: {cv}")
            print(f"      KOSIS 코드라면 지역명(C1_NM)으로 맞춰야 합니다.")
        elif share < 0.9:
            # 같은 체계면 거의 다 맞아야 한다. 90% 는 '조금 빠졌다' 가
            # 아니라 구조적으로 어긋났다는 뜻이다 — 행정구역 개편으로
            # 코드가 바뀐 시군구(화성 41590 → 41591·41593…)가 통제 없이
            # 남는다.
            missing = sorted(set(out.loc[~hit, "sigungu_cd"].astype(str)))
            print(f"  ⚠ 시군구 코드가 {share:.0%} 만 맞습니다 — "
                  f"안 맞는 {len(missing)}개는 통제 없이 남습니다")
            print(f"      예: {missing[:5]}")

        out = out.merge(ctrl[keep], on=["sigungu_cd", "year"], how="left")
        for col in [c for c in keep if c.startswith("d_ln_")]:
            miss = out[col].isna().mean()
            if miss < 0.3:
                usable.append(col)
            else:
                print(f"  통제 제외: {col} — 결측 {miss:.0%}")

    if pressure is not None and not pressure.empty:
        out = out.merge(pressure, on=["tollgate_id", "year"], how="left")
        out["zone_area_km2"] = out["zone_area_km2"].fillna(0.0)
        key = ["tollgate_id", "band", "kind"]
        out = out.sort_values(key + ["year"])
        out["d_zone_area"] = out.groupby(key)["zone_area_km2"].diff()
        if out["d_zone_area"].notna().sum() > MIN_OBS:
            usable.append("d_zone_area")
        else:
            print("  통제 제외: d_zone_area — 관측이 모자랍니다")

    return out, usable


# ────────────────────────────────────────────────────────────────
# H2 — 교통량 탄력성, 통제 전후
# ────────────────────────────────────────────────────────────────

def h2(panel: pd.DataFrame, volume_col: str, controls: list[str],
       lag: int = 1, kind: str = "land") -> pd.DataFrame:
    """밴드별 β 를 통제 전/후로 나란히. 위약 밴드가 판정의 핵심이다."""
    treat = f"d_ln_{volume_col}_lag{lag}"
    need = ["d_ln_price", treat, "year", "sigungu_cd", "tollgate_id", "band"]
    if any(c not in panel.columns for c in need):
        return pd.DataFrame()

    df = panel[panel["kind"] == kind].dropna(subset=need)
    rows = []
    for band, grp in df.groupby("band"):
        base = grp.dropna(subset=[treat, "d_ln_price"])
        n, cl = len(base), base["tollgate_id"].nunique()
        if n < MIN_OBS or cl < MIN_CLUSTERS:
            rows.append({"밴드": band, "모형": "통제 전", "n": n, "영업소": cl,
                         "beta": np.nan, "se": np.nan, "p": np.nan, "mde": np.nan,
                              "비고": "표본 부족"})
            continue

        fe = " + C(year)" + (" + C(sigungu_cd)" if base["sigungu_cd"].nunique() > 1 else "")
        m0 = _fit(base, f"d_ln_price ~ {treat}{fe}", "tollgate_id")
        rows.append({**_row(m0, treat, treat, n, cl), "밴드": band, "모형": "통제 전", "비고": ""})

        have = [c for c in controls if c in base.columns]
        adj = base.dropna(subset=have) if have else base
        if have and len(adj) >= MIN_OBS and adj["tollgate_id"].nunique() >= MIN_CLUSTERS:
            fe2 = " + C(year)" + (" + C(sigungu_cd)" if adj["sigungu_cd"].nunique() > 1 else "")
            m1 = _fit(adj, f"d_ln_price ~ {treat} + {' + '.join(have)}{fe2}", "tollgate_id")
            rows.append({**_row(m1, treat, treat, len(adj), adj["tollgate_id"].nunique()),
                         "밴드": band, "모형": "H3 통제 후", "비고": "+".join(have)})
        else:
            rows.append({"밴드": band, "모형": "H3 통제 후", "n": len(adj),
                         "영업소": adj["tollgate_id"].nunique() if len(adj) else 0,
                         "beta": np.nan, "se": np.nan, "p": np.nan, "mde": np.nan,
                         "비고": "통제 없음" if not have else "통제 후 표본 부족"})

    cols = ["밴드", "모형", "n", "영업소", "beta", "se", "p", "mde", "비고"]
    if not rows:
        return pd.DataFrame(columns=cols)
    out = pd.DataFrame(rows)
    out["_lo"] = out["밴드"].str.split("-").str[0].astype(float)
    return out.sort_values(["_lo", "모형"]).drop(columns="_lo")[cols]


def judge_h2(table: pd.DataFrame, influence_max_km: float = 5.0) -> tuple[str, str]:
    """H2 판정. 위약 밴드를 먼저 본다 — 여기가 유의하면 나머지는 볼 필요가 없다."""
    if table.empty:
        return Verdict.UNKNOWN, "추정된 밴드가 없습니다."

    def far(b: str) -> float:
        return float(b.split("-")[1])

    after = table[table["모형"] == "H3 통제 후"]
    use = after if after["beta"].notna().any() else table[table["모형"] == "통제 전"]
    label = "H3 통제 후" if after["beta"].notna().any() else "통제 전(H3 통제 없음)"

    placebo = use[use["밴드"].map(far) > influence_max_km]
    inner = use[use["밴드"].map(far) <= influence_max_km]

    if placebo.empty or placebo["beta"].isna().all():
        return (Verdict.UNKNOWN,
                "위약 밴드를 추정하지 못했습니다. 위약 검정 없이는 IC 효과라고"
                " 말할 수 없습니다.")
    pl = placebo.dropna(subset=["beta"]).iloc[0]
    if pl["p"] < ALPHA:
        return (Verdict.CONFOUNDED,
                f"위약 밴드({pl['밴드']}km)에서도 β={pl['beta']:+.2f}(p={pl['p']:.3f})로"
                " 유의합니다. IC 주변만의 효과가 아니라 지역 전체의 움직임입니다.")

    est = inner.dropna(subset=["beta"])
    if est.empty:
        return Verdict.UNKNOWN, "영향범위 밴드를 추정하지 못했습니다."
    sig = est[(est["p"] < ALPHA) & (est["beta"] > 0)]
    if sig.empty:
        # 유의한 **음수** 는 '아직 모름' 이 아니다. 가설과 반대 방향이라는
        # 정보가 있는 결과다. 둘을 섞으면 반대 증거를 못 본 척하게 된다.
        neg = est[(est["p"] < ALPHA) & (est["beta"] < 0)]
        if len(neg):
            r = neg.sort_values("beta").iloc[0]
            return (Verdict.REJECT,
                    f"{r['밴드']}km 에서 β={r['beta']:+.2f}(p={r['p']:.3f})로 유의하지만"
                    " **음수**입니다. 교통량이 늘수록 그 구간 땅값이 내려갔다는 뜻으로,"
                    " 가설과 반대 방향입니다.")
        return (Verdict.UNKNOWN,
                f"위약은 깨끗하지만({pl['밴드']}km p={pl['p']:.2f}) 영향범위에서"
                " 유의한 양수 계수가 없습니다. 효과가 없다는 뜻이 아니라"
                " 이 표본으로는 판정할 수 없다는 뜻입니다.")
    best = sig.sort_values("beta", ascending=False).iloc[0]
    return (Verdict.SUPPORT,
            f"{label} 기준 {best['밴드']}km 에서 β={best['beta']:+.2f}"
            f"(p={best['p']:.3f}), 위약 {pl['밴드']}km 는 p={pl['p']:.2f}로 깨끗합니다.")


# ────────────────────────────────────────────────────────────────
# H1 — 개통 이벤트, H3 통제 전후
# ────────────────────────────────────────────────────────────────

def h1(event_df: pd.DataFrame, controls: list[str]) -> pd.DataFrame:
    """이중차분 교차항을 통제 전/후로. event_df 는 analyze.events.build 결과."""
    need = ["adj_ln_price", "treated", "post", "year", "sigungu_cd", "tollgate_id"]
    if event_df is None or event_df.empty or any(c not in event_df for c in need):
        return pd.DataFrame(columns=["모형", "n", "영업소", "beta", "se", "p", "mde", "비고"])

    base = event_df.dropna(subset=need)
    rows = []
    n, cl = len(base), base["tollgate_id"].nunique()
    if n < MIN_OBS or base["post"].nunique() < 2 or base["treated"].nunique() < 2:
        return pd.DataFrame([{"모형": "통제 전", "n": n, "영업소": cl, "beta": np.nan,
                              "se": np.nan, "p": np.nan, "비고": "표본 부족"}])

    fe = " + C(year)" + (" + C(sigungu_cd)" if base["sigungu_cd"].nunique() > 1 else "")
    m0 = _fit(base, f"adj_ln_price ~ treated * post{fe}", "tollgate_id")
    rows.append({**_row(m0, "treated:post", "treated:post", n, cl),
                 "모형": "통제 전", "비고": ""})

    have = [c for c in controls if c in base.columns]
    adj = base.dropna(subset=have) if have else base
    if have and len(adj) >= MIN_OBS and adj["tollgate_id"].nunique() >= 2:
        fe2 = " + C(year)" + (" + C(sigungu_cd)" if adj["sigungu_cd"].nunique() > 1 else "")
        m1 = _fit(adj, f"adj_ln_price ~ treated * post + {' + '.join(have)}{fe2}",
                  "tollgate_id")
        rows.append({**_row(m1, "treated:post", "treated:post",
                            len(adj), adj["tollgate_id"].nunique()),
                     "모형": "H3 통제 후", "비고": "+".join(have)})
    else:
        rows.append({"모형": "H3 통제 후", "n": len(adj),
                     "영업소": adj["tollgate_id"].nunique() if len(adj) else 0,
                     "beta": np.nan, "se": np.nan, "p": np.nan, "mde": np.nan,
                     "비고": "통제 없음" if not have else "통제 후 표본 부족"})

    cols = ["모형", "n", "영업소", "beta", "se", "p", "mde", "비고"]
    return pd.DataFrame(rows)[cols]


def judge_h1(table: pd.DataFrame, pre_trend_ok: bool | None) -> tuple[str, str]:
    """H1 판정. 평행추세가 깨졌으면 계수가 아무리 커도 IC 효과가 아니다."""
    if table.empty or table["beta"].isna().all():
        return Verdict.UNKNOWN, "개통 전후를 비교할 표본이 없습니다."

    after = table[table["모형"] == "H3 통제 후"].dropna(subset=["beta"])
    row = after.iloc[0] if len(after) else table.dropna(subset=["beta"]).iloc[0]
    label = row["모형"]

    if pre_trend_ok is False:
        return (Verdict.CONFOUNDED,
                "개통 **전** 계수가 유의합니다. 처치군이 개통 전부터 이미 더 빨리"
                " 오르고 있었으므로, 개통 후 차이를 IC 가 만들었다고 볼 수 없습니다.")

    ci = 1.96 * row["se"]
    span = f"{np.expm1(row['beta'] - ci):+.0%}~{np.expm1(row['beta'] + ci):+.0%}"
    if row["p"] >= ALPHA:
        return (Verdict.UNKNOWN,
                f"{label} 교차항 {row['beta']:+.3f}(p={row['p']:.2f}), 95% 구간 {span}."
                " 0 을 품고 있어 있는지 없는지 말할 수 없습니다 — '효과가 없다'"
                " 와는 다릅니다.")
    if row["beta"] <= 0:
        return (Verdict.REJECT,
                f"{label} 교차항이 음수({row['beta']:+.3f}, p={row['p']:.3f})입니다."
                " 가설과 반대 방향입니다.")
    return (Verdict.SUPPORT,
            f"{label} 교차항 {row['beta']:+.3f}(p={row['p']:.3f}) → 대조군 대비"
            f" {np.expm1(row['beta']):+.1%}, 95% 구간 {span}.")


# ────────────────────────────────────────────────────────────────
# H3 — 인구·산단 자체의 효과
# ────────────────────────────────────────────────────────────────

def h3(panel: pd.DataFrame, controls: list[str], kind: str = "land") -> pd.DataFrame:
    """통제로 쓰던 변수들을 이번엔 **주인공** 으로 놓고 계수를 본다."""
    cols = ["변수", "n", "영업소", "beta", "se", "p", "mde"]
    if not controls:
        return pd.DataFrame(columns=cols)
    need = ["d_ln_price", "year", "sigungu_cd", "tollgate_id"]
    df = panel[panel["kind"] == kind]
    rows = []
    for col in controls:
        if col not in df.columns:
            continue
        sub = df.dropna(subset=need + [col])
        if len(sub) < MIN_OBS or sub["tollgate_id"].nunique() < MIN_CLUSTERS:
            rows.append({"변수": col, "n": len(sub),
                         "영업소": sub["tollgate_id"].nunique() if len(sub) else 0,
                         "beta": np.nan, "se": np.nan, "p": np.nan, "mde": np.nan})
            continue
        fe = " + C(year)" + (" + C(sigungu_cd)" if sub["sigungu_cd"].nunique() > 1 else "")
        m = _fit(sub, f"d_ln_price ~ {col}{fe}", "tollgate_id")
        # _row 는 이름 칸을 '항' 으로 준다. 이 표의 첫 칸 이름은 '변수' 다.
        # 그대로 넣으면 표본이 모자란 줄(위쪽)과 칸 이름이 어긋나고,
        # **성공한 줄만 있을 때는 '변수' 칸이 아예 없어 KeyError 로 죽는다.**
        # H3 통제가 하나도 없던 동안에는 이 자리에 닿을 일이 없어 드러나지
        # 않았다 — 인구를 넣은 첫 실행에서 판정이 통째로 안 나왔다.
        got = _row(m, col, col, len(sub), sub["tollgate_id"].nunique())
        got["변수"] = got.pop("항")
        rows.append(got)
    out = pd.DataFrame(rows)
    if not len(out):
        return pd.DataFrame(columns=cols)
    missing = [c for c in cols if c not in out.columns]
    if missing:                       # 있어서는 안 되는 일이지만, 조용히 죽지 않게
        raise ValueError(f"h3 표에 칸이 없습니다: {missing} (있는 칸: {list(out.columns)})")
    return out[cols]


# ────────────────────────────────────────────────────────────────
# H4 · 교통량이 **많은 곳**이 비싼가 (수준 비교)
# H5 · 인구도 많고 교통량도 많으면 비싼가
#
# H1·H2 와 성격이 다르다. 저쪽은 같은 곳을 시간 앞뒤로 견주므로 그 장소의
# 고유한 성질이 저절로 빠진다. 이쪽은 **서로 다른 장소**를 견준다.
#
# 그래서 여기서 나오는 "비싸다" 는 상관이지 인과가 아니다. 교통량이 많은
# 곳은 도시 근처이고 도시 근처는 원래 비싸다 — 실제로 교통량과 서울 거리의
# 상관이 64~65% 다. 판정에 '(상관)' 을 붙여 그 사실을 판정 자체에 박는다.
# 자세한 것은 docs/hypotheses-design.md.
# ────────────────────────────────────────────────────────────────

LEVEL_MIN_OBS = 12          # IC 한 곳이 한 행이라 표본이 원래 작다


def _level_fit(table: pd.DataFrame, formula: str, term: str,
               label: str) -> dict:
    """수준 회귀 한 줄. 군집이 없으므로 이분산에 강한 표준오차를 쓴다."""
    try:
        model = smf.ols(formula, data=table).fit(cov_type="HC1")
    except Exception as exc:                          # noqa: BLE001
        return {"모형": label, "n": len(table), "영업소": len(table),
                "beta": np.nan, "se": np.nan, "p": np.nan, "mde": np.nan,
                "비고": str(exc)[:50]}
    got = _row(model, term, label, int(model.nobs), int(model.nobs))
    got["모형"] = got.pop("항")
    got["비고"] = f"R²={model.rsquared:.3f}"
    return got


LEVEL_COLS = ["모형", "n", "영업소", "beta", "se", "p", "mde", "비고"]


def h4(table: pd.DataFrame) -> pd.DataFrame:
    """교통량 수준 → 지가 수준. 통제를 하나씩 얹어 계수가 어떻게 변하는지.

    세 줄을 나란히 놓는 것이 핵심이다. **통제를 넣을 때 계수가 얼마나
    줄어드는지**가 답이다 — 그대로면 교통량이 따로 말하는 것이 있고,
    사라지면 교통량은 '서울에서 가깝다' 의 다른 이름이었다."""
    if table is None or table.empty or len(table) < LEVEL_MIN_OBS:
        return pd.DataFrame(columns=LEVEL_COLS)
    need = ["ln_price", "ln_traffic"]
    df = table.dropna(subset=need)
    if len(df) < LEVEL_MIN_OBS:
        return pd.DataFrame(columns=LEVEL_COLS)

    specs = [("통제 전", "ln_price ~ ln_traffic")]
    if "ln_km_seoul" in df and df["ln_km_seoul"].notna().sum() > LEVEL_MIN_OBS:
        specs.append(("+서울거리", "ln_price ~ ln_traffic + ln_km_seoul"))
    if "sido" in df and df["sido"].nunique() > 1:
        specs.append(("시도 안", "ln_price ~ ln_traffic + C(sido)"))
    rows = [_level_fit(df, f, "ln_traffic", label) for label, f in specs]
    return pd.DataFrame(rows)[LEVEL_COLS]


def h5(table: pd.DataFrame) -> pd.DataFrame:
    """인구와 교통량을 따로, 그리고 곱해서.

    '둘 다 많으면' 은 곱셈항이다. 다만 곱셈항을 그냥 넣으면 주효과가
    **'상대방이 1명일 때의 효과'** 가 되어 읽을 수가 없다. 두 변수를
    평균에서 빼고(중심화) 넣어야 주효과가 '평균적인 곳에서의 효과' 가 된다.
    """
    if table is None or table.empty or "ln_pop" not in table:
        return pd.DataFrame(columns=LEVEL_COLS)
    df = table.dropna(subset=["ln_price", "ln_traffic", "ln_pop"])
    if len(df) < LEVEL_MIN_OBS:
        return pd.DataFrame(columns=LEVEL_COLS)

    df = df.copy()
    df["c_traffic"] = df["ln_traffic"] - df["ln_traffic"].mean()
    df["c_pop"] = df["ln_pop"] - df["ln_pop"].mean()
    ctl = ""
    if "ln_km_seoul" in df and df["ln_km_seoul"].notna().all():
        ctl = " + ln_km_seoul"

    rows = [
        _level_fit(df, f"ln_price ~ c_traffic + c_pop{ctl}",
                   "c_traffic", "따로 · 교통량"),
        _level_fit(df, f"ln_price ~ c_traffic + c_pop{ctl}",
                   "c_pop", "따로 · 인구"),
        _level_fit(df, f"ln_price ~ c_traffic * c_pop{ctl}",
                   "c_traffic:c_pop", "같이 · 곱셈항"),
        _level_fit(df, f"ln_price ~ c_traffic * c_pop{ctl}",
                   "c_traffic", "같이 · 교통량(평균 인구에서)"),
    ]
    return pd.DataFrame(rows)[LEVEL_COLS]


def judge_h4(table: pd.DataFrame) -> tuple[str, str]:
    """통제를 다 넣은 줄로 판정한다. 통제 전 계수로 판정하면 안 된다."""
    if table.empty or table["beta"].isna().all():
        return Verdict.UNKNOWN, "견줄 IC 가 모자랍니다 (IC 한 곳이 한 행입니다)."
    ok = table.dropna(subset=["beta"])
    raw = ok.iloc[0]
    last = ok.iloc[-1]                    # 통제를 가장 많이 넣은 줄
    shrink = ""
    if raw["모형"] != last["모형"] and abs(raw["beta"]) > 1e-9:
        pct = 100 * (1 - last["beta"] / raw["beta"])
        shrink = f" 통제를 넣자 계수가 {pct:.0f}% 줄었습니다."

    if last["p"] < ALPHA and last["beta"] > 0:
        return (Verdict.CORRELATED,
                f"{last['모형']} 기준 β={last['beta']:+.3f}(p={last['p']:.3f}).{shrink}"
                " 다만 서로 다른 장소를 견준 것이라 **상관**입니다 —"
                " 교통량이 많은 곳은 도시 근처이고 도시 근처는 원래 비쌉니다.")
    if last["p"] < ALPHA and last["beta"] < 0:
        return (Verdict.REJECT,
                f"{last['모형']} 기준 β={last['beta']:+.3f}(p={last['p']:.3f}) —"
                f" 오히려 반대 방향입니다.{shrink}")
    return (Verdict.UNKNOWN,
            f"{last['모형']} 기준 β={last['beta']:+.3f}(p={last['p']:.3f}), "
            f"이 표본으로 잡을 수 있는 최소 효과는 {last['mde']:.3f} 입니다."
            f"{shrink} 그보다 작은 효과는 있어도 못 찾습니다.")


def judge_h5(table: pd.DataFrame) -> tuple[str, str]:
    """곱셈항만 보고 판정하지 않는다. 주효과와 같이 본다."""
    if table.empty or table["beta"].isna().all():
        return Verdict.UNKNOWN, "인구를 붙일 수 있는 IC 가 모자랍니다."
    by = {r["모형"]: r for _, r in table.iterrows()}
    inter = by.get("같이 · 곱셈항")
    if inter is None or pd.isna(inter["beta"]):
        return Verdict.UNKNOWN, "곱셈항을 추정하지 못했습니다."

    main = [by.get("따로 · 교통량"), by.get("따로 · 인구")]
    main_ok = [m for m in main if m is not None and not pd.isna(m["p"])
               and m["p"] < ALPHA]
    if inter["p"] < ALPHA and inter["beta"] > 0:
        if not main_ok:
            return (Verdict.UNKNOWN,
                    f"곱셈항은 유의하지만(β={inter['beta']:+.3f}, p={inter['p']:.3f}) "
                    "교통량·인구 각각은 유의하지 않습니다. 곱셈항만 서는 것은 "
                    "대개 표본 가장자리 몇 점이 만든 것이라 그대로 못 믿습니다.")
        return (Verdict.CORRELATED,
                f"곱셈항 β={inter['beta']:+.3f}(p={inter['p']:.3f}) — 인구가 많은 "
                "곳일수록 교통량이 값과 더 강하게 붙습니다. 서로 다른 장소를 "
                "견준 것이라 **상관**이고, 인구가 시군구 단위라 IC 반경의 "
                "인구가 아니라는 점도 함께 봐야 합니다.")
    return (Verdict.UNKNOWN,
            f"곱셈항 β={inter['beta']:+.3f}(p={inter['p']:.3f}), 최소 탐지 가능 "
            f"효과는 {inter['mde']:.3f} 입니다. 둘이 겹칠 때 더 비싸지는지는 "
            "이 표본으로 판정할 수 없습니다.")


def judge_h3(table: pd.DataFrame) -> tuple[str, str]:
    if table.empty:
        return (Verdict.UNKNOWN,
                "인구·산단 자료를 아직 확보하지 못했습니다. 이게 없으면 H1·H2 의"
                " 계수도 'IC 효과' 라고 부를 수 없습니다 — 교란을 못 뺐기 때문입니다.")
    est = table.dropna(subset=["beta"])
    if est.empty:
        return Verdict.UNKNOWN, "자료는 있으나 추정할 만큼의 표본이 없습니다."
    sig = est[(est["p"] < ALPHA) & (est["beta"] > 0)]
    if sig.empty:
        neg = est[(est["p"] < ALPHA) & (est["beta"] < 0)]
        if len(neg):
            r = neg.iloc[0]
            return (Verdict.REJECT,
                    f"{r['변수']} 계수가 음수({r['beta']:+.3f}, p={r['p']:.3f})입니다.")
        return Verdict.UNKNOWN, "유의한 계수가 없습니다."
    r = sig.sort_values("p").iloc[0]
    return (Verdict.SUPPORT,
            f"{r['변수']} β={r['beta']:+.3f}(p={r['p']:.3f})로 유의한 양수입니다.")


# ────────────────────────────────────────────────────────────────

# 판정을 화면·요약으로 옮길 때 쓰는 이름. 코드 안의 'H1' 은 사람에게
# 아무 말도 안 한다.
NAMES = {
    "H1": ("H1 IC 개통", "IC 가 새로 뚫리면 주변 지가는 오른다"),
    "H2": ("H2 교통량 변화", "IC 통행량이 늘면 주변 지가는 오른다"),
    "H3": ("H3 인구·산단", "주변 인구·산업단지·택지지구가 늘면 지가는 오른다"),
    "H4": ("H4 교통량 수준", "교통량이 많은 곳의 지가가 그렇지 않은 곳보다 비싸다"),
    "H5": ("H5 인구 × 교통량", "주변 인구가 많고 교통량도 많으면 더 비싸다"),
}

# 무엇을 '판정' 하고 무엇을 '참고' 로만 적을 것인가.
#
# 계수를 다 세면 80개쯤 된다(5 가설 × 4 밴드 × 2 종류 × 2 차종). 유의수준
# 5% 는 효과가 없어도 20번에 1번은 유의하다는 뜻이니, 80개를 던지면 4개는
# 아무 이유 없이 유의하다. 결과를 본 뒤에 무엇을 주장할지 고르면 그 4개를
# 고르게 된다.
#
# 그래서 **미리** 나눠 둔다. 주 가설은 토지·전체 교통량이다. 공장과 화물은
# 탐색이고, 거기서 뭐가 나와도 '다음에 확인할 것' 이지 결론이 아니다.
PRIMARY_KIND = "land"
PRIMARY_VOLUME = "volume_total"


def is_primary(kind: str, volume_col: str) -> bool:
    return kind == PRIMARY_KIND and volume_col == PRIMARY_VOLUME


def _rows(table: pd.DataFrame) -> list[dict]:
    """추정 표를 JSON 으로 옮긴다. 신뢰구간을 여기서 만들어 붙인다.

    계수 하나만 보면 '0.03' 이 큰지 작은지 알 수 없다. 구간이 있어야
    '0 을 품고 있다(=말할 수 없다)' 와 '0 위에 있다' 가 갈린다. 화면에서
    이것을 계산하게 두면 화면과 로그가 다른 말을 하게 된다."""
    def num(v, cast=float):
        return None if v is None or pd.isna(v) else cast(v)

    out = []
    for r in table.to_dict("records") if len(table) else []:
        beta, se = num(r.get("beta")), num(r.get("se"))
        ok = beta is not None and se is not None
        # 세 가설의 표는 첫 칸 이름이 다르다 — H1 은 '모형', H2 는 '밴드'+
        # '모형', H3 은 '변수'. 하나로 뭉개면 화면에서 어느 줄인지 못
        # 읽으므로 각각 그대로 넘기고, 사람이 읽을 한 줄도 같이 만든다.
        band = r.get("밴드")
        model = r.get("모형")
        var = r.get("변수")
        parts = [f"{band}km" if band else None, model, var]
        out.append({
            "label": " · ".join(x for x in parts if x) or "—",
            "band": band, "model": model, "var": var,
            "note": r.get("비고") or "",
            "n": num(r.get("n"), int),
            "clusters": num(r.get("영업소"), int),
            "beta": beta, "se": se, "p": num(r.get("p")),
            # 이 표본으로 잡을 수 있는 최소 효과. 계수가 0 근처일 때
            # '효과가 없다' 와 '작아서 못 봤다' 를 가르는 유일한 단서다.
            "mde": num(r.get("mde")),
            # 95% 구간. 군집표준오차라 정규근사를 쓴다.
            "ci_lo": None if not ok else beta - 1.96 * se,
            "ci_hi": None if not ok else beta + 1.96 * se,
        })
    return out


def payload(verdicts: pd.DataFrame, tables: dict[str, pd.DataFrame],
            *, kind: str, volume_col: str, controls: list[str],
            pre_trend_ok: bool | None, synthetic: bool = False) -> dict:
    """판정 결과를 파일로 남길 수 있는 모양으로.

    지금까지 이 숫자들은 러너 로그에만 있었다. 실행이 끝나고 로그가
    지워지면 무엇이 나왔는지 아무도 모른다 — 사장님께 결과를 물어보실
    때마다 내가 로그를 다시 뒤져야 했던 이유다. 파일로 남긴다."""
    from datetime import datetime, timezone
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": kind,
        "volume_col": volume_col,
        # 합성 자료로 돌린 판정은 **판정이 아니다.** 화면이 이것을 못
        # 읽으면 연습용 숫자를 사실로 내보내게 된다.
        "synthetic": bool(synthetic),
        "controls": list(controls),
        # 통제가 없으면 아래 계수는 교란을 빼지 않은 값이다. 화면이 이
        # 사실을 숨기면 안 되므로 값으로 넘긴다.
        "controlled": bool(controls),
        "pre_trend_ok": pre_trend_ok,
        # 주 가설인가, 탐색인가. 화면이 이걸 안 보이면 탐색에서 우연히
        # 나온 것을 결론으로 읽게 된다.
        "primary": is_primary(kind, volume_col),
        "primary_kind": PRIMARY_KIND,
        "primary_volume": PRIMARY_VOLUME,
        "alpha": ALPHA,
        "min_obs": MIN_OBS,
        "min_clusters": MIN_CLUSTERS,
        "hypotheses": [
            {
                "key": key,
                "name": NAMES[key][0],
                "claim": NAMES[key][1],
                "verdict": str(row["판정"]),
                "why": str(row["근거"]),
                "rows": _rows(tables.get(key, pd.DataFrame())),
            }
            for key, (_, row) in zip(NAMES, verdicts.iterrows())
        ],
    }


def report(panel: pd.DataFrame, event_df: pd.DataFrame | None,
           region: pd.DataFrame | None, pressure: pd.DataFrame | None,
           volume_col: str = "volume_total", kind: str = "land",
           pre_trend_ok: bool | None = None,
           synthetic: bool = False,
           level: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict]:
    """level 은 IC 한 곳이 한 행인 수준 비교표(analyze.cross.build).

    없으면 H4·H5 는 '자료 없음' 으로 남는다 — 조용히 건너뛰지 않는다."""
    primary = is_primary(kind, volume_col)
    print(f"\n{'='*66}")
    print(f"다섯 가설 판정 ({kind}, {volume_col})"
          f"{'  [주 가설]' if primary else '  [탐색 — 참고용]'}")
    print(f"{'='*66}")
    if not primary:
        print(f"  이 조합은 탐색입니다. 판정은 {PRIMARY_KIND}·{PRIMARY_VOLUME} 에서만")
        print("  합니다 — 계수를 여럿 던지면 그중 몇은 우연히 유의합니다.")

    with_ctrl, usable = attach_controls(panel, region, pressure)
    print(f"\nH3 통제로 쓸 수 있는 변수: {usable or '없음'}")
    if not usable:
        print("  ⚠ 통제가 하나도 없습니다. 아래 H1·H2 계수는 교란을 빼지 않은 값이라,")
        print("    유의하게 나와도 'IC 효과' 라고 부를 수 없습니다.")

    print("\n── H1 · IC 개통 → 지가 ──")
    t1 = h1(event_df, usable) if event_df is not None else pd.DataFrame()
    print(t1.to_string(index=False) if len(t1) else "  표본 없음")
    v1, why1 = judge_h1(t1, pre_trend_ok)

    print("\n── H2 · 교통량 증가 → 지가 ──")
    t2 = h2(with_ctrl, volume_col, usable, kind=kind)
    print(t2.to_string(index=False) if len(t2) else "  표본 없음")
    v2, why2 = judge_h2(t2)

    print("\n── H3 · 인구·산단·택지 → 지가 ──")
    t3 = h3(with_ctrl, usable, kind=kind)
    print(t3.to_string(index=False) if len(t3) else "  자료 없음")
    v3, why3 = judge_h3(t3)

    # H4·H5 는 수준 비교다. 여기서부터는 서로 다른 장소를 견준다.
    lv = level if level is not None else pd.DataFrame()
    print("\n── H4 · 교통량이 많은 곳이 비싼가 (수준) ──")
    if lv.empty:
        print("  수준 비교표가 없습니다 (analyze.cross.build 결과가 비었습니다).")
    t4 = h4(lv)
    print(t4.to_string(index=False) if len(t4) else "  표본 없음")
    v4, why4 = judge_h4(t4)

    print("\n── H5 · 인구도 많고 교통량도 많으면 비싼가 ──")
    if len(lv) and "ln_pop" not in lv:
        print("  인구를 못 붙였습니다 (region_year 에 그 해 인구가 없습니다).")
    t5 = h5(lv)
    print(t5.to_string(index=False) if len(t5) else "  표본 없음")
    v5, why5 = judge_h5(t5)

    verdicts = pd.DataFrame([
        {"가설": NAMES[k][0], "판정": v, "근거": w}
        for k, v, w in (("H1", v1, why1), ("H2", v2, why2), ("H3", v3, why3),
                        ("H4", v4, why4), ("H5", v5, why5))
    ])
    print(f"\n{'='*66}")
    print("판정")
    print(f"{'='*66}")
    for r in verdicts.itertuples():
        print(f"  {r.가설:<14} {r.판정}")
        print(f"                 {r.근거}")
    print("\n  '아직 모름' 은 '효과가 없다' 가 아닙니다. 표본이 모자라 판정하지")
    print("  못했다는 뜻입니다. 둘을 섞으면 투자 판단이 뒤집힙니다.")
    print("  H4·H5 의 '관계 있음' 은 **상관**입니다. 서로 다른 장소를 견준")
    print("  것이라, 교통량 때문에 비싼 것인지는 이것으로 알 수 없습니다.")
    return verdicts, payload(
        verdicts, {"H1": t1, "H2": t2, "H3": t3, "H4": t4, "H5": t5},
        kind=kind, volume_col=volume_col, controls=usable,
        pre_trend_ok=pre_trend_ok, synthetic=synthetic)
