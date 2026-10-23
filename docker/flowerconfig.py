"""Private task metadata UI. Arguments are UUIDs; result/payload browsing is unnecessary."""
import os

address = "0.0.0.0"
port = 5555
basic_auth = [item for item in os.environ.get("FLOWER_BASIC_AUTH", "").split(",") if item]
if not basic_auth or any(":" not in item or not item.split(":", 1)[1] for item in basic_auth):
    raise RuntimeError("Set FLOWER_BASIC_AUTH=user:strong-password before starting Flower.")
read_only = True
persistent = True
db = "/app/runtime/flower/flower.db"
state_save_interval = 10000
max_tasks = 10000
tasks_columns = "name,uuid,state,received,started,runtime,worker,retries"
