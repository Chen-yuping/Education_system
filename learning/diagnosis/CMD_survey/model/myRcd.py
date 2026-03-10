import torch
import torch.nn as nn
import logging
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


class ACDMNET(nn.Module):
    def __init__(self, stu_n, exer_n, k_n, emb_dim):

        super(ACDMNET, self).__init__()
        self.stu_n = stu_n
        self.exer_n = exer_n
        self.k_n = k_n
        self.emb_dim = emb_dim

        self.student_v = nn.Embedding(self.stu_n, self.emb_dim)
        self.exercise_v = nn.Embedding(self.exer_n, self.emb_dim)
        self.knowledge_v = nn.Embedding(self.k_n, self.emb_dim)
        self.device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')

        self.k_index = torch.LongTensor(list(range(self.k_n))).to(self.device)

        self.prednet_full1 = PosLinear(2 * self.emb_dim, self.emb_dim)
        # self.drop_3 = nn.Dropout(p=0.5)
        self.prednet_full2 = PosLinear(2 * self.emb_dim, self.emb_dim)
        # self.drop_4 = nn.Dropout(p=0.5)
        self.prednet_full3 = PosLinear(self.emb_dim, 1)

        for name, param in self.named_parameters():
            if 'weight' in name:
                nn.init.xavier_normal_(param)

    def forward(self, stu_id, exer_id, kq):
        stu_v = self.student_v(stu_id)
        exer_v = self.exercise_v(exer_id)
        k_v = self.knowledge_v(self.k_index)

        batch_stu_vector = stu_v.repeat(1, k_v.shape[0]).reshape(stu_v.shape[0], k_v.shape[0], stu_v.shape[1])
        batch_exer_vector = exer_v.repeat(1, k_v.shape[0]).reshape(exer_v.shape[0], k_v.shape[0], exer_v.shape[1])
        kn_vector = k_v.repeat(stu_v.shape[0], 1).reshape(stu_v.shape[0], k_v.shape[0], k_v.shape[1])

        preference = torch.sigmoid(self.prednet_full1(torch.cat((batch_stu_vector, kn_vector), dim=2)))
        diff = torch.sigmoid(self.prednet_full2(torch.cat((batch_exer_vector, kn_vector), dim=2)))
        advantage = preference - diff
        input_x = advantage

        o = torch.sigmoid(self.prednet_full3(input_x))
        sum_out = torch.sum(o * kq.unsqueeze(2), dim=1)
        count_of_concept = torch.sum(kq, dim=1).unsqueeze(1)
        output = sum_out / count_of_concept

        return torch.squeeze(output)

    def advantage(self, stu_id, exer_id, kq):

        stu_v = self.student_v(stu_id)
        exer_v = self.exercise_v(exer_id)
        k_v = self.knowledge_v(self.k_index)

        batch_stu_vector = stu_v.repeat(1, k_v.shape[0]).reshape(stu_v.shape[0], k_v.shape[0], stu_v.shape[1])
        batch_exer_vector = exer_v.repeat(1, k_v.shape[0]).reshape(exer_v.shape[0], k_v.shape[0], exer_v.shape[1])
        kn_vector = k_v.repeat(stu_v.shape[0], 1).reshape(stu_v.shape[0], k_v.shape[0], k_v.shape[1])

        preference = torch.sigmoid(self.prednet_full1(torch.cat((batch_stu_vector, kn_vector), dim=2)))
        diff = torch.sigmoid(self.prednet_full2(torch.cat((batch_exer_vector, kn_vector), dim=2)))

        advantage = preference - diff

        # o = torch.sigmoid(self.prednet_full3(input_x))
        advantage = advantage * kq.unsqueeze(2)
        advantage = torch.sum(advantage, dim=1)
        count_of_concept = torch.sum(kq, dim=1).unsqueeze(1)
        output = advantage / count_of_concept

        return output

    def pro_case(self, stu_id, exer_id, kq):
        stu_v = self.student_v(stu_id)
        k_v = self.knowledge_v(self.k_index)

        batch_stu_vector = stu_v.repeat(1, k_v.shape[0]).reshape(stu_v.shape[0], k_v.shape[0], stu_v.shape[1])
        kn_vector = k_v.repeat(stu_v.shape[0], 1).reshape(stu_v.shape[0], k_v.shape[0], k_v.shape[1])

        preference = torch.sigmoid(self.prednet_full1(torch.cat((batch_stu_vector, kn_vector), dim=2)))
        output = preference[kq.bool()]

        x2 = torch.zeros_like(kq)
        x2[:, 52] = 1  # change here!!!!!!
        xb2 = (x2 * kq).bool()
        output_s = preference[xb2]

        return output, output_s

    def diff_case(self, stu_id, exer_id, kq):
        exer_v = self.exercise_v(exer_id)
        k_v = self.knowledge_v(self.k_index)

        batch_exer_vector = exer_v.repeat(1, k_v.shape[0]).reshape(exer_v.shape[0], k_v.shape[0], exer_v.shape[1])
        kn_vector = k_v.repeat(exer_v.shape[0], 1).reshape(exer_v.shape[0], k_v.shape[0], k_v.shape[1])

        diff = torch.sigmoid(self.prednet_full2(torch.cat((batch_exer_vector, kn_vector), dim=2)))

        # #第一次，全筛选了
        # xb1 = [x == 3855 -1 for x in exer_id]
        # output = diff[xb1]
        # x2 = torch.zeros((output.shape[0],output.shape[1]))
        # x2[:, 21 -1] = 1  # change here!!!!!!
        # xb2 = (x2).bool()
        # output_s = output[xb2]
        # return output_s

        #第二次，只根据知识点筛选了
        x2 = torch.zeros_like(kq)
        x2[:, 21-1] = 1  # change here!!!!!!
        xb2 = (x2 * kq).bool()
        output = diff[xb2]
        return output

class ACD:
    def __init__(self, student_n, exer_n, k_n, emb_dim):
        super(ACD, self).__init__()
        self.acd_net = ACDMNET(student_n, exer_n, k_n, emb_dim)

    def train(self, train_data, test_data=None, epoch=10, device="cpu", lr=0.002):
        self.acd_net = self.acd_net.to(device)
        self.acd_net.train()
        loss_function = nn.BCELoss()
        optimizer = optim.Adam(self.acd_net.parameters(), lr=lr)
        best_epoch = 0
        best_auc = 0.
        acc1 = 0.
        rmse1 = 1.
        best_f1 = 0.

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

                pred: torch.Tensor = self.acd_net(user_id, item_id, kq)

                loss = loss_function(pred, y)

                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

                epoch_losses.append(loss.mean().item())

            print("[Epoch %d] average loss: %.6f" % (epoch_i, float(np.mean(epoch_losses))))

            if test_data is not None:
                auc, accuracy, rmse, f1 = self.eval(test_data, device=device)
                # print("[Epoch %d] auc: %.6f, accuracy: %.6f" % (epoch_i, auc, accuracy))
                print("[Epoch %d] auc: %.6f, accuracy: %.6f, rmse: %.6f, f1: %.6f" % (epoch_i, auc, accuracy, rmse, f1))

                # if rmse < rmse1:
                if best_auc < auc:
                    best_epoch = epoch_i
                    best_auc = auc
                    acc1 = accuracy
                    rmse1 = rmse
                    best_f1 = f1

                    # self.save("params/rcd.params")
            # print('BEST epoch<%d>, auc: %s, acc: %s' % (best_epoch, best_auc, acc1))
            print('BEST epoch<%d>, auc: %s, acc: %s, rmse: %.6f, f1: %.6f' % (best_epoch, best_auc, acc1, rmse1, best_f1))

        return best_epoch, best_auc, acc1, rmse1

    def eval(self, test_data, device="cpu"):
        self.acd_net = self.acd_net.to(device)
        self.acd_net.eval()
        y_true, y_pred = [], []
        rmse = 0.
        for batch_data in tqdm(test_data, "Evaluating", file=sys.stdout):
            user_id, item_id, kq, y = batch_data
            user_id: torch.Tensor = user_id.to(device)
            item_id: torch.Tensor = item_id.to(device)
            kq = kq.to(device)
            pred: torch.Tensor = self.acd_net(user_id, item_id, kq)

            y_pred.extend(pred.detach().cpu().tolist())
            y_true.extend(y.tolist())
        rmse = np.sqrt(np.mean((np.array(y_true) - np.array(y_pred)) ** 2))
        return roc_auc_score(y_true, y_pred), accuracy_score(y_true, np.array(y_pred) >= 0.5), rmse, f1_score(y_true, np.array(y_pred) >= 0.5)

    def save(self, filepath):
        torch.save(self.acd_net.state_dict(), filepath)
        logging.info("save parameters to %s" % filepath)

    def load(self, filepath):
        self.acd_net.load_state_dict(torch.load(filepath))  # , map_location=lambda s, loc: s
        logging.info("load parameters from %s" % filepath)

    def advantage(self, test_data, device="cpu"):
        self.acd_net = self.acd_net.to(device)
        self.acd_net.eval()
        label, feature = [], []
        for batch_data in tqdm(test_data, "Get advantage", file=sys.stdout):
            user_id, item_id, kq, y = batch_data
            user_id: torch.Tensor = user_id.to(device)
            item_id: torch.Tensor = item_id.to(device)
            kq = kq.to(device)
            advantage = self.acd_net.advantage(user_id, item_id, kq)

            feature.extend(advantage.detach().cpu().tolist())
            label.extend(y.tolist())
        return feature, label

    def pro_case(self, test_data, device="cpu"):
        self.acd_net = self.acd_net.to(device)
        self.acd_net.eval()
        feature, feature_s = [], []
        for batch_data in tqdm(test_data, "Get some pro", file=sys.stdout):
            user_id, item_id, kq, _ = batch_data
            user_id: torch.Tensor = user_id.to(device)
            item_id: torch.Tensor = item_id.to(device)
            kq = kq.to(device)
            pro, pro_s = self.acd_net.pro_case(user_id, item_id, kq)

            feature.extend(pro.detach().cpu().tolist())
            feature_s.extend(pro_s.detach().cpu().tolist())

        return feature, feature_s

    def diff_case(self, test_data, device="cpu"):
        self.acd_net = self.acd_net.to(device)
        self.acd_net.eval()
        feature_s = []
        for batch_data in tqdm(test_data, "Get some diff", file=sys.stdout):
            user_id, item_id, kq, _ = batch_data
            user_id: torch.Tensor = user_id.to(device)
            item_id: torch.Tensor = item_id.to(device)
            kq = kq.to(device)
            diff_s = self.acd_net.diff_case(user_id, item_id, kq)

            feature_s.extend(diff_s.detach().cpu().tolist())

        return feature_s