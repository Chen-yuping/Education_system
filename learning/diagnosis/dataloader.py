import torch
from torch.utils.data import TensorDataset, DataLoader
import json
import params
import random
import numpy as np

def my_collate(batch):
    input_stu_ids, input_exer_ids, input_knowledge_embs, ys = [], [], [], []
    for log in batch:
        if log['knowledge_code']==[]:
            knowledge_emb = [1.0] * params.kn
        else:
            knowledge_emb = [0.] * params.kn
            for knowledge_code in log['knowledge_code']:
                # 将ID减1，适配0-indexed
                idx = knowledge_code - 1
                if 0 <= idx < params.kn:
                    knowledge_emb[idx] = 1.0
        y = log['score']
        # 将user_id和exer_id减1
        input_stu_ids.append(log['user_id'] - 1)
        input_exer_ids.append(log['exer_id'] - 1)
        input_knowledge_embs.append(knowledge_emb)
        ys.append(y)

    return torch.LongTensor(input_stu_ids), torch.LongTensor(input_exer_ids), torch.Tensor(input_knowledge_embs), torch.Tensor(ys)

def CD_DL():
    with open(params.src) as i_f:
        src_dataset = json.load(i_f)
    with open(params.tgt) as i_f:
        tgt_dataset = json.load(i_f)
    src_DL = DataLoader(dataset=src_dataset, batch_size=params.batch_size, shuffle=True, collate_fn=my_collate)
    tgt_DL = DataLoader(dataset=tgt_dataset, batch_size=params.batch_size, shuffle=True, collate_fn=my_collate)
    return src_DL, tgt_DL

def slice_d(data = params.all):
    with open(data) as i_f:
        all_dataset = json.load(i_f)
    all_DL = DataLoader(dataset=all_dataset, batch_size=params.batch_size, shuffle=False, collate_fn=my_collate)
    return all_DL
