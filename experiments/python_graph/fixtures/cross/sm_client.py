"""Synthetic SM entry; dependency identity is configured per experiment."""
from dnd5e_engine.evaluation import evaluate as rule_evaluate

def call_rules():
    return rule_evaluate()  # case:cross_repository
