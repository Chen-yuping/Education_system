"""Compatibility for legacy CDF adapters on pandas versions without _append."""

import pandas as pd


def ensure_pandas_append():
    if hasattr(pd.DataFrame, '_append'):
        return

    def _append(self, other, ignore_index=False, **kwargs):
        return pd.concat([self, other], ignore_index=ignore_index, **kwargs)

    pd.DataFrame._append = _append
