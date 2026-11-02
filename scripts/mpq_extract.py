#!/usr/bin/env python3
"""mpq_extract.py <archive.mpq> <outdir> [substring-filter ...]
Extract files from an MPQ via StormLib (ctypes). Lists with no filter-> prints names only."""
import ctypes, os, sys

lib = ctypes.CDLL("/opt/homebrew/lib/libstorm.dylib")
MAX_PATH = 1024

class FindData(ctypes.Structure):
    _fields_ = [("cFileName", ctypes.c_char * MAX_PATH),
                ("szPlainName", ctypes.c_char_p),
                ("dwHashIndex", ctypes.c_uint32), ("dwBlockIndex", ctypes.c_uint32),
                ("dwFileSize", ctypes.c_uint32), ("dwFileFlags", ctypes.c_uint32),
                ("dwCompSize", ctypes.c_uint32),
                ("dwFileTimeLo", ctypes.c_uint32), ("dwFileTimeHi", ctypes.c_uint32),
                ("lcLocale", ctypes.c_uint32)]

lib.SFileOpenArchive.argtypes = [ctypes.c_char_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
lib.SFileFindFirstFile.restype = ctypes.c_void_p
lib.SFileFindFirstFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(FindData), ctypes.c_char_p]
lib.SFileFindNextFile.argtypes = [ctypes.c_void_p, ctypes.POINTER(FindData)]
lib.SFileOpenFileEx.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
lib.SFileReadFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
lib.SFileGetFileSize.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
lib.SFileGetFileSize.restype = ctypes.c_uint32


def main():
    path, out = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else None)
    filt = [f.lower() for f in sys.argv[3:]]
    h = ctypes.c_void_p()
    if not lib.SFileOpenArchive(path.encode(), 0, 0x100, ctypes.byref(h)):  # READ_ONLY
        sys.exit(f"cannot open {path}")
    fd = FindData()
    fh = lib.SFileFindFirstFile(h, b"*", ctypes.byref(fd), None)
    n = 0
    ok = fh is not None
    while ok:
        name = fd.cFileName.decode("latin1")
        if not filt or any(f in name.lower() for f in filt):
            if out is None or out == "-":
                print(name, fd.dwFileSize)
            else:
                f = ctypes.c_void_p()
                if lib.SFileOpenFileEx(h, name.encode("latin1"), 0, ctypes.byref(f)):
                    size = lib.SFileGetFileSize(f, None)
                    buf = ctypes.create_string_buffer(size)
                    got = ctypes.c_uint32()
                    lib.SFileReadFile(f, buf, size, ctypes.byref(got), None)
                    dest = os.path.join(out, name.replace("\\", "/"))
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    open(dest, "wb").write(buf.raw[:got.value])
                    lib.SFileCloseFile(f)
                    n += 1
        ok = lib.SFileFindNextFile(fh, ctypes.byref(fd))
    print(f"extracted {n}", file=sys.stderr)

main()
