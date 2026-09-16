from google.genai import errors

from app import llm


def client_error(code, quota_id=None):
    details = [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                "violations": [{"quotaId": quota_id}]}] if quota_id else []
    return errors.ClientError(code, {"error": {"code": code, "message": "x", "status": "S", "details": details}})


def test_daily_quota_is_not_retried_but_falls_back():
    exc = client_error(429, "GenerateRequestsPerDayPerProjectPerModel-FreeTier")
    assert llm.is_daily_quota(exc)
    assert llm.is_transient(exc)            # try another model
    assert not llm._worth_retrying(exc)     # but don't hammer this one


def test_per_minute_limit_and_overload_are_retried():
    assert llm._worth_retrying(client_error(429, "GenerateRequestsPerMinutePerProjectPerModel"))
    assert llm._worth_retrying(errors.ServerError(503, {"error": {"code": 503, "message": "busy", "status": "UNAVAILABLE"}}))


def test_bad_request_is_not_transient():
    assert not llm.is_transient(client_error(400))
