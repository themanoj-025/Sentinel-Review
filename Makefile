# Sentinel Review Makefile — Common development commands.
# Run `make <target>` from the project root.

.PHONY: help install test lint format docker-up docker-down docker-build clean

.DEFAULT_GOAL := help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# Python

install: ## Install Python dependencies
	pip install -r requirements.txt

test: ## Run all tests with coverage
	cd backend && python -m pytest --cov=. --cov-report=term-missing --nomigrations -p no:cacheprovider

test-quick: ## Run tests without coverage (faster)
	cd backend && python -m pytest --nomigrations -p no:cacheprovider -x

test-file: ## Run a specific test file: make test-file FILE=tests/test_signature.py
	cd backend && python -m pytest $(FILE) -v --nomigrations -p no:cacheprovider

lint: ## Run ruff linter
	cd backend && ruff check .

lint-fix: ## Auto-fix lint issues
	cd backend && ruff check . --fix

format: ## Format code with ruff
	cd backend && ruff format .

check: lint test ## Run lint + tests (CI pipeline)

# Docker

docker-up: ## Start all services
	docker compose up --build -d

docker-down: ## Stop all services
	docker compose down

docker-logs: ## Follow logs
	docker compose logs -f

docker-build: build Docker images
	docker compose build

docker-clean: remove all containers, volumes, and images
	docker compose down -v --rmi all

# Django

migrate: run database migrations
	cd backend && python manage.py migrate

makemigrations: create new migrations
	cd backend && python manage.py makemigrations

shell: open Django shell
	cd backend && python manage.py shell

admin: create Django superuser
	cd backend && python manage.py createsuperuser

collectstatic: collect static files
	cd backend && python manage.py collectstatic --noinput

# Cleanup

clean: remove Python cache artifacts
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf .ruff_cache .pytest_cache htmlcov .coverage
	rm -rf backend/staticfiles
