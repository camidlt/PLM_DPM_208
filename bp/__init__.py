from . import config


def make_repo():
    """Crée l'accès aux données selon la configuration (Neo4j ou mémoire)."""
    if config.BACKEND == "neo4j":
        from .neo4j_repo import Neo4jRepo
        return Neo4jRepo()
    from .memory_repo import MemoryRepo
    return MemoryRepo()
