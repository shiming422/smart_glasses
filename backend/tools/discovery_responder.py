import os
import socket
import sys
import time


REQUEST = b"AIGLASS_DISCOVER"
DEFAULT_PORT = 54321


def _local_ip() -> str:
    override = (os.getenv("AIGLASS_DISCOVERY_HOST") or "").strip()
    if override:
        return override
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    finally:
        sock.close()


def main() -> int:
    port = int(os.getenv("AIGLASS_DISCOVERY_PORT", str(DEFAULT_PORT)))
    host = _local_ip()
    reply = f"AIGLASS_HOST:{host}".encode("ascii")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("", port))
    print(f"[HOST DISC] listening udp/{port}, advertised IP={host}", flush=True)

    while True:
        try:
            data, addr = sock.recvfrom(256)
            if data.strip() != REQUEST:
                continue
            sock.sendto(reply, addr)
            print(f"[HOST DISC] replied {host} to {addr[0]}:{addr[1]}", flush=True)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            print(f"[HOST DISC] error: {exc}", flush=True)
            time.sleep(0.2)


if __name__ == "__main__":
    raise SystemExit(main())
