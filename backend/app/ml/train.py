"""Reproducible CrossEncoder training."""
from __future__ import annotations
from pathlib import Path
import random, numpy as np
from sentence_transformers import InputExample
from sentence_transformers.cross_encoder import CrossEncoder
from torch.utils.data import DataLoader
from app.core.config import settings
from app.ml.dataset import load_jsonl,split_dataset
from app.ml.preprocessing import preprocess
from app.ml.model_registry import ModelRegistry


def train(dataset_path:Path,output_path:Path,epochs:int=1,seed:int=42):
    random.seed(seed); np.random.seed(seed)
    rows=preprocess(load_jsonl(dataset_path))
    train_rows,_,_=split_dataset(rows,seed=seed)
    examples=[]
    for r in train_rows:
        examples.append(InputExample(texts=[r.query,r.positive_code],label=1.0))
        examples.append(InputExample(texts=[r.query,r.negative_code],label=0.0))
    if not examples: raise ValueError("Training dataset is empty.")
    model=CrossEncoder(settings.reranker_model,num_labels=1)
    model.fit(train_dataloader=DataLoader(examples,shuffle=True,batch_size=16),epochs=epochs,warmup_steps=max(1,len(examples)//10),output_path=str(output_path))
    return ModelRegistry().register(output_path,"repomind-crossencoder",{"train_examples":len(examples),"epochs":epochs,"seed":seed})
