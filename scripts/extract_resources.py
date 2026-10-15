"""Step 1b: pull the string table and every bitmap out of the executable.

Writes out/string_table.txt (each string with its numeric ID), out/bitmaps.txt
(ID, size, colour depth), out/sprites/ski32_N.bmp and a numbered contact sheet,
out/sprites/contact_sheet.png (needs Pillow).

Usage: python scripts/extract_resources.py [path/to/file.exe] [output_dir]
"""
import struct
import sys
from pathlib import Path

import pefile

ROOT = Path(__file__).resolve().parent.parent
exe = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "original" / "ski32.exe"
out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "out"
sprite_dir = out_dir / "sprites"
sprite_dir.mkdir(parents=True, exist_ok=True)

pe = pefile.PE(str(exe))


def resource_bytes(entry) -> bytes:
    return pe.get_data(entry.data.struct.OffsetToData, entry.data.struct.Size)


strings, bitmaps = [], []
for rtype in pe.DIRECTORY_ENTRY_RESOURCE.entries:
    type_name = pefile.RESOURCE_TYPE.get(rtype.id, str(rtype.name))
    for res in rtype.directory.entries:
        for lang in res.directory.entries:
            raw = resource_bytes(lang)
            if type_name == "RT_STRING":
                # A string block holds 16 strings: [length:u16][UTF-16 chars]. ID = (block - 1) * 16 + index.
                pos = 0
                for i in range(16):
                    (length,) = struct.unpack_from("<H", raw, pos)
                    pos += 2
                    text = raw[pos:pos + 2 * length].decode("utf-16le")
                    pos += 2 * length
                    if length:
                        strings.append(((res.id - 1) * 16 + i, text))
            elif type_name == "RT_BITMAP":
                bitmaps.append((res.id, raw))

with open(out_dir / "string_table.txt", "w", encoding="utf-8") as f:
    for sid, text in sorted(strings):
        f.write(f"{sid:4d}  {text!r}\n")
print(f"{len(strings)} strings with IDs -> {out_dir / 'string_table.txt'}")

# An RT_BITMAP is a BMP file without its 14-byte file header. Put the header back.
info = []
for bid, raw in sorted(bitmaps):
    header_size, width, height, _planes, bpp = struct.unpack_from("<IiiHH", raw, 0)
    colors = struct.unpack_from("<I", raw, 32)[0] or (1 << bpp if bpp <= 8 else 0)
    pixel_offset = 14 + header_size + colors * 4
    bmp = b"BM" + struct.pack("<IHHI", 14 + len(raw), 0, 0, pixel_offset) + raw
    (sprite_dir / f"ski32_{bid}.bmp").write_bytes(bmp)
    info.append((bid, width, abs(height), bpp))

with open(out_dir / "bitmaps.txt", "w", encoding="utf-8") as f:
    f.write(" id  width  height  bpp\n")
    for bid, w, h, bpp in info:
        f.write(f"{bid:3d}  {w:5d}  {h:6d}  {bpp:3d}\n")
print(f"{len(info)} bitmaps -> {sprite_dir}")

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("Pillow not installed: skipping the contact sheet (pip install pillow)")
    sys.exit(0)

images = [(bid, Image.open(sprite_dir / f"ski32_{bid}.bmp").convert("RGB")) for bid, *_ in info]
cell = max(max(img.size) for _, img in images) + 4
cols = 10
rows = (len(images) + cols - 1) // cols
sheet = Image.new("RGB", (cols * (cell + 24), rows * (cell + 14)), "white")
draw = ImageDraw.Draw(sheet)
for k, (bid, img) in enumerate(images):
    x, y = (k % cols) * (cell + 24), (k // cols) * (cell + 14)
    sheet.paste(img, (x + 2, y + 12))
    draw.text((x + 2, y), str(bid), fill="red")
sheet.save(sprite_dir / "contact_sheet.png")
print(f"Contact sheet -> {sprite_dir / 'contact_sheet.png'}")
