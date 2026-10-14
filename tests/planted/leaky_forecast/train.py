"""Training entrypoint for the planted leaky scenario."""

import warnings

warnings.filterwarnings("ignore")


def fit_all(items):
    for item in items:
        try:
            fit_one(item)
        except:
            continue


def fit_one(item):
    return item
