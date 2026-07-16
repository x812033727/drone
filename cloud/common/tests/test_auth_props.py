"""drone_common.auth 純函式屬性測試(hypothesis;derandomize 確保決定性)。"""

from __future__ import annotations

from drone_common.auth import (
    ROLE_ORDER,
    build_principal,
    extract_org,
    extract_roles,
    highest_role,
    read_org,
    role_rank,
)
from hypothesis import given, settings
from hypothesis import strategies as st

# 決定性設定:auto-merge 不容 flaky
settings.register_profile("ci", derandomize=True, max_examples=200)
settings.load_profile("ci")

# 任意 JSON-ish claims(含蓄意奇形怪狀的值)
_json_scalars = st.one_of(
    st.none(), st.booleans(), st.integers(), st.floats(allow_nan=False), st.text()
)
claims_st = st.dictionaries(
    st.text(min_size=0, max_size=12),
    st.one_of(
        _json_scalars,
        st.lists(_json_scalars, max_size=4),
        st.dictionaries(st.text(max_size=8), st.lists(_json_scalars, max_size=3), max_size=3),
    ),
    max_size=8,
)


@given(claims_st)
def test_extract_roles_never_raises_and_only_known(claims):
    roles = extract_roles(claims)
    assert roles <= set(ROLE_ORDER)


@given(claims_st)
def test_role_rank_bounds(claims):
    rank = role_rank(extract_roles(claims))
    assert -1 <= rank <= 2


@given(claims_st)
def test_highest_role_consistent_with_rank(claims):
    roles = extract_roles(claims)
    top = highest_role(claims)
    if role_rank(roles) == -1:
        assert top is None
    else:
        assert top in roles
        assert ROLE_ORDER[top] == role_rank(roles)


@given(claims_st)
def test_extract_org_str_or_none(claims):
    org = extract_org(claims)
    assert org is None or (isinstance(org, str) and org)


@given(claims_st)
def test_principal_read_org_symmetry(claims):
    """admin 讀取不限 org(None);非 admin 恆有具體 org 字串。"""
    principal = build_principal(claims)
    scope = read_org(principal)
    if principal.is_admin:
        assert scope is None
    else:
        assert isinstance(scope, str) and scope


@given(st.sampled_from(["role", "roles"]), st.text())
def test_unknown_role_strings_ignored(key, value):
    claims = {key: value if key == "role" else [value]}
    roles = extract_roles(claims)
    assert roles <= set(ROLE_ORDER)
