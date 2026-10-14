"""Feature construction for the planted leaky scenario."""


def add_lag(df):
    df["lag"] = df["actual"].shift(-1)
    return df
