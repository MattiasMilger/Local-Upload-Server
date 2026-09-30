#!/usr/bin/env python3
"""Local Upload Server - send files from your phone to your PC over your home network.

Standard library only, no pip installs.

    python main.py                   open the desktop window
    python main.py --cli             command line: asks for save folder and passcode
    python main.py --passcode Fox42  command line: use this passcode
    python main.py --no-passcode     command line: no passcode, no questions

Other options: --port 8080  --dir "D:\\My\\Uploads"
Giving any option starts the command-line mode instead of the window.
"""

import argparse
import os
import sys

from server import (APP_NAME, DEFAULT_BASE, DEFAULT_PORT, MAX_PASSCODE_LEN, STATE, AlreadyRunning,
                    LocalServer, check_passcode, check_writable, get_local_ip, random_passcode)


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------
def choose_passcode():
    """Ask for a passcode. Returns None for no passcode."""
    print("Passcode (recommended on shared or public Wi-Fi)")
    while True:
        try:
            ans = input(f"  Enter = no passcode  |  r = random passcode  |  or type your own (max {MAX_PASSCODE_LEN} characters): ").strip()
        except EOFError:
            return None
        if not ans:
            return None
        if ans.lower() == "r":
            return random_passcode()
        err = check_passcode(ans)
        if err is None:
            return ans
        print(f"  {err}")


def choose_location():
    print("Save location")
    print(f"  Default: {DEFAULT_BASE}")
    while True:
        try:
            ans = input("  Enter = default  |  or paste a folder path: ").strip().strip("\"'")
        except EOFError:
            return DEFAULT_BASE
        if not ans:
            return DEFAULT_BASE
        path = os.path.abspath(os.path.expandvars(os.path.expanduser(ans)))
        err = check_writable(path)
        if err is None:
            return path
        print(f"  Can't use that folder: {err}")


def print_banner(ip, port):
    """Show the phone address, save folder, and passcode."""
    passcode = STATE["passcode"] if STATE["passcode"] else "off (anyone on your network can upload)"
    print()
    print("=" * 56)
    print(" LOCAL UPLOAD SERVER")
    print(" Open this on your phone (same Wi-Fi):")
    print(f"     http://{ip}:{port}")
    print()
    print(f" Saving to: {STATE['dir']}")
    print("            (folder is created when the first file arrives)")
    print(f" Passcode:  {passcode}")
    print()
    print(" First run: if Windows asks, allow access on PRIVATE networks.")
    print(" Press Ctrl+C to stop.")
    print("=" * 56)


def run_cli(args):
    """Apply the command-line options, ask about anything missing, and serve until Ctrl+C."""
    if args.dir:
        base = os.path.abspath(os.path.expandvars(os.path.expanduser(args.dir)))
        err = check_writable(base)
        if err:
            raise RuntimeError(f"Can't use --dir folder: {err}")
    else:
        base = choose_location()
        err = check_writable(base)
        if err:
            raise RuntimeError(f"Can't use save folder {base}: {err}")
    STATE["dir"] = base

    if args.passcode is not None:
        err = check_passcode(args.passcode)
        if err:
            raise RuntimeError(f"Can't use --passcode: {err}")
        STATE["passcode"] = args.passcode
    elif args.no_passcode:
        STATE["passcode"] = None
    else:
        STATE["passcode"] = choose_passcode()

    port = args.port if args.port is not None else DEFAULT_PORT
    with LocalServer(port) as httpd:
        print_banner(get_local_ip(), port)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


# --------------------------------------------------------------------------
# Startup
# --------------------------------------------------------------------------
def parse_args():
    ap = argparse.ArgumentParser(description=f"{APP_NAME} - phone -> PC file transfer")
    ap.add_argument("--cli", action="store_true", help="use the command line instead of the desktop window")
    ap.add_argument("--port", type=int, default=None, help=f"port to listen on (default {DEFAULT_PORT})")
    ap.add_argument("--dir", help="folder to save uploads in (default: your Downloads folder)")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--passcode", help=f"require this passcode (max {MAX_PASSCODE_LEN} characters)")
    group.add_argument("--no-passcode", action="store_true", help="don't use a passcode")
    return ap.parse_args()


def open_window():
    """Open the desktop window. Returns False if that isn't possible (no tkinter or no display)."""
    try:
        from gui import UploadApp
    except ImportError:
        print("The desktop window needs tkinter, which isn't installed - using the command line instead.\n")
        return False

    import tkinter
    try:
        app = UploadApp()
    except tkinter.TclError as e:
        print(f"Couldn't open the window ({e}) - using the command line instead.\n")
        return False
    app.run()
    return True


def main():
    args = parse_args()

    # Any option means "command line"; with no options the window opens.
    wants_cli = (args.cli or args.dir is not None or args.passcode is not None
                 or args.no_passcode or args.port is not None)
    if wants_cli or not open_window():
        run_cli(args)


if __name__ == "__main__":
    try:
        main()
    except AlreadyRunning as e:
        print(f"\n[ERROR] {e}")
        input("\nPress Enter to exit...")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] {APP_NAME} failed to start: {e}")
        if isinstance(e, OSError):
            print("Is the port already in use? Try --port 8081")
        input("\nPress Enter to exit...")
        sys.exit(1)
