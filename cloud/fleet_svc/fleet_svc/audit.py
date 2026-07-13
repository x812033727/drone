"""fleet-svc 審計進入點(schema=`fleet`,寫入 fleet.audit_log)。實作在
drone_common.audit(Wave 1 A1 去重)。保留 record(...) / actor_of(...) 呼叫介面不變。
"""

from __future__ import annotations

from functools import partial

from drone_common.audit import actor_of, make_insert
from drone_common.audit import record as _record

__all__ = ["actor_of", "record"]

# schema 綁定到本服務;呼叫端 `audit.record(conn, claims=..., action=...)` 不變。
record = partial(_record, insert_sql=make_insert("fleet"))
