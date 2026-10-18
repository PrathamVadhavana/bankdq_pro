from __future__ import annotations
import csv, io, json, logging, os, time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Annotated
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func, desc
from sqlalchemy.orm import Session
from .db import Base, engine, get_db
from .models import User, Batch, TransactionRecord, QualityIssue, ReconciliationResult, AuditLog
from .security import hash_password, verify_password, create_token, get_current_user

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}')
logger = logging.getLogger("bankdq")
MAX_FILE_BYTES = 25 * 1024 * 1024

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Tables are created for local convenience. Production deployments should run Alembic migrations.
    Base.metadata.create_all(bind=engine)
    yield

app = FastAPI(
    title="BankDQ Pro",
    version="2.0.0",
    description="Portfolio prototype for batch data quality, reconciliation, and audit trails. Use synthetic data only.",
    lifespan=lifespan,
)

class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=10, max_length=128)

class LoginRequest(BaseModel):
    username: str
    password: str

def audit(db: Session, owner_id: str, action: str, batch_id: str | None = None, detail: dict | None = None):
    db.add(AuditLog(owner_id=owner_id, batch_id=batch_id, action=action,
                    detail=json.dumps(detail or {}, separators=(",", ":"))))

def own_batch(db: Session, batch_id: str, user: User) -> Batch:
    batch = db.scalar(select(Batch).where(Batch.id == batch_id, Batch.owner_id == user.id))
    if not batch:
        raise HTTPException(404, "Batch not found")
    return batch

def normalize_row(row: dict) -> dict:
    return {str(k or "").strip().lower().replace(" ", "_"): (v.strip() if isinstance(v, str) else v) for k,v in row.items()}

def parse_amount(value):
    if value is None or str(value).strip() == "":
        raise ValueError("amount is missing")
    try:
        amount = Decimal(str(value).replace(",", "").strip()).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ValueError("amount is not numeric")
    if not amount.is_finite():
        raise ValueError("amount must be finite")
    return amount

def business_key(row: dict) -> str:
    # Stronger duplicate detection: stable key across files when a provider transaction ID is missing.
    # Key fields intentionally exclude description because text formatting varies by provider.
    return "|".join(str(row.get(k) or "").strip().casefold() for k in
                    ("account_id", "transaction_date", "amount", "currency"))

def read_csv(upload: UploadFile) -> tuple[list[dict], str]:
    filename = (upload.filename or "upload.csv").replace("\\", "/").split("/")[-1][:255]
    if not filename.lower().endswith(".csv"):
        raise HTTPException(400, f"{filename}: only CSV files are accepted")
    raw = upload.file.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise HTTPException(413, f"{filename}: exceeds 25 MB limit")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(400, f"{filename}: CSV must be UTF-8 encoded")
    try:
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise HTTPException(400, f"{filename}: missing CSV header")
        headers = {str(h or "").strip().lower().replace(" ", "_") for h in reader.fieldnames}
        required = {"transaction_id", "amount"}
        missing = required - headers
        if missing:
            raise HTTPException(400, f"{filename}: missing required columns: {', '.join(sorted(missing))}")
        rows = [normalize_row(r) for r in reader]
        return rows, filename
    except csv.Error as exc:
        raise HTTPException(400, f"{filename}: invalid CSV ({exc})")

@app.get("/health")
def health():
    return {"status":"ok","service":"BankDQ Pro","version":"2.0.0"}

@app.post("/auth/register", status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.username == payload.username)):
        raise HTTPException(409, "Username already exists")
    user = User(username=payload.username, password_hash=hash_password(payload.password))
    db.add(user); db.commit(); db.refresh(user)
    logger.info(json.dumps({"event":"user_registered","user_id":user.id}))
    return {"id":user.id,"username":user.username}

@app.post("/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == payload.username))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Incorrect username or password")
    minutes = int(os.getenv("ACCESS_TOKEN_MINUTES", "60"))
    return {"access_token":create_token(user.id, user.username, minutes),"token_type":"bearer","expires_in":minutes*60}

@app.get("/auth/me")
def me(user: User = Depends(get_current_user)):
    return {"id":user.id,"username":user.username}

@app.post("/batches", status_code=201)
def create_batch(
    files: Annotated[list[UploadFile], File(description="One or more source transaction CSV files")],
    name: Annotated[str, Form(min_length=1, max_length=180)] = "Untitled batch",
    chunk_size: Annotated[int, Form(ge=50, le=10000)] = 500,
    ledger_file: Annotated[UploadFile | None, File(description="Optional ledger/reference CSV")] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not files:
        raise HTTPException(400, "Upload at least one source CSV")
    if len(files) > 20:
        raise HTTPException(400, "A batch can contain at most 20 source CSV files")
    batch = Batch(owner_id=user.id, name=name, configured_chunk_size=chunk_size,
                  files_received=len(files) + (1 if ledger_file else 0))
    db.add(batch); db.flush()
    seen_tx_ids: dict[str, tuple[str,int]] = {}
    seen_keys: dict[str, tuple[str,int]] = {}
    source_by_id: dict[str, list[dict]] = {}
    total = valid = invalid = duplicate_count = 0
    start = time.perf_counter()
    try:
        for upload in files:
            rows, filename = read_csv(upload)
            # Process in configurable chunks; rows are persisted as chunks to bound working-set size.
            for offset in range(0, len(rows), chunk_size):
                chunk = rows[offset:offset+chunk_size]
                for j, row in enumerate(chunk, start=offset + 2):
                    total += 1
                    txid = str(row.get("transaction_id") or "").strip() or None
                    account = str(row.get("account_id") or "").strip() or None
                    date = str(row.get("transaction_date") or row.get("date") or "").strip() or None
                    currency = str(row.get("currency") or "INR").strip().upper() or "INR"
                    description = str(row.get("description") or "").strip()[:500] or None
                    row_issues = []
                    amount = None
                    try: amount = parse_amount(row.get("amount"))
                    except ValueError as exc: row_issues.append(("INVALID_AMOUNT", str(exc)))
                    if not txid: row_issues.append(("MISSING_TRANSACTION_ID", "transaction_id is required"))
                    if not account: row_issues.append(("MISSING_ACCOUNT_ID", "account_id is recommended for reconciliation"))
                    if date:
                        try: datetime.fromisoformat(date.replace("Z", "+00:00"))
                        except ValueError: row_issues.append(("INVALID_DATE", "transaction_date must be ISO format YYYY-MM-DD"))
                    keyrow = {"account_id":account,"transaction_date":date,"amount":str(amount) if amount is not None else row.get("amount"),"currency":currency}
                    bkey = business_key(keyrow)
                    duplicate = False
                    if txid and txid in seen_tx_ids:
                        duplicate = True
                        row_issues.append(("DUPLICATE_TRANSACTION_ID", f"Transaction ID also appears in {seen_tx_ids[txid][0]} row {seen_tx_ids[txid][1]}"))
                    elif txid:
                        seen_tx_ids[txid] = (filename,j)
                    if bkey.strip("|") and all(x for x in (account,date,str(amount),currency)) and bkey in seen_keys:
                        duplicate = True
                        row_issues.append(("POSSIBLE_BUSINESS_KEY_DUPLICATE", f"Account/date/amount/currency matches {seen_keys[bkey][0]} row {seen_keys[bkey][1]}"))
                    elif bkey.strip("|") and all(x for x in (account,date,str(amount),currency)):
                        seen_keys[bkey] = (filename,j)
                    record = TransactionRecord(batch_id=batch.id, owner_id=user.id, source_file=filename,
                        row_number=j, transaction_id=txid, account_id=account, transaction_date=date,
                        amount=amount, currency=currency, description=description, business_key=bkey, record_type="SOURCE")
                    db.add(record)
                    if txid:
                        source_by_id.setdefault(txid, []).append({"amount":amount,"account_id":account,"date":date,"currency":currency,"file":filename,"row":j})
                    for code,msg in row_issues:
                        severity = "WARNING" if code in {"POSSIBLE_BUSINESS_KEY_DUPLICATE"} else "ERROR"
                        db.add(QualityIssue(batch_id=batch.id, owner_id=user.id, source_file=filename,
                            row_number=j, transaction_id=txid, issue_code=code, severity=severity, message=msg))
                    if row_issues: invalid += 1
                    else: valid += 1
                    if duplicate: duplicate_count += 1
                db.flush()
        if ledger_file:
            ledger_rows, ledger_name = read_csv(ledger_file)
            ledger_by_id: dict[str, list[dict]] = {}
            for offset in range(0, len(ledger_rows), chunk_size):
                for j,row in enumerate(ledger_rows[offset:offset+chunk_size], start=offset+2):
                    txid = str(row.get("transaction_id") or "").strip() or None
                    try: amount = parse_amount(row.get("amount"))
                    except ValueError: amount = None
                    item = {"amount":amount,"account_id":str(row.get("account_id") or "").strip() or None,
                            "date":str(row.get("transaction_date") or row.get("date") or "").strip() or None,
                            "currency":str(row.get("currency") or "INR").strip().upper() or "INR"}
                    if txid:
                        ledger_by_id.setdefault(txid, []).append(item)
                    db.add(TransactionRecord(batch_id=batch.id, owner_id=user.id, source_file=ledger_name,
                        row_number=j, transaction_id=txid, account_id=item["account_id"], transaction_date=item["date"],
                        amount=amount, currency=item["currency"], business_key=business_key(item), record_type="LEDGER"))
            all_ids = set(source_by_id) | set(ledger_by_id)
            for txid in sorted(all_ids):
                srcs, ledgers = source_by_id.get(txid, []), ledger_by_id.get(txid, [])
                if not srcs:
                    status, source_amount, ledger_amount, delta, detail = "LEDGER_ONLY", None, ledgers[0]["amount"], None, "Present in ledger, missing from source"
                elif not ledgers:
                    status, source_amount, ledger_amount, delta, detail = "SOURCE_ONLY", srcs[0]["amount"], None, None, "Present in source, missing from ledger"
                elif len(srcs) > 1 or len(ledgers) > 1:
                    status, source_amount, ledger_amount, delta, detail = "DUPLICATE_REFERENCE", srcs[0]["amount"], ledgers[0]["amount"], None, f"source_count={len(srcs)}, ledger_count={len(ledgers)}"
                else:
                    source_amount, ledger_amount = srcs[0]["amount"], ledgers[0]["amount"]
                    delta = (source_amount - ledger_amount) if source_amount is not None and ledger_amount is not None else None
                    if delta != Decimal("0.00"): status, detail = "AMOUNT_MISMATCH", f"Amount delta={delta}"
                    elif srcs[0]["account_id"] != ledgers[0]["account_id"]: status, detail = "ACCOUNT_MISMATCH", "Account ID differs"
                    elif srcs[0]["date"] != ledgers[0]["date"]: status, detail = "DATE_MISMATCH", "Transaction date differs"
                    elif srcs[0]["currency"] != ledgers[0]["currency"]: status, detail = "CURRENCY_MISMATCH", "Currency differs"
                    else: status, detail = "MATCHED", "Transaction matched on reference ID and key fields"
                db.add(ReconciliationResult(batch_id=batch.id, owner_id=user.id, transaction_id=txid,
                    status=status, source_amount=source_amount, ledger_amount=ledger_amount,
                    amount_delta=delta, details=detail))
        batch.rows_received=total; batch.rows_valid=valid; batch.rows_invalid=invalid; batch.duplicates=duplicate_count
        batch.status="COMPLETED"; batch.completed_at=datetime.now(timezone.utc)
        audit(db,user.id,"BATCH_PROCESSED",batch.id,{"rows":total,"files":batch.files_received,"chunk_size":chunk_size,
              "duration_ms":round((time.perf_counter()-start)*1000,2)})
        db.commit()
        logger.info(json.dumps({"event":"batch_processed","batch_id":batch.id,"owner_id":user.id,"rows":total,
            "files":batch.files_received,"chunk_size":chunk_size,"duration_ms":round((time.perf_counter()-start)*1000,2)}))
        return {"batch_id":batch.id,"name":batch.name,"status":batch.status,"files_received":batch.files_received,
                "rows_received":total,"rows_valid":valid,"rows_invalid":invalid,"duplicates":duplicate_count,
                "chunk_size":chunk_size,"duration_ms":round((time.perf_counter()-start)*1000,2),
                "reconciliation_enabled":ledger_file is not None}
    except Exception:
        db.rollback()
        logger.exception("batch_processing_failed")
        raise

@app.get("/batches")
def list_batches(page: int = Query(1,ge=1), page_size: int = Query(20,ge=1,le=100),
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    base = select(Batch).where(Batch.owner_id==user.id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    items = db.scalars(base.order_by(desc(Batch.created_at)).offset((page-1)*page_size).limit(page_size)).all()
    return {"page":page,"page_size":page_size,"total":total,"items":[{"id":b.id,"name":b.name,"status":b.status,
        "files_received":b.files_received,"rows_received":b.rows_received,"rows_valid":b.rows_valid,
        "rows_invalid":b.rows_invalid,"duplicates":b.duplicates,"created_at":b.created_at.isoformat()} for b in items]}

@app.get("/batches/{batch_id}")
def batch_detail(batch_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    b=own_batch(db,batch_id,user)
    rec_count=db.scalar(select(func.count()).select_from(TransactionRecord).where(TransactionRecord.batch_id==b.id)) or 0
    issue_count=db.scalar(select(func.count()).select_from(QualityIssue).where(QualityIssue.batch_id==b.id)) or 0
    recon_count=db.scalar(select(func.count()).select_from(ReconciliationResult).where(ReconciliationResult.batch_id==b.id)) or 0
    return {"id":b.id,"name":b.name,"status":b.status,"files_received":b.files_received,"rows_received":b.rows_received,
        "rows_valid":b.rows_valid,"rows_invalid":b.rows_invalid,"duplicates":b.duplicates,
        "record_count":rec_count,"issue_count":issue_count,"reconciliation_count":recon_count,
        "created_at":b.created_at.isoformat(),"completed_at":b.completed_at.isoformat() if b.completed_at else None}

@app.get("/batches/{batch_id}/issues")
def list_issues(batch_id: str, page: int=Query(1,ge=1), page_size: int=Query(50,ge=1,le=200),
                severity: str|None=None, issue_code: str|None=None,
                user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    own_batch(db,batch_id,user)
    q=select(QualityIssue).where(QualityIssue.batch_id==batch_id,QualityIssue.owner_id==user.id)
    if severity: q=q.where(QualityIssue.severity==severity.upper())
    if issue_code: q=q.where(QualityIssue.issue_code==issue_code.upper())
    total=db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows=db.scalars(q.order_by(QualityIssue.row_number).offset((page-1)*page_size).limit(page_size)).all()
    return {"page":page,"page_size":page_size,"total":total,"items":[{"id":x.id,"file":x.source_file,"row":x.row_number,
        "transaction_id":x.transaction_id,"code":x.issue_code,"severity":x.severity,"message":x.message} for x in rows]}

@app.get("/batches/{batch_id}/reconciliation")
def reconciliation(batch_id: str, page: int=Query(1,ge=1), page_size: int=Query(50,ge=1,le=200),
                   status: str|None=None, user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    own_batch(db,batch_id,user)
    q=select(ReconciliationResult).where(ReconciliationResult.batch_id==batch_id,ReconciliationResult.owner_id==user.id)
    if status: q=q.where(ReconciliationResult.status==status.upper())
    total=db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows=db.scalars(q.order_by(ReconciliationResult.transaction_id).offset((page-1)*page_size).limit(page_size)).all()
    return {"page":page,"page_size":page_size,"total":total,"items":[{"transaction_id":x.transaction_id,"status":x.status,
        "source_amount":str(x.source_amount) if x.source_amount is not None else None,
        "ledger_amount":str(x.ledger_amount) if x.ledger_amount is not None else None,
        "amount_delta":str(x.amount_delta) if x.amount_delta is not None else None,"details":x.details} for x in rows]}

@app.get("/batches/{batch_id}/reconciliation.csv")
def reconciliation_csv(batch_id: str, user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    own_batch(db,batch_id,user)
    rows=db.scalars(select(ReconciliationResult).where(ReconciliationResult.batch_id==batch_id,
        ReconciliationResult.owner_id==user.id).order_by(ReconciliationResult.transaction_id)).all()
    output=io.StringIO(); writer=csv.writer(output)
    writer.writerow(["transaction_id","status","source_amount","ledger_amount","amount_delta","details"])
    for r in rows: writer.writerow([r.transaction_id,r.status,r.source_amount,r.ledger_amount,r.amount_delta,r.details])
    return StreamingResponse(iter([output.getvalue()]),media_type="text/csv",
        headers={"Content-Disposition":f'attachment; filename="bankdq_reconciliation_{batch_id[:8]}.csv"'})

@app.get("/audit")
def get_audit(page: int=Query(1,ge=1), page_size: int=Query(50,ge=1,le=200),
              user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    q=select(AuditLog).where(AuditLog.owner_id==user.id)
    total=db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows=db.scalars(q.order_by(desc(AuditLog.created_at)).offset((page-1)*page_size).limit(page_size)).all()
    return {"page":page,"page_size":page_size,"total":total,"items":[{"id":x.id,"batch_id":x.batch_id,"action":x.action,
        "detail":x.detail,"created_at":x.created_at.isoformat()} for x in rows]}

@app.get("/batches/{batch_id}/metrics")
def metrics(batch_id: str, user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    b=own_batch(db,batch_id,user)
    counts=db.execute(select(ReconciliationResult.status,func.count()).where(
        ReconciliationResult.batch_id==batch_id).group_by(ReconciliationResult.status)).all()
    recon_rows=db.scalars(select(ReconciliationResult).where(
        ReconciliationResult.batch_id==batch_id, ReconciliationResult.owner_id==user.id)).all()
    from decimal import Decimal
    amount_mismatch_exposure=Decimal("0.00")
    source_only_exposure=Decimal("0.00")
    ledger_only_exposure=Decimal("0.00")
    for item in recon_rows:
        if item.status == "AMOUNT_MISMATCH" and item.amount_delta is not None:
            amount_mismatch_exposure += abs(Decimal(str(item.amount_delta)))
        elif item.status == "SOURCE_ONLY" and item.source_amount is not None:
            source_only_exposure += abs(Decimal(str(item.source_amount)))
        elif item.status == "LEDGER_ONLY" and item.ledger_amount is not None:
            ledger_only_exposure += abs(Decimal(str(item.ledger_amount)))
    total_exposure=amount_mismatch_exposure+source_only_exposure+ledger_only_exposure
    return {"batch_id":b.id,"quality_rate_pct":round((b.rows_valid / b.rows_received * 100),2) if b.rows_received else 0,
        "rows_per_batch":b.rows_received,"files_received":b.files_received,"issue_count":b.rows_invalid,
        "duplicate_rows":b.duplicates,"reconciliation_status_counts":{k:v for k,v in counts},
        "financial_exposure_estimate":str(total_exposure.quantize(Decimal("0.01"))),
        "amount_mismatch_exposure":str(amount_mismatch_exposure.quantize(Decimal("0.01"))),
        "source_only_exposure":str(source_only_exposure.quantize(Decimal("0.01"))),
        "ledger_only_exposure":str(ledger_only_exposure.quantize(Decimal("0.01"))),
        "exposure_currency_note":"Amounts use source CSV currency values; only sum comparable currencies before interpreting as one currency."}

@app.get("/openapi.json")
def openapi_json():
    return app.openapi()
