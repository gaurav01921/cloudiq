from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AppSetting


class RuntimeSettingsService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

    def get_data_mode(self) -> str:
        row = self.db.execute(select(AppSetting).where(AppSetting.key == "data_mode")).scalar_one_or_none()
        return row.value if row else self.settings.data_mode

    def set_data_mode(self, value: str) -> str:
        normalized = value.lower().strip()
        if normalized not in {"live", "demo", "hybrid"}:
            raise ValueError("Invalid data mode.")
        row = self.db.execute(select(AppSetting).where(AppSetting.key == "data_mode")).scalar_one_or_none()
        if row:
            row.value = normalized
        else:
            self.db.add(AppSetting(key="data_mode", value=normalized))
        self.db.commit()
        return normalized
