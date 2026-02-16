from pypdf import PdfReader, PdfWriter
import sys

def extract_specific_pages(source_path, output_path, page_indices):
    """
    Reads a PDF and saves specific pages to a new file.
    """
    try:
        reader = PdfReader(source_path)
        writer = PdfWriter()
        
        total_pages = len(reader.pages)
        pages_added = 0

        print(f"Processing '{source_path}' ({total_pages} total pages)...")

        for i in page_indices:
            # Check if the page exists in the doc
            if 0 <= i < total_pages:
                writer.add_page(reader.pages[i])
                pages_added += 1
            else:
                # Page numbers (human readable) are index + 1
                print(f"  Warning: Page {i + 1} is out of range. Skipping.")

        if pages_added > 0:
            with open(output_path, "wb") as out_file:
                writer.write(out_file)
            print(f"Success! Created '{output_path}' with {pages_added} pages.")
        else:
            print("No pages were added. Check your page numbers.")

    except FileNotFoundError:
        print(f"Error: Could not find the file '{source_path}'.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

# --- CONFIGURATION ---

# 1. Update this to match your actual file name
input_filename = "_linear_algebra_source.pdf" 
output_filename = "linear_algebra_proofs_source.pdf"

# 2. These are the specific pages you requested.
# Note: These are 0-indexed (Page 201 = Index 200).
# The logic handles the overlap you mentioned (211-212 & 212-213 become 211-213).
pages_to_extract = [
    200, 201,       # Pages 201-202
    203, 204,       # Pages 204-205
    205,            # Page 206
    210, 211, 212,  # Pages 211-213 (Merged)
    224,            # Page 225
    226, 227, 228,  # Pages 227-229
    240, 241, 242,  # Pages 241-243
    245,            # Page 246
    248             # Page 249
]

# --- EXECUTION ---
if __name__ == "__main__":
    extract_specific_pages(input_filename, output_filename, pages_to_extract)
