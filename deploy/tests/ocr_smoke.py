"""CRL-95: a PDF with a scanned page and a text page, uploaded to a running Corelata with
ingest.ocr: auto, comes back with the scanned page read by OCR. Runs inside the app image (it
builds the scan with corelata.testing.pdf), so the language pack it uses is the image's:
    python3 ocr_smoke.py BASE_URL
Exit 0 on success; prints the source's OCR record."""

import json
import sys
import urllib.request
import uuid

from corelata.testing.pdf import Scan, make_pdf

LINE = "The port of Varna handled more containers in 2026."


def post(base, path, data, content_type):
    req = urllib.request.Request(
        base + path, data=data, method="POST", headers={"Content-Type": content_type}
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read())


def main(base):
    pdf = make_pdf([Scan((LINE,)), ["Page two has a text layer."]])
    project = post(
        base, "/api/projects", json.dumps({"name": f"ocr-{uuid.uuid4().hex[:8]}"}).encode(),
        "application/json",
    )
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"scan.pdf\"\r\n"
        "Content-Type: application/pdf\r\n\r\n"
    ).encode() + pdf + f"\r\n--{boundary}--\r\n".encode()
    [source] = post(
        base, f"/api/projects/{project['id']}/sources", body,
        f"multipart/form-data; boundary={boundary}",
    )
    record = source["provenance"]
    if record.get("ocr_pages") != [1] or record.get("ocr_languages") != ["eng"]:
        raise SystemExit(f"ocr smoke: the scanned page was not read by OCR: {source}")
    print(f"ocr smoke: {source['name']} read by OCR: {record}")
    return source["id"]


if __name__ == "__main__":
    print(main(sys.argv[1]))
