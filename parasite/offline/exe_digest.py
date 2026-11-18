"""Print a digest of a .NET exe: PE header, sections and each embedded resource.

Usage:
    python parasite/offline/exe_digest.py ParasiteOffline.exe [other.exe]

With two files it prints only what differs. builds-check.yml runs it when the CI-built
ParasiteOffline.exe differs from the committed one, so the log shows where they differ
(header, IL/metadata, or an embedded resource such as a Costura-compressed assembly).
"""

import hashlib
import struct
import sys


def short(data):
    return hashlib.sha256(data).hexdigest()[:16]


def digest(path):
    data = open(path, "rb").read()
    out = {"file": f"{len(data)} bytes sha256 {hashlib.sha256(data).hexdigest()}"}
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    machine, nsections, timestamp = struct.unpack_from("<HHI", data, pe + 4)
    opt_size, characteristics = struct.unpack_from("<HH", data, pe + 20)
    opt = pe + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    out["header"] = (f"machine {machine:#x} timestamp {timestamp:#010x} "
                     f"characteristics {characteristics:#x} optional-magic {magic:#x}")
    checksum = struct.unpack_from("<I", data, opt + 64)[0]
    out["checksum"] = f"{checksum:#x}"
    dirs = opt + (96 if magic == 0x10B else 112)
    sections = []
    for i in range(nsections):
        off = opt + opt_size + i * 40
        name = data[off:off + 8].rstrip(b"\0").decode("ascii", "replace")
        vsize, va, rsize, raw = struct.unpack_from("<IIII", data, off + 8)
        sections.append((va, vsize, raw))
        out[f"section {name}"] = f"va {va:#x} size {rsize} sha {short(data[raw:raw + rsize])}"

    def rva(r):
        for va, vsize, raw in sections:
            if va <= r < va + max(vsize, 1):
                return raw + r - va
        raise ValueError(f"rva {r:#x} outside sections")

    for idx, label in ((2, "win32 resources"), (6, "debug directory")):
        r, size = struct.unpack_from("<II", data, dirs + idx * 8)
        if r:
            out[label] = f"size {size} sha {short(data[rva(r):rva(r) + size])}"
    cli_rva = struct.unpack_from("<I", data, dirs + 14 * 8)[0]
    if cli_rva:
        cli = rva(cli_rva)
        md_rva, md_size, flags = struct.unpack_from("<III", data, cli + 8)
        out["clr flags"] = f"{flags:#x}"
        out["metadata"] = f"size {md_size} sha {short(data[rva(md_rva):rva(md_rva) + md_size])}"
        res_rva, res_size = struct.unpack_from("<II", data, cli + 24)
        if res_rva:
            base, pos, n = rva(res_rva), 0, 0
            while pos + 4 <= res_size:
                length = struct.unpack_from("<I", data, base + pos)[0]
                blob = data[base + pos + 4:base + pos + 4 + length]
                out[f"resource #{n} at {pos}"] = f"length {length} sha {short(blob)} head {blob[:8].hex()}"
                pos += 4 + length
                n += 1
    return out


def main():
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    first = digest(sys.argv[1])
    if len(sys.argv) == 2:
        for key, value in first.items():
            print(f"{key}: {value}")
        return
    second = digest(sys.argv[2])
    print(f"A = {sys.argv[1]}\nB = {sys.argv[2]}")
    for key in list(first) + [k for k in second if k not in first]:
        a, b = first.get(key), second.get(key)
        if a != b:
            print(f"{key}:\n  A {a}\n  B {b}")


if __name__ == "__main__":
    main()
