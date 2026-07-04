from typing import Any, Dict, Optional


def extract_ws_auth_token(query_params: Optional[Dict[str, Any]], headers: Optional[Dict[str, Any]] = None) -> Optional[str]:
    if query_params:
        for key in ("token", "auth_token", "session_token"):
            value = query_params.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    if headers:
        authorization = headers.get("authorization") or headers.get("Authorization")
        if isinstance(authorization, str) and authorization.strip():
            candidate = authorization.strip()
            if candidate.lower().startswith("bearer "):
                candidate = candidate[7:].strip()
            if candidate:
                return candidate

    return None


def is_ws_request_authorized(query_params: Optional[Dict[str, Any]], expected_token: Optional[str], headers: Optional[Dict[str, Any]] = None) -> bool:
    if not expected_token:
        return True

    provided_token = extract_ws_auth_token(query_params, headers)
    return provided_token == expected_token
