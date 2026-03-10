import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
from sklearn.metrics import roc_auc_score, accuracy_score, f1_score
from tqdm import tqdm
import sys


device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')

class GateLayer(nn.Module):
    """
    猜测和滑动因素的门控机制模块，从AGCDM模型中移植
    """
    def __init__(self, feature_size, num_layers, f=torch.relu):
        super(GateLayer, self).__init__()

        self.num_layers = num_layers
        self.guess = nn.ModuleList([nn.Linear(feature_size, feature_size) for _ in range(num_layers)])
        self.slip = nn.ModuleList([nn.Linear(feature_size, feature_size) for _ in range(num_layers)])
        self.pass_func = nn.ModuleList([nn.Linear(feature_size, feature_size) for _ in range(num_layers)])
        self.nopass_func = nn.ModuleList([nn.Linear(feature_size, feature_size) for _ in range(num_layers)])
        self.f = f

        for name, param in self.named_parameters():
            if 'weight' in name:
                nn.init.xavier_normal_(param)

    def forward(self, x):
        """
        gs门控机制：
        猜测(guess)表示学生不懂但猜对的概率
        滑动(slip)表示学生懂但答错的概率
        gate = guess_prob + slip_prob
        """
        for layer in range(self.num_layers):
            guess_prob = torch.sigmoid(self.guess[layer](x))  # 猜测分布
            slip_prob = torch.sigmoid(self.slip[layer](x))  # 滑动分布
            gate = guess_prob + slip_prob

            pass_results = self.f(self.pass_func[layer](x))  # f只作用于通过部分
            no_pass_results = self.nopass_func[layer](x)

            x = pass_results + gate * no_pass_results

        return x


class Net(nn.Module):
    def __init__(self, stu_n, exer_n, k_n, emb_dim):
        self.knowledge_dim = k_n
        self.exer_n = exer_n
        self.emb_num = stu_n
        self.stu_dim = self.knowledge_dim
        self.lowdim = emb_dim
        self.prednet_input_len = self.knowledge_dim
        self.prednet_len1, self.prednet_len2 = 512, 256  # changeable
        self.dropout = 0
        self.net1 = k_n

        super(Net, self).__init__()

        # network structure
        self.student_emb = nn.Embedding(self.emb_num, self.lowdim)  # 学生的低维表示
        self.knowledge_emb = nn.Embedding(self.knowledge_dim, self.lowdim)  # 知识点矩阵的低维表示
        self.k_difficulty = nn.Embedding(self.exer_n, self.lowdim)  # 习题的低维表示

        self.k_index = torch.LongTensor(list(range(self.stu_dim))).to(device)

        self.prednet_full1 = nn.Linear(self.knowledge_dim + self.lowdim, self.net1, bias=False)
        self.drop_1 = nn.Dropout(p=self.dropout)
        self.prednet_full2 = nn.Linear(self.knowledge_dim + self.lowdim, self.net1, bias=False)
        self.drop_2 = nn.Dropout(p=self.dropout)
        
        # 添加GateLayer处理gs因素
        self.gate = GateLayer(self.net1, 1, torch.sigmoid)
        
        self.prednet_full3 = nn.Linear(1 * self.net1, 1)
        self.student_q = nn.Embedding(self.emb_num, self.lowdim)
        self.exercise_k = nn.Embedding(self.exer_n, 1)

        # initialization
        for name, param in self.named_parameters():
            if 'weight' in name:
                nn.init.xavier_normal_(param)

    def forward(self, stu_id, exer_id, kn_emb):
        knowledge_low_emb = self.knowledge_emb(self.k_index).to(device)
        batch_stu_emb = self.student_emb(stu_id)
        batch_stu_emb = torch.sigmoid(torch.mm(batch_stu_emb, knowledge_low_emb.T))
        batch_stu_vector = batch_stu_emb.repeat(1, self.knowledge_dim).reshape(batch_stu_emb.shape[0], self.knowledge_dim, batch_stu_emb.shape[1])
        batch_exer_emb = self.k_difficulty(exer_id)
        batch_exer_emb = torch.sigmoid(torch.mm(batch_exer_emb, knowledge_low_emb.T))
        batch_exer_vector = batch_exer_emb.repeat(1, self.knowledge_dim).reshape(batch_exer_emb.shape[0], self.knowledge_dim, batch_exer_emb.shape[1])
        kn_vector = knowledge_low_emb.repeat(batch_stu_emb.shape[0], 1).reshape(batch_stu_emb.shape[0],knowledge_low_emb.shape[0],knowledge_low_emb.shape[1])
        stu_q = self.student_q(stu_id)
        exer_k = self.exercise_k(exer_id)

        preference = torch.sigmoid(self.prednet_full1(torch.cat((batch_stu_vector, kn_vector), dim=2)))
        diff = torch.sigmoid(self.prednet_full2(torch.cat((batch_exer_vector, kn_vector), dim=2)))

        input_x = preference - diff
        
        # 应用GateLayer处理gs因素
        input_x = self.gate(input_x)

        o = torch.sigmoid(self.prednet_full3(input_x))
        sum_out = torch.sum(o * kn_emb.unsqueeze(2), dim=1)
        count_of_concept = torch.sum(kn_emb, dim=1).unsqueeze(1)
        output = sum_out / count_of_concept
        return torch.squeeze(output)

    def apply_clipper(self):
        clipper = NoneNegClipper()
        self.prednet_full1.apply(clipper)
        self.prednet_full2.apply(clipper)
        self.prednet_full3.apply(clipper)


class NoneNegClipper(object):
    def __init__(self):
        super(NoneNegClipper, self).__init__()

    def __call__(self, module):
        if hasattr(module, 'weight'):
            w = module.weight.data
            a = torch.relu(torch.neg(w))
            w.add_(a)


class kscd_gs:
    """带有猜测和滑动因素的知识状态认知诊断模型"""
    
    def __init__(self, student_n, exer_n, k_n, emb_dim):
        super(kscd_gs, self).__init__()
        self.net = Net(student_n, exer_n, k_n, emb_dim)

    def train(self, train_data, test_data=None, epoch=10, device="cpu", lr=0.002):
        self.net = self.net.to(device)
        self.net.train()

        loss_function = nn.BCELoss()
        optimizer = optim.Adam(self.net.parameters(), lr=lr)
        best_epoch = 0
        best_auc = 0.
        acc1 = 0.
        best_f1 = 0.
        rmse1 = 1.
        for epoch_i in range(epoch):
            epoch_losses = []
            batch_count = 0
            for batch_data in tqdm(train_data, "Epoch %s" % epoch_i, file=sys.stdout):
                batch_count += 1
                user_id, item_id, kq, y = batch_data
                user_id: torch.Tensor = user_id.to(device)
                item_id: torch.Tensor = item_id.to(device)
                kq = kq.to(device)
                y: torch.Tensor = y.to(device)

                pred: torch.Tensor = self.net(user_id, item_id, kq)

                loss = loss_function(pred, y)

                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

                epoch_losses.append(loss.mean().item())

            print("[Epoch %d] average loss: %.6f" % (epoch_i, float(np.mean(epoch_losses))))

            if test_data is not None:
                auc, accuracy, rmse, f1 = self.eval(test_data, device=device)
                print("[Epoch %d] auc: %.6f, accuracy: %.6f, rmse: %.6f, f1: %.6f" % (epoch_i, auc, accuracy, rmse, f1))

                if best_auc < auc:
                    best_epoch = epoch_i
                    best_auc = auc
                    acc1 = accuracy
                    rmse1 = rmse
                    best_f1 = f1

            print('BEST epoch<%d>, auc: %s, acc: %s, rmse: %.6f, f1: %.6f' % (best_epoch, best_auc, acc1, rmse1, best_f1))

        return best_epoch, best_auc, acc1, rmse1

    def eval(self, test_data, device="cpu"):
        self.net = self.net.to(device)
        self.net.eval()
        y_true, y_pred = [], []
        rmse = 0.
        for batch_data in tqdm(test_data, "Evaluating", file=sys.stdout):
            user_id, item_id, kq, y = batch_data
            user_id: torch.Tensor = user_id.to(device)
            item_id: torch.Tensor = item_id.to(device)
            kq = kq.to(device)
            pred: torch.Tensor = self.net(user_id, item_id, kq)

            y_pred.extend(pred.detach().cpu().tolist())
            y_true.extend(y.tolist())
        rmse = np.sqrt(np.mean((np.array(y_true) - np.array(y_pred)) ** 2))
        return roc_auc_score(y_true, y_pred), accuracy_score(y_true, np.array(y_pred) >= 0.5), rmse, f1_score(y_true, np.array(y_pred) >= 0.5) 