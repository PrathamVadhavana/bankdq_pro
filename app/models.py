from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base

def now_utc():
    return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    batches: Mapped[list["Batch"]] = relationship(back_populates="owner")

class Batch(Base):
    __tablename__ = "batches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(String(24), default="PROCESSING")
    configured_chunk_size: Mapped[int] = mapped_column(Integer, default=500)
    files_received: Mapped[int] = mapped_column(Integer, default=0)
    rows_received: Mapped[int] = mapped_column(Integer, default=0)
    rows_valid: Mapped[int] = mapped_column(Integer, default=0)
    rows_invalid: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner: Mapped["User"] = relationship(back_populates="batches")
    records: Mapped[list["TransactionRecord"]] = relationship(back_populates="batch", cascade="all, delete-orphan")
    issues: Mapped[list["QualityIssue"]] = relationship(back_populates="batch", cascade="all, delete-orphan")
    reconciliations: Mapped[list["ReconciliationResult"]] = relationship(back_populates="batch", cascade="all, delete-orphan")
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="batch", cascade="all, delete-orphan")

class TransactionRecord(Base):
    __tablename__ = "transaction_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    source_file: Mapped[str] = mapped_column(String(255))
    row_number: Mapped[int] = mapped_column(Integer)
    transaction_id: Mapped[str | None] = mapped_column(String(140), nullable=True, index=True)
    account_id: Mapped[str | None] = mapped_column(String(140), nullable=True)
    transaction_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    amount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    business_key: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)
    record_type: Mapped[str] = mapped_column(String(20), default="SOURCE")
    batch: Mapped["Batch"] = relationship(back_populates="records")
    __table_args__ = (Index("ix_record_owner_business_key", "owner_id", "business_key"),)

class QualityIssue(Base):
    __tablename__ = "quality_issues"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    source_file: Mapped[str] = mapped_column(String(255))
    row_number: Mapped[int] = mapped_column(Integer)
    transaction_id: Mapped[str | None] = mapped_column(String(140), nullable=True)
    issue_code: Mapped[str] = mapped_column(String(60), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="ERROR")
    message: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    batch: Mapped["Batch"] = relationship(back_populates="issues")

class ReconciliationResult(Base):
    __tablename__ = "reconciliation_results"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    transaction_id: Mapped[str] = mapped_column(String(140), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    source_amount: Mapped[float | None] = mapped_column(Numeric(18,2), nullable=True)
    ledger_amount: Mapped[float | None] = mapped_column(Numeric(18,2), nullable=True)
    amount_delta: Mapped[float | None] = mapped_column(Numeric(18,2), nullable=True)
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    batch: Mapped["Batch"] = relationship(back_populates="reconciliations")

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("batches.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(80))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    batch: Mapped["Batch | None"] = relationship(back_populates="audit_logs")
