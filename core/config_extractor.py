import json
import re
import tomllib
import yaml
from pathlib import Path
import networkx as nx

from utils.logger import get_logger

logger = get_logger()

class ConfigExtractor:
    def __init__(self, graph: nx.MultiDiGraph):
        self.graph = graph

    def extract(self, absolute_path: str, relative_path: str, file_node_id: str):
        """Routes the config file to the correct parser based on its filename."""
        filename = Path(absolute_path).name.lower()

        if filename == "package.json":
            self._parse_package_json(absolute_path, file_node_id)
        elif filename == "requirements.txt":
            self._parse_requirements_txt(absolute_path, file_node_id)
        elif filename in ["docker-compose.yml", "docker-compose.yaml"]:
            self._parse_docker_compose(absolute_path, file_node_id)
        elif filename == "pyproject.toml":
            self._parse_pyproject_toml(absolute_path, file_node_id)

    def _add_dependency_node(self, node_name: str, file_node_id: str, node_type: str = "library"):
        """Creates the external node and draws the structural edge."""
        # Use a different prefix for infrastructure vs libraries
        prefix = "infra" if node_type == "infrastructure" else "lib"
        target_node_id = f"{prefix}::{node_name}"
        
        if not self.graph.has_node(target_node_id):
            self.graph.add_node(
                target_node_id, 
                type=node_type, 
                name=node_name, 
                summary=f"External {node_type}: {node_name}",
                analysis_status="complete" 
            )
        
        relation = "defines_service" if node_type == "infrastructure" else "depends_on"
        self.graph.add_edge(file_node_id, target_node_id, relation=relation)

    def _parse_package_json(self, file_path: str, file_node_id: str):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            for lib_name in deps.keys():
                self._add_dependency_node(lib_name, file_node_id, "library")
            logger.info(f"Extracted {len(deps)} dependencies from package.json")
        except Exception as e:
            logger.warning(f"Failed to parse package.json: {e}")

    def _parse_requirements_txt(self, file_path: str, file_node_id: str):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                count = 0
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    # Match base package name, stripping version pins (==, >=, ~)
                    match = re.match(r'^([a-zA-Z0-9\-_]+)', line)
                    if match:
                        lib_name = match.group(1).lower()
                        self._add_dependency_node(lib_name, file_node_id, "library")
                        count += 1
            logger.info(f"Extracted {count} dependencies from requirements.txt")
        except Exception as e:
            logger.warning(f"Failed to parse requirements.txt: {e}")

    def _parse_docker_compose(self, file_path: str, file_node_id: str):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            
            services = data.get("services", {})
            for service_name in services.keys():
                # Extract infrastructure services (postgres, redis, etc.)
                self._add_dependency_node(service_name, file_node_id, "infrastructure")
            logger.info(f"Extracted {len(services)} infra services from docker-compose")
        except Exception as e:
            logger.warning(f"Failed to parse docker-compose.yml: {e}")

    def _parse_pyproject_toml(self, file_path: str, file_node_id: str):
        try:
            with open(file_path, "rb") as f:
                data = tomllib.load(f)
            
            deps = []
            # 1. Standard PEP 621 dependencies
            if "project" in data and "dependencies" in data["project"]:
                deps.extend(data["project"]["dependencies"])
            
            # 2. Poetry fallback
            if "tool" in data and "poetry" in data["tool"] and "dependencies" in data["tool"]["poetry"]:
                deps.extend(data["tool"]["poetry"]["dependencies"].keys())

            count = 0
            for dep in deps:
                # Same regex logic as requirements.txt to strip versions
                match = re.match(r'^([a-zA-Z0-9\-_]+)', dep)
                if match:
                    lib_name = match.group(1).lower()
                    # Skip python version pins
                    if lib_name != "python":
                        self._add_dependency_node(lib_name, file_node_id, "library")
                        count += 1
                        
            logger.info(f"Extracted {count} dependencies from pyproject.toml")
        except Exception as e:
            logger.warning(f"Failed to parse pyproject.toml: {e}")