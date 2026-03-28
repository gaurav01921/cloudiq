import pandas as pd
from sklearn.ensemble import IsolationForest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Anomaly, CostRecord


class AnomalyDetectionService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

    def run(self) -> int:
        cost_records = self.db.execute(select(CostRecord)).scalars().all()
        if len(cost_records) < 10:
            return 0

        raw_frame = pd.DataFrame(
            [
                {
                    "provider": record.provider,
                    "service": record.service,
                    "usage_date": record.usage_date,
                    "cost_amount": record.cost_amount,
                }
                for record in cost_records
            ]
        )
        if raw_frame.empty:
            return 0

        analysis_frame = self._build_analysis_frame(raw_frame)
        self.db.execute(delete(Anomaly))
        anomalies_created = 0

        for (provider, scope, scope_key), group in analysis_frame.groupby(["provider", "scope", "scope_key"]):
            if len(group) < 7:
                continue
            ordered = group.sort_values("usage_date").copy()
            ordered["rolling_mean_3"] = ordered["cost_amount"].rolling(window=3, min_periods=1).mean()
            ordered["rolling_mean_7"] = ordered["cost_amount"].rolling(window=7, min_periods=1).mean()
            ordered["rolling_std_7"] = (
                ordered["cost_amount"].rolling(window=7, min_periods=3).std().fillna(0.0)
            )
            ordered["pct_change"] = ordered["cost_amount"].pct_change().replace([float("inf"), -float("inf")], 0.0).fillna(0.0)
            ordered["deviation_pct"] = (
                (ordered["cost_amount"] - ordered["rolling_mean_7"]) / ordered["rolling_mean_7"].replace(0, 0.01)
            ).fillna(0.0)
            ordered["day_of_week"] = pd.to_datetime(ordered["usage_date"]).dt.dayofweek
            ordered["z_score"] = ordered.apply(self._z_score, axis=1)

            features = ordered[
                ["cost_amount", "rolling_mean_3", "rolling_mean_7", "pct_change", "deviation_pct", "day_of_week"]
            ]
            contamination = 0.15 if len(ordered) < 20 else 0.08
            model = IsolationForest(random_state=42, contamination=contamination)
            model.fit(features)
            predictions = model.predict(features)
            normalized_scores = self._normalize(model.decision_function(features))
            threshold = (
                self.settings.aws_cost_anomaly_threshold
                if provider == "aws"
                else self.settings.gcp_cost_anomaly_threshold
            )

            enriched = ordered.assign(score=normalized_scores, prediction=predictions)
            for _, row in enriched.iterrows():
                expected_cost = float(row["rolling_mean_7"])
                observed_cost = float(row["cost_amount"])
                positive_spike = observed_cost > max(expected_cost * 1.35, expected_cost + 1.0)
                model_flag = row["prediction"] == -1 and row["score"] >= threshold
                zscore_flag = row["z_score"] >= 2.5 and positive_spike
                if not (model_flag or zscore_flag):
                    continue
                if not positive_spike and row["z_score"] < 3.0:
                    continue
                self.db.add(
                    Anomaly(
                        provider=provider,
                        scope=scope,
                        scope_key=scope_key,
                        usage_date=str(row["usage_date"]),
                        observed_cost=observed_cost,
                        expected_cost=expected_cost,
                        anomaly_score=max(float(row["score"]), min(float(row["z_score"]) / 5.0, 1.0)),
                        metadata_json={
                            "delta": round(observed_cost - expected_cost, 2),
                            "delta_pct": round(((observed_cost - expected_cost) / max(expected_cost, 0.01)) * 100, 2),
                            "z_score": round(float(row["z_score"]), 2),
                            "pct_change": round(float(row["pct_change"]) * 100, 2),
                            "model_flag": bool(model_flag),
                            "zscore_flag": bool(zscore_flag),
                        },
                    )
                )
                anomalies_created += 1

        self.db.commit()
        return anomalies_created

    @staticmethod
    def _build_analysis_frame(frame: pd.DataFrame) -> pd.DataFrame:
        service_scope = (
            frame.groupby(["provider", "service", "usage_date"], as_index=False)["cost_amount"].sum()
            .assign(scope="service")
            .rename(columns={"service": "scope_key"})
        )
        provider_scope = (
            frame.groupby(["provider", "usage_date"], as_index=False)["cost_amount"].sum()
            .assign(scope="provider")
            .assign(scope_key=lambda df: df["provider"] + ":all-services")
        )
        return pd.concat([service_scope[["provider", "scope", "scope_key", "usage_date", "cost_amount"]], provider_scope], ignore_index=True)

    @staticmethod
    def _normalize(scores: pd.Series) -> list[float]:
        series = pd.Series(scores)
        span = series.max() - series.min()
        if span == 0:
            return [0.0 for _ in series]
        normalized = 1 - ((series - series.min()) / span)
        return normalized.tolist()

    @staticmethod
    def _z_score(row: pd.Series) -> float:
        std = float(row["rolling_std_7"])
        if std <= 0:
            return 0.0
        return max((float(row["cost_amount"]) - float(row["rolling_mean_7"])) / std, 0.0)
