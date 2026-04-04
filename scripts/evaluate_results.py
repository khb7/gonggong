import pandas as pd
import io
import math
import traceback
from fastapi.testclient import TestClient
from app.main import app

csv_path = 'md/UI-ADOFAA-003R.입찰공고 결과내역_3-25_12-25.csv'

def clean_price(val):
    if pd.isna(val):
        return None
    val = str(val).replace(',', '').strip()
    if not val:
        return None
    try:
        return float(val)
    except:
        return None

try:
    with open(csv_path, 'r', encoding='utf-16le', errors='replace') as f:
        lines = f.readlines()
        
    start_idx = -1
    for i, line in enumerate(lines):
        if line.startswith('"입찰공고번호"'):
            start_idx = i
            break
            
    if start_idx != -1:
        data_str = "".join(lines[start_idx:])
        df = pd.read_csv(io.StringIO(data_str), sep="\t", dtype=str)
        
        with TestClient(app, raise_server_exceptions=False) as client:
            count = 0
            with open("eval_report.txt", "w", encoding="utf-8") as out:
                out.write(f"Total rows in CSV: {len(df)}\n\n")
                for idx, row in df.iterrows():
                    if count >= 10:
                        break
                        
                    notice_id = str(row['입찰공고번호'])
                    client_name = str(row['Unnamed: 38']) if 'Unnamed: 38' in row and not pd.isna(row['Unnamed: 38']) else ""
                    region = str(row['수요기관지역']) if not pd.isna(row['수요기관지역']) else ""
                    project_type = str(row['공공조달분류']) if not pd.isna(row['공공조달분류']) else ""
                    
                    base_price = clean_price(row.get('기초금액'))
                    if base_price is None:
                        base_price = clean_price(row.get('예정가격'))
                    if base_price is None:
                        base_price = clean_price(row.get('입찰추정가격'))
                        
                    if base_price is None or math.isnan(base_price):
                        continue
                        
                    actual_bid_price = clean_price(row.get('투찰금액'))
                    actual_bid_rate = str(row.get('투찰율'))
                    
                    payload = {
                        "bid_notice_id": notice_id,
                        "overrides": {
                            "base_price": int(base_price),
                            "client_name": client_name,
                            "project_type": project_type,
                            "region": region
                        }
                    }
                    
                    try:
                        response = client.post("/api/v1/bid/calculate", json=payload)
                        if response.status_code == 200:
                            res_data = response.json()
                            out.write(f"--- Notice: {notice_id} ---\n")
                            out.write(f"Overrides: {client_name} | {region} | {project_type}\n")
                            out.write(f"Base Price: {int(base_price):,} | Actual Bid: {int(actual_bid_price) if actual_bid_price else 'N/A':,} | Actual Rate: {actual_bid_rate}%\n")
                            
                            bids = res_data.get("bids", [])
                            if bids:
                                for b in bids:
                                    out.write(f"Strategy: {b.get('label')} | Pred Rate: {b.get('rate_pct')}% | Pred Bid: {int(b.get('price_krw', 0)):,}\n")
                            else:
                                out.write("No calculated prices returned.\n")
                            
                            out.write(f"Data Source: {res_data.get('fallback_level')}\n\n")
                            count += 1
                        else:
                            out.write(f"Error for {notice_id}: {response.status_code} {response.text}\n")
                        out.flush()
                    except Exception as ex:
                        out.write(f"Exception on {notice_id}:\n")
                        traceback.print_exc(file=out)
                        out.flush()
                    
    else:
        print("Header not found")
except Exception as e:
    traceback.print_exc()
