import shutil
import subprocess
import tempfile
from pathlib import Path

from app.core.config import get_settings
from app.models.deck import Deck


def render_deck_snapshots(deck: Deck, pptx_path: Path) -> Deck:
    renderer = _find_libreoffice()
    if renderer is None:
        return _mark_unavailable(deck, "LibreOffice/soffice is not installed or LIBREOFFICE_PATH is not configured.")

    try:
        import fitz
    except ImportError:
        return _mark_unavailable(deck, "PyMuPDF is not installed. Run pip install -r backend/requirements.txt.")

    settings = get_settings()
    snapshot_dir = settings.media_dir / deck.id / "slides"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as temp_dir:
        output_dir = Path(temp_dir)
        command = [
            str(renderer),
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_dir),
            str(pptx_path),
        ]
        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=settings.slide_render_timeout,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            return _mark_unavailable(deck, _format_render_error(exc))

        pdf_path = output_dir / f"{pptx_path.stem}.pdf"
        if not pdf_path.exists():
            candidates = list(output_dir.glob("*.pdf"))
            if not candidates:
                return _mark_unavailable(deck, "LibreOffice did not produce a PDF file.")
            pdf_path = candidates[0]

        document = fitz.open(pdf_path)
        zoom = settings.slide_render_dpi / 72
        matrix = fitz.Matrix(zoom, zoom)
        try:
            for slide in deck.slides:
                page_index = slide.index - 1
                if page_index >= document.page_count:
                    slide.render_status = "missing"
                    slide.render_error = "Rendered PDF has fewer pages than the PPTX."
                    continue
                page = document.load_page(page_index)
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                filename = f"slide-{slide.index}.png"
                target = snapshot_dir / filename
                pixmap.save(target)
                slide.snapshot_url = f"/media/{deck.id}/slides/{filename}"
                slide.render_status = "ready"
                slide.render_error = None
        finally:
            document.close()

    return deck


def _find_libreoffice() -> Path | None:
    configured = get_settings().libreoffice_path.strip()
    candidates = [
        configured,
        shutil.which("soffice") or "",
        shutil.which("libreoffice") or "",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return Path(candidate)
    return None


def _mark_unavailable(deck: Deck, message: str) -> Deck:
    for slide in deck.slides:
        slide.render_status = "unavailable"
        slide.render_error = message
    return deck


def _format_render_error(exc: subprocess.CalledProcessError | subprocess.TimeoutExpired) -> str:
    if isinstance(exc, subprocess.TimeoutExpired):
        return "LibreOffice rendering timed out."
    detail = (exc.stderr or exc.stdout or "").strip()
    return detail or f"LibreOffice exited with status {exc.returncode}."

