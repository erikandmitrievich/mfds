import os
import shutil

# --- CONFIGURATION ---
ROOT_DIRECTORY = r'/Users/ziro2173/personal/university/01_bachelor/01_semester/02_linear_algebra/02_exercises'
# ---------------------

def collect_org_files():
    # Verify the source directory exists before proceeding
    if not os.path.exists(ROOT_DIRECTORY):
        print(f"Error: The directory '{ROOT_DIRECTORY}' does not exist.")
        return

    # Define the new target directory inside the root
    target_dir = os.path.join(ROOT_DIRECTORY, "ps_total")

    # Create the target directory if it doesn't exist
    if not os.path.exists(target_dir):
        os.makedirs(target_dir)
        print(f"Created directory: {target_dir}")
    else:
        print(f"Directory already exists: {target_dir}")

    # Walk through the directory tree starting from ROOT_DIRECTORY
    for dirpath, dirnames, filenames in os.walk(ROOT_DIRECTORY):

        # Prevent the script from looking inside the target directory itself
        # This prevents infinite loops if you run the script multiple times
        if os.path.abspath(dirpath) == os.path.abspath(target_dir):
            continue

        for filename in filenames:
            # Check for files starting with 'ps_' and ending with '.org'
            if filename.startswith("ps_") and filename.endswith(".org"):
                source_path = os.path.join(dirpath, filename)
                destination_path = os.path.join(target_dir, filename)

                # Copy the file
                shutil.copy2(source_path, destination_path)
                print(f"Copied: {filename}")

if __name__ == "__main__":
    collect_org_files()
