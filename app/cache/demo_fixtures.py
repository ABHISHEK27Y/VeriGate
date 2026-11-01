"""Factual fixtures for the explicitly mock-backed local semantic demo."""

FACTS = (
    ("Who wrote the novel Pride and Prejudice?", "Jane Austen"),
    ("In what year did Apollo 11 land on the Moon?", "1969"),
    ("Which planet is known as the Red Planet?", "Mars"),
)

DEMO_API_KEY = "demo-key-123"


def demo_enabled(config) -> bool:
    """Never expose fixture restoration outside the named development demo."""
    return (
        config.environment == "development"
        and config.llm_provider == "mock"
        and config.cache_match_mode == "semantic"
        and bool(config.answer_policy_artifact)
        and bool(config.redis_url)
        and config.vector_backend == "redisearch"
        and config.embedding_backend == "minilm"
        and DEMO_API_KEY in config.api_key_set
    )
