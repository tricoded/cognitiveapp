# Lazy exports: importing any app.ml submodule must not pull in torch /
# sentence-transformers (slow, and not needed for the lightweight models).
__all__ = ["TaskDifficultyPredictor", "SemanticMemoryEngine"]


def __getattr__(name):
    if name == "TaskDifficultyPredictor":
        from app.ml.task_predictor import TaskDifficultyPredictor
        return TaskDifficultyPredictor
    if name == "SemanticMemoryEngine":
        from app.ml.semantic_engine import SemanticMemoryEngine
        return SemanticMemoryEngine
    raise AttributeError(name)
