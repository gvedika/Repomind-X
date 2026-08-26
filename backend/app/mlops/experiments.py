from pathlib import Path
from app.mlops.tracking import log_experiment


def run_retrieval_experiment(name,metrics,params=None,artifacts=None):
    return log_experiment(name,params=params,metrics=metrics,artifacts=artifacts)
