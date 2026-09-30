"""Local Upload Server - the engine.

Settings, shared state, file and network helpers, the passcode, the one-at-a-time
guard, and the HTTP server that receives uploads. The window (gui.py) and the command line (main.py)
are just two ways of driving this.
"""

import getpass
import hmac
import ipaddress
import os
import re
import secrets
import shutil
import socket
import sys
import tempfile
import threading
import time
import uuid
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote

import pages

if sys.platform == "win32":
    import msvcrt      # file locking on Windows
else:
    import fcntl       # file locking on macOS and Linux

# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------
APP_NAME = "Local Upload Server"
DEFAULT_PORT = 8080

CHUNK = 1024 * 1024                     # uploads are streamed to disk 1 MB at a time
MIN_FREE_SPACE = 50 * 1024 * 1024       # refuse an upload if the disk would drop below this
REQUEST_TIMEOUT = 60                    # seconds before a stalled connection is dropped
MAX_LOGIN_BODY = 1024                   # bytes; the login form is tiny, so anything bigger is junk

MAX_PASSCODE_LEN = 12                   # longest passcode allowed
MAX_FAILS = 5                           # wrong passcodes allowed ...
LOCKOUT_SECONDS = 60                    # ... before that device is locked out for this long


# --------------------------------------------------------------------------
# Files and folders
# --------------------------------------------------------------------------
# Names Windows refuses to use for files
RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}


def get_downloads_folder():
    """The user's real Downloads folder (follows Windows relocation), falling back to ~/Downloads."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

            # FOLDERID_Downloads = {374DE290-123F-4565-9164-39C4925E467B}
            fid = GUID(0x374DE290, 0x123F, 0x4565,
                       (ctypes.c_ubyte * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))
            buf = ctypes.c_wchar_p()
            res = ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(fid), 0, None, ctypes.byref(buf))
            if res == 0 and buf.value:
                path = buf.value
                ctypes.windll.ole32.CoTaskMemFree(buf)
                return path
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Downloads")


def safe_filename(raw):
    """Turn whatever the browser sends into a safe Windows filename."""
    name = raw.replace("\\", "/").split("/")[-1]
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name).strip().rstrip(". ")
    if not name:
        name = "upload"
    stem, ext = os.path.splitext(name)
    if stem.upper() in RESERVED:
        stem = "_" + stem
    stem = stem[:150]
    return stem + ext[:20]


def unique_name(folder, name):
    """Never overwrite: photo.jpg -> photo_1.jpg -> photo_2.jpg ..."""
    stem, ext = os.path.splitext(name)
    candidate, n = name, 1
    while os.path.exists(os.path.join(folder, candidate)):
        candidate = f"{stem}_{n}{ext}"
        n += 1
    return candidate


def check_writable(path):
    """Return None if we can create/write in this folder, otherwise a readable error."""
    try:
        os.makedirs(path, exist_ok=True)
        with tempfile.TemporaryFile(dir=path):
            pass
        return None
    except OSError as e:
        return e.strerror or str(e)


def human_size(n):
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.0f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.1f} MB"
    return f"{n / 1024 ** 3:.2f} GB"


DEFAULT_BASE = get_downloads_folder()   # where uploads go unless another folder is chosen


# --------------------------------------------------------------------------
# Shared state and the activity log
# --------------------------------------------------------------------------
# Settings for the current run: passcode (None = no passcode) and save folder
STATE = {"passcode": None, "dir": DEFAULT_BASE}
STATS = {"files": 0, "bytes": 0}    # uploads received since the server started

SESSIONS = set()                    # login cookies that are currently valid
FAILS = {}                          # client ip -> (wrong passcodes so far, locked until)
AUTH_LOCK = threading.Lock()        # guards SESSIONS and FAILS
FILE_LOCK = threading.Lock()        # stops two uploads from picking the same filename


def _console_log(kind, text):
    """Default log sink: print to the terminal."""
    prefix = {"ok": "[+]", "warn": "[!]", "err": "[x]"}.get(kind, "   ")
    print(f"{prefix} {text}")


_sink = _console_log


def set_log_sink(sink=None):
    """Send log lines to `sink(kind, text)`; no argument goes back to the terminal."""
    global _sink
    _sink = sink or _console_log


def log(kind, text):
    """Report an event. kind: 'ok' (file received), 'info', 'warn' or 'err'."""
    try:
        _sink(kind, text)
    except Exception:
        pass  # logging must never break a transfer


def reset_runtime_state():
    """Fresh start: forget old logins, lockouts, and counters."""
    with AUTH_LOCK:
        SESSIONS.clear()
        FAILS.clear()
    STATS["files"] = 0
    STATS["bytes"] = 0


# --------------------------------------------------------------------------
# Network
# --------------------------------------------------------------------------
def get_local_ip():
    """Find the LAN address (no traffic is actually sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def is_local_client(ip):
    """Only accept devices on your own network (blocks accidental internet exposure)."""
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
        if getattr(addr, "ipv4_mapped", None):
            addr = addr.ipv4_mapped
        return addr.is_private or addr.is_loopback or addr.is_link_local
    except ValueError:
        return False


# --------------------------------------------------------------------------
# Passcode
# --------------------------------------------------------------------------
def random_passcode():
    """A random 4-digit passcode."""
    return f"{secrets.randbelow(10000):04d}"


def check_passcode(passcode):
    """Return a message if the passcode can't be used, otherwise None."""
    if not passcode:
        return "The passcode can't be empty."
    if len(passcode) > MAX_PASSCODE_LEN:
        return f"The passcode can be at most {MAX_PASSCODE_LEN} characters."
    if any(ch.isspace() for ch in passcode):
        return "The passcode can't contain spaces."
    return None


def remaining_lockout(ip):
    """Seconds this device must still wait, or 0 if it may try."""
    with AUTH_LOCK:
        _, locked_until = FAILS.get(ip, (0, 0))
    wait = locked_until - time.time()
    return int(wait) + 1 if wait > 0 else 0


def passcode_matches(attempt):
    """Constant-time comparison; an over-long guess is simply wrong."""
    return len(attempt) <= MAX_PASSCODE_LEN and hmac.compare_digest(attempt.encode(), STATE["passcode"].encode())


def record_failure(ip):
    """Count a wrong guess and start the lockout once the limit is reached."""
    with AUTH_LOCK:
        fails = FAILS.get(ip, (0, 0))[0] + 1
        FAILS[ip] = (0, time.time() + LOCKOUT_SECONDS) if fails >= MAX_FAILS else (fails, 0)


def start_session(ip):
    """Create a login cookie value for a device that entered the right passcode."""
    token = secrets.token_urlsafe(24)
    with AUTH_LOCK:
        SESSIONS.add(token)
        FAILS.pop(ip, None)
    return token


def is_session_valid(token):
    return token in SESSIONS


# --------------------------------------------------------------------------
# One at a time
# --------------------------------------------------------------------------
# Two copies on one PC would fight over the port, the save folder, and the phone's
# address - and on Windows they could even end up sharing a port. So the server takes
# an exclusive lock on a small file first. The operating system frees the lock if the
# program is closed, crashes, or is killed, so it can never get stuck.

def _lock_path():
    try:
        user = re.sub(r"\W", "_", getpass.getuser())
    except Exception:
        user = "user"
    return os.path.join(tempfile.gettempdir(), f"local-upload-server-{user}.lock")


def _try_lock(fd):
    """Lock the file without waiting. True on success, False if another process holds it."""
    if sys.platform == "win32":
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)      # raises OSError if already locked
            return True
        except OSError:
            return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


class AlreadyRunning(Exception):
    """Another Local Upload Server is already running on this PC."""


class InstanceLock:
    """The one-at-a-time lock. acquire() to start, release() to stop."""

    def __init__(self):
        self._fd = None

    def acquire(self):
        """Take the lock or raise AlreadyRunning. If this PC can't lock files at all, carry on without it."""
        try:
            fd = os.open(_lock_path(), os.O_RDWR | os.O_CREAT, 0o600)
            locked = _try_lock(fd)
        except OSError:
            return                      # no usable lock file: don't block the user over it
        if not locked:
            os.close(fd)
            raise AlreadyRunning(f"Another {APP_NAME} is already running on this PC - close it first.")
        self._fd = fd

    def release(self):
        """Give the lock back. Safe to call more than once."""
        fd, self._fd = self._fd, None
        if fd is not None:
            os.close(fd)                # closing the file releases the lock


# --------------------------------------------------------------------------
# HTTP server
# --------------------------------------------------------------------------
def login_page(error=""):
    """The passcode page for the current settings."""
    return pages.render_login(APP_NAME, error, numeric=(STATE["passcode"] or "").isdigit(), max_len=MAX_PASSCODE_LEN)


def upload_page():
    """The upload page for the current save folder."""
    return pages.render_upload(APP_NAME, STATE["dir"])


class Handler(BaseHTTPRequestHandler):
    """Serves the login and upload pages and receives files."""

    server_version = "LocalUploadServer"
    timeout = REQUEST_TIMEOUT

    def log_message(self, fmt, *args):
        pass  # silence the default per-request console output

    # ---- utilities ----
    def send_out(self, code, body=b"", ctype="text/plain; charset=utf-8", headers=None, html=False):
        """Send a response with the standard security headers."""
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if html:
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                "connect-src 'self'; form-action 'self'",
            )
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def client_ip(self):
        """Address of the connecting device."""
        return self.client_address[0]

    def is_authed(self):
        """True if no passcode is set, or the request carries a valid session cookie."""
        if STATE["passcode"] is None:
            return True
        try:
            morsel = SimpleCookie(self.headers.get("Cookie", "")).get("session")
        except Exception:
            return False
        return bool(morsel and is_session_valid(morsel.value))

    def local_only(self):
        """Reject (403) anything that is not on the local network."""
        if is_local_client(self.client_ip()):
            return True
        self.send_out(403, b"Forbidden: local network only")
        return False

    # ---- routes ----
    def do_GET(self):
        """The page: login if the device isn't signed in, otherwise the upload page."""
        if not self.local_only():
            return
        if self.path.split("?")[0] != "/":
            return self.send_out(404, b"Not found")
        page = upload_page() if self.is_authed() else login_page()
        self.send_out(200, page, "text/html; charset=utf-8", html=True)

    def do_POST(self):
        """Route /login and /upload."""
        if not self.local_only():
            return
        path = self.path.split("?")[0]
        if path == "/login":
            return self.handle_login()
        if path == "/upload":
            return self.handle_upload()
        if path == "/":
            # A phone still showing a cached old page posts here: send it to a fresh one
            return self.send_out(
                200,
                b'<meta name="viewport" content="width=device-width">'
                b'<meta http-equiv="refresh" content="1;url=/">'
                b'<p style="font-family:sans-serif;text-align:center;padding:30px">'
                b"Old cached page detected - reloading, then try again.</p>",
                "text/html; charset=utf-8",
                headers={"Connection": "close"},
                html=True,
            )
        self.send_out(404, b"Not found")

    # ---- login ----
    def handle_login(self):
        """Check the submitted passcode; lock the device out after too many wrong ones."""
        if STATE["passcode"] is None:
            return self.send_out(303, headers={"Location": "/"})

        ip = self.client_ip()
        wait = remaining_lockout(ip)
        if wait:
            return self.send_out(429, login_page(f"Too many attempts. Try again in {wait}s."),
                                 "text/html; charset=utf-8", html=True)

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_LOGIN_BODY:
            return self.send_out(400, b"Bad request")
        form = parse_qs(self.rfile.read(length).decode("utf-8", errors="ignore"))

        if passcode_matches(form.get("passcode", [""])[0]):
            cookie = f"session={start_session(ip)}; HttpOnly; SameSite=Strict; Path=/"
            return self.send_out(303, headers={"Location": "/", "Set-Cookie": cookie})

        record_failure(ip)
        log("warn", f"Wrong passcode from {ip}")
        self.send_out(403, login_page("Wrong passcode."), "text/html; charset=utf-8", html=True)

    # ---- upload (the raw body is streamed straight to disk) ----
    def handle_upload(self):
        """Stream one file to disk under a safe, unused name."""
        if not self.is_authed():
            return self.send_out(401, b"Not logged in", headers={"Connection": "close"})

        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self.send_out(411, b"Content-Length required")
        if length <= 0:
            return self.send_out(400, b"Empty file")

        folder = STATE["dir"]
        try:
            os.makedirs(folder, exist_ok=True)  # created on the first upload, so no empty folders
            if shutil.disk_usage(folder).free < length + MIN_FREE_SPACE:
                return self.send_out(507, b"Not enough disk space on PC")
        except OSError:
            return self.send_out(500, b"Cannot write to the save folder on the PC")

        name = safe_filename(unquote(self.headers.get("X-Filename", "")))
        tmp = os.path.join(folder, f".{uuid.uuid4().hex}.part")
        received = 0
        try:
            with open(tmp, "wb") as f:
                while received < length:
                    chunk = self.rfile.read(min(CHUNK, length - received))
                    if not chunk:
                        raise ConnectionError("client disconnected")
                    f.write(chunk)
                    received += len(chunk)
            with FILE_LOCK:  # two simultaneous uploads must not pick the same name
                final = unique_name(folder, name)
                os.replace(tmp, os.path.join(folder, final))
                STATS["files"] += 1
                STATS["bytes"] += received
        except (OSError, ConnectionError) as e:
            try:
                os.remove(tmp)
            except OSError:
                pass
            log("err", f"Upload of '{name}' failed: {e}")
            try:
                self.send_out(500, b"Upload failed")
            except OSError:
                pass
            return

        log("ok", f"{final}  ({human_size(received)})")
        self.send_out(200, final.encode("utf-8"))


class LocalServer(ThreadingHTTPServer):
    """The HTTP server. It holds the one-at-a-time lock from creation until it is closed.

    Raises AlreadyRunning if another copy is running, or OSError if the port is taken.
    """

    # On Windows, SO_REUSEADDR lets two programs share a port, so it stays off there.
    # On macOS and Linux it only allows a quick restart, so it stays on.
    allow_reuse_address = sys.platform != "win32"

    def __init__(self, port):
        self._instance = InstanceLock()
        self._instance.acquire()
        try:
            super().__init__(("", port), Handler)
        except BaseException:
            self._instance.release()
            raise

    def server_close(self):
        super().server_close()
        self._instance.release()


class ServerRunner:
    """Runs a LocalServer on a background thread so the window can start and stop it."""

    def __init__(self, port):
        self.httpd = LocalServer(port)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
