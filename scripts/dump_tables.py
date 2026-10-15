"""Step 3 helper: print SkiFree's data tables, the behaviour that lives in data, not code.

The addresses come from reading the decompiled code (see docs/INTERNALS.md).
File offsets are computed by pefile: never compute PE offsets by hand.

Usage: python scripts/dump_tables.py [path/to/ski32.exe] [output_dir]
"""
import struct
import sys
from pathlib import Path

import pefile

ROOT = Path(__file__).resolve().parent.parent
exe = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "original" / "ski32.exe"
out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "out"
out_dir.mkdir(parents=True, exist_ok=True)

pe = pefile.PE(str(exe))
data = exe.read_bytes()
BASE = pe.OPTIONAL_HEADER.ImageBase


def off(va: int) -> int:
    return pe.get_offset_from_rva(va - BASE)


def physics_rows(va: int, count: int, first_state: int):
    rows = []
    for i in range(count):
        raw = data[off(va) + i * 16: off(va) + i * 16 + 16]
        values = struct.unpack("<5h", raw[:10])
        (state,) = struct.unpack("<I", raw[12:16])
        rows.append(f"  state 0x{state:02x}: {values}" if state == first_state + i else f"  row {i}: {values} state={state}")
    return rows


out = []
table = struct.unpack_from("<64H", data, off(0x40A1AC))
out.append("tbl_stateToBitmap @0x40a1ac: animation state -> bitmap number")
for i in range(0, 64, 8):
    out.append("  " + "  ".join(f"0x{i + k:02x}->{table[i + k]:2d}" for k in range(8)))

init = struct.unpack_from("<11I", data, off(0x40A22C))
out.append("\ntbl_typeInitState @0x40a22c: object type -> first animation state")
out.append("  " + "  ".join(f"type {t}->0x{s:02x}" for t, s in enumerate(init)))

out.append("\ntbl_turnLeft / tbl_turnRight @0x40a258: skier state -> state after pressing left / right")
for i in range(22):
    left, right = struct.unpack_from("<II", data, off(0x40A258) + i * 8)
    out.append(f"  0x{i:02x}: left->0x{left:02x}  right->0x{right:02x}")

out.append("\ntbl_playerPhysics @0x40a308: per skier state (field 1 = top speed)")
out += physics_rows(0x40A308, 22, 0)

land = struct.unpack_from("<9I", data, off(0x40A468))
out.append("\ntbl_landState @0x40a468: airborne state -> state on landing (0x11 never appears: the -64 penalty is dead code)")
out.append("  " + "  ".join(f"0x{0x0d + i:02x}->0x{s:02x}" for i, s in enumerate(land)))

out.append("\ntbl_novicePhysics @0x40a490: beginner skier")
out += physics_rows(0x40A490, 5, 0x16)
out.append("\ntbl_boarderPhysics @0x40a4e0: snowboarder")
out += physics_rows(0x40A4E0, 8, 0x1F)

report = "\n".join(out)
(out_dir / "tables.txt").write_text(report, encoding="utf-8")
print(report)
