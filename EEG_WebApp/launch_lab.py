"""Start the local session server and open wiring setup after the port is listening."""
import os
import webbrowser
import json
from urllib.error import URLError
from urllib.request import urlopen

import uvicorn


class LabServer(uvicorn.Server):
    async def startup(self, sockets=None):
        await super().startup(sockets)
        if self.started:
            url = f"http://127.0.0.1:{self.config.port}/"
            print(url, flush=True)
            webbrowser.open(url)


if __name__ == "__main__":
    try:
        with urlopen("http://127.0.0.1:8766/openapi.json", timeout=1) as response:
            schema = json.load(response)
            if "/api/field/sessions" in schema.get("paths", {}) and "/api/offline" not in schema.get("paths", {}):
                raise SystemExit("먼저 기존 실측 서버 창을 닫고 start_lab.cmd를 다시 실행하세요.")
            if "/api/field/sessions" in schema.get("paths", {}):
                webbrowser.open("http://127.0.0.1:8766/")
                raise SystemExit(0)
    except (URLError, OSError, ValueError):
        pass
    os.environ["EEG_SOURCE"] = "lsl"
    os.environ["LAB_REQUIRE_LAYOUT"] = "1"
    LabServer(uvicorn.Config("backend.main:app", host="127.0.0.1", port=8766)).run()

