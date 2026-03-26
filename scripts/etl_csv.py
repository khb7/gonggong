import asyncio
import os
import sys

# Add project root to python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.db.models import BidsHistory

FILE_NOTICE = r"c:\Users\Lenovo\gonggong\md\UI-ADODAA-008R.입찰공고 내역.csv"
FILE_RESULT = r"c:\Users\Lenovo\gonggong\md\UI-ADOFAA-003R.입찰공고 결과내역.csv"

PROJECT_TYPE_MAP = {
    "0002": "실내건축",
    "0023": "조경",
}

def map_project_type(code_list_str: str) -> str:
    """
    '[건축공사업(0001)]' 등 한글이 포함되어 있을 수 있고 
    '0002', '0002|0023' 처럼 코드로만 존재할 수도 있음.
    
    여기서는 원칙대로 0002 -> 실내건축, 0023 -> 조경으로 변환하며
    복합 공종('|' 포함)은 None을 반환하여 필터링함.
    """
    if pd.isna(code_list_str):
        return None
    
    code_list_str = str(code_list_str)
    if "|" in code_list_str:
        return None  # 복수 공종 제외
    
    # 0002나 0023이 포함되어 있는지 확인
    if "0002" in code_list_str:
        return "실내건축"
    elif "0023" in code_list_str:
        return "조경"
    else:
        # 매핑 안되는 경우 임시로 코드 자체를 반환
        return code_list_str.strip()


def extract_and_transform() -> pd.DataFrame:
    print("1. Extracting data...")
    # Notice: Header at line 107 (idx 106), Data at line 126 (idx 125). Skip 0~105, 107~124
    notice_skiprows = list(range(106)) + list(range(107, 125))
    df_notice = pd.read_csv(FILE_NOTICE, sep="\t", encoding="utf-16", skiprows=notice_skiprows)
    
    # Result: Header at line 75 (idx 74), Data at line 76 (idx 75). Skip 0~73
    df_result = pd.read_csv(FILE_RESULT, sep="\t", encoding="utf-16", skiprows=74)
    
    print(f"Loaded {len(df_notice)} notice rows, {len(df_result)} result rows.")
    
    # 데이터 정리 - 결과 내역
    # 컬럼 이름에 양끝 공백이나 \t 가 있을 수 있으므로 스트립
    df_result.columns = df_result.columns.str.strip()
    df_notice.columns = df_notice.columns.str.strip()

    # 필수 컬럼 존재하는지 확인
    req_res_cols = ["입찰공고번호", "개찰순위", "기초금액", "낙찰하한율", "예정가격", "투찰금액", "입찰참여자수", "면허업종제한목록"]
    for col in req_res_cols:
        if col not in df_result.columns:
            print(f"Warning: '{col}' not in file_result. Cols: {df_result.columns.tolist()}")

    # 개찰순위 = 1 인 행만 결과 테이블로 사용 (1순위 낙찰자)
    if "개찰순위" in df_result.columns:
        # 개찰순위가 숫자가 아닐수도 있으니 문자로 변환 후 비교
        df_result = df_result[df_result["개찰순위"].astype(str).str.strip() == "1"]
    
    # 조인 (Notice의 중복 컬럼명에는 _notice 접미사 부여)
    if "입찰공고번호" in df_notice.columns and "입찰공고번호" in df_result.columns:
        df_joined = pd.merge(df_result, df_notice, on="입찰공고번호", how="inner", suffixes=("", "_notice"))
    else:
        raise ValueError("입찰공고번호 column missing")

    print(f"Joined data size: {len(df_joined)}")
    
    # 파생 컬럼 및 정제 (Transform)
    records = []
    
    # 디버그 카운터
    err_base_est = 0
    err_adj_rate = 0
    err_ptype = 0
    err_parse = 0
    
    # 필요한 컬럼만 추출 (공고번호가 동일하게 있지만 suffix 붙었을 수 있음 탐색 방지용)
    for _, row in df_joined.iterrows():
        try:
            # 기본 필수항목 파싱
            b_str = str(row.get("기초금액", 0)).replace(",", "")
            e_str = str(row.get("예정가격", 0)).replace(",", "")
            w_str = str(row.get("투찰금액", 0)).replace(",", "")
            
            base_price = float(b_str)
            est_price = float(e_str)
            winner_price = float(w_str)
            
            lower_limit = float(row.get("낙찰하한율", 0))
            participants = int(row.get("입찰참여자수", 0))
            
            # 유효성 검사
            if base_price <= 0 or est_price <= 0 or participants <= 0:
                err_base_est += 1
                continue
                
            # 사정률 계산
            adjustment_rate = est_price / base_price
            
            # 사정률 이상치 제거 (0.95 ~ 1.05)
            if not (0.95 < adjustment_rate < 1.05):
                err_adj_rate += 1
                continue
                
            # 사업 유형(공종) 변환 및 복수면 제외
            p_type = map_project_type(row.get("면허업종제한목록", ""))
            if not p_type:
                err_ptype += 1
                continue
                
            # 낙찰하한율 단위 변환 (80.xxx 면 0.8xxx 로)
            if lower_limit > 1:
                lower_limit = lower_limit / 100.0
                
            region = str(row.get("현장지역", ""))
            if pd.isna(region) or not region.strip():
                region = "unknown" # NULL이 들어오지 않도록
                
            records.append({
                "project_id": str(row["입찰공고번호"]),
                "client_name": None, # nullable
                "region": region,
                "project_type": p_type,
                "base_price": int(base_price),
                "lower_limit_rate": lower_limit,
                "adjustment_rate": adjustment_rate,
                "winner_price": int(winner_price),
                "participants": participants,
                "bid_date": None # nullable
            })
        except Exception as e:
            err_parse += 1

    print(f"Filter drops -> zero values: {err_base_est}, adj_rate: {err_adj_rate}, ptype: {err_ptype}, parse err: {err_parse}")
    df_final = pd.DataFrame(records)
    print(f"Transformed to {len(df_final)} rows to insert.")
    return df_final


async def load_to_db(df: pd.DataFrame):
    if df.empty:
        print("No data to insert.")
        return
        
    print(f"2. Loading {len(df)} records to database...")
    async with AsyncSessionLocal() as session:
        for idx, row in df.iterrows():
            bid = BidsHistory(
                project_id=row["project_id"],
                client_name=row["client_name"],
                region=row["region"],
                project_type=row["project_type"],
                base_price=row["base_price"],
                lower_limit_rate=row["lower_limit_rate"],
                adjustment_rate=row["adjustment_rate"],
                winner_price=row["winner_price"],
                participants=row["participants"],
                bid_date=row["bid_date"]
            )
            session.add(bid)
            
            if idx > 0 and idx % 1000 == 0:
                await session.commit()
                print(f"Inserted {idx} rows...")
                
        await session.commit()
        print("Load complete!")


async def main():
    try:
        df = extract_and_transform()
        await load_to_db(df)
    except Exception as e:
        print(f"Error during ETL: {e}")


if __name__ == "__main__":
    asyncio.run(main())
