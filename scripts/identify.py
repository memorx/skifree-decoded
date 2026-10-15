"""Step 1: identify a Windows executable before disassembling it.

Prints the PE headers, sections with entropy, imports, resources and the Rich
header, and writes every printable string (ASCII and UTF-16) with its file offset.

Usage: python scripts/identify.py [path/to/file.exe] [output_dir]
"""
import datetime
import hashlib
import math
import re
import sys
from collections import Counter
from pathlib import Path

import pefile

ROOT = Path(__file__).resolve().parent.parent
exe = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "original" / "ski32.exe"
out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "out"
out_dir.mkdir(parents=True, exist_ok=True)


def entropy(data: bytes) -> float:
    """Shannon entropy in bits per byte: ~5-6.5 for code, >7 means packed or encrypted."""
    if not data:
        return 0.0
    counts, n = Counter(data), len(data)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


data = exe.read_bytes()
pe = pefile.PE(str(exe))
fh, oh = pe.FILE_HEADER, pe.OPTIONAL_HEADER
lines = [
    f"File:        {exe.name}",
    f"Size:        {len(data)} bytes",
    f"SHA-256:     {hashlib.sha256(data).hexdigest()}",
    f"Machine:     0x{fh.Machine:x} ({pefile.MACHINE_TYPE.get(fh.Machine)})",
    f"Linked:      {datetime.datetime.fromtimestamp(fh.TimeDateStamp, datetime.timezone.utc):%Y-%m-%d %H:%M:%S} UTC",
    f"Linker:      {oh.MajorLinkerVersion}.{oh.MinorLinkerVersion}   (6.0 = Visual C++ 6)",
    f"Subsystem:   {pefile.SUBSYSTEM_TYPE.get(oh.Subsystem)}, minimum OS {oh.MajorOperatingSystemVersion}.{oh.MinorOperatingSystemVersion}",
    f"Image base:  0x{oh.ImageBase:x}",
    f"Entry point: 0x{oh.ImageBase + oh.AddressOfEntryPoint:x}",
    "",
    "Sections (entropy above 7 = compressed or encrypted; normal code is 5 to 6.5):",
]
for s in pe.sections:
    name = s.Name.decode(errors="replace").strip("\x00")
    lines.append(
        f"  {name:8s} VA=0x{oh.ImageBase + s.VirtualAddress:08x} "
        f"virtual={s.Misc_VirtualSize:6d} raw={s.SizeOfRawData:6d} entropy={entropy(s.get_data()):.2f}"
    )

lines.append("\nImports (what it asks Windows for):")
for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
    names = [i.name.decode() if i.name else f"ord{i.ordinal}" for i in entry.imports]
    lines.append(f"  {entry.dll.decode()} ({len(names)}): {', '.join(names)}")

lines.append("\nResources:")
resource_types = pe.DIRECTORY_ENTRY_RESOURCE.entries if hasattr(pe, "DIRECTORY_ENTRY_RESOURCE") else []
for t in resource_types:
    tname = str(t.name) if t.name else pefile.RESOURCE_TYPE.get(t.id, str(t.id))
    count = sum(len(lang.directory.entries) for lang in t.directory.entries)
    lines.append(f"  {tname}: {count}")

rich = pe.parse_rich_header()
if rich:
    lines.append("\nRich header (which Microsoft tools built the objects; prodid 10 = VC6 C compiler, 11 = VC6 C++, 14 = MASM 6.13):")
    v = rich["values"]
    for i in range(0, len(v), 2):
        lines.append(f"  prodid={v[i] >> 16:3d} build={v[i] & 0xffff:5d} count={v[i + 1]}")
else:
    lines.append("\nNo Rich header.")

report = "\n".join(lines)
(out_dir / "identify.txt").write_text(report, encoding="utf-8")
print(report)

# Strings: runs of 5+ printable characters, ASCII and UTF-16LE, with their file offset.
found = [(m.start(), m.group().decode()) for m in re.finditer(rb"[\x20-\x7e]{5,}", data)]
found += [(m.start(), "U16: " + m.group().decode("utf-16le")) for m in re.finditer(rb"(?:[\x20-\x7e]\x00){5,}", data)]
found.sort()
with open(out_dir / "strings.txt", "w", encoding="utf-8") as f:
    for offset, text in found:
        f.write(f"{offset:06x}  {text}\n")
print(f"\n{len(found)} strings written to {out_dir / 'strings.txt'}")
