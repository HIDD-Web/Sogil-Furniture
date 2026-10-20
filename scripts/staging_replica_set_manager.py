"""Manager for the Isolated 3-Node MongoDB Replica Set for Phase 3D Staging.

Provides automated provisioning, topology discovery, controlled failover,
node interruption, network drop simulation, and clean teardown.
"""

import os
import sys
import time
import signal
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List

import pymongo

BASE_DIR = Path("/Users/syahidmujahid/local_mongodb_runtime/phase_3d_staging")
MONGOD_BIN = "/Users/syahidmujahid/local_mongodb_runtime/mongodb-macos-aarch64--8.0.32/bin/mongod"
REPL_SET_NAME = "sogil-staging-rs"
NODES = [
    {"id": 0, "port": 27101, "name": "127.0.0.1:27101", "dbpath": BASE_DIR / "node1", "log": BASE_DIR / "logs" / "node1.log", "pid": BASE_DIR / "logs" / "node1.pid"},
    {"id": 1, "port": 27102, "name": "127.0.0.1:27102", "dbpath": BASE_DIR / "node2", "log": BASE_DIR / "logs" / "node2.log", "pid": BASE_DIR / "logs" / "node2.pid"},
    {"id": 2, "port": 27103, "name": "127.0.0.1:27103", "dbpath": BASE_DIR / "node3", "log": BASE_DIR / "logs" / "node3.log", "pid": BASE_DIR / "logs" / "node3.pid"},
]
CONNECTION_URI = f"mongodb://127.0.0.1:27101,127.0.0.1:27102,127.0.0.1:27103/?replicaSet={REPL_SET_NAME}"


def ensure_dirs():
    (BASE_DIR / "logs").mkdir(parents=True, exist_ok=True)
    for node in NODES:
        node["dbpath"].mkdir(parents=True, exist_ok=True)


import socket


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(('127.0.0.1', port)) == 0


def can_bind_port(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('127.0.0.1', port))
            return True
    except OSError:
        return False


def is_node_running(node_idx: int) -> bool:
    node = NODES[node_idx]
    if not is_port_in_use(node["port"]):
        return False
    if not node["pid"].exists():
        return False
    try:
        pid = int(node["pid"].read_text().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, OSError):
        return False


def start_node(node_idx: int):
    node = NODES[node_idx]
    if is_node_running(node_idx):
        return

    # Wait for port to be bindable if recently stopped
    for _ in range(60):
        if can_bind_port(node["port"]):
            break
        time.sleep(0.1)

    ensure_dirs()
    cmd = [
        MONGOD_BIN,
        "--dbpath", str(node["dbpath"]),
        "--logpath", str(node["log"]),
        "--pidfilepath", str(node["pid"]),
        "--port", str(node["port"]),
        "--bind_ip", "127.0.0.1",
        "--replSet", REPL_SET_NAME,
        "--fork"
    ]
    last_err = None
    for attempt in range(8):
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            # Wait for socket to become active
            for _ in range(40):
                if is_port_in_use(node["port"]):
                    return
                time.sleep(0.1)
            return
        last_err = res.stderr or res.stdout
        time.sleep(0.5)

    raise RuntimeError(f"Failed to start mongod node {node_idx} on port {node['port']}: {last_err}")


def stop_node(node_idx: int, immediate: bool = True):
    node = NODES[node_idx]
    pid = None
    if node["pid"].exists():
        try:
            pid = int(node["pid"].read_text().strip())
        except (ValueError, OSError):
            pass

    if pid is None and is_port_in_use(node["port"]):
        # Find pid via lsof if pidfile is missing
        try:
            out = subprocess.check_output(["lsof", "-ti", f":{node['port']}"]).decode().strip()
            if out:
                pid = int(out.split()[0])
        except Exception:
            pass

    if pid is not None:
        try:
            if immediate:
                os.kill(pid, signal.SIGKILL)
            else:
                os.kill(pid, signal.SIGTERM)
                # Allow 1.5s for graceful shutdown, then SIGKILL
                for _ in range(15):
                    os.kill(pid, 0)
                    time.sleep(0.1)
                os.kill(pid, signal.SIGKILL)
        except OSError:
            pass

    # Wait for process and port to be released
    for _ in range(60):
        if can_bind_port(node["port"]):
            break
        time.sleep(0.1)

    if node["pid"].exists():
        try:
            node["pid"].unlink()
        except OSError:
            pass


def start_all_nodes():
    ensure_dirs()
    for i in range(len(NODES)):
        start_node(i)


def stop_all_nodes():
    for i in range(len(NODES)):
        stop_node(i)


def initiate_replica_set_if_needed():
    # Connect directly to node 0
    client = pymongo.MongoClient("mongodb://127.0.0.1:27101/?directConnection=true", serverSelectionTimeoutMS=2000)
    try:
        status = client.admin.command("replSetGetStatus")
        # Ensure fast election settings
        try:
            conf = client.admin.command("replSetGetConfig")["config"]
            if conf.get("settings", {}).get("electionTimeoutMillis") != 2000:
                conf["version"] += 1
                conf.setdefault("settings", {})
                conf["settings"]["electionTimeoutMillis"] = 2000
                conf["settings"]["heartbeatIntervalMillis"] = 500
                conf["settings"]["heartbeatTimeoutSecs"] = 2
                client.admin.command("replSetReconfig", conf)
        except Exception:
            pass
        return
    except pymongo.errors.OperationFailure as e:
        if "no replSet" not in str(e).lower() and "not yet initialized" not in str(e).lower() and e.code != 94:
            raise

    # Needs initiation
    config = {
        "_id": REPL_SET_NAME,
        "members": [
            {"_id": 0, "host": "127.0.0.1:27101", "priority": 1},
            {"_id": 1, "host": "127.0.0.1:27102", "priority": 1},
            {"_id": 2, "host": "127.0.0.1:27103", "priority": 1},
        ],
        "settings": {
            "electionTimeoutMillis": 2000,
            "heartbeatIntervalMillis": 500,
            "heartbeatTimeoutSecs": 2,
        }
    }
    client.admin.command("replSetInitiate", config)


def wait_for_cluster_healthy(timeout_sec: float = 30.0) -> Dict[str, Any]:
    start_time = time.time()
    last_err = None
    while time.time() - start_time < timeout_sec:
        try:
            client = pymongo.MongoClient(
                CONNECTION_URI,
                serverSelectionTimeoutMS=2000,
                directConnection=False
            )
            status = client.admin.command("replSetGetStatus")
            members = status.get("members", [])
            primary = next((m for m in members if m.get("stateStr") == "PRIMARY"), None)
            secondaries = [m for m in members if m.get("stateStr") == "SECONDARY"]
            if primary and len(secondaries) == 2:
                client.close()
                return {
                    "healthy": True,
                    "primary": primary["name"],
                    "secondaries": [s["name"] for s in secondaries],
                    "members": members,
                    "set": status.get("set")
                }
            client.close()
        except Exception as e:
            last_err = e
        time.sleep(0.5)

    raise TimeoutError(f"Cluster did not reach healthy 1 PRIMARY + 2 SECONDARY state within {timeout_sec}s: {last_err}")


def get_cluster_status() -> Dict[str, Any]:
    client = pymongo.MongoClient(CONNECTION_URI, serverSelectionTimeoutMS=3000)
    status = client.admin.command("replSetGetStatus")
    client.close()
    return status


def stepdown_primary(seconds: int = 15) -> str:
    """Forces current primary to step down and returns the name of stepped-down node."""
    client = pymongo.MongoClient(CONNECTION_URI, serverSelectionTimeoutMS=3000)
    hello = client.admin.command("hello")
    primary_host = hello.get("primary")
    if not primary_host:
        client.close()
        raise RuntimeError("No primary currently found to step down")

    # Connect directly to the primary node to issue stepdown
    p_client = pymongo.MongoClient(f"mongodb://{primary_host}/?directConnection=true", serverSelectionTimeoutMS=2000)
    try:
        p_client.admin.command("replSetStepDown", seconds, secondaryCatchUpPeriodSecs=0, force=True)
    except (pymongo.errors.ConnectionFailure, pymongo.errors.AutoReconnect):
        pass  # Expected when stepping down
    finally:
        p_client.close()
        client.close()

    return primary_host


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    if action == "start":
        print("Starting 3 MongoDB nodes...")
        start_all_nodes()
        print("Initiating replica set...")
        initiate_replica_set_if_needed()
        print("Waiting for cluster health...")
        info = wait_for_cluster_healthy()
        print(f"Cluster ready: Primary={info['primary']}, Secondaries={info['secondaries']}")
    elif action == "stop":
        print("Stopping all nodes...")
        stop_all_nodes()
        print("All nodes stopped.")
    elif action == "status":
        info = wait_for_cluster_healthy(timeout_sec=5.0)
        print(f"Cluster status: Primary={info['primary']}, Secondaries={info['secondaries']}")
    elif action == "stepdown":
        old_p = stepdown_primary()
        print(f"Stepped down primary: {old_p}")
