"""Rebuild the B/MAX_T64/SCORE_SHIFT3 TD source project from a pinned DDR baseline.

This script only assembles and checks files. It does not invoke TD or program hardware.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path


HERE = Path(__file__).resolve().parent
DEFAULT_TD = Path(r"C:\Anlogic\TD_Release_2026.1_SP2.200.067")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def verify(path: Path, expected: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Missing required file: {path}")
    actual = sha256(path)
    if actual != expected.upper():
        raise ValueError(f"SHA256 mismatch: {path}: {actual} != {expected}")


def apply_unified(base: Path, patch: Path) -> bytes:
    """Apply a pinned, ordinary unified diff and normalize to TD's CRLF UTF-8."""
    old = base.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    lines = patch.read_text(encoding="utf-8").splitlines(keepends=True)
    if len(lines) < 3 or not lines[0].startswith("--- ") or not lines[1].startswith("+++ "):
        raise ValueError(f"Invalid patch header: {patch}")
    result: list[str] = []
    cursor = 0
    i = 2
    while i < len(lines):
        header = re.fullmatch(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@.*\n", lines[i])
        if header is None:
            raise ValueError(f"Invalid patch hunk: {patch}:{i + 1}")
        start = int(header.group(1)) - 1
        old_count = int(header.group(2) or 1)
        new_count = int(header.group(4) or 1)
        if start < cursor:
            raise ValueError(f"Overlapping patch hunk: {patch}:{i + 1}")
        result.extend(old[cursor:start])
        cursor = start
        i += 1
        removed = added = 0
        while i < len(lines) and not lines[i].startswith("@@ "):
            marker, content = lines[i][:1], lines[i][1:]
            if marker in (" ", "-"):
                if cursor >= len(old) or old[cursor] != content:
                    raise ValueError(f"Patch context mismatch: {patch}:{i + 1}")
                cursor += 1
                removed += 1
            if marker in (" ", "+"):
                result.append(content)
                added += 1
            if marker not in (" ", "-", "+"):
                raise ValueError(f"Unexpected patch line: {patch}:{i + 1}")
            i += 1
        if removed != old_count or added != new_count:
            raise ValueError(f"Patch hunk length mismatch: {patch}:{i + 1}")
    result.extend(old[cursor:])
    return "".join(result).replace("\n", "\r\n").encode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True,
                        help="Unmodified fpga_ddr_diag_20261014 project with generated vendor IP")
    parser.add_argument("--out", type=Path, help="New directory for the assembled TD project")
    parser.add_argument("--td-root", type=Path, default=DEFAULT_TD)
    parser.add_argument("--check-only", action="store_true", help="Verify package and base without writing")
    args = parser.parse_args()
    if args.check_only == bool(args.out):
        parser.error("Choose exactly one of --check-only or --out")

    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    for rel, digest in manifest["release_file_sha256"].items():
        verify(HERE / rel, digest)
    base = args.base.resolve(strict=True)
    for rel, digest in manifest["baseline_tree_sha256"].items():
        verify(base / rel, digest)
    if args.check_only:
        print(f"PASS: {len(manifest['release_file_sha256'])} package files, "
              f"{len(manifest['baseline_tree_sha256'])} baseline files")
        return

    out = args.out.resolve()
    if out.exists():
        raise FileExistsError(f"Output directory must be new: {out}")
    if out == base or out.is_relative_to(base) or base.is_relative_to(out):
        raise ValueError("Output and base must be separate trees")
    for dirname in ("uisrc", "al_ip"):
        shutil.copytree(base / dirname, out / dirname)

    for rel in manifest["owned_rtl"]:
        shutil.copyfile(HERE / "rtl" / Path(rel).name, out / rel)
    for rel, patch_name in manifest["vendor_integration_patches"].items():
        (out / rel).write_bytes(apply_unified(base / rel, HERE / "patches" / patch_name))
    for rel in manifest["config_files_sha256"]:
        shutil.copyfile(HERE / "configs" / rel, out / rel)

    root_str = out.as_posix().encode("utf-8")
    td_str = args.td_root.resolve().as_posix().encode("utf-8")
    for template in sorted((HERE / "td").rglob("*.in")):
        rel = template.relative_to(HERE / "td").as_posix()[:-3]
        content = template.read_bytes().replace(b"@BUILD_ROOT@", root_str).replace(b"@TD_ROOT@", td_str)
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)

    for rel, digest in manifest["active_td_inputs_sha256"].items():
        verify(out / rel, digest)
    for project in ("attention_ddr.al", "attention_ddr.prj", "build/syn_1/attention_ddr.prj"):
        refs = re.findall(r'<File Path="([^"]+)"', (out / project).read_text(encoding="utf-8"))
        normalized = [p[6:] if p.startswith("../../") else p for p in refs]
        if set(normalized) != set(manifest["active_td_inputs_sha256"]) or len(refs) != 154:
            raise ValueError(f"TD project file list differs from pinned manifest: {project}")
    print(f"PASS: assembled {len(refs)} byte-identical TD inputs in {out}")
    print("Next: use TD in this separate project copy to run synth_functional.tcl, then physical_functional.tcl")


if __name__ == "__main__":
    main()
