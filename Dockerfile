# The release image: docker build -t graphcalc . && docker run --rm graphcalc
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN python -c "import subprocess, sys, tomllib; deps = tomllib.load(open('pyproject.toml', 'rb'))['project'].get('dependencies', []); deps and subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--no-cache-dir', *deps])"
ENV HOST=0.0.0.0
EXPOSE 8000
CMD ["python", "-m", "graphcalc", "--port", "8000", "--in-memory"]
