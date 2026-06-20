import platform
from collections import namedtuple

# Apply monkeypatch to platform module to bypass Windows WMI hangs
print("[Launcher] Patching platform module system calls...")
uname_result = namedtuple('uname_result', ['system', 'node', 'release', 'version', 'machine', 'processor'])
platform.system = lambda: "Windows"
platform.release = lambda: "10"
platform.version = lambda: "10.0.19045"
platform.machine = lambda: "AMD64"
platform.uname = lambda: uname_result("Windows", "localhost", "10", "10.0.19045", "AMD64", "Intel64 Family 6 Model 158 Stepping 10, GenuineIntel")

import uvicorn

if __name__ == "__main__":
    print("[Launcher] Starting Uvicorn backend...")
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, log_level="info", reload=False)
