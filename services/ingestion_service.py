from core.librarian import Librarian
from intelligence_layer.analyst import GraphAnalyst
from utils.logger import get_logger

logger = get_logger()

async def run_ingestion_pipeline(
    repo_name: str,
    target_path: str
):
    logger.info(f"--- Starting Background Ingestion for {repo_name} ---")

    try:
        # Phase 1: Static AST Parsing
        librarian = Librarian(
            workspace_root=".",
            repo_name=repo_name
        )

        manifest = librarian.scan_repository(target_path)

        from core.ast_parser import CodebaseASTParser

        parser = CodebaseASTParser(librarian.graph)

        modified_count = 0

        for rel_path, file_meta in manifest.items():

            if file_meta["status"] == "modified":

                parser.parse_file(
                    file_meta["absolute_path"],
                    rel_path,
                    file_meta["hash"]
                )

                modified_count += 1

        if modified_count > 0:
            librarian.save_graph()

        # Phase 2: LLM Semantic Analysis
        analyst = GraphAnalyst(
            librarian=librarian,
            target_repo_path=target_path
        )

        await analyst.analyze_and_update()

        logger.info(
            f"--- Completed Background "
            f"Ingestion for {repo_name} ---"
        )

    except Exception as e:
        logger.error(f"Ingestion failed for {repo_name}: {e}")