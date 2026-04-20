# (Docker uniquement)
# Usage: make help

.PHONY: help up down restart logs build clean status health

# Couleurs
BLUE := \033[36m
GREEN := \033[32m
YELLOW := \033[33m
RED := \033[31m
NC := \033[0m

COMPOSE := docker compose

help:
	@echo "$(BLUE)MVP ALAO/LLM - Commandes Docker$(NC)"
	@echo "================================"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "$(GREEN)%-20s$(NC) %s\n", $$1, $$2}'

# ========== Démarrage ==========
up:
	@echo "$(BLUE)▶ Démarrage de tous les services...$(NC)"
	$(COMPOSE) up -d
	@echo "$(GREEN)✓ Services démarrés$(NC)"
	@echo ""
	@echo "$(YELLOW)URLs:$(NC)"
	@echo "  Frontend: http://localhost:5173"
	@echo "  API:      http://localhost:8000"
	@echo "  Docs:     http://localhost:8000/docs"
	@echo "  DB:       localhost:5432"
	@echo "  Redis:    localhost:6379"

down:
	@echo "$(BLUE)▶ Arrêt des services...$(NC)"
	$(COMPOSE) down
	@echo "$(GREEN)✓ Services arrêtés$(NC)"

restart: down up

status:
	@echo "$(BLUE)Statut des conteneurs:$(NC)"
	$(COMPOSE) ps

# ========== Logs ==========

logs:
	$(COMPOSE) logs -f

logs-api:
	$(COMPOSE) logs -f api

logs-frontend:
	$(COMPOSE) logs -f frontend

logs-db:
	$(COMPOSE) logs -f db

# ========== Base de données ==========

db:
	$(COMPOSE) exec db psql -U app -d app

psql: db

db-migrate:
	@echo "$(BLUE)▶ Création des tables...$(NC)"
	$(COMPOSE) exec api python -c "from main import engine, metadata; import asyncio; asyncio.run(engine.begin().__aenter__().run_sync(metadata.create_all))"
	@echo "$(GREEN)✓ Tables créées$(NC)"

# ========== Données ==========

dataset-load:
	@if [ -z "$(FILE)" ]; then \
		echo "$(YELLOW)⚠️  Usage: make dataset-load FILE=chemin/vers/fichier.jsonl [MAX=100]$(NC)"; \
		exit 1; \
	fi
	@echo "$(BLUE)▶ Chargement du dataset...$(NC)"
	$(COMPOSE) exec api python main.py load-c4 --file $(FILE) $(if $(MAX),--max-examples $(MAX),)

dataset-stats:
	@echo "$(BLUE)▶ Statistiques du dataset:$(NC)"
	@$(COMPOSE) exec -T api curl -s http://localhost:8000/dataset/stats

# ========== Maintenance ==========

build:
	@echo "$(BLUE)▶ Rebuild des images...$(NC)"
	$(COMPOSE) build --no-cache
	@echo "$(GREEN)✓ Images rebuildées$(NC)"

clean: down
	@echo "$(BLUE)▶ Nettoyage...$(NC)"
	$(COMPOSE) rm -f
	docker system prune -f
	@echo "$(GREEN)✓ Nettoyage terminé$(NC)"

clean-all: down
	@echo "$(RED)⚠️  Cela va supprimer TOUTES les données !$(NC)"
	@read -p "Êtes-vous sûr ? [y/N] " confirm; \
	if [ "$$confirm" = "y" ] || [ "$$confirm" = "Y" ]; then \
		$(COMPOSE) down -v; \
		docker volume rm -f mvp_pgdata mvp_redis_data mvp_node_modules 2>/dev/null || true; \
		docker system prune -af; \
		echo "$(GREEN)✓ Tout a été supprimé$(NC)"; \
	else \
		echo "$(BLUE)Annulé$(NC)"; \
	fi

reload-frontend:
	$(COMPOSE) restart frontend

reload-api:
	$(COMPOSE) restart api


info:
	@echo "$(BLUE)MVP ALAO/LLM$(NC)"
	@echo "=============="
	@echo "Frontend: Vue.js 3 + Vite (port 5173)"
	@echo "Backend:  FastAPI (port 8000)"
	@echo "Database: PostgreSQL + pgvector (port 5432)"
	@echo "Cache:    Redis (port 6379)"
	@echo ""
	@echo "$(YELLOW)Commandes rapides:$(NC)"
	@echo "  make up          → Démarrer tout"
	@echo "  make down        → Arrêter tout"
	@echo "  make logs        → Voir les logs"
	@echo "  make health      → Vérifier la santé"
