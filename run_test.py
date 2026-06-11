import asyncio
from dotenv import load_dotenv
load_dotenv()
import main

async def run():
    try:
        res = await main.test()
        print(res)
    except Exception as e:
        print({"ok": False, "error": str(e)})

if __name__ == "__main__":
    asyncio.run(run())
