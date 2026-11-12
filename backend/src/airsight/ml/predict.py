"""Correct live sensor readings with a trained model.

Serving goes through the same add_features as training, so a feature can never be computed
one way for the model's lessons and another way for its answers.
"""

import lightgbm as lgb
import pandas as pd

from airsight.ml.features import add_features


def correct(booster: lgb.Booster, rows: pd.DataFrame) -> pd.Series:
    """Corrected PM2.5 (µg/m³) for rows holding the stored INPUT_COLUMNS of each sensor-hour."""
    # The columns this model was trained on, in its order: a model trained before a change to
    # FEATURE_COLUMNS (such as v1, which uses sensor_humidity) still gets exactly its inputs
    features = add_features(rows)[booster.feature_name()]
    return pd.Series(booster.predict(features), index=rows.index, name="corrected")
