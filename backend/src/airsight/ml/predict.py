"""Correct live sensor readings with a trained model.

Serving goes through the same add_features as training, so a feature can never be computed
one way for the model's lessons and another way for its answers.
"""

import lightgbm as lgb
import pandas as pd

from airsight.ml.features import FEATURE_COLUMNS, add_features


def correct(booster: lgb.Booster, rows: pd.DataFrame) -> pd.Series:
    """Corrected PM2.5 (µg/m³) for rows holding the stored INPUT_COLUMNS of each sensor-hour."""
    features = add_features(rows)[FEATURE_COLUMNS]
    return pd.Series(booster.predict(features), index=rows.index, name="corrected")
