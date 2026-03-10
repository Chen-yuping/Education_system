import logging
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
import numpy as np
from tqdm import tqdm
from sklearn.metrics import roc_auc_score, accuracy_score, f1_score
import sys


class PosLinear(nn.Linear):
    def forward(self, input: torch.Tensor) -> torch.Tensor:
        weight = 2 * F.relu(1 * torch.neg(self.weight)) + self.weight
        return F.linear(input, weight, self.bias)


class Net(nn.Module):

    def __init__(self, knowledge_n, exer_n, student_n):
        self.knowledge_dim = knowledge_n
        self.exer_n = exer_n
        self.emb_num = student_n
        self.stu_dim = self.knowledge_dim
        self.prednet_input_len = self.knowledge_dim
        self.prednet_len1, self.prednet_len2 = 512, 256  # changeable

        super(Net, self).__init__()

        # prediction sub-net
        self.student_emb = nn.Embedding(self.emb_num, self.stu_dim)
        self.k_difficulty = nn.Embedding(self.exer_n, self.knowledge_dim)
        self.e_difficulty = nn.Embedding(self.exer_n, 1)
        self.prednet_full1 = PosLinear(self.prednet_input_len, self.prednet_len1)
        self.drop_1 = nn.Dropout(p=0.5)
        self.prednet_full2 = PosLinear(self.prednet_len1, self.prednet_len2)
        self.drop_2 = nn.Dropout(p=0.5)
        self.prednet_full3 = PosLinear(self.prednet_len2, 1)

        # initialize
        for name, param in self.named_parameters():
            if 'weight' in name:
                nn.init.xavier_normal_(param)

    def forward(self, stu_id, input_exercise, input_knowledge_point):
        # before prednet
        stu_emb = self.student_emb(stu_id)
        stat_emb = torch.sigmoid(stu_emb)
        k_difficulty = torch.sigmoid(self.k_difficulty(input_exercise))
        e_difficulty = torch.sigmoid(self.e_difficulty(input_exercise)) * 2
        # prednet
        input_x = e_difficulty * (stat_emb - k_difficulty) * input_knowledge_point
        # input_x = e_difficulty * (stat_emb - k_difficulty)

        input_x = self.drop_1(torch.sigmoid(self.prednet_full1(input_x)))
        input_x = self.drop_2(torch.sigmoid(self.prednet_full2(input_x)))
        output_1 = torch.sigmoid(self.prednet_full3(input_x))

        return output_1.view(-1)

    def advantage(self, stu_id, exer_id, kq):

        stu_emb = self.student_emb(stu_id)
        stat_emb = torch.sigmoid(stu_emb)
        k_difficulty = torch.sigmoid(self.k_difficulty(exer_id))
        e_difficulty = torch.sigmoid(self.e_difficulty(exer_id))  # * 10
        # prednet
        input_x = e_difficulty * (stat_emb - k_difficulty) * kq
        input_x = self.drop_1(torch.sigmoid(self.prednet_full1(input_x)))
        return input_x

    def pro_case(self, stu_id, input_exercise, input_knowledge_point):
        # before prednet
        stu_emb = self.student_emb(stu_id)
        stat_emb = torch.sigmoid(stu_emb)
        e_difficulty = torch.sigmoid(self.e_difficulty(input_exercise))  # * 10
        # prednet
        output = e_difficulty * stat_emb * input_knowledge_point

        x2 = torch.zeros_like(input_knowledge_point)
        x2[:, 96] = 1  # change here!!!!!!
        xb2 = (x2 * input_knowledge_point).bool()
        output_s = output[xb2]
        x3 = torch.zeros((len(output_s), self.knowledge_dim))
        x3[:, 96] = output_s

        return output, x3

    def params(self, device):
        self.to(device)
        stu_index = torch.LongTensor(range(self.emb_num)).to(device)
        stu_v = torch.sigmoid(self.student_emb(stu_index))
        return stu_v

    def exer_v(self, device):
        self.to(device)
        exer_index = torch.LongTensor(range(self.exer_n)).to(device)
        exer_v = torch.sigmoid(self.k_difficulty(exer_index))
        return exer_v

class NCDM:
    '''Neural Cognitive Diagnosis Model'''

    def __init__(self, knowledge_n, exer_n, student_n):
        super(NCDM, self).__init__()
        self.ncdm_net = Net(knowledge_n, exer_n, student_n)

    def train(self, train_data, test_data=None, epoch=10, device="cpu", lr=0.002, silence=False):
        self.ncdm_net = self.ncdm_net.to(device)
        self.ncdm_net.train()
        loss_function = nn.BCELoss()
        optimizer = optim.Adam(self.ncdm_net.parameters(), lr=lr)
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
                user_id, item_id, knowledge_emb, y = batch_data
                user_id: torch.Tensor = user_id.to(device)
                item_id: torch.Tensor = item_id.to(device)
                knowledge_emb: torch.Tensor = knowledge_emb.to(device)
                y: torch.Tensor = y.to(device)
                pred: torch.Tensor = self.ncdm_net(user_id, item_id, knowledge_emb)
                loss = loss_function(pred, y)

                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

                epoch_losses.append(loss.mean().item())

            print("[Epoch %d] average loss: %.6f" % (epoch_i, float(np.mean(epoch_losses))))

            if test_data is not None:
                auc, accuracy, rmse, f1 = self.eval(test_data, device=device)
                print("[Epoch %d] auc: %.6f, accuracy: %.6f, rmse: %.6f, f1: %.6f" % (epoch_i, auc, accuracy, rmse, f1))
                if auc > best_auc:
                    best_epoch = epoch_i
                    best_auc = auc
                    acc1 = accuracy
                    best_f1 = f1
                    rmse1 = rmse
                    # self.save("params/ncdm.params")
            print('BEST epoch<%d>, auc: %s, acc: %s, rmse: %.6f, f1: %.6f' % (best_epoch, best_auc, acc1, rmse1, best_f1))
        return best_epoch, best_auc, acc1

    def eval(self, test_data, device="cpu"):
        self.ncdm_net = self.ncdm_net.to(device)
        self.ncdm_net.eval()
        y_true, y_pred = [], []
        for batch_data in tqdm(test_data, "Evaluating", file=sys.stdout):
            user_id, item_id, knowledge_emb, y = batch_data
            user_id: torch.Tensor = user_id.to(device)
            item_id: torch.Tensor = item_id.to(device)
            knowledge_emb: torch.Tensor = knowledge_emb.to(device)
            pred: torch.Tensor = self.ncdm_net(user_id, item_id, knowledge_emb)

            y_pred.extend(pred.detach().cpu().tolist())
            y_true.extend(y.tolist())
        rmse = np.sqrt(np.mean((np.array(y_true) - np.array(y_pred)) ** 2))

        return roc_auc_score(y_true, y_pred), accuracy_score(y_true, np.array(y_pred) >= 0.5), rmse, f1_score(y_true, np.array(y_pred) >= 0.5)

    def save(self, filepath):
        torch.save(self.ncdm_net.state_dict(), filepath)
        logging.info("save parameters to %s" % filepath)

    def load(self, filepath):
        self.ncdm_net.load_state_dict(torch.load(filepath))  # , map_location=lambda s, loc: s
        logging.info("load parameters from %s" % filepath)

    def advantage(self, test_data, device="cpu"):
        self.ncdm_net = self.ncdm_net.to(device)
        self.ncdm_net.eval()
        label, feature = [], []
        for batch_data in tqdm(test_data, "Get advantage", file=sys.stdout):
            user_id, item_id, kq, y = batch_data
            user_id: torch.Tensor = user_id.to(device)
            item_id: torch.Tensor = item_id.to(device)
            kq = kq.to(device)
            advantage = self.ncdm_net.advantage(user_id, item_id, kq)

            feature.extend(advantage.detach().cpu().tolist())
            label.extend(y.tolist())
        return feature, label

    def pro_case(self, test_data, device="cpu"):
        self.ncdm_net = self.ncdm_net.to(device)
        self.ncdm_net.eval()
        feature, feature_s = [], []
        for batch_data in tqdm(test_data, "Get some pro", file=sys.stdout):
            user_id, item_id, kq, _ = batch_data
            user_id: torch.Tensor = user_id.to(device)
            item_id: torch.Tensor = item_id.to(device)
            kq = kq.to(device)
            pro, pro_s = self.ncdm_net.pro_case(user_id, item_id, kq)

            feature.extend(pro.detach().cpu().tolist())
            feature_s.extend(pro_s.detach().cpu().tolist())

        return feature, feature_s

    def student_v(self, device="cpu"):
        self.load("params/ncdm.params")
        stu_v = self.ncdm_net.params(device)
        return stu_v

    def exer_v(self, device="cpu"):
        self.load("params/ncdm.params")
        exer_v = self.ncdm_net.exer_v(device)
        return exer_v