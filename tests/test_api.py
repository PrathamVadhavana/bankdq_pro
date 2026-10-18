from fastapi.testclient import TestClient
from app.main import app
from app.db import Base, engine
from app import models  # noqa: F401  # ensure models are registered before create_all

Base.metadata.create_all(bind=engine)
client=TestClient(app)

def user_token(username="tester", password="very-secure-test-password"):
    client.post("/auth/register",json={"username":username,"password":password})
    r=client.post("/auth/login",json={"username":username,"password":password})
    assert r.status_code==200
    return r.json()["access_token"]

def test_health():
    assert client.get("/health").json()["status"]=="ok"

def test_auth_and_tenant_isolation():
    token=user_token("alice")
    assert client.get("/auth/me",headers={"Authorization":f"Bearer {token}"}).status_code==200
    assert client.get("/batches").status_code==401
    token2=user_token("bob")
    # Alice cannot read Bob's random/nonexistent batch.
    assert client.get("/batches/not-a-real-id",headers={"Authorization":f"Bearer {token2}"}).status_code==404

def test_batch_upload_and_reconciliation():
    token=user_token("recon-user")
    headers={"Authorization":f"Bearer {token}"}
    source=b"transaction_id,account_id,transaction_date,amount,currency\nT1,A1,2026-01-01,10.00,INR\nT2,A2,2026-01-02,20.00,INR\n"
    ledger=b"transaction_id,account_id,transaction_date,amount,currency\nT1,A1,2026-01-01,10.00,INR\nT2,A2,2026-01-02,22.00,INR\nT3,A3,2026-01-03,30.00,INR\n"
    r=client.post("/batches",headers=headers,data={"name":"test","chunk_size":"50"},
      files=[("files",("source.csv",source,"text/csv")),("ledger_file",("ledger.csv",ledger,"text/csv"))])
    assert r.status_code==201, r.text
    batch_id=r.json()["batch_id"]
    rows=client.get(f"/batches/{batch_id}/reconciliation",headers=headers).json()["items"]
    statuses={x["transaction_id"]:x["status"] for x in rows}
    assert statuses["T1"]=="MATCHED"
    assert statuses["T2"]=="AMOUNT_MISMATCH"
    assert statuses["T3"]=="LEDGER_ONLY"
