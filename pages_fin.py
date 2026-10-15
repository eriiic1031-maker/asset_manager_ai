"""
재무 · 분석 화면: 회계 분개 내보내기, 추이 분석
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import data as d
import ops
import ui


# =========================================================
# 🧾 회계 분개
# =========================================================
def journal_page(u: dict):
    st.title("🧾 회계 분개 내보내기")
    st.caption("한 달 동안의 자산 취득·자본적 지출·감가상각·처분을 현장·계정별로 묶어 전표(차변·대변)로 만듭니다. "
               "더존·SAP 같은 ERP의 전표 일괄 업로드 양식에 맞춰 열을 옮겨 쓰세요. 계정코드는 일반적인 K-GAAP 코드 예시입니다.")
    today = d.today()
    c1, c2 = st.columns(2)
    year = c1.selectbox("연도", list(range(today.year, today.year - 6, -1)), key="jr-year")
    month = c2.selectbox("월", list(range(1, 13)), index=today.month - 1 if year == today.year else 11, key="jr-month",
                         format_func=lambda m: f"{m}월")
    with st.spinner("분개를 만드는 중입니다..."):
        rows = ops.journal_entries(year, month)
    if not rows:
        st.info(f"{year}년 {month}월에는 분개할 거래가 없습니다.")
        return
    df = pd.DataFrame(rows)
    debit = df.loc[df["차대"] == "차변", "금액"].sum()
    credit = df.loc[df["차대"] == "대변", "금액"].sum()
    k = st.columns(4)
    with k[0]: ui.kpi("전표", df["전표번호"].nunique(), f"{len(df)}줄", unit="장")
    with k[1]: ui.kpi("차변 합계", ui.short_won(debit), ui.won(debit), unit="원")
    with k[2]: ui.kpi("대변 합계", ui.short_won(credit), ui.won(credit), unit="원")
    with k[3]: ui.kpi("대차 일치", "일치" if round(debit) == round(credit) else "불일치", "", "ok" if round(debit) == round(credit) else "crit")
    tabs = st.tabs(["📒 전표", "🧮 계정별 합계"])
    with tabs[0]:
        st.dataframe(df, hide_index=True, width="stretch", column_config=ui.money_config("금액"), height=460)
    with tabs[1]:
        piv = df.pivot_table(index=["계정코드", "계정과목"], columns="차대", values="금액", aggfunc="sum", fill_value=0).reset_index()
        st.dataframe(piv, hide_index=True, width="stretch", column_config=ui.money_config("차변", "대변"))
    c1, c2 = st.columns(2)
    c1.download_button("📥 분개 엑셀", d.rows_to_xlsx({"분개": (ops.JOURNAL_COLS, rows)}),
                       file_name=f"자산분개_{year}{month:02d}.xlsx", width="stretch", type="primary")
    c2.download_button("📥 분개 CSV (ERP 업로드용)", d.rows_to_csv(ops.JOURNAL_COLS, rows),
                       file_name=f"자산분개_{year}{month:02d}.csv", width="stretch")


# =========================================================
# 📈 분석
# =========================================================
def analytics_page(u: dict):
    st.title("📈 자산 분석")
    st.caption("취득·처분 추이, 현장별 건전성(유휴율·만료율·수리비), 노후도 분포, 실제 사용 기간을 봅니다. "
               "교체 예산 계획과 유휴 자산 재배치 판단에 씁니다.")
    tabs = st.tabs(["📅 월별 취득·처분", "🏢 현장별 건전성", "⏳ 노후도", "♻️ 실제 사용 기간", "💸 수리비 상위"])
    with tabs[0]:
        years = st.slider("기간(년)", 1, 10, 3, key="an-years")
        flow = ops.monthly_flow(years)
        if not flow:
            st.info("데이터가 없습니다.")
        else:
            df = pd.DataFrame(flow)
            cnt = pd.concat([pd.DataFrame({"월": df["월"], "구분": "취득", "건수": df["취득 건수"]}),
                             pd.DataFrame({"월": df["월"], "구분": "처분", "건수": df["처분 건수"]})])
            st.bar_chart(cnt, x="월", y="건수", color="구분", height=300)
            amt = pd.DataFrame({"월": df["월"], "취득 금액(백만원)": (df["취득 금액"] / 1e6).round(1)})
            st.line_chart(amt, x="월", y="취득 금액(백만원)", height=220)
            st.dataframe(df, hide_index=True, width="stretch", column_config=ui.money_config("취득 금액", "처분 금액"))
    with tabs[1]:
        health = ops.site_health()
        if health:
            df = pd.DataFrame(health)
            st.dataframe(df, hide_index=True, width="stretch", column_config={
                **ui.money_config("누적 수리비"),
                "유휴율(%)": st.column_config.ProgressColumn("유휴율", min_value=0, max_value=100, format="%.1f%%"),
                "만료율(%)": st.column_config.ProgressColumn("내용연수 만료율", min_value=0, max_value=100, format="%.1f%%"),
                "평균 경과율(%)": st.column_config.ProgressColumn("평균 경과율", min_value=0, max_value=100, format="%.1f%%")})
            st.caption("유휴율이 높은 현장은 다른 현장 구매요청 전에 재배치 후보, 만료율이 높은 현장은 교체 예산이 필요한 곳입니다.")
    with tabs[2]:
        dist = ops.age_distribution()
        st.bar_chart(pd.DataFrame(dist), x="경과율", y="자산 수", height=300)
        st.caption("내용연수 대비 사용 기간 비율입니다(소모품 제외). '만료' 자산이 많으면 교체·처분 계획이 필요합니다.")
    with tabs[3]:
        rows = ops.disposal_age_by_account()
        if rows:
            df = pd.DataFrame(rows)
            st.dataframe(df, hide_index=True, width="stretch")
            long = pd.concat([pd.DataFrame({"계정과목": df["계정과목"], "구분": "실제 평균 사용(년)", "년": df["평균 사용(년)"]}),
                              pd.DataFrame({"계정과목": df["계정과목"], "구분": "기본 내용연수(년)", "년": df["기본 내용연수(년)"]})])
            st.bar_chart(long, x="계정과목", y="년", color="구분", stack=False, height=280)
            st.caption("처분된 자산이 실제로 몇 년 쓰였는지와 회계 내용연수를 비교합니다. 차이가 크면 내용연수 설정을 검토하세요.")
        else:
            st.info("처분 자산이 없습니다.")
    with tabs[4]:
        top = ops.top_repairs(30)
        if top:
            st.dataframe(pd.DataFrame(top), hide_index=True, width="stretch", column_config=ui.money_config("누적 수리비", "장부가"))
        else:
            st.info("수리 기록이 없습니다.")
