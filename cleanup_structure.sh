#!/usr/bin/env sh

#!/bin/bash

# ==============================================================================
# CONFIGURATION
# ==============================================================================
DRY_RUN=false  # Set to false to apply changes

echo "Starting cleanup process..."
if [ "$DRY_RUN" = true ]; then
    echo "!!! DRY RUN MODE: No files will be renamed !!!"
    echo "Edit the script and set DRY_RUN=false to execute."
    echo "--------------------------------------------------"
fi

# ==============================================================================
# PHASE 1: Specific Rename (problem-set-XX -> ps_XX)
# We do this FIRST so these files get the special names, not just generic "_"
# ==============================================================================
echo "--- Phase 1: Applying specific 'ps_XX' rules ---"

# Find .org and .pdf files starting with "problem-set-"
find . -type f \( -name "problem-set-*.org" -o -name "problem-set-*.pdf" \) | while read filepath; do

    dir=$(dirname "$filepath")
    filename=$(basename "$filepath")
    extension="${filename##*.}"

    # Extract the number (digits) from the filename
    number=$(echo "$filename" | grep -oE '[0-9]+')

    if [ -z "$number" ]; then
        echo "[SKIP] No number found in: $filename"
        continue
    fi

    # Format with zero padding (1 -> 01, 10 -> 10)
    padded_num=$(printf "%02d" "$number")

    # Determine new filename based on extension
    if [ "$extension" == "org" ]; then
        new_name="ps_${padded_num}.org"
    elif [ "$extension" == "pdf" ]; then
        new_name="ps_${padded_num}_source.pdf"
    else
        continue
    fi

    new_full_path="$dir/$new_name"

    # Execute Rename
    if [ "$filepath" != "$new_full_path" ]; then
        if [ "$DRY_RUN" = true ]; then
            echo "[DRY RUN] Specific: '$filename' -> '$new_name'"
        else
            mv "$filepath" "$new_full_path"
            echo "[OK] Specific: $filename -> $new_name"
        fi
    fi
done

# ==============================================================================
# PHASE 2: General Cleanup (Replace '-' with '_')
# We use -depth to rename files inside folders BEFORE renaming the folders themselves
# ==============================================================================
echo "--- Phase 2: Replacing all remaining hyphens with underscores ---"

find . -depth -name "*-*" | while read path; do

    # Skip the script itself to avoid errors
    if [[ "$path" == *"cleanup_structure.sh"* ]]; then continue; fi

    dir=$(dirname "$path")
    base=$(basename "$path")

    # Replace all hyphens with underscores
    new_base="${base//-/_}"
    new_full_path="$dir/$new_base"

    if [ "$DRY_RUN" = true ]; then
        echo "[DRY RUN] General:  '$base' -> '$new_base'"
    else
        # check if target exists to prevent overwriting
        if [ -e "$new_full_path" ]; then
             echo "[SKIP] Target exists: $new_base"
        else
             mv "$path" "$new_full_path"
             echo "[OK] General: $base -> $new_base"
        fi
    fi
done

echo "--------------------------------------------------"
echo "Cleanup complete."
