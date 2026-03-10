import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from sklearn.metrics import accuracy_score, roc_auc_score, f1_score
from tqdm import tqdm
import sys

class GateLayer(nn.Module):
    def __init__(self, feature_size, num_layers, f=torch.relu):
        super(GateLayer, self).__init__()
        self.num_layers = num_layers
        self.guess = nn.ModuleList([nn.Linear(feature_size, feature_size) for _ in range(num_layers)])
        self.slip = nn.ModuleList([nn.Linear(feature_size, feature_size) for _ in range(num_layers)])
        self.pass_func = nn.ModuleList([nn.Linear(feature_size, feature_size) for _ in range(num_layers)])
        self.nopass_func = nn.ModuleList([nn.Linear(feature_size, feature_size) for _ in range(num_layers)])
        self.f = f

        # 参数初始化
        for name, param in self.named_parameters():
            if 'weight' in name:
                nn.init.xavier_normal_(param)

    def forward(self, x):
        for layer in range(self.num_layers):
            # 计算猜测概率和失误概率
            guess_prob = torch.sigmoid(self.guess[layer](x))  # 猜测概率
            slip_prob = torch.sigmoid(self.slip[layer](x))    # 失误概率
            gate = guess_prob + slip_prob

            # 计算通过和不通过的结果
            pass_results = self.f(self.pass_func[layer](x))
            no_pass_results = self.nopass_func[layer](x)

            # 组合结果
            x = pass_results + gate * no_pass_results
        return x

class CDFKC(nn.Module):
    def __init__(self, student_n, item_n, knowledge_n, knowledge_embed_size, n_heads=8):
        super(CDFKC, self).__init__()
        self.n_heads = n_heads
        self.knowledge_embed_size = knowledge_embed_size
        
        # 学生和题目的嵌入层
        self.emb_stu = nn.Embedding(student_n, knowledge_embed_size)
        self.emb_item = nn.Embedding(item_n, knowledge_embed_size)
        self.emb_knowledge = nn.Linear(knowledge_n, knowledge_embed_size)
        
        # 注意力权重矩阵
        self.W_stu_knowledge = nn.Linear(knowledge_embed_size, knowledge_embed_size * n_heads, bias=False)
        self.W_item_knowledge = nn.Linear(knowledge_embed_size, knowledge_embed_size * n_heads, bias=False)
        self.W_skill_knowledge = nn.Linear(knowledge_embed_size, knowledge_embed_size * n_heads, bias=False)
        
        # 添加gate层
        self.gate = GateLayer(knowledge_embed_size * n_heads, 1, torch.sigmoid)
        
        # 输出层
        self.linear = nn.Linear(knowledge_embed_size * n_heads, 1)
        
        # 参数初始化
        for name, param in self.named_parameters():
            if 'weight' in name:
                nn.init.xavier_normal_(param)

    def forward(self, batch_stu_id, batch_item_id, batch_knowledge_id):
        # 获取嵌入表示
        embed_stu = torch.sigmoid(self.emb_stu(batch_stu_id))
        embed_item = torch.sigmoid(self.emb_item(batch_item_id))
        embed_knowledge = torch.sigmoid(self.emb_knowledge(batch_knowledge_id.float()))
        
        # 计算注意力分数
        stu_knowledge_attention = self.W_stu_knowledge(embed_stu)
        item_knowledge_attention = self.W_item_knowledge(embed_item)
        skill_knowledge_attention = self.W_skill_knowledge(embed_knowledge)
        
        # 计算最终的注意力分数
        attention_score = (stu_knowledge_attention * item_knowledge_attention) / np.sqrt(self.knowledge_embed_size) \
                         * skill_knowledge_attention
        
        # 应用gate机制
        gate_score = self.gate(attention_score)
        
        # 输出预测分数
        score = self.linear(gate_score)
        return score

class Learner:
    def __init__(self, train_data, val_data, test_data,
                 student_n, item_n, knowledge_n,
                 knowledge_embed_size, epoch_size,
                 batch_size, lr, device):
        self.train_data = train_data
        self.val_data = val_data
        self.test_data = test_data
        self.student_n = student_n
        self.item_n = item_n
        self.knowledge_n = knowledge_n
        self.knowledge_embed_size = knowledge_embed_size
        self.train_epochs = epoch_size
        self.batch_size = batch_size
        self.lr = lr
        self.device = device

        self.model = CDFKC(student_n, item_n, knowledge_n, knowledge_embed_size)
        self.model = self.model.to(device)
        self.loss_func = nn.MSELoss()
        self.optimizer = optim.Adam(self.model.parameters(), lr=lr)

        self.train_losses = []
        self.val_losses = []
        self.test_losses = []

    def new_model(self):
        model = CDFKC(self.student_n, self.item_n, self.knowledge_n, self.knowledge_embed_size)
        model = model.to(self.device)
        return model

    def reset_model(self):
        self.model = self.new_model()
        self.optimizer = optim.Adam(self.model.parameters(), lr=self.lr)
        self.meta = False
        del self.train_losses[:]
        del self.val_losses[:]
        del self.test_losses[:]

    def evaluate(self):
        self.model.eval()
        error = 0.
        with torch.no_grad():
            for batch_data in tqdm(self.val_data, "Evaluating", file=sys.stdout):
                batch_stu_id, batch_exer_id, batch_knowledge_id, batch_label = batch_data
                batch_stu_id, batch_exer_id, batch_knowledge_id, batch_label = \
                    batch_stu_id.to(self.device), batch_exer_id.to(self.device), \
                    batch_knowledge_id.to(self.device), batch_label.to(self.device)

                predict = self.model(batch_stu_id, batch_exer_id, batch_knowledge_id)
                batch_error = self.loss_func(predict.view(-1), batch_label)
                error += batch_error
        self.model.train()
        return error.item()

    def train(self):
        scheduler = torch.optim.lr_scheduler.ExponentialLR(self.optimizer, 0.5)
        acc_u = 0.
        auc_u = 0.
        f1_u = 0.
        rmse_u = 1.
        
        for epoch in range(self.train_epochs):
            epoch_losses = []

            for batch_stu_id, batch_item_id, batch_knowledge_id, batch_label in tqdm(self.train_data, "training", file=sys.stdout):
                batch_stu_id, batch_item_id, batch_knowledge_id, batch_label = \
                    batch_stu_id.to(self.device), batch_item_id.to(self.device), \
                    batch_knowledge_id.to(self.device), batch_label.to(self.device)

                self.optimizer.zero_grad()
                batch_out = self.model(batch_stu_id, batch_item_id, batch_knowledge_id)
                loss_batch = self.loss_func(batch_out.view(-1), batch_label)
                loss_batch.backward()
                epoch_losses.append(loss_batch.mean().item())
                self.optimizer.step()

            val_loss = self.evaluate()
            self.val_losses.append(val_loss)
            accuracy, roc_auc, rmse, f1 = self.get_test_score()

            if len(self.val_losses) == 0 or val_loss <= min(self.val_losses):
                if self.meta == False:
                    pass
            else:
                scheduler.step()
                self.optimizer = torch.optim.Adam(self.model.parameters(), lr=self.lr)

            if auc_u < roc_auc:
                acc_u = accuracy
                auc_u = roc_auc
                f1_u = f1
                rmse_u = rmse

            print("epoch: ", epoch+1, "| loss: ", float(np.mean(epoch_losses)))
            print("accuracy: ", accuracy, "| roc_auc: ", roc_auc, "| rmse: ", rmse, "| f1: ", f1)
            print('%.4f'%acc_u, '%.4f'%auc_u, '%.4f'%rmse_u, '%.4f'%f1_u)

    def get_scores(self, true_scores, pred_scores):
        accuracy = accuracy_score(true_scores, np.array(pred_scores) >= 0.5)
        roc_auc = roc_auc_score(true_scores, pred_scores)
        rmse = np.sqrt(np.mean((np.array(true_scores) - np.array(pred_scores)) ** 2))
        f1 = f1_score(true_scores, np.array(pred_scores) >= 0.5)
        return accuracy, roc_auc, rmse, f1

    def get_test_score(self):
        self.model.eval()
        y_true = []
        y_pred = []
        for stu_id, item_id, knowledge_id, true_scores in self.test_data:
            stu_id, item_id, knowledge_id, true_scores = \
                stu_id.to(self.device), item_id.to(self.device), \
                knowledge_id.to(self.device), true_scores.to(self.device)

            true_scores = true_scores.view(-1).cpu().detach().numpy()
            pred_scores = self.model(stu_id, item_id, knowledge_id).view(-1).cpu().detach().numpy()
            y_pred.extend(pred_scores.tolist())
            y_true.extend(true_scores.tolist())
        accuracy, roc_auc, rmse, f1 = self.get_scores(y_true, y_pred)
        self.model.train()
        return accuracy, roc_auc, rmse, f1 