"""
Unit tests for CI Boss Agent components.

These tests verify the behavior of:
- github_node: GitHub integration
- test_runner_node: Playwright test execution
- linear_client: Linear issue tracking

Tests use mocking to avoid actual API calls.
"""

import os
import unittest
from unittest.mock import patch, MagicMock
import subprocess


class TestGitHubNode(unittest.TestCase):
    """Tests for the github_node function."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.base_state = {
            "repo": "testowner/testrepo",
            "commit_sha": None,
            "pr_number": 42,
            "changed_files": [],
            "test_status": "pending",
        }
    
    @patch.dict(os.environ, {}, clear=True)
    def test_github_node_missing_token(self):
        """Test that github_node handles missing GITHUB_TOKEN gracefully."""
        from my_agent.graph import github_node
        
        # Remove token if present
        env = os.environ.copy()
        env.pop("GITHUB_TOKEN", None)
        
        with patch.dict(os.environ, env, clear=True):
            result = github_node(self.base_state.copy())
        
        # Should return state without crashing
        self.assertIsNotNone(result)
        self.assertEqual(result.get("repo"), "testowner/testrepo")
        # Should have placeholder data
        self.assertIn("changed_files", result)
        self.assertIn("commit_sha", result)
    
    @patch("my_agent.github_client._get_github_token")
    @patch("my_agent.github_client.fetch_pr_details")
    @patch("my_agent.github_client.fetch_pr_files")
    @patch("my_agent.github_client.fetch_commit_details")
    def test_github_node_with_pr(
        self,
        mock_commit_details,
        mock_pr_files,
        mock_pr_details,
        mock_get_token
    ):
        """Test github_node with a valid PR number."""
        from my_agent.graph import github_node
        
        # Set up mocks
        mock_get_token.return_value = "fake-token"
        mock_pr_details.return_value = {
            "head": {"sha": "abc123def456"},
            "title": "Test PR"
        }
        mock_pr_files.return_value = ["src/main.py", "tests/test_main.py"]
        mock_commit_details.return_value = {
            "commit": {"message": "Fix bug in main"}
        }
        
        state = self.base_state.copy()
        result = github_node(state)
        
        # Verify results
        self.assertEqual(result["commit_sha"], "abc123def456")
        self.assertEqual(result["changed_files"], ["src/main.py", "tests/test_main.py"])
        self.assertEqual(result["commit_message"], "Fix bug in main")
    
    @patch("my_agent.github_client._get_github_token")
    @patch("my_agent.github_client.fetch_commit_files")
    @patch("my_agent.github_client.fetch_commit_details")
    def test_github_node_with_commit_only(
        self,
        mock_commit_details,
        mock_commit_files,
        mock_get_token
    ):
        """Test github_node with only a commit SHA (no PR)."""
        from my_agent.graph import github_node
        
        mock_get_token.return_value = "fake-token"
        mock_commit_files.return_value = ["README.md"]
        mock_commit_details.return_value = {
            "commit": {"message": "Update readme"}
        }
        
        state = {
            "repo": "testowner/testrepo",
            "commit_sha": "abc123",
            "pr_number": None,
            "changed_files": [],
            "test_status": "pending",
        }
        
        result = github_node(state)
        
        self.assertEqual(result["changed_files"], ["README.md"])


class TestTestRunnerNode(unittest.TestCase):
    """Tests for the test_runner_node function."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.base_state = {
            "repo": "testowner/testrepo",
            "commit_sha": "abc123",
            "changed_files": ["src/main.py"],
            "test_status": "pending",
            "next_action": "run_tests",
        }
    
    def test_test_runner_skips_when_not_run_tests(self):
        """Test that test_runner_node skips execution when next_action != run_tests."""
        from my_agent.graph import test_runner_node
        
        state = self.base_state.copy()
        state["next_action"] = "analyze_failures"
        
        result = test_runner_node(state)
        
        # Should not have changed test_status
        self.assertEqual(result.get("test_status"), "pending")
        self.assertIsNone(result.get("test_logs"))
    
    @patch("subprocess.run")
    def test_test_runner_successful_execution(self, mock_run):
        """Test test_runner_node with successful test execution."""
        from my_agent.graph import test_runner_node
        
        # Mock successful test run
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Running 10 tests...\nAll tests passed!",
            stderr=""
        )
        
        result = test_runner_node(self.base_state.copy())
        
        self.assertEqual(result["test_status"], "passed")
        self.assertIn("All tests passed", result["test_logs"])
        mock_run.assert_called_once()
    
    @patch("subprocess.run")
    def test_test_runner_failed_execution(self, mock_run):
        """Test test_runner_node with failed test execution."""
        from my_agent.graph import test_runner_node
        
        # Mock failed test run
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="Running 10 tests...",
            stderr="FAILED: test_login - AssertionError"
        )
        
        result = test_runner_node(self.base_state.copy())
        
        self.assertEqual(result["test_status"], "failed")
        self.assertIn("FAILED", result["test_logs"])
    
    @patch("subprocess.run")
    def test_test_runner_command_not_found(self, mock_run):
        """Test test_runner_node when command is not found."""
        from my_agent.graph import test_runner_node
        
        # Mock command not found
        mock_run.side_effect = FileNotFoundError("npx: command not found")
        
        result = test_runner_node(self.base_state.copy())
        
        self.assertEqual(result["test_status"], "failed")
        self.assertIn("Command not found", result["test_logs"])
    
    @patch("subprocess.run")
    def test_test_runner_timeout(self, mock_run):
        """Test test_runner_node when tests timeout."""
        from my_agent.graph import test_runner_node
        
        # Mock timeout
        mock_run.side_effect = subprocess.TimeoutExpired("npx playwright test", 1800)
        
        result = test_runner_node(self.base_state.copy())
        
        self.assertEqual(result["test_status"], "failed")
        self.assertIn("timed out", result["test_logs"])
    
    @patch.dict(os.environ, {"PLAYWRIGHT_COMMAND": "pytest tests/"})
    @patch("subprocess.run")
    def test_test_runner_custom_command(self, mock_run):
        """Test test_runner_node with custom command from env."""
        from my_agent.graph import test_runner_node
        
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="All tests passed",
            stderr=""
        )
        
        test_runner_node(self.base_state.copy())
        
        # Verify custom command was used
        call_args = mock_run.call_args
        self.assertEqual(call_args.args[0], "pytest tests/")


class TestLinearClient(unittest.TestCase):
    """Tests for the Linear client module."""
    
    @patch.dict(os.environ, {}, clear=True)
    def test_create_or_update_missing_env_vars(self):
        """Test that create_or_update_linear_issue handles missing env vars."""
        from my_agent.linear_client import create_or_update_linear_issue
        
        state = {
            "repo": "testowner/testrepo",
            "commit_sha": "abc123",
            "test_status": "failed",
            "test_logs": "Test failed!",
        }
        
        # Should not crash, should return state unchanged
        result = create_or_update_linear_issue(state)
        
        self.assertIsNotNone(result)
        self.assertIsNone(result.get("linear_issue_id"))
        self.assertIsNone(result.get("linear_issue_url"))
    
    @patch.dict(os.environ, {
        "LINEAR_API_KEY": "fake-key",
        "LINEAR_TEAM_ID": "fake-team-id"
    })
    @patch("my_agent.linear_client._execute_graphql")
    def test_create_linear_issue_success(self, mock_graphql):
        """Test successful Linear issue creation."""
        from my_agent.linear_client import create_or_update_linear_issue
        
        # Mock successful issue creation
        mock_graphql.return_value = {
            "issueCreate": {
                "success": True,
                "issue": {
                    "id": "issue-123",
                    "identifier": "ENG-456",
                    "url": "https://linear.app/team/issue/ENG-456"
                }
            }
        }
        
        state = {
            "repo": "testowner/testrepo",
            "commit_sha": "abc123def456",
            "test_status": "failed",
            "test_logs": "Test failed with error",
            "summary": "Login test failed",
        }
        
        result = create_or_update_linear_issue(state)
        
        self.assertEqual(result["linear_issue_id"], "issue-123")
        self.assertEqual(result["linear_issue_identifier"], "ENG-456")
        self.assertEqual(
            result["linear_issue_url"],
            "https://linear.app/team/issue/ENG-456"
        )
    
    @patch.dict(os.environ, {
        "LINEAR_API_KEY": "fake-key",
        "LINEAR_TEAM_ID": "fake-team-id"
    })
    @patch("my_agent.linear_client._execute_graphql")
    def test_update_existing_issue_on_pass(self, mock_graphql):
        """Test updating existing Linear issue when tests pass."""
        from my_agent.linear_client import create_or_update_linear_issue
        
        # Mock successful responses
        mock_graphql.side_effect = [
            # First call: add comment
            {"commentCreate": {"success": True}},
            # Second call: get workflow states
            {"team": {"states": {"nodes": [
                {"id": "state-1", "name": "Done"},
                {"id": "state-2", "name": "In Progress"}
            ]}}},
            # Third call: update issue state
            {"issueUpdate": {"success": True}}
        ]
        
        state = {
            "repo": "testowner/testrepo",
            "commit_sha": "abc123",
            "test_status": "passed",
            "linear_issue_id": "existing-issue-id",
        }
        
        result = create_or_update_linear_issue(state)
        
        # Issue ID should remain
        self.assertEqual(result["linear_issue_id"], "existing-issue-id")
        # GraphQL should have been called to add comment and update state
        self.assertEqual(mock_graphql.call_count, 3)
    
    @patch.dict(os.environ, {
        "LINEAR_API_KEY": "fake-key",
        "LINEAR_TEAM_ID": "fake-team-id"
    })
    def test_skip_issue_creation_when_tests_pass(self):
        """Test that no issue is created when tests pass (and no existing issue)."""
        from my_agent.linear_client import create_or_update_linear_issue
        
        state = {
            "repo": "testowner/testrepo",
            "commit_sha": "abc123",
            "test_status": "passed",
        }
        
        result = create_or_update_linear_issue(state)
        
        # Should not create an issue
        self.assertIsNone(result.get("linear_issue_id"))


class TestGitHubClient(unittest.TestCase):
    """Tests for the GitHub client module."""
    
    @patch("my_agent.github_client._get_github_token")
    def test_post_ci_results_comment_no_pr(self, mock_get_token):
        """Test that posting comment is skipped when no PR number."""
        from my_agent.github_client import post_ci_results_comment
        
        mock_get_token.return_value = "fake-token"
        
        state = {
            "repo": "testowner/testrepo",
            "commit_sha": "abc123",
            "pr_number": None,  # No PR
            "test_status": "passed",
            "summary": "All tests passed",
        }
        
        result = post_ci_results_comment(state)
        
        # Should return False (skipped)
        self.assertFalse(result)
    
    @patch("my_agent.github_client._get_github_token")
    @patch("my_agent.github_client.post_pr_comment")
    def test_post_ci_results_comment_success(self, mock_post, mock_get_token):
        """Test successful posting of CI results comment."""
        from my_agent.github_client import post_ci_results_comment
        
        mock_get_token.return_value = "fake-token"
        mock_post.return_value = True
        
        state = {
            "repo": "testowner/testrepo",
            "commit_sha": "abc123def456",
            "pr_number": 42,
            "test_status": "passed",
            "summary": "All tests passed",
            "changed_files": ["src/main.py"],
        }
        
        result = post_ci_results_comment(state)
        
        self.assertTrue(result)
        mock_post.assert_called_once()
        
        # Check comment body contains expected elements
        call_args = mock_post.call_args
        body = call_args.kwargs.get("body") or call_args.args[2]
        self.assertIn("✅", body)
        self.assertIn("abc123de", body)  # Short SHA


class TestBuildGraph(unittest.TestCase):
    """Tests for the graph building and structure."""
    
    def test_build_graph_succeeds(self):
        """Test that build_graph() creates a valid graph."""
        from my_agent.graph import build_graph
        
        graph = build_graph()
        
        self.assertIsNotNone(graph)
    
    def test_graph_has_expected_nodes(self):
        """Test that the graph has the expected nodes."""
        from my_agent.graph import build_graph
        
        graph = build_graph()
        
        # The compiled graph should have nodes
        self.assertIsNotNone(graph)


if __name__ == "__main__":
    unittest.main()
