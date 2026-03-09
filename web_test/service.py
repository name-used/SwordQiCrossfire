# relay_server.py
import asyncio
import json
import secrets
import string
import time
from dataclasses import dataclass
from typing import Dict, Optional, Set, Tuple


ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 去掉易混淆字符 I/O/1/0
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8765


def gen_room_code(n: int = 6) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(n))


def now_ms() -> int:
    return int(time.time() * 1000)


def jdump(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


async def send(writer: asyncio.StreamWriter, obj: dict) -> None:
    writer.write(jdump(obj))
    await writer.drain()


@dataclass
class ClientInfo:
    session_id: str
    nickname: str
    install_id: str
    room: Optional[str]
    peer: Tuple[str, int]  # (ip, port)


class RelayServer:
    def __init__(self) -> None:
        self.clients_by_writer: Dict[asyncio.StreamWriter, ClientInfo] = {}
        self.writer_by_session: Dict[str, asyncio.StreamWriter] = {}
        self.rooms: Dict[str, Set[str]] = {}  # room_code -> {session_id}

    def _room_state(self, room: str) -> dict:
        members = []
        for sid in sorted(self.rooms.get(room, set())):
            w = self.writer_by_session.get(sid)
            if not w:
                continue
            ci = self.clients_by_writer.get(w)
            if not ci:
                continue
            ip, port = ci.peer
            members.append({
                "session_id": ci.session_id,
                "nickname": ci.nickname,
                "install_id": ci.install_id,
                "ip": ip,
                "port": port,
            })
        return {"type": "room_state", "room": room, "members": members, "ts": now_ms()}

    async def _broadcast_room_state(self, room: str) -> None:
        msg = self._room_state(room)
        for sid in list(self.rooms.get(room, set())):
            w = self.writer_by_session.get(sid)
            if w:
                await send(w, msg)

    async def _leave_room(self, ci: ClientInfo) -> None:
        if not ci.room:
            return
        room = ci.room
        sids = self.rooms.get(room)
        if sids and ci.session_id in sids:
            sids.remove(ci.session_id)
            if not sids:
                self.rooms.pop(room, None)
        ci.room = None
        await self._broadcast_room_state(room)

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername") or ("?", 0)
        peer_ip, peer_port = peer[0], peer[1]

        # 等待 hello
        line = await reader.readline()
        if not line:
            writer.close()
            await writer.wait_closed()
            return

        try:
            msg = json.loads(line.decode("utf-8", errors="replace"))
        except Exception:
            writer.close()
            await writer.wait_closed()
            return

        if msg.get("type") != "hello":
            await send(writer, {"type": "error", "error": "first_message_must_be_hello"})
            writer.close()
            await writer.wait_closed()
            return

        session_id = secrets.token_hex(8)
        nickname = str(msg.get("nickname") or "anon")[:32]
        install_id = str(msg.get("install_id") or "unknown")[:64]

        ci = ClientInfo(
            session_id=session_id,
            nickname=nickname,
            install_id=install_id,
            room=None,
            peer=(peer_ip, peer_port),
        )
        self.clients_by_writer[writer] = ci
        self.writer_by_session[session_id] = writer

        await send(writer, {
            "type": "welcome",
            "session_id": session_id,
            "your_ip_seen_by_server": peer_ip,
            "server_ts": now_ms(),
        })

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line.decode("utf-8", errors="replace"))
                except Exception:
                    await send(writer, {"type": "error", "error": "bad_json"})
                    continue

                mtype = msg.get("type")
                if mtype == "ping":
                    await send(writer, {"type": "pong", "ts": now_ms()})
                    continue

                if mtype == "create_room":
                    # 先离开旧房间
                    await self._leave_room(ci)

                    room = gen_room_code()
                    self.rooms.setdefault(room, set()).add(ci.session_id)
                    ci.room = room
                    await send(writer, {"type": "room_created", "room": room, "ts": now_ms()})
                    await self._broadcast_room_state(room)
                    continue

                if mtype == "join_room":
                    room = str(msg.get("room") or "").strip().upper()
                    if not room or room not in self.rooms:
                        await send(writer, {"type": "error", "error": "room_not_found", "room": room})
                        continue

                    await self._leave_room(ci)
                    self.rooms.setdefault(room, set()).add(ci.session_id)
                    ci.room = room
                    await send(writer, {"type": "room_joined", "room": room, "ts": now_ms()})
                    await self._broadcast_room_state(room)
                    continue

                if mtype == "leave_room":
                    await self._leave_room(ci)
                    await send(writer, {"type": "left_room", "ts": now_ms()})
                    continue

                if mtype == "relay":
                    # 服务器不校验 payload 语义，只做最基本的房间与目标检查
                    room = str(msg.get("room") or "").strip().upper()
                    if not ci.room or room != ci.room:
                        await send(writer, {"type": "error", "error": "not_in_room_or_room_mismatch"})
                        continue

                    to = msg.get("to", "all")  # "all" or session_id
                    payload = msg.get("payload", {})

                    out = {
                        "type": "relay",
                        "room": room,
                        "from": ci.session_id,
                        "from_nickname": ci.nickname,
                        "payload": payload,
                        "ts": now_ms(),
                    }

                    if to == "all":
                        for sid in list(self.rooms.get(room, set())):
                            if sid == ci.session_id:
                                continue
                            w = self.writer_by_session.get(sid)
                            if w:
                                await send(w, out)
                    else:
                        # 单播
                        sid = str(to)
                        if sid not in self.rooms.get(room, set()):
                            await send(writer, {"type": "error", "error": "target_not_in_room", "to": sid})
                            continue
                        w = self.writer_by_session.get(sid)
                        if w:
                            await send(w, out)
                    continue

                await send(writer, {"type": "error", "error": "unknown_type", "got": mtype})
        finally:
            # 清理
            try:
                await self._leave_room(ci)
            except Exception:
                pass

            self.clients_by_writer.pop(writer, None)
            self.writer_by_session.pop(ci.session_id, None)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


async def main() -> None:
    srv = RelayServer()
    server = await asyncio.start_server(srv.handle_client, DEFAULT_HOST, DEFAULT_PORT)
    addrs = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
    print(f"[server] listening on {addrs}")

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[server] bye")
