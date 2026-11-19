import ctypes
import sys
from pathlib import Path


def process_memory():
    try:
        if sys.platform == "win32":
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("faults", wintypes.DWORD),
                    ("peak", ctypes.c_size_t),
                    ("rss", ctypes.c_size_t),
                    ("peak_paged", ctypes.c_size_t),
                    ("paged", ctypes.c_size_t),
                    ("peak_nonpaged", ctypes.c_size_t),
                    ("nonpaged", ctypes.c_size_t),
                    ("pagefile", ctypes.c_size_t),
                    ("peak_pagefile", ctypes.c_size_t),
                ]

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.GetCurrentProcess.restype = wintypes.HANDLE
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            if not psapi.GetProcessMemoryInfo(
                kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb
            ):
                return None, None
            return counters.rss, counters.peak
        if sys.platform.startswith("linux"):
            lines = Path("/proc/self/status").read_text().splitlines()
            values = {
                line.split(":")[0]: int(line.split()[1]) * 1024
                for line in lines
                if line.startswith(("VmRSS:", "VmHWM:"))
            }
            return values.get("VmRSS"), values.get("VmHWM")
    except OSError, ValueError, AttributeError:
        pass
    return None, None
