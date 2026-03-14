import json
import os

# 从环境变量获取数据集名称，如果没有则使用默认值
dataset_name = os.environ.get('CD_DATASET', 'Q-free/DBE22')
dataset = f'data/{dataset_name}/'
batch_size = 128
lr = 0.002
epoch = 100

# src = dataset + 'enhanced_train_d_updated_unlimited.json'
# tgt = dataset + 'enhanced_val_d_updated_unlimited.json'
src = dataset + 'train.json'
tgt = dataset + 'val.json'

test = tgt
all = dataset + 'slice_d.json'

with open(dataset + 'config.txt') as f:
    f.readline()
    un, en, kn = f.readline().split(',')
    un, en, kn = int(un), int(en), int(kn)
latent_dim = kn
kn_select = 21
pass
