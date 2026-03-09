# client_host.py
import asyncio
import json
import os
import secrets
import time


SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8765
INSTALL_ID_FILE = "install_id.txt"


def load_or_create_install_id() -> str:
    if os.path.exists(INSTALL_ID_FILE):
        return open(INSTALL_ID_FILE, "r", encoding="utf-8").read().strip() or secrets.token_hex(8)
    iid = secrets.token_hex(8)
    with open(INSTALL_ID_FILE, "w", encoding="utf-8") as f:
        f.write(iid)
    return iid


def jdump(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


async def send(writer: asyncio.StreamWriter, obj: dict) -> None:
    writer.write(jdump(obj))
    await writer.drain()


async def recv_loop(reader: asyncio.StreamReader) -> None:
    while True:
        line = await reader.readline()
        if not line:
            print("[host] disconnected.")
            return
        msg = json.loads(line.decode("utf-8", errors="replace"))
        mtype = msg.get("type")
        if mtype == "room_state":
            members = msg.get("members", [])
            print(f"\n[room_state] members={len(members)}")
            for m in members:
                sid = m.get("session_id", "")
                nick = m.get("nickname", "")
                ip = m.get("ip", "")
                iid = m.get("install_id", "")
                print(f"  - {nick}  sid={sid[:8]}  ip={ip}  install={iid[:8]}")
            print("> ", end="", flush=True)
        elif mtype == "relay":
            frm = msg.get("from_nickname", "?")
            payload = msg.get("payload", {})
            print(f"\n[recv] {frm}: {payload}")
            print("> ", end="", flush=True)
        else:
            print(f"\n[server] {msg}")
            print("> ", end="", flush=True)


async def input_loop(writer: asyncio.StreamWriter, room: str) -> None:
    while True:
        text = await asyncio.to_thread(input, "> ")
        text = text.strip()
        if not text:
            continue
        if text.lower() == "/quit":
            return
        await send(writer, {
            "type": "relay",
            "room": room,
            "to": "all",
            "payload": {"text": text, "client_ts": int(time.time() * 1000)},
        })


async def main() -> None:
    nickname = input("nickname: ").strip() or "host"
    install_id = load_or_create_install_id()

    reader, writer = await asyncio.open_connection(SERVER_HOST, SERVER_PORT)

    await send(writer, {"type": "hello", "nickname": nickname, "install_id": install_id})
    welcome = json.loads((await reader.readline()).decode("utf-8", errors="replace"))
    print("[host] welcome:", welcome)

    await send(writer, {"type": "create_room"})
    created = json.loads((await reader.readline()).decode("utf-8", errors="replace"))
    room = created.get("room")
    print(f"[host] room_code = {room} (tell your friend to join)")
    print("Type anything to broadcast. /quit to exit.\n")

    t1 = asyncio.create_task(recv_loop(reader))
    t2 = asyncio.create_task(input_loop(writer, room))
    done, pending = await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()
    writer.close()
    await writer.wait_closed()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[host] bye")