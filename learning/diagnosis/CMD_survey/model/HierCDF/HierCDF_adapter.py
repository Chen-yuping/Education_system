import os
import importlib.util
import pandas as pd
import numpy as np
import torch
from django.conf import settings

# 导入 HierCDF 模型
from learning.diagnosis.CMD_survey.model.HierCDF.HierCDF import HierCDF


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


def train_hiercdm(dataset_name, device='cpu'):
    base_path = os.path.join(settings.BASE_DIR, 'learning', 'diagnosis', 'CMD_survey', 'data', dataset_name)

    # 加载数据（文件名根据实际情况调整）
    kg_path = os.path.join(base_path, 'knowledge_graphs_prereq.csv')
    q_path = os.path.join(base_path, 'q_matrix.txt')
    train_path = os.path.join(base_path, 'log_split__train_mini.csv')
    valid_path = os.path.join(base_path, 'log_split__valid_mini.csv')

    know_graph = pd.read_csv(kg_path)
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
    hparams['Hier_log_path'] = log_path

    # 实例化模型
    model = HierCDF(
        n_user=n_user, n_item=n_item, n_know=n_know,
        hidden_dim=hidden_dim, know_graph=know_graph, log_path=log_path,
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
