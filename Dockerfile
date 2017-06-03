FROM python:2-alpine

COPY requirements.txt /requirements.txt
RUN pip install -r requirements.txt
COPY linter /linter

WORKDIR /linter
ENTRYPOINT ["python", "/linter/main.py"]