.PHONY: test lint typecheck demo eval clean install reproduce reproduce-fast review-queue

# Default target
all: test

# Install dependencies
install:
	pip install -e .[dev]

# Run tests
test:
	python -m pytest tests/ -v

# Run tests with coverage
test-cov:
	python -m pytest tests/ --cov=app --cov-report=term-missing --cov-report=html

# Lint with ruff
lint:
	ruff check app/ tests/ evaluation/
	ruff format --check app/ tests/ evaluation/

# Type check with mypy
typecheck:
	mypy app/

# Run all checks
check: lint typecheck test

# Run demos
demo:
	python demo.py

demo-semantic:
	python demo_semantic.py

demo-live:
	python demo_live.py

# Run evaluation
eval:
	python -m evaluation.run

reproduce:
	python scripts/download_evaluation_data.py qqp stsb paws
	python -m evaluation.reproduce
	python -m evaluation.train_accept
	python -m evaluation.stream
	python -m evaluation.risk_guarantee
	python scripts/summarize_v2.py
	python scripts/summarize_experiments.py

reproduce-fast:
	python -m evaluation.reproduce --fast
	python scripts/summarize_v2.py

review-queue:
	python -m scripts.build_answer_review_queue

eval-latency:
	python -m evaluation.latency

# Start development server
serve:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Docker commands
docker-build:
	docker build -t verigate .

docker-up:
	docker compose up --build

docker-down:
	docker compose down

docker-obs-up:
	docker compose -f docker-compose.observability.yml up -d

docker-obs-down:
	docker compose -f docker-compose.observability.yml down

# Clean up
clean:
	rm -rf __pycache__ .pytest_cache .mypy_cache .ruff_cache
	rm -rf *.egg-info build dist
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

# Security audit
audit:
	pip-audit

# Format code
format:
	ruff format app/ tests/ evaluation/
