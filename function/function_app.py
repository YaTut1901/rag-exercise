"""Lab 1: two blob-triggered OCR functions (prebuilt-read + prebuilt-invoice)."""

import logging
import os

import azure.functions as func

from shared.ocr import process_pdf

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

logger = logging.getLogger(__name__)


@app.blob_trigger(
    arg_name="pdfblob",
    path="invoices-in/{name}",
    connection="DOCUMENTS_STORAGE",
)
def ocr_read(pdfblob: func.InputStream) -> None:
    """General OCR via Azure AI Document Intelligence model prebuilt-read."""
    name = pdfblob.name  # e.g. invoices-in/invoice-01.pdf
    if not name.lower().endswith(".pdf"):
        logger.warning("Skipping non-PDF blob: %s", name)
        return

    # Avoid processing own outputs if misconfigured
    if "/invoices-out-" in name:
        return

    source = name.split("/", 1)[-1] if "/" in name else name
    process_pdf(
        pdf_bytes=pdfblob.read(),
        source_blob=source,
        model_id="prebuilt-read",
        output_container=os.environ["OUTPUT_CONTAINER_READ"],
    )


@app.blob_trigger(
    arg_name="pdfblob",
    path="invoices-in/{name}",
    connection="DOCUMENTS_STORAGE",
)
def ocr_invoice(pdfblob: func.InputStream) -> None:
    """Invoice-specialized model via prebuilt-invoice."""
    name = pdfblob.name
    if not name.lower().endswith(".pdf"):
        logger.warning("Skipping non-PDF blob: %s", name)
        return

    if "/invoices-out-" in name:
        return

    source = name.split("/", 1)[-1] if "/" in name else name
    process_pdf(
        pdf_bytes=pdfblob.read(),
        source_blob=source,
        model_id="prebuilt-invoice",
        output_container=os.environ["OUTPUT_CONTAINER_INVOICE"],
    )
