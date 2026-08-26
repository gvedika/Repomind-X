from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config=SettingsConfigDict(env_file=".env",extra="ignore")
    repository_root:Path=Path("./data/repos")
    neo4j_uri:str|None=None
    neo4j_username:str|None=None
    neo4j_password:str|None=None
    neo4j_pool_size:int=50
    neo4j_timeout_seconds:float=15.0
    graph_backend:str="neo4j"
    chroma_host:str|None=None
    chroma_port:int=8000
    openai_api_key:str|None=None
    anthropic_api_key:str|None=None
    llm_provider:str="openai"
    llm_model:str="gpt-4o-mini"
    openai_model:str="gpt-4o-mini"
    llm_base_url:str|None=None
    llm_temperature:float=0.0
    embedding_model:str="BAAI/bge-small-en-v1.5"
    reranker_model:str="cross-encoder/ms-marco-MiniLM-L-6-v2"
    reranker_path:Path|None=None
    mlflow_tracking_uri:str|None=None
    enable_llm_reasoning:bool=True
    mcp_server_command:str="python -m app.mcp_server.server"
    mcp_timeout_seconds:float=30.0
    max_agent_iterations:int=8
    max_tool_calls:int=12
    log_level:str="INFO"


settings=Settings()
