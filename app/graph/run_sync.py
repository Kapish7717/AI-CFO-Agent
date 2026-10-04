# ==========================================================
# End-to-end proof harness: python -m app.graph.run_sync <user_id>
# ==========================================================

import asyncio
import json
import sys

from app.graph.supervisor import graph


async def main(user_id: int) -> None:
    result = await graph.ainvoke({"user_id": user_id, "trigger": "new_data"})
    print(json.dumps(result.get("anomaly_result"), indent=2, default=str))
    print(json.dumps(result.get("report"), indent=2, default=str))


if __name__ == "__main__":
    uid = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    asyncio.run(main(uid))