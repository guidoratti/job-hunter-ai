"""Extract plain text from uploaded PDF, DOCX, or TXT resumes and work-history files."""

from __future__ import annotations

from pathlib import Path


def extract_text_from_file(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix == ".txt" or suffix == ".md":
        return file_path.read_text(encoding="utf-8", errors="ignore").strip()

    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(file_path))
        chunks = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                chunks.append(text.strip())
        return "\n\n".join(chunks).strip()

    if suffix == ".docx":
        from docx import Document

        doc = Document(str(file_path))
        lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    lines.append(" | ".join(cells))
        return "\n".join(lines).strip()

    raise ValueError(f"Unsupported file type: {suffix}. Use PDF, DOCX, TXT, or MD.")
