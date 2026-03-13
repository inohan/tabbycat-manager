FROM python:3.13-slim-trixie
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
RUN apt-get update && apt-get install -y git
COPY . /app
ENV UV_NO_DEV=1

WORKDIR /app
RUN uv sync --locked
EXPOSE 8550

CMD ["uv", "run", "flet", "run", "-wnd", "-p", "8550"]
