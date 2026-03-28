from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ResourceSnapshot(Base):
    __tablename__ = "resource_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(16), index=True)
    account_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    project_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    resource_id: Mapped[str] = mapped_column(String(256), index=True)
    resource_type: Mapped[str] = mapped_column(String(64), index=True)
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)
    state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cpu_utilization_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    network_utilization_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    monthly_cost_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_idle: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
