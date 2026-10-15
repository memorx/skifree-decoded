"""Reproduce the whole SkiFree analysis with one command.

    python run.py               # everything: download, identify, extract, Ghidra, names
    python run.py --names-only  # re-apply names.tsv after editing it (needs one full run first)
    python run.py --no-ghidra   # only the Python steps (no Ghidra or Java needed)

Requirements: Python 3.9+, `pip install -r requirements.txt`, and for the Ghidra steps
Ghidra (tested with 12.1.2) with Java 21, and the GHIDRA_HOME environment variable
pointing at the Ghidra folder.
"""
import argparse
import hashlib
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXE = ROOT / "original" / "ski32.exe"
OUT = ROOT / "out"
PROJECT = ROOT / "build" / "ghidra"
URL = "https://ski.ihoc.net/ski32.exe"  # the author's own site; the binary is never committed
SHA256 = "3572d3757638bc1ae388c3d007ba59ba1f370911901e2a35d2f1297e8cf0ff35"


def step(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


def get_binary() -> None:
    step("Step 0: get ski32.exe from the author's site and check its hash")
    if not EXE.exists():
        EXE.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {URL}")
        urllib.request.urlretrieve(URL, EXE)
    digest = hashlib.sha256(EXE.read_bytes()).hexdigest()
    if digest != SHA256:
        sys.exit(f"SHA-256 mismatch: got {digest}, expected {SHA256}. Every address in this repo refers to the expected file.")
    print(f"OK {EXE.name} {digest}")


def python_step(title: str, script: str) -> None:
    step(title)
    subprocess.run([sys.executable, str(ROOT / "scripts" / script), str(EXE), str(OUT)], check=True)


def headless() -> Path:
    home = os.environ.get("GHIDRA_HOME")
    if not home:
        sys.exit("Set GHIDRA_HOME to your Ghidra folder (the one that contains support/analyzeHeadless).")
    name = "analyzeHeadless.bat" if os.name == "nt" else "analyzeHeadless"
    tool = Path(home) / "support" / name
    if not tool.exists():
        sys.exit(f"Not found: {tool}")
    return tool


def ghidra(args: list, log: str) -> None:
    PROJECT.mkdir(parents=True, exist_ok=True)
    cmd = [str(headless()), str(PROJECT), "SkiFree", *args,
           "-scriptPath", str(ROOT / "ghidra"), "-log", str(PROJECT / log)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    for line in (result.stdout + result.stderr).splitlines():
        if any(k in line for k in ("ExportDecomp:", "ApplyNames:", "ERROR", "Exception", "Could not", "Failed")):
            print(line.strip())
    if result.returncode != 0:
        sys.exit(f"Ghidra exited with code {result.returncode}; see {PROJECT / log}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--names-only", action="store_true", help="only re-apply names.tsv and re-export the named C")
    parser.add_argument("--no-ghidra", action="store_true", help="skip the Ghidra steps")
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)

    if not args.names_only:
        get_binary()
        python_step("Step 1: identify the executable", "identify.py")
        python_step("Step 1b: extract strings and bitmaps", "extract_resources.py")
        python_step("Step 3 helper: dump the data tables", "dump_tables.py")
        if args.no_ghidra:
            return
        step("Step 2: Ghidra auto-analysis and raw export (takes a few minutes)")
        ghidra(["-import", str(EXE), "-overwrite", "-postScript", "ExportDecomp.java", str(OUT)], "analyze.log")

    step("Step 3: apply names.tsv and export the named C")
    ghidra(["-process", EXE.name, "-noanalysis", "-postScript", "ApplyNames.java", str(ROOT / "names.tsv"), str(OUT)], "names.log")
    print(f"\nDone. Read {OUT / 'decompiled.c'}")


if __name__ == "__main__":
    main()
