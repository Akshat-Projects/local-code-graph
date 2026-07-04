import pytest
import networkx as nx
from pathlib import Path
from core.universal_parser import UniversalParser

def test_markdown_heading_parsing(tmp_path):
    # 1. Create a mock markdown file
    md_content = (
        "# Title 1\n"
        "Some description.\n"
        "\n"
        "## Heading 1.1\n"
        "Content of heading 1.1.\n"
        "\n"
        "### Sub-heading 1.1.1\n"
        "Content of sub-heading 1.1.1.\n"
        "\n"
        "# Title 2\n"
        "Content of Title 2.\n"
        "\n"
        "### Sub-heading 2.0.1\n"
        "Content of sub-heading 2.0.1 directly under Title 2.\n"
    )
    
    target_file = tmp_path / "README.md"
    target_file.write_text(md_content, encoding="utf-8")
    
    # 2. Parse the markdown file
    graph = nx.MultiDiGraph()
    parser = UniversalParser(graph)
    
    rel_path = "README.md"
    parser.parse_file(str(target_file), rel_path, "dummy_hash")
    
    # 3. Assertions
    # File node
    file_node_id = "file::README.md"
    assert file_node_id in graph
    assert graph.nodes[file_node_id]["type"] == "file"
    
    # H1: Title 1
    h1_1_id = "README.md::Title 1"
    assert h1_1_id in graph
    assert graph.nodes[h1_1_id]["type"] == "class"
    assert graph.nodes[h1_1_id]["name"] == "Title 1"
    assert graph.nodes[h1_1_id]["line_start"] == 1
    assert graph.nodes[h1_1_id]["line_end"] == 9
    assert graph.nodes[h1_1_id]["summary"].startswith("# Title 1\nSome description.")
    assert graph.nodes[h1_1_id]["analysis_status"] == "complete"
    
    # Check H1 relation to file
    assert graph.has_edge(file_node_id, h1_1_id)
    edges = [d for u, v, d in graph.edges(data=True) if u == file_node_id and v == h1_1_id]
    assert any(e["relation"] == "contains" for e in edges)
    
    # H2: Heading 1.1 under Title 1
    h2_1_id = f"{h1_1_id}::Heading 1.1"
    assert h2_1_id in graph
    assert graph.nodes[h2_1_id]["type"] == "class"
    assert graph.nodes[h2_1_id]["name"] == "Heading 1.1"
    assert graph.nodes[h2_1_id]["line_start"] == 4
    assert graph.nodes[h2_1_id]["line_end"] == 9
    assert graph.nodes[h2_1_id]["summary"].startswith("## Heading 1.1\nContent of heading 1.1.")
    assert graph.nodes[h2_1_id]["analysis_status"] == "complete"
    
    # Check H2 relations (contains from file and H1)
    assert graph.has_edge(file_node_id, h2_1_id)
    assert graph.has_edge(h1_1_id, h2_1_id)
    h1_to_h2_edges = [d for u, v, d in graph.edges(data=True) if u == h1_1_id and v == h2_1_id]
    assert any(e["relation"] == "contains" for e in h1_to_h2_edges)
    
    # H3: Sub-heading 1.1.1 under Heading 1.1
    h3_1_id = f"{h2_1_id}::Sub-heading 1.1.1"
    assert h3_1_id in graph
    assert graph.nodes[h3_1_id]["type"] == "function"
    assert graph.nodes[h3_1_id]["name"] == "Sub-heading 1.1.1"
    assert graph.nodes[h3_1_id]["line_start"] == 7
    assert graph.nodes[h3_1_id]["line_end"] == 9
    assert graph.nodes[h3_1_id]["summary"] == "### Sub-heading 1.1.1\nContent of sub-heading 1.1.1.\n"
    assert graph.nodes[h3_1_id]["analysis_status"] == "complete"
    
    # Check H3 relation (defines from parent H2)
    assert graph.has_edge(h2_1_id, h3_1_id)
    h2_to_h3_edges = [d for u, v, d in graph.edges(data=True) if u == h2_1_id and v == h3_1_id]
    assert any(e["relation"] == "defines" for e in h2_to_h3_edges)
    
    # H1: Title 2
    h1_2_id = "README.md::Title 2"
    assert h1_2_id in graph
    assert graph.nodes[h1_2_id]["type"] == "class"
    assert graph.nodes[h1_2_id]["name"] == "Title 2"
    assert graph.nodes[h1_2_id]["line_start"] == 10
    assert graph.nodes[h1_2_id]["line_end"] == 14
    assert graph.nodes[h1_2_id]["summary"].startswith("# Title 2\nContent of Title 2.")
    assert graph.nodes[h1_2_id]["analysis_status"] == "complete"
    
    # H3: Sub-heading 2.0.1 directly under Title 2
    h3_2_id = f"{h1_2_id}::Sub-heading 2.0.1"
    assert h3_2_id in graph
    assert graph.nodes[h3_2_id]["type"] == "function"
    assert graph.nodes[h3_2_id]["name"] == "Sub-heading 2.0.1"
    assert graph.nodes[h3_2_id]["line_start"] == 13
    assert graph.nodes[h3_2_id]["line_end"] == 14
    assert graph.nodes[h3_2_id]["summary"] == "### Sub-heading 2.0.1\nContent of sub-heading 2.0.1 directly under Title 2."
    assert graph.nodes[h3_2_id]["analysis_status"] == "complete"
    
    # Check H3 relation (defines from parent H1)
    assert graph.has_edge(h1_2_id, h3_2_id)
    h1_to_h3_edges = [d for u, v, d in graph.edges(data=True) if u == h1_2_id and v == h3_2_id]
    assert any(e["relation"] == "defines" for e in h1_to_h3_edges)
