"""Part 25 - SSRF guard (real app/core/net_safety.py, stdlib only). No external network is contacted:
hostnames that need real DNS are checked only for 'refused' (no DNS in the sandbox = unresolved = refused)."""
import asyncio, importlib.util, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("ns", Path(__file__).resolve().parent.parent / "app/core/net_safety.py")
ns = importlib.util.module_from_spec(spec); spec.loader.exec_module(ns)
res = []
def check(n, ok): res.append(bool(ok)); print(f"[{'PASS' if ok else 'FAIL'}] {n}")
def refused(url):
    try: asyncio.run(ns.assert_public_destination(url)); return False
    except ns.UnsafeDestination: return True
bad = ["http://127.0.0.1/x", "http://localhost/x", "http://[::1]/x", "http://169.254.169.254/latest/meta-data", "http://10.0.0.5/", "http://192.168.1.1/",
       "http://172.16.0.9/", "http://2130706433/", "http://0x7f.1/", "http://017700000001/", "http://[::ffff:127.0.0.1]/", "http://0.0.0.0/", "http://100.64.0.1/",
       "http://localtest.invalid/"]
for u in bad: check(f"refuses {u}", refused(u))
check("allows a public IPv4 literal (93.184.216.34)", not refused("https://93.184.216.34/pb?c=1"))
check("allows a public IPv6 literal", not refused("https://[2606:2800:220:1:248:1893:25c8:1946]/"))
print(f"{sum(res)}/{len(res)} passed"); sys.exit(0 if all(res) else 1)
