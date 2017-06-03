# github-pr-python-linter
GitHub Webhook handler to listen for Pull requests changes to lint python file.

This utility will syntax check all python files which are part of PR using pylint.

If syntax errors are found, it will add comment to PR with error details and change status of PR to "Change Requested"

```
❯ python linter/main.py -h
usage: main.py [-h] [-t TOKEN] [-f CONFIG_FILE_PATH] [-p PORT]

GitHub PR Webook handler to syntax check python files.

optional arguments:
  -h, --help            show this help message and exit
  -t TOKEN, --token TOKEN
                        Github Access token
  -f CONFIG_FILE_PATH, --config-file CONFIG_FILE_PATH
                        YAML based config file to pass token and other options
  -p PORT, --port PORT  HTTP Server Port for listening webhook requests
```
##
Run Locally:
1. Install required packages:

   `pip install -r requirements.txt`

2. Start listening for Github Webhook requests on port 8080

   `python linter/main.py -t <github_token> -p 8080`


## Run as Docker container
1. Build docker container:

   `docker build -t github-pr-linter .`
2. Run container
   1. Providing Github access token in config.yaml and using that

   `docker run -p 8080:8080 -v `pwd`/linter/config.yaml:/config.yaml -it github-pr-linter -f /config.yaml`
   
   This will start HTTP server to listen for webook requests on port 8080

   2. Provide token as CLI argument when running container:
   
   `docker run -p 8080:8080 -it github-pr-linter -t <github_token>`

