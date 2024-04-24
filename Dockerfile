FROM python:3.11-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt requirements.txt

RUN pip install -r requirements.txt

COPY smtp_relay.py smtp_relay.py

ENTRYPOINT ["python3", "smtp_relay.py"]
