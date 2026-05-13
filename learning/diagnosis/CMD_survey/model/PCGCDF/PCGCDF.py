import os
import networkx as nx
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score, mean_squared_error
import torch
import torch.nn as nn
import warnings
import torch.nn.functional as F
from torch.nn.init import zeros_
from dataloader import TrainDataLoader
from itf import mirt2pl, sigmoid_dot, dot, itf_dict
from tools import Logger, df_preview, format_hparams, labelize, to_numpy

torch.set_default_tensor_type(torch.DoubleTensor)   # 注释或删除这一行

class ConCDF(nn.Module):
    '''
    The hierarchical cognitive diagnosis model
    '''

    def __init__(self, n_user, n_item, n_know, hidden_dim, know_graph: pd.DataFrame,priori,know_diff,edge_logits,relatin_strength,itf_type='mirt', \
                 log_path='./log/',init_R=None,init_diff=None):

        super(ConCDF, self).__init__()
        self.logger = Logger(path=log_path)

        self.n_user = n_user
        self.n_item = n_item
        self.n_know = n_know
        self.hidden_dim = hidden_dim
        self.know_graph = know_graph
        self.know_edge = nx.DiGraph()  # nx.DiGraph(know_graph.values.tolist())
        self.num_edges = know_graph.shape[0]


        # 添加结点
        for k in range(n_know):
            self.know_edge.add_node(k)

        # 添加边
        for edge in know_graph.values.tolist():
            self.know_edge.add_edge(edge[0], edge[1])

        # 将表示知识的图进行拓扑排序，排序点和边
        self.topo_order = list(nx.topological_sort(self.know_edge))

        #####相关度初始化
        self.relation_strength = relatin_strength

        ##### 知识点难度初始化
        self.know_diff = know_diff

        #####边权重初始化
        self.edge_logits = edge_logits

        ##### 构建每个目标节点的前驱节点列表及对应边索引
        self.pred_nodes = [[] for _ in range(n_know)]
        self.pred_edge_idx = [[] for _ in range(n_know)]
        for idx, row in know_graph.iterrows():
            src, tgt = int(row['from']), int(row['to'])
            self.pred_nodes[tgt].append(src)
            self.pred_edge_idx[tgt].append(idx)

        # the priori mastery degree of parent父结点的先验概率
        self.priori = priori

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

    '''
    神经认知诊断交互函数
    参数：
    user_emb:用户嵌入表示
    item_emb:题目嵌入表示
    item_offset:题目偏移量（区分度）

    返回：
    预测得分
    '''

    def get_edge_weights(self):
        """返回每条边的 (alpha, beta)，满足 alpha + beta = 1"""
        weights = F.softmax(self.edge_logits, dim=-1)  # (E, 2)
        alpha = weights[:, 0]  # 难度权重
        beta = weights[:, 1]  # 相关度权重
        return alpha, beta

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

    def get_posterior(self, user_ids, device='cpu'):
        batch_size = user_ids.shape[0]
        priori_logit = self.priori[user_ids]                # (B, K)

        # 确保难度、关联度为正
        diff_pos = F.softplus(self.know_diff)               # (K,)
        rel_pos  = F.softplus(self.relation_strength)       # (E,)

        # 获取边权重 alpha, beta
        alpha, beta = self.get_edge_weights()               # 各 (E,)

        posterior = torch.zeros(batch_size, self.n_know).to(device)

        for k in self.topo_order:
            preds = self.pred_nodes[k]
            eids  = self.pred_edge_idx[k]

            if len(preds) == 0:
                # 无前驱：仅由先验和难度决定
                m = torch.sigmoid(priori_logit[:, k] - diff_pos[k])
                posterior[:, k] = m
            else:
                # 父节点掌握度 (已按拓扑顺序计算)
                m_parents = posterior[:, preds]

                # 提取对应参数
                diff_p = diff_pos[preds]
                alpha_p = alpha[eids]
                beta_p  = beta[eids]
                rel_p   = rel_pos[eids]

                # 计算原始权重
                w = diff_p * alpha_p + rel_p * beta_p
                w_sum = w.sum(dim=0, keepdim=True)
                w_norm = w / (w_sum + 1e-10)

                #广义均值
                m_safe = m_parents.clamp(min=1e-8, max=1.0)
                p = -2.0
                m_k = torch.pow((torch.pow(m_safe, p) * w_norm.unsqueeze(0)).sum(dim=1), 1.0 / p)

                posterior[:, k] = m_k

        return posterior

    '''
    自制拼接操作
    '''

    def concat(self, a, b, dim=0):
        if a is None:
            return b.reshape(-1, 1)
        else:
            return torch.cat([a, b], dim=dim)



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

    def _to_device(self, device):
        #self.to(device)
        self.priori = nn.Parameter(self.priori.to(device))
        self.user_contract = self.user_contract.to(device)
        self.item_contract = self.item_contract.to(device)
        self.item_diff = self.item_diff.to(device)
        self.item_disc = self.item_disc.to(device)
        self.cross_layer1 = self.cross_layer1.to(device)  # 对于 nn.Module 对象，.to() 可直接赋值
        self.cross_layer2 = self.cross_layer2.to(device)
        self.relation_strength.data = nn.Parameter(self.relation_strength.data.to(device))
        self.know_diff.data = nn.Parameter(self.know_diff.data.to(device))
        self.edge_logits.data = nn.Parameter(self.edge_logits.data.to(device))

    def save(self, model_name='./model.pkl'):
        path = '/'.join(model_name.split('/')[:-1]) + '/'
        if not os.path.exists(path):
            os.makedirs(path)
        torch.save(self.state_dict(), model_name)

    def load(self, model_name='./model.pkl'):
        self.load_state_dict(torch.load(model_name))

class HierCDF(nn.Module):
    '''
    The hierarchical cognitive diagnosis model
    '''

    def __init__(self, n_user, n_item, n_know, hidden_dim, know_graph: pd.DataFrame,priori,condi_n,condi_p,itf_type='mirt', \
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
        self.condi_p = condi_p

        # the conditional mastery degree when parent is non-mastered父结点未掌握的概率
        self.condi_n = condi_n

        # the priori mastery degree of parent父结点的先验概率
        self.priori = priori

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

class MixedModel(nn.Module):
    def __init__(self, n_user, n_item, n_know, hidden_dim, hier_graph: pd.DataFrame, con_graph: pd.DataFrame, itf_type='mirt', \
                 log_path='./log/', init_R=None, init_diff=None, embed_dim=16):

        super(MixedModel, self).__init__()
        self.logger = Logger(path=log_path)
        self.max_exercise_id = None

        self.n_user = n_user
        self.n_item = n_item
        self.n_know = n_know
        self.hidden_dim = hidden_dim
        self.hier_graph = hier_graph
        self.con_graph = con_graph

        priori = torch.Tensor(n_user,n_know)
        self.priori = nn.Parameter(priori)

        condi_n = torch.Tensor(n_user,hier_graph.shape[0])
        self.condi_n = nn.Parameter(condi_n)

        condi_p = torch.Tensor(n_user,hier_graph.shape[0])
        self.condi_p = nn.Parameter(condi_p)

        #####相关度初始化
        if init_R is not None:
            init_R = torch.tensor(init_R, dtype=torch.float32)
        else:
            init_R = torch.randn(self.num_edges) * 0.1
        self.relation_strength = nn.Parameter(init_R)

        ##### 知识点难度初始化
        if init_diff is not None:
            init_diff = torch.tensor(init_diff, dtype=torch.float32)
        else:
            init_diff = torch.randn(n_know) * 0.1  # 随机初始化
        self.know_diff = nn.Parameter(init_diff)

        #####边权重初始化
        self.edge_logits = nn.Parameter(torch.Tensor(con_graph.shape[0], 2))

        self.HierCDF = HierCDF(n_user=n_user, n_item=n_item,n_know=n_know,hidden_dim=hidden_dim,
                               know_graph=hier_graph,
                               priori=self.priori,condi_n=self.condi_n,condi_p=self.condi_p,
                               itf_type=itf_type,log_path=log_path)
        self.ConCDF = ConCDF(n_user=n_user, n_item=n_item,n_know=n_know,hidden_dim=hidden_dim,
                             know_graph=con_graph,
                             priori=self.priori,know_diff=self.know_diff,edge_logits=self.edge_logits,relatin_strength=self.relation_strength,
                             itf_type=itf_type,log_path=log_path)

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

        nn.init.xavier_normal_(self.priori)
        nn.init.xavier_normal_(self.condi_p)
        nn.init.xavier_normal_(self.condi_n)
        nn.init.xavier_uniform_(self.edge_logits)
        for name, param in self.named_parameters():
            if 'weight' in name:
                nn.init.xavier_normal_(param)


        # Gating mechanism
        self.know_embed = nn.Embedding(n_know, embed_dim)
        context_dim = embed_dim + 1  # avg_mastery (1) + know_vec (embed_dim) + know_diff (1)
        self.gate_layer = nn.Linear(context_dim, 2)  # 2 models: HierCDF and ConCDF

        # layer for featrue cross module设置交互函数类型
        self.set_itf(itf_type)

        # param initialization参数初始化 Xavier是一种初始化方法
        nn.init.xavier_normal_(self.priori)
        nn.init.xavier_normal_(self.condi_p)
        nn.init.xavier_normal_(self.condi_n)
        nn.init.xavier_uniform_(self.edge_logits)
        nn.init.normal_(self.know_embed.weight, mean=0.0, std=0.01)
        nn.init.xavier_uniform_(self.gate_layer.weight)
        nn.init.zeros_(self.gate_layer.bias)
        # Inject prior bias
        with torch.no_grad():
            self.gate_layer.bias[0] = 0.5  # HierCDF initial positive

        for name, param in self.named_parameters():
            if 'weight' in name and 'gate_layer' not in name and 'know_embed' not in name:
                nn.init.xavier_normal_(param)

    def set_itf(self, itf_type):
        self.itf_type = itf_type
        self.itf = itf_dict.get(itf_type, self.ncd)

    def ncd(self, user_emb: torch.Tensor, item_emb: torch.Tensor, item_offset: torch.Tensor):
        input_vec = (user_emb - item_emb) * item_offset
        x_vec = torch.sigmoid(self.cross_layer1(input_vec))
        x_vec = torch.sigmoid(self.cross_layer2(x_vec))
        return x_vec

    def get_edge_weights(self):
        """返回每条边的 (alpha, beta)，满足 alpha + beta = 1"""
        weights = F.softmax(self.edge_logits, dim=-1)  # (E, 2)
        alpha = weights[:, 0]  # 难度权重
        beta = weights[:, 1]  # 相关度权重
        return alpha, beta

    def get_posterior(self, user_ids: torch.LongTensor, device='cpu') -> torch.Tensor:
        batch_size = user_ids.shape[0]
        con_posterior=self.ConCDF.get_posterior(user_ids, device)
        hier_posterior = self.HierCDF.get_posterior(user_ids, device)

        posterior = torch.zeros(batch_size, self.n_know).to(device)

        for k in self.HierCDF.topo_order:
            # Build context vector h
            know_vec = self.know_embed(torch.tensor(k, device=device))
            know_vec = know_vec.unsqueeze(0).expand(batch_size, -1)  # (batch, embed_dim)
            know_diff_val = self.know_diff[k].view(1, 1).expand(batch_size, 1)  # (batch, 1)
            h = torch.cat([know_vec, know_diff_val], dim=1)  # (batch, context_dim)

            # Compute gate weights
            gate_logits = self.gate_layer(h)  # (batch, 2)
            gate_weights = F.softmax(gate_logits, dim=-1)  # (batch, 2)

            # Weighted fusion
            m_k = gate_weights[:, 0] * hier_posterior[:,k] + gate_weights[:, 1] * con_posterior[:,k]

            posterior[:, k] = m_k

        return posterior

    def forward(self, user_ids: torch.LongTensor, item_ids: torch.LongTensor, item_know: torch.Tensor,
                device='cpu') -> torch.Tensor:
        '''
        论文主要的整体操作步骤
        @Param item_know: the item q matrix of the batch
        '''
        # 论文中的认知状态模块(Cognitive State)
        user_mastery = self.get_posterior(user_ids, device)  # 获取后验掌握情况

        # 论文中的问题特征模块(Question Feature)
        item_diff = torch.sigmoid(self.item_diff(item_ids))
        item_disc = torch.sigmoid(self.item_disc(item_ids))

        # 论文中的适配器模块(CDM Adaptor)
        user_factor = torch.tanh(self.user_contract(user_mastery * item_know))
        item_factor = torch.sigmoid(self.item_contract(item_diff * item_know))

        # 调用现有模型进行诊断
        output = self.itf(user_factor, item_factor, item_disc)

        return output

    def _to_device(self, device):
        self.to(device)

    def pos_clipper(self, layers):
        for layer in layers:
            layer.weight.data.clamp_(0)

    def train(self, hparams: dict, train_data: pd.DataFrame, Q_matrix: np.array, valid_data: pd.DataFrame = None):
        # 从config文件中导入相关配置
        lr = hparams.get('mixed_lr', 0.01)
        #weight_decay = hparams.get('weight_decay', 0.0)
        epoch = hparams.get('epoch', 5)
        batch_size = hparams.get('batch_size', 64)
        logger_mode = hparams.get('logger_mode', 'both')
        loss_factor = hparams.get('loss_factor', 1.0)
        device = hparams.get('device', 'cpu')
        batch_show = hparams.get('batch_show', 200)
        self.max_exercise_id = hparams.get('max_exercise_id', None)

        # 将配置信息写入日志
        self.logger.write('Before PCGCDF train.\n{}'.format(format_hparams(hparams)), logger_mode)

        # 转换设备可用数据
        self._to_device(device)

        # train_data = self._filter_samples_by_item_id(train_data, self.max_exercise_id, logger_mode, 'train')
        # if train_data.shape[0] == 0:
        #     raise ValueError('No training samples left after applying max_exercise_id={}'.format(self.max_exercise_id))
        # if not valid_data is None:
        #     valid_data = self._filter_samples_by_item_id(valid_data, self.max_exercise_id, logger_mode, 'valid')
        #     if valid_data.shape[0] == 0:
        #         self.logger.write('Valid data empty after filtering. Skip validation stage.', logger_mode)
        #         valid_data = None

        # 选择NLLLoss损失函数
        loss_fn = MyLoss(self, nn.NLLLoss, loss_factor)

        dataloader = TrainDataLoader(train_data, Q_matrix, batch_size)

        optimizer = torch.optim.Adam(params=self.parameters(), lr=lr)

        # 记录最佳指标
        best_epoch = -1
        best_auc = 0.0
        best_acc = 0.0
        best_rmse = float('inf')

        for step in range(1, epoch + 1):
            dataloader.reset(shuffle=False)
            n_batch = 0
            y_pred_all = np.array([])
            y_score_all = np.array([])
            y_target_all = np.array([], dtype=np.int_)
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
                y_score_all = np.concatenate([y_score_all, to_numpy(y_pred)], axis=0)
                y_target_all = np.concatenate([y_target_all, y_target.to('cpu').numpy()], axis=0)

                loss_all += loss.item()
                n_batch += 1

                if batch_count % batch_show == batch_show - 1:
                    self.logger.write('PCGCDF:'
                                      'epoch = {}, batch = {}, loss = {}'.format(
                        step, batch_count, loss_all / batch_show), logger_mode)
                    loss_all = 0.0
                batch_count += 1

            train_acc = accuracy_score(y_target_all, y_pred_all)
            train_f1 = f1_score(y_target_all, y_pred_all)
            train_auc = roc_auc_score(y_target_all, y_score_all)
            train_rmse = mean_squared_error(y_target_all, y_score_all) ** 0.5

            self.logger.write('PCGCDF:'
                              'epoch = {}, train_acc = {}, train_f1 = {}, train_auc = {}, train_rmse = {}'.format(
                step, train_acc, train_f1, train_auc, train_rmse), logger_mode)

            # 如果有验证集，计算验证指标并更新最佳值
            if valid_data is not None:
                metrics = self.eval(valid_data, Q_matrix, batch_size ,device)
                auc = metrics['auc']
                acc = metrics['acc']
                rmse = metrics['rmse']

                if auc > best_auc:
                    best_auc = auc
                    best_acc = acc
                    best_rmse = rmse
                    best_epoch = step

        self.logger.write('PCGCDF Training finished.', logger_mode)

            # 返回最佳指标
        if valid_data is None:
            return None, None, None, None
        else:
            return best_epoch, best_auc, best_acc, best_rmse

    def eval(self, test_data: pd.DataFrame, Q_matrix: np.array, batch_size: int, device='cpu'):
        dataloader = TrainDataLoader(test_data, Q_matrix, batch_size)
        y_pred_all = np.array([])
        y_score_all = np.array([])
        y_target_all = np.array(test_data.loc[:, 'score']).astype(np.int_)

        while not dataloader.is_end():
            user_ids, item_ids, item_know, y_target = dataloader.next_batch()
            user_ids = user_ids.to(device)
            item_ids = item_ids.to(device)
            item_know = item_know.to(device)
            y_pred = self.forward(user_ids, item_ids, item_know, device)
            y_pred_batch = labelize(y_pred)
            y_pred_all = np.concatenate([y_pred_all, y_pred_batch], axis=0)
            y_score_all = np.concatenate([y_score_all, to_numpy(y_pred)], axis=0)

        acc = accuracy_score(y_target_all, y_pred_all)
        f1 = f1_score(y_target_all, y_pred_all)
        auc = roc_auc_score(y_target_all, y_score_all)
        rmse = mean_squared_error(y_target_all, y_score_all) ** 0.5

        metrics_dict = {}
        metrics_dict['acc'] = (acc)
        metrics_dict['f1'] = (f1)
        metrics_dict['auc'] = (auc)
        metrics_dict['rmse'] = (rmse)

        return metrics_dict

class MyLoss(nn.Module):
    def __init__(self, model, loss_fn, loss_factor=1.0):
        super(MyLoss, self).__init__()
        self.model = model
        self.loss_fn = loss_fn()  # Instantiate the loss function
        self.factor = loss_factor

    def forward(self, y_pred, y_target, user_ids):
        #loss = self.loss_fn(y_pred, y_target)
        loss = self.loss_fn(y_pred, y_target) + self.factor * torch.sum(
            torch.relu(self.model.condi_n[user_ids, :] - self.model.condi_p[user_ids, :]))
        # Add regularization if needed
        return loss


def compute_relation_init(log_df: pd.DataFrame,
                              q_matrix: np.ndarray,
                              edge_list: pd.DataFrame,
                              threshold: float = 0.5) -> np.ndarray:
    # 检查 GPU 是否可用
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    if device.type == 'cpu':
        print("警告: GPU 不可用，将使用 CPU 运行（建议安装 CUDA 版本 PyTorch 以获得加速）")

    # ==================== 步骤 1: 数据预处理 ====================
    # 对同一学生-习题的多次作答取平均
    user_exer_avg = log_df.groupby(['user_id', 'exercise_id'])['score'].mean().reset_index()

    # 获取唯一学生和习题，并建立连续索引映射
    users = user_exer_avg['user_id'].unique()
    exercises = user_exer_avg['exercise_id'].unique()
    U = len(users)          # 学生数
    S = len(exercises)      # 习题数
    user_to_idx = {u: i for i, u in enumerate(users)}
    exer_to_idx = {e: j for j, e in enumerate(exercises)}

    # ==================== 步骤 2: 构建用户-习题得分矩阵和掩码矩阵 ====================
    scores_mat = torch.zeros((U, S), dtype=torch.float32, device=device)
    mask_mat = torch.zeros((U, S), dtype=torch.float32, device=device)

    # 提取填充所需的数据
    u_indices = [user_to_idx[uid] for uid in user_exer_avg['user_id']]
    e_indices = [exer_to_idx[eid] for eid in user_exer_avg['exercise_id']]
    score_vals = user_exer_avg['score'].values.astype(np.float32)

    # 批量赋值（使用索引张量）
    u_tensor = torch.tensor(u_indices, dtype=torch.long, device=device)
    e_tensor = torch.tensor(e_indices, dtype=torch.long, device=device)
    s_tensor = torch.tensor(score_vals, dtype=torch.float32, device=device)

    scores_mat[u_tensor, e_tensor] = s_tensor
    mask_mat[u_tensor, e_tensor] = 1.0

    # ==================== 步骤 3: 将 Q 矩阵移到 GPU ====================
    q = torch.tensor(q_matrix, dtype=torch.float32, device=device)  # (S_full, K)

    exer_indices = torch.tensor([exer_to_idx[e] for e in exercises], dtype=torch.long, device=device)
    q_sub = q[exer_indices]  # (S, K)

    # ==================== 步骤 4: 计算学生-知识点得分矩阵 ====================
    # 加权得分: scores_mat @ q_sub   (U x K)
    user_know_scores = torch.mm(scores_mat, q_sub)
    # 考察次数: mask_mat @ q_sub     (U x K)
    user_know_counts = torch.mm(mask_mat, q_sub)
    # 避免除零
    user_know_counts = torch.clamp(user_know_counts, min=1.0)
    user_know_scores = user_know_scores / user_know_counts

    # ==================== 步骤 5: 二值化掌握状态 ====================
    mastery = (user_know_scores >= threshold).to(torch.int32)  # (U, K)

    # ==================== 步骤 6: 并行计算所有边的条件概率 ====================
    edge_from = torch.tensor(edge_list['from'].values, dtype=torch.long, device=device)
    edge_to = torch.tensor(edge_list['to'].values, dtype=torch.long, device=device)

    # 提取列向量: (U, E)
    a_master = mastery[:, edge_from]
    b_master = mastery[:, edge_to]

    # 统计
    both = (a_master & b_master).sum(dim=0).float()   # (E,)
    a_only = a_master.sum(dim=0).float()              # (E,)
    prob = both / (a_only + 1e-8)
    prob[a_only == 0] = 0.0   # 无学生掌握 from 知识点时，概率置 0

    # 返回 CPU numpy 数组
    return prob.cpu().numpy()

def compute_know_diff_from_logs(log_df: pd.DataFrame, q_matrix: np.ndarray, method='inverse_accuracy'):
    """
    基于日志数据计算每个知识点的初始难度
    log_df: 包含列 ['exercise_id', 'score'] 的DataFrame（可含重复记录）
    q_matrix: (S, K) 0-1矩阵
    method: 计算方法
        - 'inverse_accuracy': 难度 = 1 - 平均正确率
        - 'log_odds': 难度 = -log(正确率 + ϵ)
    """
    # 计算每个习题的平均正确率
    exer_acc = log_df.groupby('exercise_id')['score'].mean().to_dict()
    S, K = q_matrix.shape
    know_acc = np.zeros(K)

    for k in range(K):
        # 找到所有考察知识点k的习题
        exers = np.where(q_matrix[:, k] == 1)[0]
        if len(exers) > 0:
            # 取这些习题正确率的平均值
            acc_sum = 0.0
            cnt = 0
            for e in exers:
                if e in exer_acc:
                    acc_sum += exer_acc[e]
                    cnt += 1
            know_acc[k] = acc_sum / cnt if cnt > 0 else 0.5
        else:
            know_acc[k] = 0.5  # 默认中等难度

    if method == 'inverse_accuracy':
        know_diff = 1.0 - know_acc
    elif method == 'log_odds':
        eps = 1e-6
        know_diff = -np.log(know_acc + eps)
    else:
        raise ValueError(f"Unknown method: {method}")
    return know_diff
