from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
import httpx
import tarfile
import io

from app.agents.courtroom import run_trial
from app.core.security import CurrentUser, get_current_user
from app.schemas.models import TrialRequest, TrialResponse
from app.services import db
from app.services.n8n import notify_verdict

router = APIRouter(prefix="/cases", tags=["cases"])

class HTTPStreamProxy(io.RawIOBase):
    def __init__(self, url):
        self.client = httpx.Client()
        self.response = self.client.stream("GET", url)
        self.stream = self.response.__enter__()
        self.iterator = self.stream.iter_bytes(chunk_size=8192)
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
        self.response.__exit__(None, None, None)
        self.client.close()
        super().close()

def extract_pdf_from_tar(url: str, member_name: str):
    proxy = HTTPStreamProxy(url)
    try:
        tar = tarfile.open(fileobj=proxy, mode="r|")
        # Example member_name from db: 1996_3_868_869.pdf
        # Example member in tar: S_1996_3_868_869_EN.pdf
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
        print(f"Error reading tar: {e}")
    finally:
        proxy.close()
    return None

@router.get("/pdf/proxy")
def proxy_pdf(url: str = Query(..., description="The full S3 URL including #member=...")):
    if "#member=" not in url:
        raise HTTPException(status_code=400, detail="URL must contain #member= fragment")
    
    base_url, member_part = url.split("#member=", 1)
    
    try:
        content = extract_pdf_from_tar(base_url, member_part)
        if not content:
            raise HTTPException(status_code=404, detail="PDF member not found in tar archive")
            
        headers = {
            "Content-Disposition": f'inline; filename="{member_part}"',
            "Content-Length": str(len(content)),
        }
        return Response(content=content, media_type="application/pdf", headers=headers)
    except HTTPException:
        raise
    except Exception as e:
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
        result = await run_trial(req.model_copy(update={"user_id": user.id or req.user_id}))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Trial simulation failed: {exc}")

    # Best-effort fire-and-forget notification (Email/Slack/Telegram via n8n).
    await notify_verdict({
        "case_id":             result.case_id,
        "court_level":         result.court_level,
        "final_judgment":      result.judgment.final_judgment,
        "applicable_sections": result.judgment.applicable_sections,
        "user_email":          user.email,
    })

    return result


@router.get("/{case_id}")
async def get_case(case_id: str):
    case = db.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case
