import os
import pytest
import networkx as nx
from pathlib import Path

from core.ast_searcher import ASTSearcher
from core.universal_parser import resolve_python_import, resolve_js_import


def test_import_resolvers(tmp_path):
    # Setup mock files
    target_repo = tmp_path
    
    # Create python directories and files
    core_dir = target_repo / "core"
    core_dir.mkdir()
    librarian_file = core_dir / "librarian.py"
    librarian_file.write_text("class Librarian: pass")
    
    init_file = core_dir / "__init__.py"
    init_file.write_text("")
    
    # 1. Resolve absolute import
    resolved = resolve_python_import(str(target_repo), "main.py", "core.librarian")
    assert resolved == "core/librarian.py"
    
    # 2. Resolve package init import
    resolved_init = resolve_python_import(str(target_repo), "main.py", "core")
    assert resolved_init == "core/__init__.py"
    
    # 3. Resolve relative import from nested file
    resolved_rel = resolve_python_import(str(target_repo), "core/assembler.py", "librarian", relative_dots=".")
    assert resolved_rel == "core/librarian.py"


def test_graph_structural_querying():
    # Setup mock graph
    G = nx.MultiDiGraph()
    
    # Add nodes
    G.add_node("file::core/librarian.py", type="file", file_path="core/librarian.py")
    G.add_node("core/librarian.py::Librarian", type="class", name="Librarian", file_path="core/librarian.py")
    G.add_node("core/librarian.py::Librarian::save", type="function", name="save", file_path="core/librarian.py")
    G.add_node("api/routes/ingest.py::trigger_ingest", type="function", name="trigger_ingest", file_path="api/routes/ingest.py")
    
    # Add edges
    # inherits edge
    G.add_node("core/model.py::BaseModel", type="class", name="BaseModel")
    G.add_edge("core/librarian.py::Librarian", "core/model.py::BaseModel", relation="inherits")
    
    # calls edge
    G.add_edge("api/routes/ingest.py::trigger_ingest", "core/librarian.py::Librarian", relation="calls")
    
    searcher = ASTSearcher(G)
    
    # Test filtering by node type
    res = searcher.query_graph_structure({"node_type": "class"})
    assert len(res) >= 1
    assert any(item["name"] == "Librarian" for item in res)
    
    # Test filtering by name
    res_name = searcher.query_graph_structure({"name": "save"})
    assert len(res_name) == 1
    assert res_name[0]["id"] == "core/librarian.py::Librarian::save"
    
    # Test filtering by inheritance
    res_inherits = searcher.query_graph_structure({"inherits": "BaseModel"})
    assert len(res_inherits) == 1
    assert res_inherits[0]["id"] == "core/librarian.py::Librarian"
    
    # Test filtering by calls
    res_calls = searcher.query_graph_structure({"calls": "Librarian"})
    assert len(res_calls) == 1
    assert res_calls[0]["id"] == "api/routes/ingest.py::trigger_ingest"
