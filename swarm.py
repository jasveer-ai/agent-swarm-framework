import asyncio
import sys
import yaml
import os
import argparse
from src.core.agent import Message
from src.core.bus import MessageBus
from src.orchestrator.base import Orchestrator

async def run_swarm(goal: str, config_path: str):
    print(f"\n[🌀] Initializing Swarm for goal: '{goal}'")
    
    if not os.path.exists(config_path):
        print(f"Error: Config file not found at {config_path}. Please run setup first.")
        sys.exit(1)

    # Load Config
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    bus = MessageBus()
    
    # Setup Orchestrator
    orch_conf = config.get('orchestrator', {})
    orchestrator = Orchestrator(
        agent_id="master-orch", 
        identity="System Orchestrator", 
        bus=bus
    )
    
    print(f"[🚀] Orchestrator ({orch_conf.get('model', 'default')}) is active.")
    print(f"[📡] Message Bus initialized. Listening on mesh...")
    
    # Simulate a goal decomposition
    await orchestrator.decompose(goal)
    
    # Task creation
    task_id = "task-" + os.urandom(2).hex()
    print(f"[🛠️] Dispatching task {task_id}...")
    await bus.publish("new_task", Message(
        id=f"msg-{task_id}", 
        sender_id="system", 
        receiver_id="workers", 
        type="task", 
        payload={"task_id": task_id, "description": goal, "complexity": "medium"}
    ))

    await asyncio.sleep(3)
    print("\n[🏁] Swarm execution cycle complete.")

def main():
    parser = argparse.ArgumentParser(description="Agent Swarm Framework CLI")
    parser.add_argument("goal", help="The high-level goal for the swarm to achieve")
    parser.add_argument("--config", default=".swarm/config.yaml", help="Path to the swarm config file")
    
    args = parser.parse_args()
    
    # Resolve config path relative to the current directory or the repo root
    config_path = args.config
    if not os.path.isabs(config_path):
        config_path = os.path.join(os.getcwd(), config_path)

    asyncio.run(run_swarm(args.goal, config_path))

if __name__ == "__main__":
    main()
