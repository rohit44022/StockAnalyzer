"""File-based event bus for cross-process real-time sync between daemon and web app."""
import json, os, time as _time, fcntl

_DIR = os.path.dirname(os.path.abspath(__file__))
EVENTS_FILE = os.path.join(_DIR, ".events.jsonl")
_MAX_LINES = 500
_last_seq = 0


def publish(event_type: str, data: dict = None):
    global _last_seq
    seq = max(int(_time.time() * 1000), _last_seq + 1)
    _last_seq = seq
    line = json.dumps({
        "seq": seq, "ts": _time.time(),
        "type": event_type, "data": data or {},
    }, default=str) + "\n"
    fd = os.open(EVENTS_FILE, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, line.encode())
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def read_new(after_seq: int = 0, byte_offset: int = 0):
    """Read events after given seq. Returns (events, new_byte_offset)."""
    if not os.path.exists(EVENTS_FILE):
        return [], 0
    try:
        with open(EVENTS_FILE, "rb") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            if byte_offset > 0:
                try:
                    f.seek(byte_offset)
                except OSError:
                    f.seek(0)
            data = f.read()
            new_offset = f.tell()
            fcntl.flock(f, fcntl.LOCK_UN)
    except Exception:
        return [], byte_offset
    out = []
    for line in data.decode("utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
            if ev.get("seq", 0) > after_seq:
                out.append(ev)
        except (json.JSONDecodeError, ValueError):
            continue
    return out, new_offset


def truncate():
    if not os.path.exists(EVENTS_FILE):
        return
    try:
        with open(EVENTS_FILE) as f:
            lines = f.readlines()
        if len(lines) > _MAX_LINES * 2:
            with open(EVENTS_FILE, "w") as f:
                f.writelines(lines[-_MAX_LINES:])
    except Exception:
        pass


def clear():
    try:
        open(EVENTS_FILE, "w").close()
    except Exception:
        pass
