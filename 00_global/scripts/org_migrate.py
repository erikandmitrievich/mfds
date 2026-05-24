#!/usr/bin/env python3
"""Migrate old-format Org lecture notes to the CUSTOM_ID / LECTURE_REF format.

Usage:
    python3 org_migrate.py OLD.org map.txt OUT.org

map.txt -- pipe-delimited, one row per item, produced by the migration prompt:
    <number> | <Kind> | <custom_id> | <name>
Blank lines, code fences, stray header rows and WARN: lines are ignored.

Guarantee: only item headings, inserted property drawers, the #+columns: line,
and `/Kind N/` cross-references are modified. Every other byte of the input is
copied verbatim -- math, proofs and prose are never touched. The LLM produces
the map; this script, not the LLM, rewrites the file.

The cross-reference pass assumes references are written `/Kind N.N.N/`
(Org italic markup), matching the existing note style. Adjust REF if not.
"""

import re
import sys

KINDS = "Theorem|Lemma|Definition|Proposition|Corollary"
HEAD = re.compile(rf"^\* ({KINDS})\s+([0-9][0-9.]*[0-9]|[0-9]):\s+(.+?)\s*$")
REF = re.compile(rf"/({KINDS})\s+([0-9][0-9.]*[0-9]|[0-9])/")
COLUMNS = "#+columns: %45ITEM(Item) %14LECTURE_REF(Lecture) %34CUSTOM_ID(ID)\n"


def norm(num):
    """6.1.01 -> 6.1.1 ; idempotent on already-normalised numbers."""
    return ".".join(str(int(p)) for p in num.split("."))


def load_map(path):
    table = {}  # normalised number -> (custom_id, kind, name)
    for raw in open(path, encoding="utf-8"):
        line = raw.strip()
        if not line or line[0] in "#`" or line.startswith("WARN"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 4:
            continue
        num, kind, cid, name = parts
        if num.lower() in ("number", "num"):  # stray header row
            continue
        table[norm(num)] = (cid, kind, name)
    return table


def migrate(text, table):
    warnings = []
    out, migrated = [], 0

    for line in text.splitlines(keepends=True):
        m = HEAD.match(line.rstrip("\n"))
        if not m:
            out.append(line)
            continue
        kind, num, name = m.groups()
        key = norm(num)
        if key not in table:
            warnings.append(f"heading not in map: {kind} {num} -- left unchanged")
            out.append(line)
            continue
        cid, map_kind, _ = table[key]
        if map_kind != kind:
            warnings.append(f"kind mismatch at {num}: file={kind} map={map_kind}")
        out += [
            f"* {kind}: {name}\n",
            ":PROPERTIES:\n",
            f":CUSTOM_ID: {cid}\n",
            f":LECTURE_REF: {key}\n",
            ":END:\n",
        ]
        migrated += 1

    text = "".join(out)

    ref_hits = [0]

    def repl(mo):
        kind, num = mo.groups()
        hit = table.get(norm(num))
        if not hit:
            warnings.append(f"cross-ref not resolvable: /{kind} {num}/ -- left as text")
            return mo.group(0)
        ref_hits[0] += 1
        return f"[[#{hit[0]}][{kind} {norm(num)}]]"

    text = REF.sub(repl, text)

    if "#+columns:" not in text.lower():
        lines = text.splitlines(keepends=True)
        idx = next((i for i, l in enumerate(lines)
                    if l.lower().startswith("#+options:")), None)
        if idx is None:
            idx = next((i for i, l in enumerate(lines)
                        if l.startswith("* ")), 0) - 1
        lines.insert(idx + 1, COLUMNS)
        text = "".join(lines)

    return text, migrated, ref_hits[0], warnings


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    old, mapfile, out = sys.argv[1:]
    table = load_map(mapfile)
    if not table:
        sys.exit("map is empty -- check the file you pasted the LLM output into")
    new, migrated, refs, warnings = migrate(
        open(old, encoding="utf-8").read(), table)
    open(out, "w", encoding="utf-8").write(new)

    print(f"items in map      : {len(table)}")
    print(f"headings migrated : {migrated}")
    print(f"cross-refs linked : {refs}")
    if warnings:
        print(f"\n{len(warnings)} WARNING(S):")
        for w in warnings:
            print(f"  - {w}")
        sys.exit(1)
    print("no warnings")


if __name__ == "__main__":
    main()
