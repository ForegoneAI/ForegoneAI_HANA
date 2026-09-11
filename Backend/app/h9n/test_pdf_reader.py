from Backend.app.h9n.ingestion.pdf_reader import read_pdf


# Path to the PDF we want H9N to read
file_path = "data/test_deal.pdf"

# Extracts the PDF into page-level text
pages = read_pdf(file_path)

# Shows how many pages were extracted
print(f"Total pages: {len(pages)}")

# Prints a preview of the first page
print("\nPAGE 1:")
print(pages[0]["text"][:1000])