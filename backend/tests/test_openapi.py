import json

from airsight.api.openapi import SCHEMA_PATH, current_schema
from airsight.api.problems import PROBLEM_JSON


def test_committed_contract_matches_the_code() -> None:
    committed = json.loads(SCHEMA_PATH.read_text())

    assert current_schema() == committed, (
        "The API changed but docs/openapi.json did not. If the change is on purpose, run "
        "`uv run python -m airsight.api.openapi` in backend/ and commit the file. "
        "Within /v1 changes must be additive (ADR 0008)."
    )


def test_every_error_is_documented_as_problem_details() -> None:
    schema = current_schema()

    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            errors = {code: r for code, r in operation["responses"].items() if code >= "400"}
            expected = {"500"} if path == "/v1/health" else {"422", "429", "500"}
            assert expected <= errors.keys(), f"{method} {path}"
            for code, response in errors.items():
                assert list(response["content"]) == [PROBLEM_JSON], f"{method} {path} {code}"
    assert "HTTPValidationError" not in schema["components"]["schemas"]


def test_every_endpoint_in_adr_0008_exists() -> None:
    paths = set(current_schema()["paths"])

    assert paths == {
        "/v1/health",
        "/v1/sensors",
        "/v1/sensors/{sensor_id}",
        "/v1/sensors/{sensor_id}/history",
        "/v1/readings/nearest",
        "/v1/model",
        "/v1/accuracy",
    }
