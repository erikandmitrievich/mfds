#!/usr/bin/env python3

import json
import re
import sys
from pathlib import Path


def make_markdown_cell(source: str) -> dict:
    lines = [line + "\n" for line in source.split("\n")]
    if lines:
        lines[-1] = lines[-1].rstrip("\n")
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": lines,
    }


def make_code_cell(source: str) -> dict:
    lines = [line + "\n" for line in source.split("\n")]
    if lines:
        lines[-1] = lines[-1].rstrip("\n")
    return {
        "cell_type": "code",
        "metadata": {},
        "source": lines,
        "execution_count": None,
        "outputs": [],
    }


def parse_org(text: str) -> list[dict]:
    """Parse org text into a list of cells."""
    cells = []
    lines = text.split("\n")
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]

        # ── Top-level heading: * Problem N ──
        if re.match(r"^\*\s+", line) and not re.match(r"^\*\*\s+", line):
            # Strip org tags like :DONE:
            heading = re.sub(r"\s+:\w+:\s*$", "", line)
            heading = heading.lstrip("* ").strip()
            cells.append(make_markdown_cell(f"# {heading}"))
            i += 1
            continue

        # ── Second-level heading: ** Task or ** Solution ──
        if re.match(r"^\*\*\s+Task", line):
            i += 1
            # Collect task content (look for quote block or raw text)
            task_lines = []
            in_quote = False
            while i < n and not re.match(r"^\*", lines[i]):
                l = lines[i]
                if l.strip().lower() == "#+begin_quote":
                    in_quote = True
                    i += 1
                    continue
                if l.strip().lower() == "#+end_quote":
                    in_quote = False
                    i += 1
                    continue
                task_lines.append(l)
                i += 1
            # Clean up trailing blank lines
            while task_lines and task_lines[-1].strip() == "":
                task_lines.pop()
            if task_lines:
                cells.append(make_markdown_cell("## Task\n\n" + "\n".join(task_lines)))
            continue

        if re.match(r"^\*\*\s+Solution", line):
            i += 1
            # Collect solution content, splitting prose and code blocks
            prose_lines = []
            while i < n and not re.match(r"^\*\s+", lines[i]):
                l = lines[i]

                # Code block
                src_match = re.match(
                    r"^\s*#\+begin_src\s+(\w+)(.*)$", l, re.IGNORECASE
                )
                if src_match:
                    # Flush any accumulated prose as a markdown cell
                    if any(pl.strip() for pl in prose_lines):
                        while prose_lines and prose_lines[-1].strip() == "":
                            prose_lines.pop()
                        while prose_lines and prose_lines[0].strip() == "":
                            prose_lines.pop(0)
                        cells.append(
                            make_markdown_cell(
                                "## Solution\n\n" + "\n".join(prose_lines)
                            )
                        )
                        prose_lines = []
                    elif prose_lines:
                        prose_lines = []

                    # Collect code
                    i += 1
                    code_lines = []
                    while i < n and not re.match(
                        r"^\s*#\+end_src", lines[i], re.IGNORECASE
                    ):
                        code_lines.append(lines[i])
                        i += 1
                    if i < n:
                        i += 1  # skip #+end_src

                    # Strip trailing blank lines from code
                    while code_lines and code_lines[-1].strip() == "":
                        code_lines.pop()

                    cells.append(make_code_cell("\n".join(code_lines)))
                    continue

                # Results block — skip
                if re.match(r"^\s*#\+RESULTS:", l, re.IGNORECASE):
                    i += 1
                    # Skip result content (lines starting with : or blank,
                    # or until next meaningful content)
                    while i < n:
                        rl = lines[i]
                        if rl.startswith(": ") or rl.strip() == "":
                            i += 1
                            continue
                        break
                    continue

                # Sub-headings within solution (*** (a), etc.)
                sub_match = re.match(r"^\*\*\*\s+(.*)", l)
                if sub_match:
                    # Flush prose
                    if any(pl.strip() for pl in prose_lines):
                        while prose_lines and prose_lines[-1].strip() == "":
                            prose_lines.pop()
                        while prose_lines and prose_lines[0].strip() == "":
                            prose_lines.pop(0)
                        cells.append(
                            make_markdown_cell(
                                "## Solution\n\n" + "\n".join(prose_lines)
                            )
                        )
                        prose_lines = []
                    cells.append(
                        make_markdown_cell(f"### {sub_match.group(1).strip()}")
                    )
                    i += 1
                    continue

                prose_lines.append(l)
                i += 1

            # Flush remaining prose
            if any(pl.strip() for pl in prose_lines):
                while prose_lines and prose_lines[-1].strip() == "":
                    prose_lines.pop()
                while prose_lines and prose_lines[0].strip() == "":
                    prose_lines.pop(0)
                cells.append(
                    make_markdown_cell("## Solution\n\n" + "\n".join(prose_lines))
                )
            continue

        # Skip any other line
        i += 1

    return cells


def build_notebook(cells: list[dict], kernel_name: str = "julia") -> dict:
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {
                "display_name": "Julia",
                "language": "julia",
                "name": kernel_name,
            },
            "language_info": {
                "name": "julia",
            },
        },
        "cells": cells,
    }


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} input.org [output.ipynb]")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    if len(sys.argv) >= 3:
        output_path = Path(sys.argv[2])
    else:
        output_path = input_path.with_suffix(".ipynb")

    text = input_path.read_text(encoding="utf-8")
    cells = parse_org(text)
    notebook = build_notebook(cells)

    output_path.write_text(json.dumps(notebook, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(cells)} cells to {output_path}")


if __name__:
    main()
