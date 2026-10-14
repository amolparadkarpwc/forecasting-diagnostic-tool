"""Building blocks registered by name."""

from diag.blocks import code_call, config_key, fact_pattern, log_stats, phrase_search, sql_pattern

BLOCKS = {
    "phrase_search": phrase_search.run,
    "fact_pattern": fact_pattern.run,
    "config_key": config_key.run,
    "code_call": code_call.run,
    "sql_pattern": sql_pattern.run,
    "log_stats": log_stats.run,
}
