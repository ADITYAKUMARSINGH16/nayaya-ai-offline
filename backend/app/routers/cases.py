from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
import httpx
import tarfile
import io
import hashlib
import logging
import os
from pathlib import Path

from app.agents.courtroom import run_trial
from app.core.security import CurrentUser, get_current_user
from app.schemas.models import TrialRequest, TrialResponse
from app.services import db
# notify_verdict moved into agents.courtroom.run_trial so every caller fires it.

log = logging.getLogger(__name__)
router = APIRouter(prefix="/cases", tags=["cases"])

# ---------------------------------------------------------------------------
# PDF proxy cache
# ---------------------------------------------------------------------------
# The Supreme Court source PDFs live inside multi-PDF tar archives on S3.
# Without a cache, every click on "View Source PDF" re-downloads the whole tar,
# scans it sequentially, extracts the matching member, and only then returns
# the bytes to the browser — frequently 10-30s per click for tars >10MB.
#
# Strategy: cache the extracted PDFs to local disk keyed by the member name,
# so the second click on the same case is instant.
_PDF_CACHE_DIR = Path(os.environ.get("PDF_CACHE_DIR", "/tmp/nyaya_pdf_cache"))
_PDF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_PDF_CACHE_MAX_BYTES = int(os.environ.get("PDF_CACHE_MAX_BYTES", str(500 * 1024 * 1024)))  # 500 MB default


def _cache_key(url: str, member: str) -> str:
    """Stable filename for a (tar_url, member) pair."""
    h = hashlib.sha256(f"{url}|{member}".encode("utf-8")).hexdigest()[:32]
    safe_member = member.replace("/", "_").replace("..", "_")
    return f"{h}__{safe_member}"


def _evict_lru_if_needed() -> None:
    """Best-effort LRU cap so the cache dir doesn't grow unbounded."""
    try:
        files = sorted(
            _PDF_CACHE_DIR.glob("*.pdf"),
            key=lambda p: p.stat().st_atime,
        )
        total = sum(p.stat().st_size for p in files)
        while total > _PDF_CACHE_MAX_BYTES and files:
            victim = files.pop(0)
            total -= victim.stat().st_size
            victim.unlink(missing_ok=True)
    except Exception:
        pass


class HTTPStreamProxy(io.RawIOBase):
    def __init__(self, url):
        self.client = httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0))
        self.response = self.client.stream("GET", url)
        self.stream = self.response.__enter__()
        self.iterator = self.stream.iter_bytes(chunk_size=64 * 1024)   # 64KB chunks (was 8KB)
        self.buffer = b""

    def readinto(self, b):
        if not self.buffer:
            try:
                self.buffer = next(self.iterator)
            except StopIteration:
                return 0

        length = min(len(b), len(self.buffer))
        b[:length] = self.buffer[:length]
        self.buffer = self.buffer[length:]
        return length

    def close(self):
        try:
            self.response.__exit__(None, None, None)
        except Exception:
            pass
        try:
            self.client.close()
        except Exception:
            pass
        super().close()


def extract_pdf_from_tar(url: str, member_name: str) -> bytes | None:
    """Stream the tar from S3, find the matching member, return its bytes.

    Closes the network stream the moment the right member is found so we
    don't download the rest of the tar unnecessarily.
    """
    proxy = HTTPStreamProxy(url)
    try:
        tar = tarfile.open(fileobj=proxy, mode="r|")
        core_id = member_name.replace(".pdf", "")
        for member in tar:
            if core_id in member.name:
                f = tar.extractfile(member)
                if f:
                    content = f.read()
                    tar.close()
                    return content
        tar.close()
    except Exception as e:
        log.warning("extract_pdf_from_tar: %s url=%s member=%s", e, url, member_name)
    finally:
        proxy.close()
    return None


@router.get("/pdf/proxy")
def proxy_pdf(
    url: str = Query(..., description="The full S3 URL including #member=..."),
    download: int = Query(0, description="Set to 1 to force browser download instead of inline view"),
):
    if "#member=" not in url:
        raise HTTPException(status_code=400, detail="URL must contain #member= fragment")

    base_url, member_part = url.split("#member=", 1)
    cache_path = _PDF_CACHE_DIR / f"{_cache_key(base_url, member_part)}.pdf"

    # Inline (default) opens in the browser tab; ?download=1 forces a save dialog.
    disposition = f'{"attachment" if download else "inline"}; filename="{member_part}"'

    # --- Fast path: cache hit --------------------------------------------------
    if cache_path.exists() and cache_path.stat().st_size > 0:
        try:
            cache_path.touch()    # bump atime for LRU
        except Exception:
            pass
        content = cache_path.read_bytes()
        log.info("pdf/proxy cache HIT  %s (%d bytes)", member_part, len(content))
        return Response(
            content=content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": disposition,
                "Content-Length":      str(len(content)),
                "Cache-Control":       "public, max-age=2592000, immutable",  # 30 days
                "X-Cache":             "HIT",
            },
        )

    # --- Slow path: extract from S3 tar, then cache ---------------------------
    log.info("pdf/proxy cache MISS %s — extracting from %s", member_part, base_url)
    try:
        content = extract_pdf_from_tar(base_url, member_part)
        if not content:
            raise HTTPException(status_code=404, detail="PDF member not found in tar archive")

        # Write to a .tmp and rename for atomicity (avoids serving partial files
        # if two requests race for the same member).
        tmp_path = cache_path.with_suffix(".pdf.tmp")
        tmp_path.write_bytes(content)
        tmp_path.replace(cache_path)
        _evict_lru_if_needed()

        return Response(
            content=content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": disposition,
                "Content-Length":      str(len(content)),
                "Cache-Control":       "public, max-age=2592000, immutable",
                "X-Cache":             "MISS",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        log.exception("pdf/proxy failed")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("")
async def list_cases(
    user: Annotated[CurrentUser, Depends(get_current_user)],
):
    if user.role in ("judge", "admin", "lawyer"):
        return db.list_all_cases()
    return db.list_user_cases(user.id)


@router.post("/trial", response_model=TrialResponse)
async def trial(
    req: TrialRequest,
    user: Annotated[CurrentUser, Depends(get_current_user)],
):
    try:
        # Notification fan-out happens inside run_trial itself — we just pass
        # the user's email through TrialRequest so the email channel knows
        # where to address the reply.
        result = await run_trial(req.model_copy(update={
            "user_id":    user.id or req.user_id,
            "user_email": user.email or req.user_email,
        }))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Trial simulation failed: {exc}")

    return result


@router.get("/{case_id}")
async def get_case(case_id: str):
    case = db.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case
