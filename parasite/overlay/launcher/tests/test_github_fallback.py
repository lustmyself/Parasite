import unittest
from unittest.mock import MagicMock, patch

import requests

from launcher.update import github_client
from launcher.update.github_client import GitHubClient

PACKAGE_URL = "https://github.com/lustmyself/Parasite/releases/download/v1.5.3.1/update_package_1.5.3.1.zip"


def _redirect(location, code=302):
    response = MagicMock(status_code=code)
    response.headers = {"Location": location}
    return response


def _head(code=200, length="1234"):
    response = MagicMock(status_code=code)
    response.headers = {"Content-Length": length}
    return response


class GitHubFallbackTests(unittest.TestCase):
    def setUp(self):
        allowed = patch.object(github_client.github_rate_limit, "api_allowed", return_value=True)
        allowed.start()
        self.addCleanup(allowed.stop)

    def test_the_redirect_names_the_package_without_the_v(self):
        redirect = _redirect("https://github.com/lustmyself/Parasite/releases/tag/v1.5.3.1")
        with patch.object(github_client.requests, "get", return_value=redirect), \
                patch.object(github_client.requests, "head", return_value=_head()) as head:
            release = GitHubClient().get_latest_release()
        client = GitHubClient()
        self.assertEqual(client.get_release_version(release), "v1.5.3.1")
        self.assertEqual(client.get_zip_asset(release)["browser_download_url"], PACKAGE_URL)
        self.assertEqual(head.call_args.args[0], PACKAGE_URL)

    def test_api_limit_falls_back_to_github_com(self):
        no_redirect = _redirect("", 200)
        limited = MagicMock()
        limited.raise_for_status.side_effect = requests.HTTPError("403 rate limit exceeded")
        redirect = _redirect("https://github.com/lustmyself/Parasite/releases/tag/v1.5.3.1")
        with patch.object(github_client.requests, "get", side_effect=[no_redirect, limited, redirect]):
            release = GitHubClient().get_latest_release()
        client = GitHubClient()
        self.assertEqual(client.get_release_version(release), "v1.5.3.1")
        self.assertEqual(client.get_zip_asset(release)["browser_download_url"], PACKAGE_URL)

    def test_no_release_when_github_com_gives_no_tag(self):
        limited = MagicMock()
        limited.raise_for_status.side_effect = requests.HTTPError("403")
        with patch.object(github_client.requests, "get",
                          side_effect=[_redirect("", 200), limited, _redirect("https://github.com/login", 302)]):
            self.assertIsNone(GitHubClient().get_latest_release())
        with patch.object(github_client.requests, "get",
                          side_effect=[_redirect("", 200), limited, _redirect("", 200)]):
            self.assertIsNone(GitHubClient().get_latest_release())


if __name__ == "__main__":
    unittest.main()
