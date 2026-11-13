# Space Hugging Face (SDK Docker) : sert la démo marimo en lecture seule.
FROM python:3.12-slim

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH
WORKDIR /home/user/app

COPY --chown=user pyproject.toml README.md ./
COPY --chown=user src ./src
RUN pip install --no-cache-dir --user ".[demo]"

COPY --chown=user demo.py ./

EXPOSE 7860
CMD ["marimo", "run", "demo.py", "--host", "0.0.0.0", "--port", "7860", "--headless"]
