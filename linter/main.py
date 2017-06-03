#!/usr/bin/env python
"""

"""
import tempfile

import requests

__author__ = "Bharat Patel"
import cherrypy
import json
import logging
import sys
from pylint import lint
from pylint.reporters.text import ParseableTextReporter
import yaml
import os.path

DEBUG_LEVEL = logging.DEBUG

logger = logging.getLogger('github-pr-python-linter')
logger.setLevel(DEBUG_LEVEL)
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(DEBUG_LEVEL)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
logger.addHandler(ch)

DEFAULT_CONFIG_FILE_PATH = "/config/.github-linter-config.yaml"
GITHUB_ACCESS_TOKEN = None


# https://stackoverflow.com/a/7919648/1592568
class WritableObject(object):
    def __init__(self):
        self.content = []

    def write(self, st):
        self.content.append(st)

    def read(self):
        return self.content


class GitHubPRLinterException(Exception):
    pass


class GithubPRLinter(object):
    def __init__(self, pr_json, add_comment_on_failure=True, access_token=None):

        super(GithubPRLinter, self).__init__()
        self._pr_json = pr_json
        self.pr_num = None
        self.pr_title = None
        self.files = []
        self.repo_url = None
        self.commit_sha = None
        self.__access_token = access_token
        self.add_comment_on_failure = add_comment_on_failure
        self.init(pr_json)

    def init(self, webhook_json):

        assert (isinstance(webhook_json, dict))

        if "hook" in webhook_json:
            # don't do anything. This is just for webhook installation
            return

        pull_request_details = webhook_json.get("pull_request")
        self.pr_num = pull_request_details.get("number")
        if not pull_request_details:
            raise GitHubPRLinterException("Invalid pull request.")
        state = pull_request_details.get("state")
        if state == "closed":
            # don't do antyhing
            logger.info("PR# %d is closed.", self.pr_num)
            return
        """
        Extract useful metadata from json which was submitted by webhook
        :return: 
        """

        self.repo_url = webhook_json.get("repository", {}).get("url")
        self.commit_sha = pull_request_details.get("head", {}).get("sha")
        logger.debug("Linter initialized: PR# = {}, REPO_URL={}, COMMIT_SHA={}".format(self.pr_num, self.repo_url,
                                                                                       self.commit_sha))
        self.validate()
        self.files = self.getFilesInCommit(commitSha=self.commit_sha)

    def validate(self):
        if not self.pr_num or not self.repo_url or not self.commit_sha:
            logger.exception(
                "Failed to validate PR deails. PR# = {}, REPO_URL={}, COMMIT_SHA={}".format(self.pr_num, self.repo_url,
                                                                                            self.commit_sha))
            raise GitHubPRLinterException("Invalid data provided for PR")

    def __get_authorization_headers(self):
        return {
            "Authorization": "Token {}".format(self.__access_token)
        }

    def getFilesInCommit(self, commitSha):
        files = []
        response = requests.get("{}/commits/{}".format(self.repo_url, commitSha),
                                headers=self.__get_authorization_headers())
        if response.status_code == 200:
            # successful
            response_json = response.json()
            if "files" in response_json:
                for file_info in response_json.get("files"):
                    if 'filename' in file_info and 'raw_url' in file_info:
                        files.append(file_info)
            logger.debug("Found {} files in commit for PR#".format(len(files), self.commit_sha, self.pr_num))
        else:
            logger.error("Gihub API call failed. Status=%d, Response=%s", response.status_code, response.text)
            raise GitHubPRLinterException("Github API Call failed with response code=%d", response.status_code)

        return files

    def run_checks(self):
        files_errors = {}
        for file_info in self.files:
            raw_url = file_info.get("raw_url")
            file_name = file_info.get("filename")
            logger.debug("Running check for file=%s", file_name)
            errors = self._check_file_content(file_name, raw_url)
            if errors:
                files_errors[file_name] = errors
        if len(files_errors) > 0:
            # atleast one file has error
            self._add_pr_review_comment(self._get_formatted_error_msg(files_errors))


    def _get_formatted_error_msg(self, files_errors):
        error_body = ["This comment was added by automated lint checker.", "Syntax Error found in one or more files. Details:"]

        for file_name, file_errors in files_errors.iteritems():
            error_body.append("- File: **{}**:".format(file_name))
            for err in file_errors:
                error_body.append("  - [ ] Line# {} ```{}```".format(err['line'], err['body']))

        return "\n".join(error_body)

    def _check_file_content(self, file_name, raw_url):
        file_errors = None
        if file_name.endswith(".py"):
            logger.info("Checking file contents for file: %s", file_name)
            response = requests.get(raw_url, headers=self.__get_authorization_headers())
            if response.status_code == 200:
                temp = tempfile.NamedTemporaryFile()
                try:
                    temp.write(response.text)
                    temp.seek(0)
                    errors = self._run_pylint(temp.name)
                    if errors:
                        file_errors = self._get_comments_for_errors(file_name, errors)
                    else:
                        logger.info("Syntax check passed for file:%s", file_name)
                finally:
                    temp.close()
            else:
                logger.error("Gihub API call failed. Status=%d, Response=%s", response.status_code, response.text)
        else:
            logger.info("Skipping running pylint for non-python file:%s", file_name)

        return file_errors

    def _get_comments_for_errors(self, file_path, errors):
        """
        Return github compatible commit comments
        Pyling error msg will be in format:
        line___column___message
        :param file_name: 
        :param errors: 
        :param type: 
        :return: 
        """
        file_errors = []
        if errors and len(errors) > 0:
            for pylint_out in errors:
                error_info = pylint_out.split("___")
                if len(error_info) == 3:
                    # we have line, column and error
                    file_errors.append({
                        "path": file_path,
                        "line": int(error_info[0]),
                        "body": error_info[2]
                    })

        return file_errors

    def _run_pylint(self, file_path):
        logger.debug("Running pylint on file:%s", file_path)
        errors = []
        try:
            pylint_output = WritableObject()
            lint.Run(['--errors-only', '--disable=print-statement',
                      '--msg-template="{line}___{column}___{msg}"', file_path],
                     reporter=ParseableTextReporter(pylint_output), exit=False)
            errors = pylint_output.read()
            logger.debug("Pylint Output=%s", errors)
        except Exception as e:
            logger.exception(e)
            logger.debug("Error executing pylint")

        return errors

    def _add_pr_review_comment(self, body):
        post_url = "{}/pulls/{}/reviews".format(self.repo_url, self.pr_num)
        post_data = {
            "commit_id": self.commit_sha,
            "body": body,
            "event": "REQUEST_CHANGES"
        }

        logger.debug("Adding PR comment: %s", post_data)
        response = requests.post(post_url, json=post_data, headers=self.__get_authorization_headers())
        if response.status_code == 200:
            logger.info("Succeffully added PR review comment for PR#%s", self.pr_num)
        else:
            logger.info("Failed to add PR review comment. Status Code=%d, Response:%s", response.status_code, response.text)

class GitHubWebHookHandler(object):
    def __init__(self, github_access_token=None):
        super(GitHubWebHookHandler, self).__init__()
        self.__access_token = github_access_token

    @cherrypy.expose
    @cherrypy.tools.json_in()
    def github_pr_handler(self):
        input_json = cherrypy.request.json
        linter = GithubPRLinter(input_json, access_token=self.__access_token)
        ret = "OK"
        try:
            linter.run_checks()
            cherrypy.response.headers["Status"] = "200"
        except:
            ret = "ERROR"
            cherrypy.response.headers["Status"] = "500"
            logger.exception("Failed to lint file.")
        return ret



def testRun(github_access_token=None):
    with open('../sample/pr_webhook_request.json') as f:
        pr_json = f.read()
        linter = GithubPRLinter(json.loads(pr_json), access_token=github_access_token)
        linter.run_checks()


def load_config(config_file_path):
    global GITHUB_ACCESS_TOKEN
    load_default_config = True

    if config_file_path:
        load_default_config = False
    else:
        config_file_path = DEFAULT_CONFIG_FILE_PATH

    if not os.path.isfile(config_file_path):
        if not load_default_config:
            logger.error("Config file '%s' doesn't exist or is not readable.", config_file_path)
            exit(1)
        else:
            logger.info("Default config file not found.")
        return
    with open(config_file_path, 'r') as config_file:
        try:
            config = yaml.load(config_file)
            if "github_token" in config:
                GITHUB_ACCESS_TOKEN = config['github_token']
        except yaml.YAMLError as exc:
            logger.exception("Failed to parse config file." + config_file_path)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='GitHub PR Webook handler to syntax check python files.')
    parser.add_argument('-t', '--token', help="Github Access token", dest="token", default=None)
    parser.add_argument('-f', '--config-file', help="YAML based config file to pass token and other options",
                        dest='config_file_path', default=None)
    parser.add_argument('-p', '--port', help="HTTP Server Port for listening webhook requests",
                        default=8080, type=int, dest='port')

    args = parser.parse_args()
    load_config(args.config_file_path)
    if args.token:
        # if token was provided as CLI option then it takes preference
        GITHUB_ACCESS_TOKEN = args.token
        logger.info("Using token provided as CLI argument")
    if not GITHUB_ACCESS_TOKEN:
        msg = "Github Access Token not set. Please provide token either in config file or via -t argument"
        logger.error(msg)
        exit(1)
    cherrypy.config.update({'server.socket_port': args.port,
                            'server.socket_host': '0.0.0.0'})
    logger.info("Starting HTTP listener on port=%d for Webhook requests", args.port)
    #cherrypy.quickstart(GitHubWebHookHandler(github_access_token=GITHUB_ACCESS_TOKEN))
    testRun(GITHUB_ACCESS_TOKEN)
