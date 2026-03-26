import asyncio
from app.api.v1.bidding import calculate_bid
from app.schemas.request import BidRequest, BidOverrides
from app.core.config import settings

settings.use_mock_g2b = True

async def main():
    req = BidRequest(
        bid_notice_id="TEST-001",
        overrides=BidOverrides(
            base_price=500000000,
            client_name="강원특별자치도교육청",
            project_type="건축공사",
            region="강원도"
        )
    )
    # mock db session
    from unittest.mock import AsyncMock
    db = AsyncMock()
    try:
        res = await calculate_bid(req, db)
        print(res)
    except Exception as e:
        import traceback
        with open("traceback.txt", "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())

asyncio.run(main())
