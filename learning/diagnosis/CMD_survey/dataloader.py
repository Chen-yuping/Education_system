import torch
from torch.utils.data import TensorDataset, DataLoader
import json
import random
import numpy as np
from functools import partial

def _get_config(config=None):
    if config is not None:
        return config
    # 保留命令行旧入口；研究者任务显式传配置，不导入共享 params。
    import params
    return params


def resolve_knowledge_index_base(datasets, knowledge_count, explicit_base=None):
    codes = {code for dataset in datasets for row in dataset for code in row['knowledge_code']}
    if any(type(code) is not int for code in codes):
        raise ValueError('Knowledge codes must be integers.')
    if explicit_base is not None:
        if explicit_base not in (0, 1):
            raise ValueError('knowledge_index_base must be 0 or 1.')
        base = explicit_base
    elif not codes:
        return 0
    elif 0 in codes:
        base = 0
    elif knowledge_count in codes:
        base = 1
    else:
        raise ValueError('Ambiguous knowledge numbering; configure params.knowledge_index_base as 0 or 1.')
    if any(not 0 <= code - base < knowledge_count for code in codes):
        raise ValueError('Knowledge codes are out of range or mix zero-based and one-based numbering.')
    return base


def my_collate(batch, knowledge_index_base=0, knowledge_count=None):
    knowledge_count = _get_config().kn if knowledge_count is None else knowledge_count
    input_stu_ids, input_exer_ids, input_knowledge_embs, ys = [], [], [], []
    for log in batch:
        if log['knowledge_code']==[]:
            knowledge_emb = [1.0] * knowledge_count
        else:
            knowledge_emb = [0.] * knowledge_count
            for knowledge_code in log['knowledge_code']:
                index = knowledge_code - knowledge_index_base
                if not 0 <= index < knowledge_count:
                    raise ValueError(f'Knowledge code {knowledge_code} is out of range.')
                knowledge_emb[index] = 1.0
        y = log['score']
        input_stu_ids.append(log['user_id'])
        input_exer_ids.append(log['exer_id'])
        input_knowledge_embs.append(knowledge_emb)
        ys.append(y)

    return torch.LongTensor(input_stu_ids), torch.LongTensor(input_exer_ids), torch.Tensor(input_knowledge_embs), torch.Tensor(ys)

def CD_DL(config=None):
    config = _get_config(config)
    with open(config.src) as i_f:
        src_dataset = json.load(i_f)
    with open(config.tgt) as i_f:
        tgt_dataset = json.load(i_f)
    base = resolve_knowledge_index_base(
        [src_dataset, tgt_dataset], config.kn, getattr(config, 'knowledge_index_base', None))
    collate = partial(my_collate, knowledge_index_base=base, knowledge_count=config.kn)
    src_DL = DataLoader(dataset=src_dataset, batch_size=config.batch_size, shuffle=True, collate_fn=collate)
    tgt_DL = DataLoader(dataset=tgt_dataset, batch_size=config.batch_size, shuffle=True, collate_fn=collate)
    return src_DL, tgt_DL

def slice_d(data=None, config=None):
    config = _get_config(config)
    data = config.all if data is None else data
    with open(data) as i_f:
        all_dataset = json.load(i_f)
    base = resolve_knowledge_index_base(
        [all_dataset], config.kn, getattr(config, 'knowledge_index_base', None))
    collate = partial(my_collate, knowledge_index_base=base, knowledge_count=config.kn)
    all_DL = DataLoader(dataset=all_dataset, batch_size=config.batch_size, shuffle=False, collate_fn=collate)
    return all_DL
