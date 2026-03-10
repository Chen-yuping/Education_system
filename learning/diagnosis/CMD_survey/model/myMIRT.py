import logging
import numpy as np
import torch
from torch import nn
import torch.nn.functional as F
from tqdm import tqdm
from sklearn.metrics import roc_auc_score, accuracy_score, f1_score
import sys


class MIRTNet(nn.Module):
    def __init__(self, user_num, item_num, latent_dim, a_range, irf_kwargs=None):
        super(MIRTNet, self).__init__()
        self.user_num = user_num
        self.item_num = item_num
        self.latent_dim = latent_dim

        self.pro = nn.Embedding(self.user_num, self.latent_dim)
        self.diff = nn.Embedding(self.item_num, self.latent_dim)
        self.student_q = nn.Embedding(self.user_num, self.latent_dim)
        # self.exercise_k = nn.Embedding(self.item_num, self.latent_dim)
        self.exercise_k = nn.Embedding(self.item_num, 1)

        # self.l1 = nn.Linear(2*self.latent_dim, 2*self.latent_dim)
        # self.l2 = nn.Linear(2 * self.latent_dim, self.latent_dim)
        # self.l3 = nn.Linear(2 * self.latent_dim, 2*self.latent_dim)
        # self.l4 = nn.Linear(2 * self.latent_dim, self.latent_dim)
        for name, param in self.named_parameters():
            if 'weight' in name:
                nn.init.xavier_normal_(param)

    def forward(self, user, item):
        pro = torch.sigmoid(self.pro(user))
        diff = torch.sigmoid(self.diff(item))
        # stu_q = self.student_q(user)
        exer_k = self.exercise_k(item)
        # disc_p = torch.tanh(self.l1(torch.cat((stu_q, perf), dim=1)))
        # disc_p = 2*torch.sigmoid(self.l2(disc_p))

        # disc_d = torch.tanh(self.l3(torch.cat((exer_k, perf), dim=1)))
        # disc_d = 2*torch.sigmoid(self.l4(disc_d))

        disc = 2*torch.sigmoid(exer_k)
        # disc = exer_k

        perf = (pro - diff) * disc
        # perf = pro - diff


        input_x = torch.sum(perf, dim=1)
        output = torch.sigmoid(input_x)

        return output


class MIRT:
    def __init__(self, user_num, item_num, latent_dim, a_range=None):
        super(MIRT, self).__init__()
        self.irt_net = MIRTNet(user_num, item_num, latent_dim, a_range)

    def train(self, train_data, test_data=None, *, epoch: int, device="cpu", lr=0.001) -> ...:
        self.irt_net = self.irt_net.to(device)
        loss_function = nn.BCELoss()

        trainer = torch.optim.Adam(self.irt_net.parameters(), lr)
        best_epoch = 0
        best_auc = 0.
        acc1 = 0.
        best_f1 = 0.
        rmse1 = 1.

        for e in range(epoch):
            losses = []
            for batch_data in tqdm(train_data, "Epoch %s" % e, file=sys.stdout):
                user_id, item_id, _, response = batch_data
                user_id: torch.Tensor = user_id.to(device)
                item_id: torch.Tensor = item_id.to(device)
                predicted_response: torch.Tensor = self.irt_net(user_id, item_id)
                response: torch.Tensor = response.to(device)
                loss = loss_function(predicted_response, response)

                # back propagation
                trainer.zero_grad()
                loss.backward()
                trainer.step()

                losses.append(loss.mean().item())
            print("[Epoch %d] LogisticLoss: %.6f" % (e, float(np.mean(losses))))

            if test_data is not None:
                auc, accuracy, rmse, f1 = self.eval(test_data, device=device)
                print("[Epoch %d] auc: %.6f, accuracy: %.6f, rmse: %.6f, f1: %.6f" % (e, auc, accuracy, rmse, f1))
                if auc > best_auc:
                    best_epoch = e
                    best_auc = auc
                    acc1 = accuracy
                    rmse1 = rmse
                    best_f1 = f1
                    # self.save("params/mymirt.params")
            print('BEST epoch<%d>, auc: %s, acc: %s, rmse: %.6f, f1: %.6f' % (best_epoch, best_auc, acc1, rmse1, best_f1))
        return best_epoch, best_auc, acc1

    def eval(self, test_data, device="cpu") -> tuple:
        self.irt_net = self.irt_net.to(device)
        self.irt_net.eval()
        y_pred = []
        y_true = []
        for batch_data in tqdm(test_data, "evaluating", file=sys.stdout):
            user_id, item_id, _, response = batch_data
            user_id: torch.Tensor = user_id.to(device)
            item_id: torch.Tensor = item_id.to(device)
            pred: torch.Tensor = self.irt_net(user_id, item_id)
            y_pred.extend(pred.tolist())
            y_true.extend(response.tolist())
        rmse = np.sqrt(np.mean((np.array(y_true) - np.array(y_pred)) ** 2))
        self.irt_net.train()
        return roc_auc_score(y_true, y_pred), accuracy_score(y_true, np.array(y_pred) >= 0.5), rmse, f1_score(y_true, np.array(y_pred) >= 0.5)

    def save(self, filepath):
        torch.save(self.irt_net.state_dict(), filepath)
        logging.info("save parameters to %s" % filepath)

    def load(self, filepath):
        self.irt_net.load_state_dict(torch.load(filepath))
        logging.info("load parameters from %s" % filepath)
