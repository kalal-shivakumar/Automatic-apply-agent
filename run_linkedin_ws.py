import asyncio
import json

import websockets


async def main():
    uri = "ws://127.0.0.1:8000/ws"
    async with websockets.connect(uri, max_size=2**22) as ws:
        await ws.recv()  # init
        actions = [
            "launch_browser_linkedin",
            "verify_login_linkedin",
            "start_linkedin",
        ]
        for action in actions:
            await ws.send(json.dumps({"action": action}))
            print(f"sent {action}")

        for _ in range(20):
            msg = await ws.recv()
            data = json.loads(msg)
            t = data.get("type")
            if t in {
                "linkedin_browser_status",
                "linkedin_login_status",
                "linkedin_agent_started",
                "linkedin_search_query",
                "linkedin_job_update",
                "error",
            }:
                print(t, data.get("message", ""))


if __name__ == "__main__":
    asyncio.run(main())
