import sys
import os

import gc
import networkx as nx
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score, mean_squared_error
import time
import torch
import torch.nn as nn
import warnings

from dataloader import TrainDataLoader
from itf import mirt2pl, sigmoid_dot, dot, itf_dict
from tools import Logger, df_preview, format_hparams, labelize, to_numpy

warnings.filterwarnings('ignore')
torch.set_default_tensor_type(torch.DoubleTensor)


class HierCDF(nn.Module):
    '''
    The hierarchical cognitive diagnosis model
    '''

    def __init__(self, n_user, n_item, n_know, hidden_dim, know_graph: pd.DataFrame, itf_type='mirt', \
                 log_path='./log/'):

        super(HierCDF, self).__init__()
        self.logger = Logger(path=log_path)
        self.max_exercise_id = None

        self.n_user = n_user
        self.n_item = n_item
        self.n_know = n_know
        self.hidden_dim = hidden_dim
        self.know_graph = know_graph
        self.know_edge = nx.DiGraph()  # nx.DiGraph(know_graph.values.tolist())

        # 添加结点
        for k in range(n_know):
            self.know_edge.add_node(k)

        # 添加边
        for edge in know_graph.values.tolist():
            self.know_edge.add_edge(edge[0], edge[1])

        # 将表示知识的图进行拓扑排序，排序点和边
        self.topo_order = list(nx.topological_sort(self.know_edge))

        # the conditional mastery degree when parent is mastered父结点掌握时的概率
        condi_p = torch.Tensor(n_user, know_graph.shape[0])
        self.condi_p = nn.Parameter(condi_p)

        # the conditional mastery degree when parent is non-mastered父结点未掌握的概率
        condi_n = torch.Tensor(n_user, know_graph.shape[0])
        self.condi_n = nn.Parameter(condi_n)

        # the priori mastery degree of parent父结点的先验概率
        priori = torch.Tensor(n_user, n_know)
        self.priori = nn.Parameter(priori)

        # item representation题目表示：难度和区分度
        self.item_diff = nn.Embedding(n_item, n_know)
        self.item_disc = nn.Embedding(n_item, 1)

        # embedding transformation嵌入层：将知识点维度映射到隐藏层维度
        self.user_contract = nn.Linear(n_know, hidden_dim)
        self.item_contract = nn.Linear(n_know, hidden_dim)

        # Neural Interaction Module (used only in ncd)神经交互模块（只用于ncd）
        self.cross_layer1 = nn.Linear(hidden_dim, max(int(hidden_dim / 2), 1))
        self.cross_layer2 = nn.Linear(max(int(hidden_dim / 2), 1), 1)

        # layer for featrue cross module设置交互函数类型
        self.set_itf(itf_type)

        # param initialization参数初始化 Xavier是一种初始化方法
        nn.init.xavier_normal_(self.priori)
        nn.init.xavier_normal_(self.condi_p)
        nn.init.xavier_normal_(self.condi_n)
        for name, param in self.named_parameters():
            if 'weight' in name:
                nn.init.xavier_normal_(param)

    '''
    神经认知诊断交互函数
    参数：
    user_emb:用户嵌入表示
    item_emb:题目嵌入表示
    item_offset:题目偏移量（区分度）

    返回：
    预测得分
    '''

    def ncd(self, user_emb: torch.Tensor, item_emb: torch.Tensor, item_offset: torch.Tensor):
        input_vec = (user_emb - item_emb) * item_offset
        x_vec = torch.sigmoid(self.cross_layer1(input_vec))
        x_vec = torch.sigmoid(self.cross_layer2(x_vec))
        return x_vec

    '''
    设置交互函数类型
    '''

    def set_itf(self, itf_type):
        self.itf_type = itf_type
        self.itf = itf_dict.get(itf_type, self.ncd)

    '''
    计算用户知识点后验掌握概率（贝叶斯网络推理）
    计算了包括c+
    eq.8~eq.10等公式
    参数：
    user_ids:用户ID张量
    device:计算设备

    返回：
    后验掌握概率矩阵：[batch_size,n_know]
    '''

    def get_posterior(self, user_ids: torch.LongTensor, device='cpu') -> torch.Tensor:
        n_batch = user_ids.shape[0]  # 获取user_ids的batch信息，表示用户数量（学生数）

        # 初始化posterior，其形式为（n_batch,n_know）
        # posterior存后验概率，行表示单一用户对不同知识点的掌握情况，
        #                   列表示单一知识点在不同用户的体现
        posterior = torch.rand(n_batch, self.n_know).to(device)

        # 获取批量参数并用sigmoid函数激活
        batch_priori = torch.sigmoid(self.priori[user_ids, :])  # 取出与user_ids相对应编号的priori信息，这里取出的是各自的n_know信息
        batch_condi_p = torch.sigmoid(self.condi_p[user_ids, :])  # c+
        batch_condi_n = torch.sigmoid(self.condi_n[user_ids, :])  # c-

        # self.logger.write('batch_priori:{}'.format(batch_priori.requires_grad),'console')

        # 按拓扑顺序计算每个知识点的后验概率
        # for k in range(self.n_know):
        for k in self.topo_order:
            # get predecessor list获取当前知识点的所有父结点
            predecessors = list(self.know_edge.predecessors(k))  # predecessors(k)返回图中的边m，且m->k存在有向边
            predecessors.sort()
            len_p = len(predecessors)

            # for each knowledge k, do:
            # 无父节点的情况:从先验(priori)中找到该无父节点的概率，然后传给对应的后验概率（posterior）
            if len_p == 0:
                priori = batch_priori[:, k]
                posterior[:, k] = priori.reshape(-1)
                continue

            # format of masks生成所有父结点掌握状态的掩码,规定掩码的形式，确定长度信息
            fmt = '{0:0%db}' % (len_p)
            # number of parent master condition父结点状态组合数，有len_p个父节点，就有2^len_p个不同掌握情况
            n_condi = 2 ** len_p

            # sigmoid to limit priori to (0,1)
            # priori = batch_priori[:,predecessors]获取父结点的后验概率，由于是拓扑排序，父结点的后验概率已经得出，因此传给对应的先验概率表示
            priori = posterior[:, predecessors]

            # self.logger.write('priori:{}'.format(priori.requires_grad),'console')

            # 获取当前知识点的条件概率参数
            pred_idx = self.know_graph[self.know_graph['to'] == k].sort_values(by='from').index
            condi_p = torch.pow(batch_condi_p[:, pred_idx], 1 / len_p)  # c+,经过几何平均进行了调整，防止结果过大
            condi_n = torch.pow(batch_condi_n[:, pred_idx], 1 / len_p)

            # 计算边际概率，Eq.(7)的C（θ）的计算的准备
            margin_p = condi_p * priori
            margin_n = condi_n * (1.0 - priori)

            # 创建全0张量，这里形式为1行n_batch列
            posterior_k = torch.zeros((1, n_batch)).to(device)

            # 对所有父结点状态组合进行边缘化
            for idx in range(n_condi):
                # for each parent mastery condition, do:
                mask = fmt.format(idx)
                # 二进制字符串-->Python字符串数组-->numpy数组-->数组各值转化为int-->Tensor
                mask = torch.Tensor(np.array(list(mask)).astype(int)).to(device)

                # mask相当于θ，对应位为1时为margin_p，否则为margin_n，这里是c(θ)的正式计算
                '''
                论文中的Eq.(8)和Eq.(9)中都有θ_i_jz，通过Eq.(10)与Eq.(9)的联合，Eq.(10)可化为先累乘后累加的形式
                当其为1时，Eq.(10)的累乘各项就可表示为：m*(c+)^(1/q)---->margin_p
                当其为0时，Eq.(10)的累乘各项可表示为：(1-m)*(c-)^(1/q)---->margin_n
                综合考虑0,1时即为margin
                '''
                margin = mask * margin_p + (1 - mask) * margin_n
                margin = torch.prod(margin, dim=1).unsqueeze(dim=0)  # 将margin的各个乘项相乘，并转换成与posterior_k相对应的形状格式，方便后续拼接操作

                # posterior_k每行代表一个父结点掌握情况组合，每列代表一个用户
                # 通过cat在posterior中添加新的一个组合行margin
                posterior_k = torch.cat([posterior_k, margin], dim=0)
            posterior_k = (torch.sum(posterior_k, dim=0)).squeeze()  # 计算完累乘后继续计算公式里的累加

            posterior[:, k] = posterior_k.reshape(-1)  # 将当前计算节点k的各个用户的结果更新至posterior中

        return posterior

    '''
    计算父结点都掌握的情况下的极端(c+)^(len_p)
    用于分析和解释
    '''

    def get_condi_p(self, user_ids: torch.LongTensor, device='cpu') -> torch.Tensor:
        n_batch = user_ids.shape[0]
        result_tensor = torch.rand(n_batch, self.n_know).to(device)
        batch_priori = torch.sigmoid(self.priori[user_ids, :])
        batch_condi_p = torch.sigmoid(self.condi_p[user_ids, :])

        # for k in range(self.n_know):
        for k in self.topo_order:
            # get predecessor list
            predecessors = list(self.know_edge.predecessors(k))
            predecessors.sort()
            len_p = len(predecessors)
            if len_p == 0:
                priori = batch_priori[:, k]
                result_tensor[:, k] = priori.reshape(-1)
                continue
            pred_idx = self.know_graph[self.know_graph['to'] == k].sort_values(by='from').index
            condi_p = torch.pow(batch_condi_p[:, pred_idx], 1 / len_p)
            result_tensor[:, k] = torch.prod(condi_p, dim=1).reshape(-1)

        return result_tensor

    '''
    计算父结点都未掌握的情况下的极端(c-)^(len_p)
    用于分析和解释
    '''

    def get_condi_n(self, user_ids: torch.LongTensor, device='cpu') -> torch.Tensor:
        n_batch = user_ids.shape[0]
        result_tensor = torch.rand(n_batch, self.n_know).to(device)
        batch_priori = torch.sigmoid(self.priori[user_ids, :])
        batch_condi_n = torch.sigmoid(self.condi_n[user_ids, :])

        # for k in range(self.n_know):
        for k in self.topo_order:
            # get predecessor list
            predecessors = list(self.know_edge.predecessors(k))
            predecessors.sort()
            len_p = len(predecessors)
            if len_p == 0:
                priori = batch_priori[:, k]
                result_tensor[:, k] = priori.reshape(-1)
                continue
            pred_idx = self.know_graph[self.know_graph['to'] == k].sort_values(by='from').index
            condi_n = torch.pow(batch_condi_n[:, pred_idx], 1 / len_p)
            result_tensor[:, k] = torch.prod(condi_n, dim=1).reshape(-1)

        return result_tensor

    '''
    自制拼接操作
    '''

    def concat(self, a, b, dim=0):
        if a is None:
            return b.reshape(-1, 1)
        else:
            return torch.cat([a, b], dim=dim)

    def _infer_item_column(self, data: pd.DataFrame):
        if data is None:
            return None
        for candidate in ('exercise_id', 'exer_id', 'item_id'):
            if candidate in data.columns:
                return candidate
        return None

    def _filter_samples_by_item_id(self, data: pd.DataFrame, max_item_id: int, logger_mode: str = 'console',
                                   stage: str = ''):
        if data is None or max_item_id is None:
            return data
        item_col = self._infer_item_column(data)
        if item_col is None:
            self.logger.write('Skip {} filtering: no exercise id column detected.'.format(stage or 'data'), logger_mode)
            return data
        mask = data[item_col] < max_item_id
        filtered = data.loc[mask].reset_index(drop=True)
        removed = data.shape[0] - filtered.shape[0]
        if removed > 0:
            self.logger.write('Filtered {} / {} {} records with {} >= {}'.format(
                removed, data.shape[0], stage or 'data', item_col, max_item_id), logger_mode)
        if filtered.shape[0] == 0:
            self.logger.write('Warning: {} is empty after filtering by {}'.format(stage or 'data', item_col),
                              logger_mode)
        return filtered

    def forward(self, user_ids: torch.LongTensor, item_ids: torch.LongTensor, item_know: torch.Tensor,
                device='cpu') -> torch.Tensor:
        '''
        论文主要的整体操作步骤
        @Param item_know: the item q matrix of the batch
        '''
        # 论文中的认知状态模块(Cofnitive State)
        user_mastery = self.get_posterior(user_ids, device)  # 获取后验掌握情况

        # 论文中的问题特征模块(Question Feature)
        # item_diff本身为（n_item,n_know）的嵌入向量，即n_item个n_know维的向量
        # 这里提取出item_ids对应的几个向量，对他们进行sigmoid激活
        item_diff = torch.sigmoid(self.item_diff(item_ids))
        item_disc = torch.sigmoid(self.item_disc(item_ids))

        # 论文中的适配器模块(CDM Adaptor)
        # user_mastery每行存的是对应用户对各个知识点的掌握情况，可以有多行表示同一个用户，user_ids是以记录形式存在，以确保与item_ids可相乘
        # item_know每行存的是对应习题对各个知识点的掌握情况，与user_mastery一样可以多行表示一个题
        user_factor = torch.tanh(self.user_contract(user_mastery * item_know))
        # item_diff每行存的是对应习题对各个知识点的考察难度
        item_factor = torch.sigmoid(self.item_contract(item_diff * item_know))

        # 调用现有模型进行诊断
        output = self.itf(user_factor, item_factor, item_disc)

        return output

    def train(self, hparams: dict, train_data: pd.DataFrame, Q_matrix: np.array, valid_data: pd.DataFrame = None):
        # 从config文件中导入相关配置
        lr = hparams.get('lr', 0.01)
        epoch = hparams.get('epoch', 5)
        batch_size = hparams.get('batch_size', 64)
        logger_mode = hparams.get('logger_mode', 'both')
        loss_factor = hparams.get('loss_factor', 1.0)
        device = hparams.get('device', 'cpu')
        batch_show = hparams.get('batch_show', 200)
        self.max_exercise_id = hparams.get('max_exercise_id', None)

        # 将配置信息写入日志
        self.logger.write('Before HierCDF train.\n{}'.format(format_hparams(hparams)), logger_mode)

        # 转换设备可用数据
        self._to_device(device)

        train_data = self._filter_samples_by_item_id(train_data, self.max_exercise_id, logger_mode, 'train')
        if train_data.shape[0] == 0:
            raise ValueError('No training samples left after applying max_exercise_id={}'.format(self.max_exercise_id))
        if not valid_data is None:
            valid_data = self._filter_samples_by_item_id(valid_data, self.max_exercise_id, logger_mode, 'valid')
            if valid_data.shape[0] == 0:
                self.logger.write('Valid data empty after filtering. Skip validation stage.', logger_mode)
                valid_data = None

        # 选择NLLLoss损失函数
        loss_fn = MyLoss(self, nn.NLLLoss, loss_factor)

        dataloader = TrainDataLoader(train_data, Q_matrix, batch_size)

        optimizer = torch.optim.Adam(params=self.parameters(), lr=lr)

        y_target_all = np.array(train_data.loc[:, 'score']).astype(np.int_)

        # 记录最佳指标
        best_epoch = -1
        best_auc = 0.0
        best_acc = 0.0
        best_rmse = float('inf')

        for step in range(1, epoch + 1):
            dataloader.reset(shuffle=False)
            n_batch = 0
            y_pred_all = np.array([])
            loss_all = 0.0
            batch_count = 0
            while not dataloader.is_end():
                optimizer.zero_grad()
                user_ids, item_ids, item_know, y_target = dataloader.next_batch()
                user_ids = user_ids.to(device)
                item_ids = item_ids.to(device)
                item_know = item_know.to(device)
                y_target = y_target.to(device)
                y_pred = self.forward(user_ids, item_ids, item_know, device)

                output_1 = y_pred  # 预测正确概率
                output_0 = torch.ones(output_1.size()).to(device) - output_1  # 预测失败概率
                output = torch.cat((output_0, output_1), 1)
                # 计算损失函数，这里是论文里的eq14,取对数是为了能够使用NLLLoss（要求对数概率）
                loss = loss_fn(torch.log(output), y_target, user_ids)
                loss.backward()
                optimizer.step()

                # pos_clipper是确保数据非负的函数
                self.pos_clipper([self.user_contract, self.item_contract])
                self.pos_clipper([self.cross_layer1, self.cross_layer2])

                # 将预测结果变为整数数组
                y_pred_batch = labelize(y_pred)
                # 将该轮预测结果链接到总数组中
                y_pred_all = np.concatenate([y_pred_all, y_pred_batch], axis=0)

                loss_all += loss.item()
                n_batch += 1

                if batch_count % batch_show == batch_show - 1:
                    self.logger.write('HierCDF:'
                                      'epoch = {}, batch = {}, loss = {}'.format(
                        step, batch_count, loss_all / batch_show), logger_mode)
                    loss_all = 0.0
                batch_count += 1

            train_acc = accuracy_score(y_target_all, y_pred_all)
            train_f1 = f1_score(y_target_all, y_pred_all)

            self.logger.write('HierCDF:'
                              'epoch = {}, train_f1 = {}'.format(step, train_acc), logger_mode)
            if not valid_data is None:
                metrics = self.validate(valid_data, Q_matrix, device, logger_mode)
                auc = metrics['auc']
                acc = metrics['acc']
                rmse = metrics['mse']  # 原 validate 返回的 mse 是均方误差，不是 rmse，这里转换一下
                if 'rmse' not in metrics:
                    rmse = np.sqrt(rmse) if rmse > 0 else 0.0

                if auc > best_auc:
                    best_auc = auc
                    best_acc = acc
                    best_rmse = rmse
                    best_epoch = step
            # 返回最佳指标
        if valid_data is None:
            return None, None, None, None
        else:
            return best_epoch, best_auc, best_acc, best_rmse

    '''
    clip the parameters of each module in the moduleList to nonnegative
    '''

    def pos_clipper(self, module_list: list):
        for module in module_list:
            module.weight.data = module.weight.clamp_min(0)
        return

    def neg_clipper(self, module_list: list):
        for module in module_list:
            module.weight.data = module.weight.clamp_max(0)
        return

    def predict(self, data: pd.DataFrame, Q_matrix: np.array, device='cpu') -> pd.DataFrame:
        data = self._filter_samples_by_item_id(data, self.max_exercise_id, 'console', 'predict')
        if data is None or data.shape[0] == 0:
            self.logger.write('Predict skipped: no samples remain after filtering by max_exercise_id.', 'console')
            if data is None:
                return pd.DataFrame(columns=['predict_score', 'predict_label'])
            empty_df = data.copy()
            empty_df['predict_score'] = pd.Series(dtype=float)
            empty_df['predict_label'] = pd.Series(dtype=float)
            return empty_df
        dataloader = TrainDataLoader(data, Q_matrix, 8192)
        dataloader.reset(shuffle=False)
        df_pred = pd.DataFrame(columns=['predict_score', 'predict_label'])
        self._to_device(device)
        while not dataloader.is_end():
            # next_batch每次调用都取一批次数据
            user_ids, item_ids, item_know, _ = dataloader.next_batch()
            user_ids = user_ids.to(device)
            item_ids = item_ids.to(device)
            item_know = item_know.to(device)

            z_output = self.forward(user_ids, item_ids, item_know, device=device)
            z_score = to_numpy(z_output).reshape(-1)
            z_label = labelize(z_output).reshape(-1)
            df_batch = pd.DataFrame({
                'predict_score': z_score,
                'predict_label': z_label
            })
            # 当需要在列表后再次添加一行元素时要避免索引重置，因此设置ignore_index为True
            df_pred = df_pred._append(df_batch, ignore_index=True)

        # 重置索引是为了避免连接时出错
        result = data.reset_index().join(df_pred)

        return result

    def validate(self, valid_data: pd.DataFrame, Q_matrix: np.array, device, logger_mode):
        valid_pred = self.predict(valid_data, Q_matrix, device)
        z_true = valid_pred['score'].astype(int).tolist()
        z_score = valid_pred['predict_score'].tolist()
        z_label = valid_pred['predict_label'].tolist()

        valid_acc = accuracy_score(z_true, z_label)
        valid_auc = roc_auc_score(z_true, z_score)
        valid_f1 = f1_score(z_true, z_label)
        valid_mse = mean_squared_error(z_true, z_score)

        self.logger.write('HierCDF:'
                          'valid acc = {}'.format(valid_acc), logger_mode)
        self.logger.write('HierCDF:'
                          'valid f1  = {}'.format(valid_f1), logger_mode)
        self.logger.write('HierCDF:'
                          'valid auc = {}'.format(valid_auc), logger_mode)
        self.logger.write('HierCDF:'
                          'valid mse = {}\n'.format(valid_mse), logger_mode)

        metrics_dict = {}
        metrics_dict['acc'] = (valid_acc)
        metrics_dict['f1'] = (valid_f1)
        metrics_dict['auc'] = (valid_auc)
        metrics_dict['mse'] = (valid_mse)

        return metrics_dict

    def _to_device(self, device):
        self.priori = nn.Parameter(self.priori.to(device))
        self.condi_p = nn.Parameter(self.condi_p.to(device))
        self.condi_n = nn.Parameter(self.condi_n.to(device))
        self.user_contract = self.user_contract.to(device)
        self.item_contract = self.item_contract.to(device)
        self.item_diff = self.item_diff.to(device)
        self.item_disc = self.item_disc.to(device)
        self.cross_layer1 = self.cross_layer1.to(device)
        self.cross_layer2 = self.cross_layer2.to(device)

    def save(self, model_name='./model.pkl'):
        path = '/'.join(model_name.split('/')[:-1]) + '/'
        if not os.path.exists(path):
            os.makedirs(path)
        torch.save(self.state_dict(), model_name)

    def load(self, model_name='./model.pkl'):
        self.load_state_dict(torch.load(model_name))


class MyLoss(nn.Module):
    '''
    The loss function of HierCDM
    '''

    def __init__(self, net: HierCDF, loss_fn: nn.Module, factor=1.0):
        super(MyLoss, self).__init__()
        self.net = net
        self.factor = factor
        self.loss_fn = loss_fn()

    def forward(self, y_pred, y_target, user_ids):
        '''
        @Param:y_pred: 预测结果
        @Param:y_target: 实际标签
        @Param:user_ids: 用户id
        当c->c+时会产生惩罚项(即论文中的eq5，J(Ω))
        整体是在计算eq14
        '''
        return self.loss_fn(y_pred, y_target) + self.factor * torch.sum(
            torch.relu(self.net.condi_n[user_ids, :] - self.net.condi_p[user_ids, :]))
