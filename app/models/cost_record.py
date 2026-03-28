from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CostRecord(Base):
    __tablename__ = "cost_records"
    __table_args__ = (
        UniqueConstraint("provider", "service", "usage_date", "resource_id", name="uq_cost_record_dimension"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(16), index=True)
    account_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    project_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    service: Mapped[str] = mapped_column(String(128), index=True)
    resource_id: Mapped[str] = mapped_column(String(256), default="aggregated", index=True)
    usage_date: Mapped[date] = mapped_column(Date, index=True)
    cost_amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(16), default="USD")
    usage_quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    usage_unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
