from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Anomaly(Base):
    __tablename__ = "anomalies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(16), index=True)
    scope: Mapped[str] = mapped_column(String(32), default="service")
    scope_key: Mapped[str] = mapped_column(String(256), index=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    usage_date: Mapped[str] = mapped_column(String(16))
    observed_cost: Mapped[float] = mapped_column(Float)
    expected_cost: Mapped[float] = mapped_column(Float)
    anomaly_score: Mapped[float] = mapped_column(Float)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
