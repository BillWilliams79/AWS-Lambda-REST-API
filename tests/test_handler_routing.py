"""
Handler routing tests for Lambda-Rest.

Tests the handler.py entry point: path parsing, HTTP method dispatch, and edge cases.
Covers OPTIONS handling, invalid databases, missing paths, None body handling, etc.
"""
import json
import pytest

from handler import lambda_handler


class TestHandlerRouting:
    """Tests for handler.py entry point and routing logic."""

    # -----------------------------------------------------------------------
    # HANDLER-01: OPTIONS returns 200
    # -----------------------------------------------------------------------

    def test_handler_options_returns_200(self, invoke):
        """HANDLER-01: OPTIONS request returns 200 with empty body."""
        response = invoke('OPTIONS', '/darwin_dev/areas')
        assert response['statusCode'] == 200

    # -----------------------------------------------------------------------
    # HANDLER-02: No path returns 400
    # -----------------------------------------------------------------------

    def test_handler_no_path_returns_400(self):
        """HANDLER-02: Missing path parameter returns 400."""
        event = {
            'httpMethod': 'GET',
            'path': None,
            'queryStringParameters': {},
            'body': '{}',
        }
        response = lambda_handler(event, {})
        assert response['statusCode'] == 400

    # -----------------------------------------------------------------------
    # HANDLER-03: Invalid database returns 404
    # -----------------------------------------------------------------------

    def test_handler_invalid_database_returns_404(self, invoke):
        """HANDLER-03: Request to non-configured database returns 404."""
        response = invoke('GET', '/nonexistent_db/sometable')
        assert response['statusCode'] == 404
        # Verify error message contains 'URL/path not found'
        body = json.loads(response['body'])
        assert 'URL/path not found' in str(body)

    # -----------------------------------------------------------------------
    # HANDLER-04: Substring db match correctly returns 404
    # -----------------------------------------------------------------------

    def test_handler_substring_match_returns_404(self):
        """HANDLER-04: db_names is a set; substring match should fail (e.g., '/dar' vs 'darwin_dev').

        db_dict bug would have allowed '/dar' to match 'darwin_dev' via string containment.
        Now that it's a set, only exact matches work.
        """
        event = {
            'httpMethod': 'GET',
            'path': '/dar/areas',
            'queryStringParameters': None,
            'body': None,
        }
        response = lambda_handler(event, {})
        assert response['statusCode'] == 404

    # -----------------------------------------------------------------------
    # HANDLER-05: None body on POST returns 400
    # -----------------------------------------------------------------------

    def test_handler_none_body_post_returns_400(self):
        """HANDLER-05: POST with None body should return 400.

        POST requires a JSON body to extract fields for insertion.
        """
        event = {
            'httpMethod': 'POST',
            'path': '/darwin_dev/areas',
            'queryStringParameters': None,
            'body': None,
        }
        response = lambda_handler(event, {})
        assert response['statusCode'] == 400

    # -----------------------------------------------------------------------
    # HANDLER-06: None body on PUT returns 400
    # -----------------------------------------------------------------------

    def test_handler_none_body_put_returns_400(self):
        """HANDLER-06: PUT with None body should return 400.

        PUT requires a JSON array body with id fields for updating.
        """
        event = {
            'httpMethod': 'PUT',
            'path': '/darwin_dev/areas',
            'queryStringParameters': None,
            'body': None,
        }
        response = lambda_handler(event, {})
        assert response['statusCode'] == 400

    # -----------------------------------------------------------------------
    # HANDLER-07: None body on DELETE returns 400
    # -----------------------------------------------------------------------

    def test_handler_none_body_delete_returns_400(self):
        """HANDLER-07: DELETE with None body should return 400.

        DELETE requires a JSON body with WHERE condition fields.
        """
        event = {
            'httpMethod': 'DELETE',
            'path': '/darwin_dev/areas',
            'queryStringParameters': None,
            'body': None,
        }
        response = lambda_handler(event, {})
        assert response['statusCode'] == 400

    # -----------------------------------------------------------------------
    # HANDLER-08: None body on GET succeeds
    # -----------------------------------------------------------------------

    def test_handler_none_body_get_succeeds(self):
        """HANDLER-08: GET with None body should succeed (body not used for GET).

        GET can work with None body since the request uses queryStringParameters.
        This tests GET /darwin_dev (no table, returns list of tables).
        """
        event = {
            'httpMethod': 'GET',
            'path': '/darwin_dev',
            'queryStringParameters': None,
            'body': None,
        }
        response = lambda_handler(event, {})
        # GET /darwin_dev should return 200 with list of tables
        assert response['statusCode'] == 200
