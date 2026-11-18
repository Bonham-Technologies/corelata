from corelata.testing.pdf import make_pdf


def test_make_pdf_text_blank_and_image_pages():
    data = make_pdf([["Hello world.", "Line one\nLine two"], [], "image"])
    assert data.startswith(b"%PDF-1.4")
    assert data.rstrip().endswith(b"%%EOF")
    assert data.count(b"/Type /Page ") == 3
    assert b"/Subtype /Image" in data
