import os
import networkx as nx
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score, mean_squared_error
import torch
import torch.nn as nn
import warnings
import torch.nn.functional as F
from dataloader import TrainDataLoader
from itf import mirt2pl, sigmoid_dot, dot, itf_dict
from tools import Logger, df_preview, format_hparams, labelize, to_numpy

warnings.filterwarnings('ignore')
torch.set_default_tensor_type(torch.DoubleTensor)


class ConCDF(nn.Module):
    '''
    The contaiment cognitive diagnosis model
    '''

    def __init__(self, n_user, n_item, n_know, hidden_dim,know_graph:pd.DataFrame,itf_type='mirt',
                 log_path='./log/',init_R=None, init_diff=None):

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
        self.edge_logits = nn.Parameter(torch.Tensor(know_graph.shape[0], 2))

        ##### 构建每个目标节点的前驱节点列表及对应边索引
        self.pred_nodes = [[] for _ in range(n_know)]
        self.pred_edge_idx = [[] for _ in range(n_know)]
        for idx, row in know_graph.iterrows():
            src, tgt = int(row['from']), int(row['to'])
            self.pred_nodes[tgt].append(src)
            self.pred_edge_idx[tgt].append(idx)

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
        nn.init.xavier_uniform_(self.edge_logits)
        for name, param in self.named_parameters():
            if 'weight' in name:
                nn.init.xavier_normal_(param)

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

                # 对数域加权几何平均
                log_m_parents = torch.log(m_parents + 1e-10)
                weighted_log = log_m_parents * w_norm.unsqueeze(0)
                log_m_k = weighted_log.sum(dim=1)
                m_k = torch.exp(log_m_k)

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

    def forward(self, user_ids: torch.LongTensor, item_ids: torch.LongTensor, item_know: torch.Tensor,
                device='cpu') -> torch.Tensor:
        '''
        论文主要的整体操作步骤
        @Param item_know: the item q matrix of the batch
        '''
        # 论文中的认知状态模块(Cofnitive State)
        user_mastery = self.get_posterior(user_ids, device)  # 获取后验掌握情况

        # 论文中的问题特征模块(Question Feature)
        # item_diff本身为（n_item,n_know）的嵌入向量，即n_item个n_know维的向量,(习题，知识点)
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

        # 将配置信息写入日志
        self.logger.write('Before ConCDF train.\n{}'.format(format_hparams(hparams)), logger_mode)

        # 转换设备可用数据
        self._to_device(device)

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
                    self.logger.write('ConCDF:'
                                      'epoch = {}, batch = {}, loss = {}'.format(
                        step, batch_count, loss_all / batch_show), logger_mode)
                    loss_all = 0.0
                batch_count += 1

            # train_acc = accuracy_score(y_target_all, y_pred_all)
            train_f1 = f1_score(y_target_all, y_pred_all)

            self.logger.write('ConCDF:'
                              'epoch = {}, train_f1 = {}'.format(step, train_f1), logger_mode)
            # 如果有验证集，计算验证指标并更新最佳值
            if valid_data is not None:
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
            df_pred = pd.concat([df_pred, df_batch], ignore_index=True)

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

        self.logger.write('ConCDF:'
                          'valid acc = {}'.format(valid_acc), logger_mode)
        self.logger.write('ConCDF:'
                          'valid f1  = {}'.format(valid_f1), logger_mode)
        self.logger.write('ConCDF:'
                          'valid auc = {}'.format(valid_auc), logger_mode)
        self.logger.write('ConCDF:'
                          'valid mse = {}\n'.format(valid_mse), logger_mode)

        metrics_dict = {}
        metrics_dict['acc'] = (valid_acc)
        metrics_dict['f1'] = (valid_f1)
        metrics_dict['auc'] = (valid_auc)
        metrics_dict['mse'] = (valid_mse)

        return metrics_dict

    def _to_device(self, device):
        self.priori = nn.Parameter(self.priori.to(device))
        self.user_contract = self.user_contract.to(device)
        self.item_contract = self.item_contract.to(device)
        self.item_diff = self.item_diff.to(device)
        self.item_disc = self.item_disc.to(device)
        self.cross_layer1 = self.cross_layer1.to(device)
        self.cross_layer2 = self.cross_layer2.to(device)
        self.relation_strength = nn.Parameter(self.relation_strength.to(device))
        self.know_diff = nn.Parameter(self.know_diff.to(device))
        self.edge_logits = nn.Parameter(self.edge_logits.to(device))

    def save(self, model_name='./model.pkl'):
        path = '/'.join(model_name.split('/')[:-1]) + '/'
        if not os.path.exists(path):
            os.makedirs(path)
        torch.save(self.state_dict(), model_name)

    def load(self, model_name='./model.pkl'):
        self.load_state_dict(torch.load(model_name))


class MyLoss(nn.Module):
    '''
    The loss function of ConCDM
    '''

    def __init__(self, net: ConCDF, loss_fn: nn.Module, factor=1.0):
        super(MyLoss, self).__init__()
        self.net = net
        self.factor = factor
        self.loss_fn = loss_fn()

    def forward(self, y_pred, y_target, user_ids=None):
        return self.loss_fn(y_pred, y_target)

def compute_relation_init(log_df: pd.DataFrame,
                              q_matrix: np.ndarray,
                              edge_list: pd.DataFrame,
                              threshold: float = 0.5) -> np.ndarray:
    """
    基于日志数据计算每条边的初始关联度（条件概率 P(掌握to | 掌握from)）
    log_df : pandas.DataFrame
        包含列 ['user_id', 'exercise_id', 'score']，每行表示一次答题记录。
    q_matrix : np.ndarray
        形状 (S, K) 的 0-1 矩阵，S = 习题数，K = 知识点数。
    edge_list : pandas.DataFrame
        包含列 ['from', 'to']，表示知识点之间的有向边。
    threshold : float, default=0.5
        判断“掌握”的分数阈值。

    返回
    np.ndarray
        形状 (E,) 的数组，E 为边数，表示每条边的条件概率。
    """
    # 检查 GPU 是否可用
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    if device.type == 'cpu':
        print("警告: GPU 不可用，将使用 CPU 运行")

    # ==================== 步骤 1: 数据预处理（CPU） ====================
    # 对同一学生-习题的多次作答取平均
    user_exer_avg = log_df.groupby(['user_id', 'exercise_id'])['score'].mean().reset_index()

    # 获取唯一学生和习题，并建立连续索引映射
    users = user_exer_avg['user_id'].unique()
    exercises = user_exer_avg['exercise_id'].unique()
    U = len(users)          # 学生数
    S = len(exercises)      # 习题数（注意：可能小于 q_matrix 的第一维，因为 log_df 中可能只出现了部分习题）
    user_to_idx = {u: i for i, u in enumerate(users)}
    exer_to_idx = {e: j for j, e in enumerate(exercises)}

    # ==================== 步骤 2: 构建用户-习题得分矩阵和掩码矩阵 ====================
    # 创建零矩阵，后续填充（由于 U*S 可能较大，但通常可放入显存）
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

    # 更稳妥的方式：直接根据索引取子矩阵
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
