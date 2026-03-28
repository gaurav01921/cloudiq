from sqlalchemy.orm import Session

from app.services.cost_intelligence import CostIntelligenceService


class BatchService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def run_sync_cycle(self) -> dict:
        result = CostIntelligenceService(self.db).sync()
        return result.model_dump()
