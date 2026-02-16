"""
Unit tests for compose_rest_response() — no database required.

These tests verify the Lambda proxy response builder in rest_api_utils.py.
The function is pure: no DB calls, no env vars, no side effects.

Run: pytest tests/test_unit_response.py -v
"""
import json
import sys
import os

import pytest

# Add Lambda-Rest root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from rest_api_utils import compose_rest_response


pytestmark = pytest.mark.unit


class TestComposeRestResponse:
    """Tests for compose_rest_response() response builder."""

    def test_success_200_with_list_body(self):
        """200 response serializes list body as JSON string."""
        response = compose_rest_response(200, [{'id': 1, 'name': 'test'}])
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert isinstance(body, list)
        assert body[0]['id'] == 1

    def test_success_201_with_list_body(self):
        """201 response preserves body (not replaced by error message)."""
        response = compose_rest_response(201, [{'id': 42}])
        assert response['statusCode'] == 201
        body = json.loads(response['body'])
        assert body[0]['id'] == 42

    def test_success_204_empty_body(self):
        """204 response with empty string body."""
        response = compose_rest_response(204, '')
        assert response['statusCode'] == 204
        # Empty string is serialized as '""'
        assert response['body'] == '""'

    def test_error_400_replaces_body_with_message(self):
        """Error status codes replace body with http_message."""
        response = compose_rest_response(400, 'original body', 'Bad request')
        assert response['statusCode'] == 400
        # Body should be the message, not the original body
        body = json.loads(response['body'])
        assert body == 'Bad request'

    def test_error_500_replaces_body_with_message(self):
        """500 error replaces body with http_message."""
        response = compose_rest_response(500, 'ignored', 'Internal server error')
        body = json.loads(response['body'])
        assert body == 'Internal server error'

    def test_none_body_excluded(self):
        """None body results in no 'body' key in response."""
        response = compose_rest_response(200, None)
        # When body is None, the key is not added
        assert 'body' not in response

    def test_empty_string_body(self):
        """Empty string body is JSON-serialized as '""'."""
        response = compose_rest_response(200, '')
        assert response['body'] == '""'

    def test_cors_headers_present(self):
        """Response includes all required CORS headers."""
        response = compose_rest_response(200, '')
        headers = response['headers']
        assert headers['Access-Control-Allow-Origin'] == '*'
        assert 'PUT' in headers['Access-Control-Allow-Methods']
        assert 'GET' in headers['Access-Control-Allow-Methods']
        assert 'POST' in headers['Access-Control-Allow-Methods']
        assert 'DELETE' in headers['Access-Control-Allow-Methods']
        assert 'OPTIONS' in headers['Access-Control-Allow-Methods']
        assert headers['Content-Type'] == 'application/json'

    def test_is_base64_encoded_is_boolean(self):
        """isBase64Encoded must be boolean False, not string 'false'."""
        response = compose_rest_response(200, '')
        assert response['isBase64Encoded'] is False
        assert type(response['isBase64Encoded']) is bool

    def test_status_code_is_int(self):
        """statusCode in response must be int type (not string)."""
        response = compose_rest_response(200, '')
        assert type(response['statusCode']) is int

    def test_error_404_replaces_body(self):
        """404 error replaces body with http_message."""
        response = compose_rest_response(404, 'original', 'Not found')
        body = json.loads(response['body'])
        assert body == 'Not found'

    def test_body_single_encoded(self):
        """Response body is single-encoded JSON (not double-encoded)."""
        data = [{'id': 1, 'name': 'test'}]
        response = compose_rest_response(200, data)
        # First json.loads should give us the Python object
        parsed = json.loads(response['body'])
        assert isinstance(parsed, list)
        # It should NOT be a string that needs another json.loads
        assert not isinstance(parsed, str)
