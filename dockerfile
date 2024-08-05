FROM python:3.10.14-alpine

COPY ./requirements.txt /tmp/requirements.txt

RUN pip install -r /tmp/requirements.txt

WORKDIR /app


CMD ["python", "-m", "interactive-bot"]

