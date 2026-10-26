"""Building blocks registered by name."""

from diag.blocks import (
    code_call,
    code_import,
    config_key,
    fact_pattern,
    lineage_lookup,
    log_stats,
    phrase_search,
    sql_pattern,
    table_extract,
)

BLOCKS = {
    "phrase_search": phrase_search.run,
    "fact_pattern": fact_pattern.run,
    "config_key": config_key.run,
    "code_call": code_call.run,
    "code_import": code_import.run,
    "sql_pattern": sql_pattern.run,
    "log_stats": log_stats.run,
    "lineage_lookup": lineage_lookup.run,
    "table_extract": table_extract.run,
}
