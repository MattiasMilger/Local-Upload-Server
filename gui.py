"""Local Upload Server - the desktop window.

Dark theme, rounded widgets drawn on tkinter canvases (no extra packages), and
the window itself: a settings screen and a running screen. The server runs on a
background thread and reports events through a queue that the window reads on a timer.
"""

import os
import queue
import subprocess
import sys
import time
import tkinter as tk
from tkinter import filedialog, ttk
from tkinter import font as tkfont

from server import (APP_NAME, DEFAULT_BASE, DEFAULT_PORT, MAX_PASSCODE_LEN, STATE, STATS,
                    AlreadyRunning, ServerRunner, check_passcode, check_writable, get_local_ip,
                    human_size, random_passcode, reset_runtime_state, set_log_sink)

# --------------------------------------------------------------------------
# Theme
# --------------------------------------------------------------------------
# Palette: navy background with a red-pink brand accent
C_BG = "#1a1a2e"            # window background
C_PANEL = "#16213e"         # cards
C_ACCENT = "#0f3460"        # secondary buttons, inner boxes, borders
C_ACCENT_HOVER = "#1a4a8a"
C_BRAND = "#e94560"         # title, primary button, switches
C_BRAND_HOVER = "#c73050"
C_TEXT = "#eaeaea"
C_MUTED = "#888888"         # secondary text
C_SOFT = "#aaaacc"          # hints on accent boxes, info lines in the log
C_OK = "#55cc88"
C_WARN = "#ffbb55"
C_WARN_BG = "#2a1a0a"
C_ERR = "#ff6666"
C_STOP = "#6b2020"          # stop button
C_STOP_HOVER = "#9b3030"
C_OFF = "#2c3557"           # switch track when off
C_DISABLED = "#252a40"      # disabled buttons and switches

SCALE = 1.0                 # screen scaling; 1.0 = 96 dpi
F = {}                      # named fonts, filled in by build_fonts()


def px(n):
    """Scale a pixel size for high-DPI screens."""
    return max(1, int(round(n * SCALE)))


def build_fonts(root):
    """Set SCALE from the screen DPI and pick the fonts. Sizes are in pixels, so they follow SCALE."""
    global SCALE
    SCALE = max(1.0, root.winfo_fpixels("1i") / 96.0)
    families = set(tkfont.families(root))
    default_ui = tkfont.nametofont("TkDefaultFont").actual("family")
    default_mono = tkfont.nametofont("TkFixedFont").actual("family")
    ui = next((f for f in ("Segoe UI", "SF Pro Text", "Helvetica Neue", "Ubuntu", "Noto Sans",
                           "DejaVu Sans") if f in families), default_ui)
    mono = next((f for f in ("Consolas", "Menlo", "DejaVu Sans Mono", "Courier New")
                 if f in families), default_mono)
    F.update({
        "title": (ui, -px(32), "bold"),
        "head": (ui, -px(15), "bold"),
        "body": (ui, -px(13)),
        "bold": (ui, -px(13), "bold"),
        "small": (ui, -px(11)),
        "btn": (ui, -px(13)),
        "btn_big": (ui, -px(15), "bold"),
        "addr": (mono, -px(21), "bold"),    # phone address
        "field": (mono, -px(15), "bold"),   # passcode and port
        "mono": (mono, -px(12)),            # activity log
    })


def enable_dpi_awareness():
    """Keep the window sharp on high-DPI Windows screens (no-op elsewhere)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def dark_titlebar(root):
    """Dark title bar on Windows 10/11 (no-op elsewhere)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        value = ctypes.c_int(1)
        for attribute in (20, 19):  # 20 = Windows 11 / recent 10, 19 = older 10 builds
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass


# --------------------------------------------------------------------------
# Widgets
# --------------------------------------------------------------------------
def round_rect(canvas, x1, y1, x2, y2, r, **kw):
    """Draw a rounded rectangle (a smoothed polygon). Extra options go to create_polygon."""
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [x1 + r, y1, x1 + r, y1, x2 - r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y1 + r,
           x2, y2 - r, x2, y2 - r, x2, y2, x2 - r, y2, x2 - r, y2, x1 + r, y2, x1 + r, y2,
           x1, y2, x1, y2 - r, x1, y2 - r, x1, y1 + r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)


def pill(canvas, x1, y1, x2, y2, fill):
    """A fully rounded bar (two circles and a rectangle) - crisper than a smoothed polygon."""
    h = y2 - y1
    canvas.create_oval(x1, y1, x1 + h, y2, fill=fill, outline=fill)
    canvas.create_oval(x2 - h, y1, x2, y2, fill=fill, outline=fill)
    canvas.create_rectangle(x1 + h / 2, y1, x2 - h / 2, y2, fill=fill, outline=fill)


class Card(tk.Frame):
    """A rounded panel. Put your widgets in card.inner."""

    def __init__(self, parent, fill=C_PANEL, radius=12, pad=(20, 18)):
        bg = parent.cget("bg")
        super().__init__(parent, bg=bg)
        self._fill = fill
        self._radius = px(radius)
        self._cv = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self._cv.place(x=0, y=0, relwidth=1, relheight=1)
        self.inner = tk.Frame(self, bg=fill)
        self.inner.pack(fill="both", expand=True, padx=px(pad[0]), pady=px(pad[1]))
        self._cv.bind("<Configure>", self._draw)

    def _draw(self, e):
        """Repaint the rounded background whenever the card is resized."""
        self._cv.delete("all")
        round_rect(self._cv, 0, 0, e.width, e.height, self._radius, fill=self._fill, outline=self._fill)


class Button(tk.Canvas):
    """A flat rounded button with a hover colour. Use fill=<background> plus outline= for a ghost button."""

    def __init__(self, parent, text, command=None, width=150, height=36, fill=C_ACCENT,
                 hover=C_ACCENT_HOVER, color=C_TEXT, outline=None, font=None, radius=8):
        bg = parent.cget("bg")
        super().__init__(parent, width=px(width), height=px(height), bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._label = text
        self._command = command
        self._fill, self._hover, self._color, self._outline = fill, hover, color, outline
        self._font = font or F["btn"]
        self._radius = px(radius)
        self._over = False
        self._enabled = True
        self.bind("<Enter>", lambda e: self._set_over(True))
        self.bind("<Leave>", lambda e: self._set_over(False))
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Configure>", lambda e: self._draw())
        self._draw()

    def _set_over(self, over):
        self._over = over
        self._draw()

    def _release(self, e):
        """Fire the command only if the mouse is still over the button."""
        if self._enabled and 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height():
            if self._command:
                self._command()

    def set(self, text=None, fill=None, hover=None, color=None):
        """Change the label or colours after creation."""
        if text is not None:
            self._label = text
        if fill is not None:
            self._fill = fill
        if hover is not None:
            self._hover = hover
        if color is not None:
            self._color = color
        self._draw()

    def set_enabled(self, enabled):
        """Grey the button out (or bring it back)."""
        self._enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow")
        self._draw()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width() if self.winfo_width() > 4 else int(self["width"])
        h = self.winfo_height() if self.winfo_height() > 4 else int(self["height"])
        if not self._enabled:
            fill, color, outline = C_DISABLED, C_MUTED, C_DISABLED
        else:
            fill = self._hover if self._over else self._fill
            color = self._color
            outline = self._outline or fill
        round_rect(self, 1, 1, w - 1, h - 1, self._radius, fill=fill, outline=outline, width=1)
        self.create_text(w / 2, h / 2, text=self._label, fill=color, font=self._font)


class Switch(tk.Frame):
    """A toggle switch with a label, bound to a BooleanVar."""

    def __init__(self, parent, text, variable, command=None):
        bg = parent.cget("bg")
        super().__init__(parent, bg=bg)
        self._var = variable
        self._command = command
        self._enabled = True
        self._cv = tk.Canvas(self, width=px(40), height=px(22), bg=bg, highlightthickness=0,
                             bd=0, cursor="hand2")
        self._cv.pack(side="left")
        self._lbl = tk.Label(self, text=text, font=F["body"], fg=C_TEXT, bg=bg, cursor="hand2")
        self._lbl.pack(side="left", padx=(px(10), 0))
        for w in (self._cv, self._lbl):
            w.bind("<Button-1>", self._toggle)
        variable.trace_add("write", lambda *a: self._draw())
        self._draw()

    def _toggle(self, e=None):
        """Flip the variable and run the command."""
        if not self._enabled:
            return
        self._var.set(not self._var.get())
        if self._command:
            self._command()

    def set_enabled(self, enabled):
        """Dim the switch and its label (or bring them back)."""
        self._enabled = enabled
        cursor = "hand2" if enabled else "arrow"
        self._cv.configure(cursor=cursor)
        self._lbl.configure(cursor=cursor, fg=C_TEXT if enabled else C_MUTED)
        self._draw()

    def _draw(self):
        cv = self._cv
        cv.delete("all")
        w, h = px(40), px(22)
        on = bool(self._var.get())
        if self._enabled:
            track = C_BRAND if on else C_OFF
        else:
            track = "#7a3040" if on else C_DISABLED
        pill(cv, 0, 0, w - 1, h - 1, track)
        pad = px(3)
        d = h - 2 * pad
        x = w - pad - d if on else pad
        cv.create_oval(x, pad, x + d, pad + d, fill=C_TEXT if self._enabled else C_MUTED, outline="")


class Field(tk.Canvas):
    """A rounded text field; the Entry inside is .entry.

    max_len caps the length and blocks spaces, for things like the passcode.
    """

    def __init__(self, parent, variable, width=None, height=34, font=None, justify="left", max_len=None):
        bg = parent.cget("bg")
        size = {"width": px(width)} if width else {}
        super().__init__(parent, height=px(height), bg=bg, highlightthickness=0, bd=0, **size)
        self._focus = False
        self._enabled = True
        self.entry = tk.Entry(self, textvariable=variable, bd=0, highlightthickness=0,
                              relief="flat", bg=C_BG, fg=C_TEXT, insertbackground=C_TEXT,
                              disabledbackground=C_BG, disabledforeground=C_MUTED,
                              selectbackground=C_ACCENT_HOVER, selectforeground=C_TEXT,
                              font=font or F["body"], justify=justify)
        if max_len:
            def allowed(proposed):
                return len(proposed) <= max_len and not any(c.isspace() for c in proposed)
            self.entry.configure(validate="key", validatecommand=(self.register(allowed), "%P"))
        self._win = self.create_window(px(12), 0, window=self.entry, anchor="w")
        self.bind("<Configure>", self._layout)
        self.entry.bind("<FocusIn>", lambda e: self._set_focus(True))
        self.entry.bind("<FocusOut>", lambda e: self._set_focus(False))

    def _set_focus(self, focus):
        """Highlight the border while the field has focus."""
        self._focus = focus
        self._layout()

    def _layout(self, e=None):
        """Redraw the border and stretch the Entry to fit."""
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4:
            return
        self.delete("bg")
        border = C_BRAND if (self._focus and self._enabled) else C_ACCENT
        round_rect(self, 1, 1, w - 1, h - 1, px(8), fill=C_BG, outline=border, width=1, tags="bg")
        self.tag_lower("bg")
        self.coords(self._win, px(12), h / 2)
        self.itemconfigure(self._win, width=max(10, w - px(24)))

    def set_enabled(self, enabled):
        """Lock the field (or unlock it)."""
        self._enabled = enabled
        self.entry.configure(state="normal" if enabled else "disabled")
        self._layout()


# --------------------------------------------------------------------------
# Window
# --------------------------------------------------------------------------
class UploadApp:
    """The window. Call run() to show it."""

    def __init__(self):
        enable_dpi_awareness()
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.configure(bg=C_BG)
        build_fonts(self.root)
        room = self.root.winfo_screenheight() - px(90)
        self.setup_height = min(px(510), room)
        self.run_height = min(px(740), room)
        self.root.geometry(f"{px(620)}x{self.setup_height}")
        dark_titlebar(self.root)

        self.queue = queue.Queue()      # log lines from server threads -> window
        self.runner = None              # ServerRunner while the server is up
        self.url = ""                   # phone address while the server is up

        self.var_dir = tk.StringVar(value=DEFAULT_BASE)
        self.var_use_passcode = tk.BooleanVar(value=True)
        self.var_passcode = tk.StringVar(value=random_passcode())
        self.var_port = tk.StringVar(value=str(DEFAULT_PORT))

        self.setup_style()
        self.build()
        self.update_passcode_widgets()
        self.show_page("setup")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---- construction ----
    def setup_style(self):
        """Dark, slim scrollbar for the activity log (the clam theme accepts custom colours)."""
        style = ttk.Style(self.root)
        style.theme_use("clam")
        name = "Dark.Vertical.TScrollbar"
        style.layout(name, [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
            ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        style.configure(name, troughcolor=C_BG, background=C_ACCENT, bordercolor=C_BG,
                        lightcolor=C_ACCENT, darkcolor=C_ACCENT, relief="flat", width=px(9))
        style.map(name, background=[("active", C_ACCENT_HOVER), ("pressed", C_ACCENT_HOVER)],
                  lightcolor=[("active", C_ACCENT_HOVER)], darkcolor=[("active", C_ACCENT_HOVER)])

    def build(self):
        """Header plus the two screens, stacked in one spot; show_page() raises one."""
        root = self.root
        root.grid_columnconfigure(0, weight=1)
        root.grid_rowconfigure(1, weight=1)

        head = tk.Frame(root, bg=C_BG)
        head.grid(row=0, column=0, pady=(px(26), px(16)))
        tk.Label(head, text=APP_NAME, font=F["title"], fg=C_BRAND, bg=C_BG).pack()
        tk.Label(head, text="by Mattias  \u00b7  phone \u2192 PC over your Wi-Fi", font=F["small"],
                 fg=C_MUTED, bg=C_BG).pack(pady=(px(2), 0))

        body = tk.Frame(root, bg=C_BG)
        body.grid(row=1, column=0, sticky="nsew", padx=px(28), pady=(0, px(22)))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)
        self.page_setup = tk.Frame(body, bg=C_BG)
        self.page_run = tk.Frame(body, bg=C_BG)
        for page in (self.page_setup, self.page_run):
            page.grid(row=0, column=0, sticky="nsew")
        self.build_setup(self.page_setup)
        self.build_run(self.page_run)

    def build_setup(self, page):
        """Settings screen: save folder, passcode, port, and the Start button."""
        page.grid_columnconfigure(0, weight=1)
        card = Card(page)
        card.grid(row=0, column=0, sticky="ew")
        c = card.inner

        tk.Label(c, text="Settings", font=F["head"], fg=C_TEXT, bg=C_PANEL, anchor="w").pack(fill="x")

        # save folder
        tk.Label(c, text="Save uploads to", font=F["small"], fg=C_MUTED, bg=C_PANEL,
                 anchor="w").pack(fill="x", pady=(px(16), px(5)))
        row = tk.Frame(c, bg=C_PANEL)
        row.pack(fill="x")
        self.f_dir = Field(row, self.var_dir)
        self.f_dir.pack(side="left", fill="x", expand=True)
        self.b_browse = Button(row, "Browse", self.browse, width=92, height=34)
        self.b_browse.pack(side="left", padx=(px(8), 0))


        tk.Frame(c, bg=C_ACCENT, height=1).pack(fill="x", pady=px(18))   # divider

        # passcode
        passcoderow = tk.Frame(c, bg=C_PANEL)
        passcoderow.pack(fill="x")
        self.sw_passcode = Switch(passcoderow, "Require passcode", self.var_use_passcode, command=self.update_passcode_widgets)
        self.sw_passcode.pack(side="left")
        self.b_rand = Button(passcoderow, "New random", lambda: self.var_passcode.set(random_passcode()),
                             width=110, height=34)
        self.b_rand.pack(side="right")
        self.f_passcode = Field(passcoderow, self.var_passcode, width=150, font=F["field"], justify="center",
                            max_len=MAX_PASSCODE_LEN)
        self.f_passcode.pack(side="right", padx=(0, px(8)))

        # port
        portrow = tk.Frame(c, bg=C_PANEL)
        portrow.pack(fill="x", pady=(px(14), 0))
        tk.Label(portrow, text="Port", font=F["body"], fg=C_TEXT, bg=C_PANEL).pack(side="left")
        self.f_port = Field(portrow, self.var_port, width=92, font=F["field"], justify="center")
        self.f_port.pack(side="right")

        # start
        self.b_start = Button(page, "Start server  \u2192", self.start_server, width=240, height=46,
                              fill=C_BRAND, hover=C_BRAND_HOVER, font=F["btn_big"], radius=10)
        self.b_start.grid(row=1, column=0, pady=(px(26), px(8)))
        self.lbl_fb = tk.Label(page, text="", font=F["small"], fg=C_ERR, bg=C_BG, wraplength=px(500))
        self.lbl_fb.grid(row=2, column=0)
        tk.Label(page, text="Only devices on your local network can connect.", font=F["small"],
                 fg=C_MUTED, bg=C_BG).grid(row=3, column=0, pady=(px(4), 0))

    def build_run(self, page):
        """Running screen: phone address, passcode, live counter, activity log, Stop button."""
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)

        # status card
        status = Card(page)
        status.grid(row=0, column=0, sticky="ew")
        s = status.inner
        top = tk.Frame(s, bg=C_PANEL)
        top.pack(fill="x")
        tk.Label(top, text="\u25cf Running", font=F["bold"], fg=C_OK, bg=C_PANEL).pack(side="left")
        self.lbl_stats = tk.Label(top, text="", font=F["small"], fg=C_MUTED, bg=C_PANEL)
        self.lbl_stats.pack(side="right")

        box = Card(s, fill=C_ACCENT, radius=8, pad=(16, 12))
        box.pack(fill="x", pady=(px(12), 0))
        b = box.inner
        tk.Label(b, text="On your phone (same Wi-Fi), open this address:", font=F["small"],
                 fg=C_SOFT, bg=C_ACCENT, anchor="w").pack(fill="x")
        arow = tk.Frame(b, bg=C_ACCENT)
        arow.pack(fill="x", pady=(px(6), 0))
        self.lbl_url = tk.Label(arow, text="", font=F["addr"], fg=C_TEXT, bg=C_ACCENT)
        self.lbl_url.pack(side="left")
        self.b_copy = Button(arow, "Copy", self.copy_url, width=84, height=32,
                             fill=C_BRAND, hover=C_BRAND_HOVER)
        self.b_copy.pack(side="right")

        # passcode, or a warning when there is none (start_server() shows the right one)
        self.passcode_row = tk.Frame(s, bg=C_PANEL)
        tk.Label(self.passcode_row, text="Passcode", font=F["small"], fg=C_MUTED, bg=C_PANEL).pack(side="left")
        self.lbl_passcode = tk.Label(self.passcode_row, text="", font=F["field"], fg=C_TEXT, bg=C_PANEL)
        self.lbl_passcode.pack(side="left", padx=(px(10), 0))
        self.warn = Card(s, fill=C_WARN_BG, radius=8, pad=(14, 9))
        tk.Label(self.warn.inner, text="No passcode - anyone on your network can upload.",
                 font=F["small"], fg=C_WARN, bg=C_WARN_BG, anchor="w").pack(fill="x")
        self.lbl_dir = tk.Label(s, text="", font=F["small"], fg=C_MUTED, bg=C_PANEL, anchor="w",
                                justify="left", wraplength=px(500))
        self.lbl_dir.pack(fill="x", pady=(px(10), 0))

        # activity log
        act = Card(page)
        act.grid(row=1, column=0, sticky="nsew", pady=(px(12), 0))
        a = act.inner
        ahead = tk.Frame(a, bg=C_PANEL)
        ahead.pack(fill="x")
        tk.Label(ahead, text="Activity", font=F["head"], fg=C_TEXT, bg=C_PANEL).pack(side="left")
        Button(ahead, "Clear", self.clear_log, width=64, height=26, fill=C_PANEL,
               hover=C_ACCENT, color=C_MUTED, font=F["small"]).pack(side="right")
        wrap = Card(a, fill=C_BG, radius=8, pad=(8, 6))
        wrap.pack(fill="both", expand=True, pady=(px(10), 0))
        self.log_box = tk.Text(wrap.inner, bg=C_BG, fg=C_TEXT, font=F["mono"], bd=0,
                               highlightthickness=0, relief="flat", wrap="word", state="disabled",
                               padx=px(6), pady=px(4), cursor="arrow", insertwidth=0,
                               selectbackground=C_ACCENT, height=6)
        bar = ttk.Scrollbar(wrap.inner, orient="vertical", style="Dark.Vertical.TScrollbar",
                            command=self.log_box.yview)
        bar.pack(side="right", fill="y")
        self.log_box.pack(side="left", fill="both", expand=True)

        def on_yview(lo, hi):
            bar.set(lo, hi)
            if float(lo) <= 0.0 and float(hi) >= 1.0:
                bar.pack_forget()                       # nothing to scroll: hide the bar
            elif not bar.winfo_manager():
                bar.pack(side="right", fill="y", before=self.log_box)
        self.log_box.configure(yscrollcommand=on_yview)
        self.log_box.tag_configure("time", foreground=C_MUTED)
        self.log_box.tag_configure("ok", foreground=C_OK)
        self.log_box.tag_configure("warn", foreground=C_WARN)
        self.log_box.tag_configure("err", foreground=C_ERR)
        self.log_box.tag_configure("info", foreground=C_SOFT)

        # buttons
        foot = tk.Frame(page, bg=C_BG)
        foot.grid(row=2, column=0, sticky="ew", pady=(px(14), 0))
        Button(foot, "Open save folder", self.open_folder, width=160, height=40, fill=C_BG,
               hover=C_ACCENT, color=C_MUTED, outline=C_MUTED).pack(side="left")
        self.b_stop = Button(foot, "Stop server", self.stop_server, width=150, height=40,
                             fill=C_STOP, hover=C_STOP_HOVER)
        self.b_stop.pack(side="right")

    # ---- small actions ----
    def show_page(self, name):
        """Switch screen ('setup' or 'run') and resize the window to fit it."""
        run = name == "run"
        (self.page_run if run else self.page_setup).tkraise()
        height = self.run_height if run else self.setup_height
        width = self.root.winfo_width() if self.root.winfo_width() > 1 else px(620)
        self.root.minsize(px(560), min(px(640 if run else 470), height))
        self.root.geometry(f"{width}x{height}")

    def browse(self):
        """Pick the save folder with the system dialog."""
        chosen = filedialog.askdirectory(initialdir=self.current_base(),
                                         title="Choose where to save uploads")
        if chosen:
            self.var_dir.set(os.path.normpath(chosen))

    def update_passcode_widgets(self):
        """The passcode field and New random button only work while Require passcode is on."""
        enabled = bool(self.var_use_passcode.get())
        self.f_passcode.set_enabled(enabled)
        self.b_rand.set_enabled(enabled)

    def copy_url(self):
        """Copy the phone address and flash Copied."""
        if not self.url:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.url)
        self.b_copy.set(text="Copied \u2713")
        self.root.after(1500, lambda: self.b_copy.set(text="Copy"))

    def open_folder(self):
        """Open the save folder in the file manager."""
        folder = STATE["dir"] if self.runner else self.current_base()
        if not os.path.isdir(folder):
            self.add_log("info", "That folder doesn't exist yet - it's created when the first file arrives.")
            return
        try:
            if sys.platform == "win32":
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except OSError as e:
            self.add_log("err", f"Can't open the folder: {e}")

    def clear_log(self):
        """Empty the activity log."""
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def current_base(self):
        """The save folder typed in the window, cleaned up (the default if empty)."""
        raw = self.var_dir.get().strip().strip("\"'")
        if not raw:
            return DEFAULT_BASE
        return os.path.abspath(os.path.expandvars(os.path.expanduser(raw)))

    def feedback(self, text=""):
        """Show (or clear) the red message under the Start button."""
        self.lbl_fb.configure(text=text)

    # ---- start / stop ----
    def start_server(self):
        """Validate the settings, start the server, and switch to the running screen."""
        self.feedback("")
        base = self.current_base()
        err = check_writable(base)
        if err:
            self.feedback(f"Can't use that folder: {err}")
            return

        passcode = None
        if self.var_use_passcode.get():
            passcode = self.var_passcode.get().strip()
            err = check_passcode(passcode)
            if err:
                self.feedback(err if passcode else "Type a passcode, or switch off \"Require passcode\".")
                return

        try:
            port = int(self.var_port.get())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            self.feedback("Port must be a number between 1 and 65535.")
            return

        STATE["dir"] = base
        STATE["passcode"] = passcode
        reset_runtime_state()
        try:
            self.runner = ServerRunner(port)
        except AlreadyRunning as e:
            self.feedback(str(e))
            return
        except OSError as e:
            self.feedback(f"Can't start the server: {e.strerror or e}. Port {port} may be in use - try another one.")
            return

        self.url = f"http://{get_local_ip()}:{port}"
        self.lbl_url.configure(text=self.url)
        self.lbl_dir.configure(text=f"Saving to:  {STATE['dir']}")
        self.passcode_row.pack_forget()
        self.warn.pack_forget()
        if passcode:
            self.lbl_passcode.configure(text=passcode)
            self.passcode_row.pack(fill="x", pady=(px(12), 0), before=self.lbl_dir)
        else:
            self.warn.pack(fill="x", pady=(px(12), 0), before=self.lbl_dir)
        self.clear_log()
        self.update_stats()
        self.add_log("info", f"Server started on port {port}")
        self.show_page("run")

    def stop_server(self):
        """Stop the server and go back to the settings screen."""
        runner, self.runner = self.runner, None
        try:
            if runner:
                runner.stop()
        finally:
            self.url = ""
            self.feedback("")
            self.show_page("setup")

    # ---- activity log ----
    def on_log(self, kind, text):
        """Log sink for the server: queue the line (runs on server threads)."""
        self.queue.put((kind, text))

    def add_log(self, kind, text):
        """Append a timestamped line to the activity log."""
        marks = {"ok": "\u2713 ", "warn": "! ", "err": "\u2717 "}
        self.log_box.configure(state="normal")
        self.log_box.insert("end", time.strftime("%H:%M:%S") + "  ", "time")
        self.log_box.insert("end", marks.get(kind, "") + text + "\n", kind)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def update_stats(self):
        """Refresh the files-received counter."""
        n = STATS["files"]
        if n:
            self.lbl_stats.configure(
                text=f"{n} file{'s' if n != 1 else ''} received  \u00b7  {human_size(STATS['bytes'])}")
        else:
            self.lbl_stats.configure(text="No files received yet")

    def poll(self):
        """Every 200 ms: move queued log lines into the window and refresh the counter."""
        try:
            while True:
                kind, text = self.queue.get_nowait()
                self.add_log(kind, text)
        except queue.Empty:
            pass
        self.update_stats()
        self.root.after(200, self.poll)

    # ---- lifecycle ----
    def on_close(self):
        """Closing the window also stops the server."""
        if self.runner:
            try:
                self.runner.stop()
            except Exception:
                pass
            self.runner = None
        set_log_sink()              # back to the terminal
        self.root.destroy()

    def run(self):
        """Show the window until it is closed."""
        set_log_sink(self.on_log)
        self.poll()
        self.root.mainloop()
