def make_target(df):
    y = df["actual"].shift(-1)
    return y
