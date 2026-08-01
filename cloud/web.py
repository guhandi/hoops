"""Upload endpoint app factory. Pure FastAPI — no Modal imports — so it is
fully testable with TestClient and reusable for future capture tools."""
import hmac
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from hoops.session import _PREFIX_RE

MAX_BYTES = 64 * 1024 * 1024

def session_key_for(filename: str) -> str:
    sid = _PREFIX_RE.match(filename).group(1)
    return f"sessions/{sid[:4]}/{sid[4:6]}/hoops__{sid}/session.json"

def make_app(store, spawn, upload_key: str) -> FastAPI:
    app = FastAPI()

    @app.post("/upload")
    async def upload(file: UploadFile = File(...),
                     x_hoops_key: str = Header(default="")):
        if not hmac.compare_digest(x_hoops_key, upload_key):
            raise HTTPException(status_code=401, detail="bad key")
        name = file.filename or ""
        m = _PREFIX_RE.match(name)
        if not m:
            raise HTTPException(status_code=400,
                                detail="filename must be hoops__YYYYMMDD-HHMMSS.m4a")
        data = await file.read()
        if len(data) > MAX_BYTES:
            raise HTTPException(status_code=413, detail="recording too large")
        sid = m.group(1)
        if store.exists(session_key_for(name)):
            return {"status": "duplicate", "sid": sid}
        store.put_bytes(f"raw/{name}", data)
        spawn(name)
        return {"status": "processing", "sid": sid}

    return app
