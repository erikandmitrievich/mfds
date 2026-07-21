# The pipeline, executable.
#
# STRUCTURE.org says what the repo is. validate_structure.py enforces it.
# This file says what you *do* to it. Together they are the three specs;
# when any two disagree, one of them is wrong.
#
#   just                 list recipes
#   just check           what pre-commit runs
#   just transcribe analysis
#
# Course arguments are slugs, not paths: `analysis`, not
# `01_coursework/02_semester/01_analysis` -- though a path is accepted too.
# Slug resolution is by suffix match and fails loudly on ambiguity.
#
# Portability: macOS /bin/bash is 3.2. No mapfile, no associative arrays,
# no ${x^^}. If a recipe needs bash 4, it is wrong.

set shell := ["bash", "-euo", "pipefail", "-c"]

root    := justfile_directory()
scripts := root / "00_global/scripts"
py      := "python3"

_default:
    @just --list --unsorted

# ---------------------------------------------------------------------------
# structure
# ---------------------------------------------------------------------------

# validate the tree against STRUCTURE.org (baseline honoured)
validate:
    @{{py}} {{scripts}}/validate_structure.py

# validate ignoring the baseline -- the real state
validate-strict:
    @{{py}} {{scripts}}/validate_structure.py --strict

# counts per rule, no paths
validate-summary:
    @{{py}} {{scripts}}/validate_structure.py --summary

# also check provenance headers on 01_extracted/ products
validate-content:
    @{{py}} {{scripts}}/validate_structure.py --content

# accept the current findings; the baseline may only ever shrink
baseline:
    @{{py}} {{scripts}}/validate_structure.py --write-baseline

# how far from a clean tree: strict findings, counted per rule
debt:
    @{{py}} {{scripts}}/validate_structure.py --strict --summary || true

# what the pre-commit hook runs
check: validate

# point git at the tracked hooks (run once per clone)
hooks:
    @cd {{root}} && git config core.hooksPath 00_global/scripts/hooks
    @echo "core.hooksPath -> 00_global/scripts/hooks"

# ---------------------------------------------------------------------------
# course resolution
# ---------------------------------------------------------------------------

# print the directory for a course slug or path
[private]
course-dir COURSE:
    @cd {{root}}; \
    if [ -d "{{COURSE}}" ]; then \
        cd "{{COURSE}}" && pwd; \
        exit 0; \
    fi; \
    matches=$(find 01_coursework -mindepth 2 -maxdepth 2 -type d -name '*_{{COURSE}}' | sort); \
    count=$(printf '%s\n' "$matches" | grep -c . || true); \
    if [ "$count" -eq 0 ]; then \
        echo "no course matching '*_{{COURSE}}' (try: just courses)" >&2; \
        exit 1; \
    fi; \
    if [ "$count" -gt 1 ]; then \
        echo "ambiguous course '{{COURSE}}':" >&2; \
        printf '  %s\n' "$matches" >&2; \
        exit 1; \
    fi; \
    echo "{{root}}/$matches"

# list every course slug
courses:
    @cd {{root}} && find 01_coursework -mindepth 2 -maxdepth 2 -type d \
        | sort | sed 's|.*/||'

# resolve a slug and print the path (debugging)
where COURSE:
    @just course-dir {{COURSE}}

# ---------------------------------------------------------------------------
# transcription
# ---------------------------------------------------------------------------
#
# Per-course vocabulary lives here rather than in a file, because
# 00_global/scripts/ admits only *.py under SCRIPTS/T001 -- a vocab/ directory
# would need a new schema node for four lines of text. Revisit if it grows.
#
# Prime with terms Whisper actually mangles, not with terms that merely appear.

[private]
vocab COURSE:
    @case "{{COURSE}}" in \
      *analysis) echo "Fréchet derivative, Jacobian, Banach space, Banach fixed point theorem, Taylor polynomial, Newton's method, gradient descent, convex function, Hessian, Lagrange multipliers, tangent space, submanifold, implicit function theorem, local extremum, KKT, positive definite, eigenvector, Julia." ;; \
      *linear_algebra) echo "eigenvalue, eigenvector, characteristic polynomial, Jordan normal form, orthogonal complement, Gram-Schmidt, singular value decomposition, bilinear form, quadratic form, kernel, image, rank-nullity, diagonalisable, unitary, Hermitian, determinant, trace." ;; \
      *algorithms) echo "loop invariant, insertion sort, merge sort, quicksort, asymptotic notation, big O, Theta, Omega, recurrence relation, master theorem, divide and conquer, binary search tree, red-black tree, hash table, dynamic programming, amortised analysis, CLRS." ;; \
      *) echo "" ;; \
    esac

# transcribe audio in a course's exam resources (add EXAM for a split stack: 01_lecture_exam)
transcribe COURSE EXAM="" *ARGS="":
    @dir=$(just course-dir {{COURSE}}); \
    res="$dir/03_exams{{ if EXAM != "" { "/" + EXAM } else { "" } }}/00_resources"; \
    test -d "$res" || { echo "no such resources dir: $res" >&2; exit 1; }; \
    {{py}} {{scripts}}/transcribe.py "$res" --prompt "$(just vocab {{COURSE}})" {{ARGS}}

# show what transcribe would do, without doing it
transcribe-plan COURSE EXAM="":
    @just transcribe {{COURSE}} "{{EXAM}}" --dry-run

# ---------------------------------------------------------------------------
# problem sets
# ---------------------------------------------------------------------------

# concatenate every ps_NN.org statement in a course into one org block (stdout)
ps-total COURSE:
    @dir=$(just course-dir {{COURSE}}); \
    {{py}} {{scripts}}/ps_total.py --ps-dir "$dir/02_problems"

# same, written to a file
ps-total-to COURSE OUT:
    @dir=$(just course-dir {{COURSE}}); \
    {{py}} {{scripts}}/ps_total.py --ps-dir "$dir/02_problems" --out "{{OUT}}"

# ---------------------------------------------------------------------------
# exam preparation
# ---------------------------------------------------------------------------

# build day_NN.org files from a plan.org
days COURSE EXAM="" *ARGS="":
    @dir=$(just course-dir {{COURSE}}); \
    stack="$dir/03_exams{{ if EXAM != "" { "/" + EXAM } else { "" } }}"; \
    {{py}} {{scripts}}/build_day_files_exam_preparation.py \
        --plan "$stack/02_plan/plan.org" \
        --out-dir "$stack/03_preparation" \
        --ps-dir "$dir/02_problems" {{ARGS}}

# preview the day files without writing
days-plan COURSE EXAM="":
    @just days {{COURSE}} "{{EXAM}}" --dry-run

# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------

# repository analytics
stats:
    @cd {{root}} && {{py}} {{scripts}}/repository_stats.py

# regenerate the tree snapshot in 00_global/_archive/
tree:
    @cd {{root}} && \
    { echo "#+title: Tree"; echo; echo "#+begin_example"; \
      git ls-files | tree --fromfile -a --noreport; \
      echo "#+end_example"; } > 00_global/_archive/tree.org
    @echo "wrote 00_global/_archive/tree.org"
