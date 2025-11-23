#!/bin/bash

# ==============================================================================
# CONFIGURATION
# ==============================================================================
# Set to true to see what would happen without actually moving files.
# Set to false to execute the rename.
DRY_RUN=false

# ==============================================================================
# SCRIPT
# ==============================================================================

echo "Starting rename process..."
if [ "$DRY_RUN" = true ]; then
    echo "!!! DRY RUN MODE: No files will be moved. !!!"
    echo "Edit this script and set DRY_RUN=false to apply changes."
    echo "-------------------------------------------------------"
fi

# Find all directories matching "problem-set-*"
# We use -depth to process child directories first (though unlikely nested here)
# We use process substitution to handle spaces in paths correctly
while IFS= read -r -d '' dirpath; do
    
    # Get the parent directory path
    parent_dir=$(dirname "$dirpath")
    
    # Get the current folder name (e.g., "problem-set-5")
    base_name=$(basename "$dirpath")

    # Extract the number from the end of the folder name
    # grep -oE '[0-9]+$' finds the digits at the end of the string
    number=$(echo "$base_name" | grep -oE '[0-9]+$')

    # If we couldn't find a number, skip this folder
    if [ -z "$number" ]; then
        echo "[SKIP] Could not extract number from: $base_name"
        continue
    fi

    # Format the new name with zero padding (e.g., 5 -> set_05, 12 -> set_12)
    new_base_name=$(printf "set_%02d" "$number")
    
    # Construct the full destination path
    new_full_path="$parent_dir/$new_base_name"

    # Check if destination already exists to avoid overwriting
    if [ -d "$new_full_path" ]; then
        echo "[WARN] Target already exists: $new_full_path. Skipping."
        continue
    fi

    # Execute the move
    if [ "$DRY_RUN" = true ]; then
        echo "[DRY RUN] Would move: '$base_name' -> '$new_base_name'"
        echo "          Path: $dirpath"
    else
        mv "$dirpath" "$new_full_path"
        echo "[OK] Renamed: $dirpath -> $new_full_path"
    fi

done < <(find . -type d -name "problem-set-*" -print0)

echo "-------------------------------------------------------"
echo "Process complete."
