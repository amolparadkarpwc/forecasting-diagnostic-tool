"""Healthy forecasting model. Parsed only; never executed."""

import mlflow
from sklearn.model_selection import TimeSeriesSplit


def seasonal_naive(history, season):
    if len(history) < season:
        return history[-1]
    return history[-season]


def run_backtest(series):
    mlflow.start_run()
    splitter = TimeSeriesSplit(n_splits=3)
    return seasonal_naive(series, 12), splitter
