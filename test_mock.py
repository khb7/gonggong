import asyncio
from app.external.g2b_fetcher import MockG2BFetcher

async def main():
    fetcher = MockG2BFetcher()
    try:
        res = await fetcher.fetch("TEST-001")
        print(res)
    except Exception as e:
        print("ERROR:", type(e), str(e))
        import traceback
        traceback.print_exc()

asyncio.run(main())
