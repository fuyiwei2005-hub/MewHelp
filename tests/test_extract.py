import pytest
from fastapi.testclient import TestClient


def client_for(result=None, error=None):
    from app.config import Settings
    from app.main import create_app
    from app.schemas import AfterSales
    class Gateway:
        async def extract(self, description):
            if error:
                raise error
            return result or AfterSales(order_id=None, request_type="退款", expected_solution="退款")
    return TestClient(create_app(Settings(_env_file=None, llm_api_key="test", llm_model="fake"), Gateway()))


@pytest.mark.parametrize("payload", [{}, {"description": ""}, {"description": "   "}, {"description": 123}, {"description": "hi", "tools": []}])
def test_rejects_invalid_description(payload):
    with client_for() as client:
        assert client.post("/after-sales/extract", json=payload).status_code == 422


def test_returns_fixed_json_fields_without_chat_history():
    with client_for() as client:
        response = client.post("/after-sales/extract", json={"description": "想退款"})
        assert response.status_code == 200
        assert response.json() == {"order_id": None, "request_type": "退款", "expected_solution": "退款"}
        assert client.app.state.store._sessions == {}


def test_extract_rejects_input_over_budget():
    with client_for() as client:
        assert client.post("/after-sales/extract", json={"description": "中"*4000}).status_code == 413


@pytest.mark.parametrize("timeout", [False, True])
def test_upstream_failure_mapping(timeout):
    from app.gateway import UpstreamError, UpstreamTimeout
    error = UpstreamTimeout() if timeout else UpstreamError()
    with client_for(error=error) as client:
        response = client.post("/after-sales/extract", json={"description": "退款"})
        assert response.status_code == (504 if timeout else 502)
        assert response.json()["detail"]["code"] == error.code

