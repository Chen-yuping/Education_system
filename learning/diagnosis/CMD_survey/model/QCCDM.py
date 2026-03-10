import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from sklearn.metrics import roc_auc_score, accuracy_score, mean_squared_error, f1_score
from tqdm import tqdm
import sys

# NoneNegClipper类实现
class NoneNegClipper(object):
    def __init__(self):
        super(NoneNegClipper, self).__init__()
    
    def __call__(self, module):
        if hasattr(module, 'weight'):
            w = module.weight.data
            module.weight.data = torch.clamp(w, min=0)

# 数据处理函数
def transform(q_matrix, user_ids, item_ids, labels, batch_size):
    """
    将数据转换为批处理格式
    """
    data_set = []
    for user_id, item_id, label in zip(user_ids, item_ids, labels):
        # 将数据转换为正确的类型
        user_id_int = int(user_id)
        item_id_int = int(item_id)
        # 确保标签是浮点类型，与默认数据类型兼容
        label_float = float(label)
        
        # 获取知识点向量（如果有）
        knowledge_emb = None
        if q_matrix is not None:
            knowledge_emb = q_matrix[item_id_int].clone().detach()  # 复制防止修改原始数据
            
        data_set.append((user_id_int, item_id_int, knowledge_emb, label_float))
    
    class Dataset(torch.utils.data.Dataset):
        def __init__(self, data):
            self.data = data
        
        def __len__(self):
            return len(self.data)
        
        def __getitem__(self, idx):
            return self.data[idx]
    
    dataset = Dataset(data_set)
    data_loader = torch.utils.data.DataLoader(dataset, batch_size=batch_size, shuffle=True)
    return data_loader

# 构建响应矩阵
def get_r_matrix(data, stu_num, prob_num):
    """
    构建学生-题目响应矩阵
    """
    r = -1 * np.ones((stu_num, prob_num))
    for d in data:
        try:
            # 确保索引为整数
            user_id = int(d[0])
            item_id = int(d[1])
            score = float(d[2])
            
            # 检查索引是否在有效范围内
            if 0 <= user_id < stu_num and 0 <= item_id < prob_num:
                r[user_id, item_id] = score
        except (IndexError, ValueError, TypeError) as e:
            print(f"警告: 在处理数据 {d} 时遇到错误: {e}")
            continue
    return r

# 计算诊断精度
def get_doa_function(kc_num):
    """
    计算知识点诊断精度的函数
    """
    def doa_function(true_mastery, q_matrix, r_matrix):
        pred_prob = np.zeros_like(r_matrix)
        for i in range(r_matrix.shape[0]):
            for j in range(r_matrix.shape[1]):
                if r_matrix[i, j] != -1:
                    kcs = np.where(q_matrix[j] == 1)[0]
                    if len(kcs) == 0:
                        pred_prob[i, j] = 0.5
                    else:
                        pred_prob[i, j] = true_mastery[i, kcs].mean()
        r_matrix = r_matrix != 0
        
        # 过滤掉-1的响应
        pred_prob_filtered = []
        r_matrix_filtered = []
        for i in range(r_matrix.shape[0]):
            for j in range(r_matrix.shape[1]):
                if r_matrix[i, j] != -1:
                    pred_prob_filtered.append(pred_prob[i, j])
                    r_matrix_filtered.append(r_matrix[i, j])
        
        if len(pred_prob_filtered) == 0:
            return 0.5
        return roc_auc_score(r_matrix_filtered, pred_prob_filtered)
    
    return doa_function

class NET(nn.Module):
    def __init__(self, stu_num, prob_num, know_num, mask, q_matrix, mode, device='cpu', num_layers=2, hidden_dim=512,
                 dropout=0.5, dtype=torch.float32, nonlinear='sigmoid', q_aug='single', dim=32):
        super(NET, self).__init__()
        self.stu_num = stu_num
        self.prob_num = prob_num
        self.know_num = know_num
        self.device = device
        self.mode = mode
        self.nonlinear = nonlinear
        self.q_aug = q_aug
        self.dim = dim
        torch.set_default_dtype(dtype)

        if not isinstance(mask, torch.Tensor):
            self.g_mask = torch.tensor(mask, dtype=dtype).to(device)
        else:
            self.g_mask = mask
        self.g_mask.requires_grad = False

        if not isinstance(q_matrix, torch.Tensor):
            self.q_mask = torch.tensor(q_matrix, dtype=dtype).to(device=device)
        else:
            self.q_mask = q_matrix
        self.q_mask.requires_grad = False

        if '1' in mode:
            self.graph = torch.randn(self.know_num, self.know_num).to(device)
            torch.nn.init.xavier_normal_(self.graph)
            # self.graph = 2 * torch.relu(torch.neg(self.graph)) + self.graph
            self.graph = torch.sigmoid(self.graph)
            self.graph = nn.Parameter(self.graph)

        if '2' in mode:
            if self.q_aug == 'single':
                self.q_neural = torch.randn(self.prob_num, self.know_num).to(device)
                torch.nn.init.xavier_normal_(self.q_neural)
                self.q_neural = torch.sigmoid(self.q_neural)
                self.q_neural = nn.Parameter(self.q_neural)
            elif self.q_aug == 'mf':
                self.A = nn.Embedding(self.prob_num, self.dim)
                self.B = nn.Embedding(self.know_num, self.dim)
                # 初始化嵌入向量
                torch.nn.init.xavier_normal_(self.A.weight)
                torch.nn.init.xavier_normal_(self.B.weight)


        self.latent_Zm_emb = nn.Embedding(self.stu_num, self.know_num)
        self.latent_Zd_emb = nn.Embedding(self.prob_num, self.know_num)
        self.e_discrimination = nn.Embedding(self.prob_num, 1)
        if self.nonlinear == 'sigmoid':
            self.nonlinear_func = F.sigmoid
        elif self.nonlinear == 'softplus':
            self.nonlinear_func = F.softplus
        elif self.nonlinear == 'tanh':
            self.nonlinear_func = F.tanh
        else:
            raise ValueError('We do not support such nonlinear function')
        layers = []
        for i in range(num_layers):
            layers.append(nn.Linear(self.know_num if i == 0 else hidden_dim // pow(2, i - 1), hidden_dim // pow(2, i)))
            layers.append(nn.BatchNorm1d(hidden_dim // pow(2, i)))
            layers.append(nn.Dropout(dropout))
            layers.append(nn.Tanh())

        layers.append(nn.Linear(hidden_dim // pow(2, num_layers - 1), 1))
        layers.append(nn.Sigmoid())
        self.layers = nn.Sequential(*layers)
        BatchNorm_names = ['layers.{}.weight'.format(4 * i + 1) for i in range(num_layers)]

        for index, (name, param) in enumerate(self.named_parameters()):
            if 'weight' in name:
                if name not in BatchNorm_names:
                    nn.init.xavier_normal_(param)

    def forward(self, stu_id, prob_id, knowledge_point=None):
        latent_zm = self.nonlinear_func(self.latent_Zm_emb(stu_id))
        latend_zd = self.nonlinear_func(self.latent_Zd_emb(prob_id))
        e_disc = torch.sigmoid(self.e_discrimination(prob_id))
        identity = torch.eye(self.know_num, device=self.device)  # 确保identity在正确的设备上

        if '1' in self.mode:
            if self.nonlinear != 'sigmoid':
                # 确保所有张量都在同一设备上
                graph_mask = torch.mul(self.graph, self.g_mask)
                inv_matrix = torch.inverse(identity - graph_mask)
                Mas = latent_zm @ inv_matrix
                Mas = torch.sigmoid(self.nonlinear_func(Mas))
                Diff = latend_zd @ inv_matrix
                Diff = torch.sigmoid(self.nonlinear_func(Diff))
                input_ability = Mas - Diff
            else:
                # 确保所有张量都在同一设备上
                graph_mask = torch.mul(self.graph, self.g_mask)
                inv_matrix = torch.inverse(identity - graph_mask)
                Mas = latent_zm @ inv_matrix
                Mas = torch.sigmoid(Mas)
                Diff = latend_zd @ inv_matrix
                Diff = torch.sigmoid(Diff)
                input_ability = Mas - Diff
        else:
            # 如果没有使用模式1，直接使用latent_zm作为能力
            input_ability = latent_zm

        if '2' in self.mode:
            if self.q_aug == 'single':
                combined_q = (self.q_neural * (1 - self.q_mask) + self.q_mask)
                input_data = e_disc * input_ability * combined_q[prob_id]
            elif self.q_aug == 'mf':
                # 计算矩阵分解生成的Q矩阵，确保在同一设备上
                q_neural = torch.sigmoid(torch.matmul(self.A.weight, self.B.weight.transpose(0, 1)))
                # 合并原始Q矩阵和生成的Q矩阵
                augmented_q = q_neural * (1 - self.q_mask) + self.q_mask
                # 获取对应题目的Q向量
                q_vectors = augmented_q[prob_id]
                # 最终的预测输入
                input_data = e_disc * input_ability * q_vectors
        else:
            # 如果没有使用模式2，使用知识点向量
            if knowledge_point is not None:
                # 确保knowledge_point在正确的设备上
                if knowledge_point.device != input_ability.device:
                    knowledge_point = knowledge_point.to(input_ability.device)
                input_data = e_disc * input_ability * knowledge_point
            else:
                # 如果没有提供knowledge_point，使用Q矩阵
                input_data = e_disc * input_ability * self.q_mask[prob_id]

        return self.layers(input_data).view(-1)

    def apply_clipper(self):
        clipper = NoneNegClipper()
        for layer in self.layers:
            if isinstance(layer, nn.Linear):
                layer.apply(clipper)

    def get_mastery_level(self):
        if '1' in self.mode:
            identity = torch.eye(self.know_num)
            if self.nonlinear != 'sigmoid':
                return torch.sigmoid(
                self.nonlinear_func(self.nonlinear_func(self.latent_Zm_emb.weight.detach().cpu()) @ torch.linalg.inv(
                    identity - self.graph.data.detach().cpu() * self.g_mask.detach().cpu()))).numpy()
            else:
                return torch.sigmoid(
                self.nonlinear_func(self.latent_Zm_emb.weight.detach().cpu()) @ torch.linalg.inv(
                    identity - self.graph.data.detach().cpu() * self.g_mask.detach().cpu())).numpy()
        else:
            return torch.sigmoid(self.latent_Zm_emb.weight.detach().cpu()).numpy()  # 修复这里的引用

    def get_Q_Pseudo(self):
        if '2' in self.mode and self.q_aug == 'single':
            return (self.q_neural * (1 - self.q_mask) + self.q_mask).detach().cpu().numpy()
        else:
            return self.q_mask.detach().cpu().numpy()

    def get_intervention_result(self, dil_emb):
        prob_id = torch.arange(self.prob_num).to(self.device)
        diff_emb = torch.sigmoid(self.latent_Zd_emb(prob_id))  # 修复这里的引用
        e_diff = torch.sigmoid(self.e_discrimination(prob_id))
        
        if '1' in self.mode:
            identity = torch.eye(self.know_num).to(self.device)
            diff_emb = diff_emb @ (torch.linalg.inv(identity - self.graph * self.g_mask))

        input_ability = dil_emb - diff_emb

        if '2' in self.mode:
            if self.q_aug == 'single':
                input_data = torch.mul(e_diff, torch.mul(input_ability, (self.q_neural * (1 - self.q_mask) + self.q_mask)[prob_id]))
            elif self.q_aug == 'mf':
                q_neural = torch.sigmoid(self.A.weight @ self.B.weight.T)
                input_data = torch.mul(e_diff, torch.mul(input_ability, (q_neural * (1 - self.q_mask) + self.q_mask)[prob_id]))
        else:
            input_data = torch.mul(e_diff, torch.mul(input_ability, self.q_mask[prob_id]))

        return self.layers(input_data).view(-1)


class QCCDM:
    def __init__(self, stu_num, prob_num, know_num, q_matrix, device='cpu',
                 graph=None, lambda_reg=0.01, mode='12', dtype=torch.float64, num_layers=2, nonlinear='sigmoid',
                 q_aug='single'):
        """
        :param stu_num: number of Student
        :param prob_num: number of Problem
        :param know_num: number of Knowledge Attributes
        :param q_matrix: q_matrix of benchmark
        :param device: running device
        :param graph: causal graph of benchmark
        :param lambda_reg: regulation hyperparameter
        :param mode: '1' only SCM '2' only Q-augmented '12' both
        :param dtype: dtype of tensor
        :param num_layers: number of interactive block
        :param nonlinear: the nonlinear function of SCM
        :param q_aug: the augmentation of Q-Matrix
        """
        self.lambda_reg = lambda_reg
        self.know_num = know_num
        self.prob_num = prob_num
        self.stu_num = stu_num
        self.mode = mode
        self.device = device
        self.q_aug = q_aug
        
        # 确保causal_graph在正确的设备上
        if graph is not None:
            if isinstance(graph, torch.Tensor):
                self.causal_graph = graph.to(device)
            else:
                self.causal_graph = torch.tensor(graph, device=device)
        else:
            # 如果没有提供graph，使用单位矩阵作为默认值
            self.causal_graph = torch.eye(know_num, device=device)
        
        # 创建模型并将其移至指定设备
        self.net = NET(stu_num, prob_num, know_num, self.causal_graph, q_matrix, device=device, mode=mode,
                       dtype=dtype, num_layers=num_layers, nonlinear=nonlinear, q_aug=q_aug).to(device)
        self.mode = mode
        self.mas_list = []

    def train(self, np_train, np_test, batch_size=128, epoch=10, lr=0.002, q=None):
        self.net.train()
        
        # 设置损失函数，并确保使用正确的数据类型
        bce_loss_function = nn.BCELoss()
        optimizer = optim.Adam(self.net.parameters(), lr=lr)
        
        # 转换数据
        train_data, test_data = [
            transform(q, _[:, 0], _[:, 1], _[:, 2], batch_size)
            for _ in [np_train, np_test]
        ]
        
        # 构建响应矩阵
        r = get_r_matrix(np_test, self.stu_num, self.prob_num)
        l1_lambda = self.lambda_reg / self.know_num / self.prob_num
        
        for epoch_i in range(epoch):
            epoch_losses = []
            bce_losses = []
            l1_losses = []
            batch_count = 0
            for batch_data in tqdm(train_data, "Epoch %s" % epoch_i):
                batch_count += 1
                user_id, item_id, knowledge_emb, y = batch_data
                
                # 移动数据到正确设备并确保正确的数据类型
                user_id = user_id.to(self.device)
                item_id = item_id.to(self.device)
                if knowledge_emb is not None:
                    knowledge_emb = knowledge_emb.to(self.device).to(torch.get_default_dtype())
                
                # 确保目标值是浮点类型
                y = y.to(self.device).to(torch.get_default_dtype())
                
                # 预测
                pred = self.net(user_id, item_id, knowledge_emb)
                
                # 计算损失
                bce_loss = bce_loss_function(pred, y)
                bce_losses.append(bce_loss.mean().item())
                
                # 正则化
                if '2' in self.mode:
                    if self.q_aug == 'single':
                        l1_reg = self.net.q_neural * (torch.ones_like(self.net.q_mask) - self.net.q_mask)
                    elif self.q_aug == 'mf':
                        q_neural = torch.sigmoid(self.net.A.weight @ self.net.B.weight.T)
                        l1_reg = q_neural * (torch.ones_like(self.net.q_mask) - self.net.q_mask)
                    l1_losses.append(l1_lambda * l1_reg.abs().sum().mean().item())
                    total_loss = bce_loss + l1_lambda * l1_reg.abs().sum()
                else:
                    total_loss = bce_loss
                    l1_losses.append(0.0)  # 添加占位符，避免空列表

                # 反向传播和优化
                optimizer.zero_grad()
                total_loss.backward()
                nn.utils.clip_grad_norm_(self.net.parameters(), max_norm=20, norm_type=2)
                optimizer.step()

                # 应用约束
                if '1' in self.mode:
                    self.net.graph.data = torch.clamp(self.net.graph.data, 0., 1.)
                if '2' in self.mode and self.q_aug == 'single':
                    self.net.q_neural.data = torch.clamp(self.net.q_neural.data, 0., 1.)

                self.net.apply_clipper()
                epoch_losses.append(total_loss.mean().item())

            print("[Epoch %d] average loss: %.6f, bce loss: %.6f, l1 loss: %.6f" % (
                epoch_i, float(np.mean(epoch_losses)), float(np.mean(bce_losses)), float(np.mean(l1_losses))))

            if test_data is not None:
                auc, accuracy, rmse, f1, doa = self.eval(test_data, q=q, r=r)
                print("[Epoch %d] auc: %.6f, accuracy: %.6f, rmse: %.6f, f1: %.6f, DOA: %.6f" % (
                    epoch_i, auc, accuracy, rmse, f1, doa))

    def eval(self, test_data, q=None, r=None):
        """评估模型性能"""
        # 确保模型在正确的设备上
        self.net = self.net.to(self.device)
        self.net.eval()
        y_true, y_pred = [], []
        
        # 获取掌握水平
        mas = self.net.get_mastery_level()
        self.mas_list.append(mas)
        
        # 准备DOA函数
        doa_func = get_doa_function(self.know_num)
        
        # 在测试数据上进行预测
        for batch_data in tqdm(test_data, "Evaluating"):
            user_id, item_id, know_emb, y = batch_data
            # 将数据移至正确的设备
            user_id = user_id.to(self.device)
            item_id = item_id.to(self.device)
            if know_emb is not None:
                know_emb = know_emb.to(self.device)
                
            # 预测
            pred = self.net(user_id, item_id, know_emb)
            
            # 收集结果
            y_pred.extend(pred.detach().cpu().tolist())
            y_true.extend(y.tolist())
        
        # 计算评估指标
        auc = roc_auc_score(y_true, y_pred)
        accuracy = accuracy_score(y_true, np.array(y_pred) >= 0.5)
        rmse = np.sqrt(mean_squared_error(y_true, y_pred))
        f1 = f1_score(y_true, np.array(y_pred) >= 0.5)
        
        # 计算DOA
        if q is not None and r is not None:
            try:
                q_cpu = q.detach().cpu().numpy() if isinstance(q, torch.Tensor) else q
                doa = doa_func(mas, q_cpu, r)
            except Exception as e:
                print(f"计算DOA时出错: {e}")
                doa = 0.0
        else:
            doa = 0.0
            
        return auc, accuracy, rmse, f1, doa
