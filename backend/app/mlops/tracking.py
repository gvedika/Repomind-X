from __future__ import annotations
from contextlib import contextmanager
from app.core.config import settings


@contextmanager
def run_experiment(name,params=None):
    import mlflow
    if settings.mlflow_tracking_uri: mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    with mlflow.start_run(run_name=name) as run:
        if params: mlflow.log_params(params)
        yield mlflow,run


def log_experiment(name,params=None,metrics=None,artifacts=None):
    with run_experiment(name,params) as (mlflow,run):
        for k,v in (metrics or {}).items(): mlflow.log_metric(k,float(v))
        for artifact in (artifacts or []): mlflow.log_artifact(str(artifact))
        return run.info.run_id
