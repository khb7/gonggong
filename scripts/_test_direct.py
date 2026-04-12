import asyncio
import traceback
from app.db.session import async_session
from app.api.v1.bidding import calculate_bid
from app.schemas.request import BidRequest, OverrideParams

async def main():
    try:
        req = BidRequest(
            bid_notice_id="R25BK01192050",
            overrides=OverrideParams(
                base_price=3094697000,
                client_name="경남 하동군 옥종농업협동조합",
                project_type="건축공사",
                region="경상남도 하동군"
            )
        )
        async with async_session() as db:
            res = await calculate_bid(body=req, db=db)
            print(res)
    except Exception as e:
        with open("traceback.txt", "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        print("Error written to traceback.txt!")

asyncio.run(main())
