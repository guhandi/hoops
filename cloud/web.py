"""Upload endpoint app factory. Pure FastAPI — no Modal imports — so it is
fully testable with TestClient and reusable for future capture tools."""
import hmac
import inspect
from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from hoops.session import _PREFIX_RE

MAX_BYTES = 64 * 1024 * 1024

def session_key_for(filename: str) -> str:
    sid = _PREFIX_RE.match(filename).group(1)
    return f"sessions/{sid[:4]}/{sid[4:6]}/hoops__{sid}/session.json"

def make_app(store, spawn, upload_key: str) -> FastAPI:
    app = FastAPI()

    @app.post("/upload")
    async def upload(request: Request, name: str | None = None,
                     file: UploadFile | None = File(None),
                     x_hoops_key: str = Header(default="")):
        if not hmac.compare_digest(x_hoops_key, upload_key):
            raise HTTPException(status_code=401, detail="bad key")

        if file is not None:
            filename = file.filename or ""
            data = await file.read()
        elif name is not None:
            filename = name
            cl = request.headers.get("content-length")
            if cl is not None and cl.isdigit() and int(cl) > MAX_BYTES:
                raise HTTPException(status_code=413, detail="recording too large")
            data = await request.body()
        else:
            raise HTTPException(status_code=400,
                                detail="send multipart form field 'file' or raw body with ?name=")

        if len(data) == 0:
            raise HTTPException(status_code=400, detail="empty body")

        m = _PREFIX_RE.match(filename)
        if not m:
            raise HTTPException(status_code=400,
                                detail="filename must be hoops__YYYYMMDD-HHMMSS.m4a")
        if len(data) > MAX_BYTES:
            raise HTTPException(status_code=413, detail="recording too large")
        sid = m.group(1)
        if store.exists(session_key_for(filename)):
            return {"status": "duplicate", "sid": sid}
        store.put_bytes(f"raw/{filename}", data)
        res = spawn(filename)
        if inspect.isawaitable(res):
            await res
        return {"status": "processing", "sid": sid}

    return app
