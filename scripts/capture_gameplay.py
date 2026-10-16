"""Play SkiFree with a script and save real screenshots. Windows only.

The game window is created hidden, moved far off-screen, shown without activation and
driven with PostMessage, so it never takes your focus or your keyboard. A fake WM_ACTIVATE
starts the game's timer (it only runs while the window "has focus"), then the script keeps
pressing Down and, past 94 m, turns on fast mode with `f`. It reads the skier's position
from the game's memory (g_player at 0x40c72c, y at +0x42) to know when the yeti is near.

Side effects: crossing the finish line of a course opens the "High Scores" dialog, which
the script clicks away, and the game saves the score to entpack.ini (for an unelevated
32-bit program that lands in %LOCALAPPDATA%\\VirtualStore\\Windows\\entpack.ini).

Usage: python scripts/capture_gameplay.py [--seconds 300]
Frames go to out/captures/: start.png, run_*.png, yeti_*.png, caught_*.png.
"""
import argparse
import ctypes
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "original" / "ski32.exe"
OUT = ROOT / "out" / "captures"

u32, g32, k32 = ctypes.windll.user32, ctypes.windll.gdi32, ctypes.windll.kernel32
H = ctypes.c_void_p
EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, H, wintypes.LPARAM)
u32.FindWindowW.restype = H
u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u32.GetDC.restype = H
u32.GetDC.argtypes = [H]
u32.ReleaseDC.argtypes = [H, H]
u32.PrintWindow.argtypes = [H, H, wintypes.UINT]
u32.GetClientRect.argtypes = [H, ctypes.POINTER(wintypes.RECT)]
u32.PostMessageW.argtypes = [H, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u32.SetWindowPos.argtypes = [H, H, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
u32.ShowWindow.argtypes = [H, ctypes.c_int]
u32.GetWindowThreadProcessId.argtypes = [H, ctypes.POINTER(wintypes.DWORD)]
u32.GetClassNameW.argtypes = [H, wintypes.LPWSTR, ctypes.c_int]
u32.EnumWindows.argtypes = [EnumProc, wintypes.LPARAM]
u32.EnumChildWindows.argtypes = [H, EnumProc, wintypes.LPARAM]
g32.CreateCompatibleDC.restype = H
g32.CreateCompatibleDC.argtypes = [H]
g32.CreateCompatibleBitmap.restype = H
g32.CreateCompatibleBitmap.argtypes = [H, ctypes.c_int, ctypes.c_int]
g32.SelectObject.restype = H
g32.SelectObject.argtypes = [H, H]
g32.DeleteObject.argtypes = [H]
g32.DeleteDC.argtypes = [H]
g32.GetDIBits.argtypes = [H, H, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
k32.ReadProcessMemory.argtypes = [H, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]

WM_ACTIVATE, WM_KEYDOWN, WM_CHAR, WM_CLOSE, BM_CLICK = 0x0006, 0x0100, 0x0102, 0x0010, 0x00F5
VK_DOWN = 0x28
G_PLAYER = 0x40C72C  # pointer to the skier's actor (see names.tsv)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


def grab(hwnd) -> Image.Image:
    """Capture the window's client area even though it is off-screen."""
    r = wintypes.RECT()
    u32.GetClientRect(hwnd, ctypes.byref(r))
    w, h = r.right, r.bottom
    hdc = u32.GetDC(hwnd)
    mdc = g32.CreateCompatibleDC(hdc)
    bmp = g32.CreateCompatibleBitmap(hdc, w, h)
    old = g32.SelectObject(mdc, bmp)
    u32.PrintWindow(hwnd, mdc, 3)  # PW_CLIENTONLY | PW_RENDERFULLCONTENT
    info = BITMAPINFOHEADER(40, w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    g32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(info), 0)
    g32.SelectObject(mdc, old)
    g32.DeleteObject(bmp)
    g32.DeleteDC(mdc)
    u32.ReleaseDC(hwnd, hdc)
    return Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")


def read(process, address: int, size: int):
    buf = ctypes.create_string_buffer(size)
    return buf.raw if k32.ReadProcessMemory(process, address, buf, size, None) else None


def skier(process):
    """(x, y, state) of the skier, or None once the yeti has eaten him."""
    raw = read(process, G_PLAYER, 4)
    ptr = int.from_bytes(raw, "little") if raw else 0
    actor = read(process, ptr, 0x50) if ptr else None
    if not actor:
        return None
    x = int.from_bytes(actor[0x40:0x42], "little", signed=True)
    y = int.from_bytes(actor[0x42:0x44], "little", signed=True)
    return x, y, int.from_bytes(actor[0x1C:0x20], "little")


def click_away_dialogs(pid: int) -> None:
    """Press the only button of any dialog the game opened (the High Scores box)."""
    dialogs = []

    def on_window(h, _):
        owner = wintypes.DWORD()
        u32.GetWindowThreadProcessId(h, ctypes.byref(owner))
        name = ctypes.create_unicode_buffer(64)
        u32.GetClassNameW(h, name, 64)
        if owner.value == pid and name.value == "#32770":
            dialogs.append(h)
        return True

    u32.EnumWindows(EnumProc(on_window), 0)
    for dialog in dialogs:
        def on_child(c, _):
            name = ctypes.create_unicode_buffer(64)
            u32.GetClassNameW(c, name, 64)
            if name.value == "Button":
                u32.PostMessageW(c, BM_CLICK, 0, 0)
            return True
        u32.EnumChildWindows(dialog, EnumProc(on_child), 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seconds", type=int, default=300, help="give up after this long (default 300)")
    args = parser.parse_args()
    if not EXE.exists():
        sys.exit("original/ski32.exe not found: run `python run.py --no-ghidra` first")
    OUT.mkdir(parents=True, exist_ok=True)

    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= 1  # STARTF_USESHOWWINDOW
    startup.wShowWindow = 0  # SW_HIDE: never flashes on screen
    game = subprocess.Popen([str(EXE)], startupinfo=startup, cwd=str(OUT))
    process = H(int(game._handle))

    hwnd = None
    for _ in range(100):
        candidate = u32.FindWindowW("SkiMain", None)
        if candidate:
            owner = wintypes.DWORD()
            u32.GetWindowThreadProcessId(candidate, ctypes.byref(owner))
            if owner.value == game.pid:
                hwnd = candidate
                break
        time.sleep(0.1)
    if not hwnd:
        game.kill()
        sys.exit("SkiFree window not found")

    u32.SetWindowPos(hwnd, None, -20000, 0, 0, 0, 0x0001 | 0x0004 | 0x0010)  # move off-screen, no activation
    u32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
    time.sleep(1.5)
    grab(hwnd).save(OUT / "start.png")

    u32.PostMessageW(hwnd, WM_ACTIVATE, 1, 0)  # the game only runs its timer while "active"
    time.sleep(0.3)
    start, tick, fast, near, caught = time.time(), 0, False, 0, 0
    try:
        while time.time() - start < args.seconds:
            click_away_dialogs(game.pid)
            state = skier(process)
            if state is None:  # the yeti got him
                caught += 1
                grab(hwnd).save(OUT / f"caught_{caught:02d}.png")
                if caught >= 12:
                    break
                time.sleep(0.25)
                continue
            x, y, s = state
            if not fast and y > 1500:
                u32.PostMessageW(hwnd, WM_CHAR, ord("f"), 0)
                fast = True
            if y > 31600:
                near += 1
                grab(hwnd).save(OUT / f"yeti_{near:03d}.png")
            elif tick % 20 == 0:
                grab(hwnd).save(OUT / f"run_{tick:04d}_y{y}.png")
            if tick % 50 == 0:
                print(f"{time.time() - start:6.1f}s  y={y:6d} ({y // 16:4d} m)  state=0x{s:02x}", flush=True)
            u32.PostMessageW(hwnd, WM_KEYDOWN, VK_DOWN, 0)
            tick += 1
            time.sleep(0.2)
    finally:
        u32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        time.sleep(1.5)
        if game.poll() is None:
            game.kill()
    print(f"Frames in {OUT}")


if __name__ == "__main__":
    main()
