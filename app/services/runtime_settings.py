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

    def get_theme(self) -> str:
        row = self.db.execute(select(AppSetting).where(AppSetting.key == "theme")).scalar_one_or_none()
        return row.value if row and row.value in {"light", "dark"} else "light"

    def set_theme(self, value: str) -> str:
        normalized = value.lower().strip()
        if normalized not in {"light", "dark"}:
            raise ValueError("Invalid theme.")
        row = self.db.execute(select(AppSetting).where(AppSetting.key == "theme")).scalar_one_or_none()
        if row:
            row.value = normalized
        else:
            self.db.add(AppSetting(key="theme", value=normalized))
        self.db.commit()
        return normalized

    def get_gemini_api_key(self) -> str | None:
        row = self.db.execute(select(AppSetting).where(AppSetting.key == "gemini_api_key")).scalar_one_or_none()
        return row.value if row and row.value else None

    def set_gemini_api_key(self, value: str) -> None:
        normalized = value.strip()
        row = self.db.execute(select(AppSetting).where(AppSetting.key == "gemini_api_key")).scalar_one_or_none()
        if row:
            row.value = normalized
        else:
            self.db.add(AppSetting(key="gemini_api_key", value=normalized))
        self.db.commit()

    def clear_gemini_api_key(self) -> None:
        row = self.db.execute(select(AppSetting).where(AppSetting.key == "gemini_api_key")).scalar_one_or_none()
        if row:
            self.db.delete(row)
            self.db.commit()

    @staticmethod
    def mask_api_key(value: str | None) -> str | None:
        if not value:
            return None
        if len(value) <= 8:
            return "*" * len(value)
        return f"{value[:4]}...{value[-4:]}"
