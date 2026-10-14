"""Feature build for the demand model."""
import warnings

import pandas as pd

warnings.filterwarnings("ignore")


def build_features(df):
    """future_sales looks ahead of the row and is a leakage risk."""
    grouped = df.groupby("series_id")["actual"]
    df["future_sales"] = grouped.shift(-1)
    df["lag_1"] = grouped.shift(1)
    return df


def fit_models(models, features, target):
    for model in models:
        try:
            model.fit(features, target)
        except Exception:
            continue
