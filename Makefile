# Makefile - ADD THIS
.PHONY: server worker redis eval-collect eval-run eval-full

# Development servers
server:
	./start_server.sh

worker:
	./start_worker.sh

redis:
	./start_redis.sh

database:
	./start_db.sh

# Stop services
stop:
	./stopAll.sh

# Evaluation tasks
eval-collect:
	poetry run python evaluation/scripts/collect_data.py

eval-run:
	poetry run python evaluation/scripts/ragas_evaluation_script.py

eval-full: eval-collect eval-run
	@echo "✅ Evaluation complete!"

clean:
	rm -f evaluation/datasets/*.json evaluation/datasets/*.csv