import os
import importlib.util
import pandas as pd
import numpy as np
import torch
from django.conf import settings

# 导入 PCGCDF 模型及相关函数
from learning.diagnosis.CMD_survey.model.PCGCDF.PCGCDF import (
    MixedModel,
    compute_relation_init,
    compute_know_diff_from_logs,
)


def _load_dataset_config(base_path):
    config_path = os.path.join(base_path, 'config.py')
    module_name = 'cmd_survey_config_{}'.format(os.path.basename(base_path))
    spec = importlib.util.spec_from_file_location(module_name, config_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_log_path(dataset_name):
    model_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(model_dir, 'logs', dataset_name)


def train_mixcdm(dataset_name, device='cpu'):
    base_path = os.path.join(settings.BASE_DIR, 'learning', 'diagnosis', 'CMD_survey', 'data', dataset_name)

    # 加载数据（文件名根据实际情况调整）
    hier_kg_path = os.path.join(base_path, 'knowledge_graphs_prereq.csv')
    con_kg_path = os.path.join(base_path, 'knowledge_edges_ids.csv')
    q_path = os.path.join(base_path, 'q_matrix.txt')
    train_path = os.path.join(base_path, 'log_split__train_mini.csv')
    valid_path = os.path.join(base_path, 'log_split__valid_mini.csv')

    hier_know_graph = pd.read_csv(hier_kg_path)
    con_know_graph = pd.read_csv(con_kg_path)
    q_matrix = np.loadtxt(q_path, delimiter=' ')
    train_df = pd.read_csv(train_path)
    valid_df = pd.read_csv(valid_path)

    config_module = _load_dataset_config(base_path)
    hparams = dict(config_module.hparams)
    n_user = hparams['n_user']
    n_item = hparams['n_item']
    n_know = hparams['n_know']
    hidden_dim = hparams['hidden_dim']
    log_path = _build_log_path(dataset_name)
    hparams['Mixed_log_path'] = log_path

    init_R = compute_relation_init(train_df, q_matrix, con_know_graph)
    init_diff = compute_know_diff_from_logs(train_df, q_matrix, method='inverse_accuracy')

    # 实例化模型
    model = MixedModel(
        n_user=n_user, n_item=n_item, n_know=n_know,
        hidden_dim=hidden_dim, hier_graph=hier_know_graph, con_graph=con_know_graph,
        init_R=init_R, init_diff=init_diff, log_path=log_path,
        itf_type='irt'
    )
    model.to(device)

    # 调用模型的 train 方法，直接获得最佳指标
    best_epoch, best_auc, best_acc, best_rmse = model.train(
        hparams=hparams,
        train_data=train_df,
        Q_matrix=q_matrix,
        valid_data=valid_df
    )

    return best_epoch, best_auc, best_acc, best_rmse
