"""Masked client feature code."""


def add_lag(df):
    df["lag"] = df["actual"].shift(-1)  # AcmeCorp
    return df
