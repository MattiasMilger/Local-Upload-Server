# Local Upload Server

A small Python tool that moves files from your phone to your PC over your home network. Open the window on the PC, press Start, open the address it shows on your phone, pick your files, and they land in a folder on your computer.

---

## What is this?

Local Upload Server is a small, no-install alternative to emailing yourself photos or plugging in a cable. It runs a tiny web server on your PC and serves a phone-friendly upload page. There is no account, no cloud, and no app to install on the phone - just a browser.

Your files travel directly from the phone to the PC over your own Wi-Fi. Nothing is sent to the internet, and the server refuses connections from anything outside your local network.

### What it does

- Opens a dark, simple desktop window to choose the save folder and passcode, start and stop the server, and watch files arrive - or runs from the command line if you prefer
- Shows the address to type on your phone, with a one-click **Copy** button
- Serves a mobile-first upload page (with drag & drop on desktop and automatic dark mode)
- Lets you review the selected files and confirm before anything is uploaded
- Streams uploads straight to disk in 1 MB chunks, so large videos do not fill up memory
- Never overwrites existing files (`photo.jpg` → `photo_1.jpg` → `photo_2.jpg` ...)
- Protects the page with a passcode - letters and numbers, up to 12 characters (a random one is filled in for you) - with automatic lockout after repeated wrong guesses
- Only accepts devices on your own network (private, loopback, and link-local addresses)
- Saves to your Downloads folder by default, or any folder you choose
- Runs only one copy at a time, so two servers can never fight over the port or the save folder
- Needs nothing but Python - standard library only, no `pip install`

---

## Requirements

### System
- **Python 3.8 or later** (3.12 tested)
- Windows 10/11 (primary target), macOS and Linux should work but are less tested
- PC and phone on the same Wi-Fi network
- **tkinter** for the desktop window - included with Python on Windows and macOS. On some Linux systems install it with `sudo apt install python3-tk`. The command-line mode works without it

### Python packages

None. The tool uses only the Python standard library. The window's dark theme, rounded cards and buttons are drawn with plain tkinter, so no extra UI package is needed.

---

## Setup

**1. Clone or download the repository**

```bash
git clone https://github.com/MattiasMilger/Local-Upload-Server.git
cd Local-Upload-Server
```

**2. Run the app**

```bash
python main.py
```

The window opens. On Windows you can also double-click the file, or start it with `pythonw main.py` to skip the black console window.

**3. Open the address on your phone**

Press **Start server**. The window shows an address like `http://192.168.1.23:8080`. Type that into your phone's browser (same Wi-Fi as the PC).

> On first run Windows may ask whether to allow Python through the firewall. Allow access on **Private networks**.

---

## How to use it

### Desktop window

Run `python main.py` with no options and the window opens. It has two screens.

**Settings screen**

| Control | What it does |
|---------|--------------|
| **Save uploads to** / **Browse** | Folder where uploads are saved (default: your Downloads folder) |
| **Require passcode** | Protects the upload page. A random 4-digit passcode is filled in - type your own (letters and numbers, up to 12 characters, no spaces) or click **New random** |
| **Port** | Port to listen on (default `8080`) |
| **Start server** | Checks your settings and starts the server. Problems (bad folder, passcode too long, port in use, another copy already running) are shown in red under the button |

**Running screen**

| Part | What it shows |
|------|---------------|
| **Address box** | The address to open on your phone, with a **Copy** button |
| **Passcode** | The passcode to type on the phone (or a warning if you switched it off) |
| **Live counter** | Number of files received and total size |
| **Activity** | A line for every file received, every failed upload, and every wrong passcode attempt. **Clear** empties it |
| **Open save folder** | Opens the destination folder in your file manager |
| **Stop server** | Stops the server and returns to the settings screen |

Closing the window stops the server. Nothing is remembered between launches - the window always starts with the defaults.

### Command line

Prefer a terminal, or running without a display? Use `--cli`. Giving any option (`--passcode`, `--no-passcode`, `--dir`, `--port`) also skips the window. With just `--cli` it asks two quick questions:

1. **Save location** - press Enter for your Downloads folder, or paste a folder path
2. **Passcode** - press Enter for no passcode, `r` for a random 4-digit one, or type your own (up to 12 characters)

You can skip the questions with options:

```bash
python main.py --cli                       # command line, asks the two questions
python main.py --passcode Fox42            # use this passcode
python main.py --no-passcode               # no passcode, no questions about it
python main.py --port 8081                 # use a different port
python main.py --dir "D:\My\Uploads"       # save here, no questions about it
```

| Option | What it does |
|--------|--------------|
| `--cli` | Use the command line instead of the desktop window |
| `--port N` | Port to listen on (default `8080`) |
| `--dir PATH` | Folder to save uploads in (default: your Downloads folder) |
| `--passcode PASSCODE` | Require this passcode (letters and numbers, up to 12 characters, no spaces) |
| `--no-passcode` | Do not use a passcode |

`--passcode` and `--no-passcode` cannot be combined. Press **Ctrl+C** to stop the server. If the window cannot open (no display, or tkinter missing), the command line starts automatically instead.

### Upload page

| Step | What you do |
|------|-------------|
| 1 | **Enter passcode** - only shown if the server was started with a passcode |
| 2 | **Choose files** - tap the drop area (or drag & drop on desktop) to select one or more files. You can keep adding more |
| 3 | **Review** - the selected files are listed with their sizes. Remove any with **×**, or click **Clear** to start over |
| 4 | **Upload** - click **Upload N files**. Files are sent one after another with a progress bar and status for each |

Each file shows **Done** when it has been saved, or a short error if it failed. Keep your phone screen on while large files upload.

### Where do my files go?

Files are saved to the folder shown on the upload page, in the window, and in the console. The folder is created when the first file arrives, so you never end up with empty folders.

If a file with the same name already exists, the new one gets a numeric suffix instead of replacing it.

---

## Security

The server is designed for a trusted home network. Please read this before using it anywhere else.

- **Plain HTTP.** Traffic is not encrypted, so the passcode and files can be seen by anyone who can sniff your network. Do not run it on untrusted or public Wi-Fi.
- **Local network only.** Requests from public internet addresses get `403 Forbidden`. Do not forward the port on your router.
- **Passcode.** Up to 12 characters, case-sensitive, no spaces. The limit is enforced in the window, on the command line, in the login form, and again on the server, so an over-long guess simply counts as a wrong one.
- **Lockout.** After 5 wrong passcodes a device is locked out for 60 seconds.
- **Passcode visibility.** The window shows the passcode on screen, and `--passcode Fox42` may end up in your shell history. The interactive `--cli` prompt avoids the second one.
- **Sessions.** Logins are held in memory only and are cleared when you stop the server.
- **Safe filenames.** Names from the phone are sanitised: paths are stripped, characters Windows forbids are replaced, and reserved names such as `CON` or `NUL` are prefixed.
- **No passcode means open.** Without a passcode, anyone on your network can upload to your PC while the server is running. The window and the console both warn you.
- **One copy at a time.** A second copy refuses to start, so a forgotten server can't keep running in the background next to a new one. See [One copy at a time](#one-copy-at-a-time).

---

## Troubleshooting

| Problem | What to try |
|---------|-------------|
| Phone cannot open the address | Check both devices are on the same Wi-Fi, that the firewall allows Python on private networks, and that the router does not have guest or client isolation turned on |
| Window does not open | tkinter is probably missing (on Linux: `sudo apt install python3-tk`) or there is no display. The command line starts instead, or use `--cli` |
| "Another Local Upload Server is already running on this PC" | Close the other copy first - look for another window, or a terminal still running it. It frees itself automatically if that copy was closed or crashed |
| "Can't start the server" / `Local Upload Server failed to start` | Another program is using the port - pick a different one (`--port 8081` on the command line) |
| "The passcode can be at most 12 characters" | Shorten the passcode. Spaces are not allowed either |
| Wrong passcode on the phone | The passcode is case-sensitive. After 5 wrong tries the phone has to wait 60 seconds |
| `403 Forbidden: local network only` | The request came from outside your local network. Some VPN ranges (for example `100.64.0.0/10`) also count as outside |
| `Not enough disk space on PC` | The save drive needs the file size plus 50 MB free |
| `Cannot write to the save folder` | Pick another folder or check its permissions |
| `Empty file` | Zero-byte files are not accepted |
| Old page keeps showing on the phone | Reload the page - a cached older version is detected and redirected automatically |

---

## Technical overview

### Architecture

The tool is four files, split by role. The engine never imports the window, so the command line works even without tkinter.

| File | Job |
|------|-----|
| `main.py` | Entry point and command-line mode - reads the options, then opens the window or serves in the terminal |
| `server.py` | The engine - settings, shared state, file and network helpers, passcode and lockout, the one-at-a-time guard, and the HTTP server |
| `pages.py` | The web pages shown on the phone (HTML, CSS, JavaScript) |
| `gui.py` | The desktop window - dark theme, rounded widgets, settings and running screens |

The engine reports events through one `log()` function. In command-line mode that prints to the terminal; the window swaps in its own sink with `set_log_sink()`. `gui.py` is only imported when the window is used.

There is no database and no config file. State lives in a few in-memory structures and is discarded when the server stops.

### Window design

The window uses a dark navy palette with a red-pink accent. Rounded cards, buttons, switches, and text fields are small custom widgets (`Card`, `Button`, `Switch`, `Field` in `gui.py`) drawn on tkinter canvases, which keeps the tool dependency-free. Sizes and fonts are scaled from the screen DPI, so it stays sharp and unclipped on high-resolution displays. On Windows the title bar is switched to dark mode where supported.

### Threading

Server threads never touch the window. They put log lines on a `queue.Queue`, and the window drains it every 200 ms on the main thread, which is the safe way to update tkinter from other threads. Received-file counters are plain integers that the window reads on the same timer.

### Request flow

| Route | Method | What it does |
|-------|--------|--------------|
| `/` | GET | Serves the login page or the upload page, depending on whether the device is authenticated |
| `/login` | POST | Checks the passcode, applies lockout rules, and sets the session cookie |
| `/upload` | POST | Streams the raw request body to disk |

Every request first passes a local-network check. Responses carry `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, and a strict Content-Security-Policy on HTML pages.

### Upload pipeline

1. The browser sends the file as a raw request body with the name in an `X-Filename` header
2. The server checks the session, the `Content-Length`, and that the drive has enough free space
3. The body is streamed into a hidden temporary `.part` file in the save folder
4. Under a lock, a free filename is chosen and the temporary file is renamed into place
5. If the connection drops or a write fails, the temporary file is deleted, so partial uploads never appear as real files

### One copy at a time

Two copies on one PC would fight over the port, the save folder, and the address on the phone - and on Windows they could even end up sharing a single port, sending uploads to whichever copy answered first. So starting the server does two things first:

1. **Takes a lock.** `InstanceLock` takes an exclusive lock on a small file in the temp folder (`local-upload-server-<user>.lock`), using `msvcrt` on Windows and `fcntl` on macOS and Linux. If another copy holds it, `AlreadyRunning` is raised and the window (or terminal) shows a clear message. The lock is tied to the running process, so the operating system frees it if the program is closed, crashes, or is killed - it can never get stuck, and there is nothing to clean up by hand.
2. **Claims the port exclusively.** On Windows, `LocalServer` turns off `SO_REUSEADDR` so another program can't share the port. On macOS and Linux it stays on, where it only allows a quick restart.

The lock is held only while the server is running. Stopping it in the window (or closing the window) releases it, so you can start a new one straight away. If the lock file can't be created at all (for example a read-only temp folder), the server still starts, just without this guard.

### Persistent state

Nothing is persisted. The only things written to disk are the uploaded files themselves, the save folder if it does not exist yet, and the tiny empty lock file described above.

---

## Project structure

```
Local-Upload-Server/
│
├── main.py                  # Entry point and command-line mode
├── server.py                # Engine - settings, state, passcode, file helpers, one-at-a-time guard, HTTP server
├── pages.py                 # HTML, CSS, and JavaScript for the login and upload pages
├── gui.py                   # Desktop window - theme, rounded widgets, settings and running screens
└── README.md                # This file
```

### Key functions and classes

**`main.py`**

| Name | Role |
|------|------|
| `choose_passcode()` / `choose_location()` | Interactive prompts for `--cli` |
| `print_banner()` | Shows the phone address, save folder, and passcode |
| `run_cli()` | Applies the options and serves until Ctrl+C |
| `parse_args()` | Defines the command-line options |
| `open_window()` | Opens the window; returns `False` if tkinter or a display is missing |
| `main()` | Window by default, command line when an option is given or the window can't open |

**`server.py`**

| Name | Role |
|------|------|
| Settings constants | `APP_NAME`, `DEFAULT_PORT`, `DEFAULT_BASE`, `CHUNK`, `MIN_FREE_SPACE`, `REQUEST_TIMEOUT`, `MAX_PASSCODE_LEN`, `MAX_FAILS`, `LOCKOUT_SECONDS` |
| `get_downloads_folder()` | The real Downloads folder (follows Windows relocation), with a fallback to `~/Downloads` |
| `safe_filename()` / `unique_name()` | Turn whatever the browser sends into a safe Windows filename, and never overwrite an existing file |
| `check_writable()` | Verifies a folder can be created and written to |
| `human_size()` | Formats byte counts as B / KB / MB / GB |
| `STATE` / `STATS` | Current passcode and save folder; files and bytes received |
| `log()` / `set_log_sink()` | Report an event to the terminal or the window |
| `reset_runtime_state()` | Clears logins, lockouts, and counters each time the server starts |
| `get_local_ip()` / `is_local_client()` | LAN address to show on screen; accept only private, loopback, and link-local clients |
| `random_passcode()` / `check_passcode()` | A random 4-digit passcode; enforces the length limit (`MAX_PASSCODE_LEN`) and no spaces |
| `passcode_matches()` / `record_failure()` / `remaining_lockout()` | Constant-time passcode check and lockout after too many wrong ones |
| `start_session()` / `is_session_valid()` | Login cookies |
| `Handler` | `do_GET`, `do_POST`, `handle_login`, `handle_upload` (streams to disk, picks the final filename) |
| `InstanceLock` / `AlreadyRunning` | The one-at-a-time lock, and the error raised when another copy holds it |
| `LocalServer` | The HTTP server: takes the lock before binding the port and gives it back when closed |
| `ServerRunner` | Runs a `LocalServer` on a background thread with a clean `stop()` |

**`pages.py`**

| Name | Role |
|------|------|
| `PAGE` / `LOGIN_BODY` / `UPLOAD_BODY` | The HTML shell and the two page bodies |
| `render_login()` / `render_upload()` | Fill in the templates. They take everything as arguments, so this file depends on nothing else |

**`gui.py`**

| Name | Role |
|------|------|
| Palette (`C_*`), `build_fonts()`, `px()` | Colours, fonts, and screen scaling |
| `enable_dpi_awareness()` / `dark_titlebar()` | Sharp text and a dark title bar on Windows |
| `Card` / `Button` / `Switch` / `Field` | The rounded dark widgets (`Field` can limit its length and block spaces) |
| `UploadApp` | Settings screen, running screen, live activity log, start/stop |

---

## Credits

**Developer**: Mattias Milger  
**Email**: mattias.r.milger@gmail.com  
**GitHub**: [MattiasMilger](https://github.com/MattiasMilger)

## More Projects

Check out more of my work at [mattiasmilger.github.io](https://mattiasmilger.github.io/)