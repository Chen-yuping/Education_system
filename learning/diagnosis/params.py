import json
import os

# 从环境变量获取subject_id，如果没有则使用默认值
subject_id = os.environ.get('CD_DATASET', '1')
# 修改路径指向 learning/diagnosis/data/{subject_id}/
dataset = f'learning/diagnosis/data/{subject_id}/'

batch_size = 128
lr = 0.002
epoch = 10

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
