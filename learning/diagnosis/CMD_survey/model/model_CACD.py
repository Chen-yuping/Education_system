import torch
import torch.nn as nn
import torch.nn.functional as F


class Net(nn.Module):
    def __init__(self, student_n, exer_n, knowledge_n):
        self.knowledge_dim = knowledge_n
        self.exer_n = exer_n
        self.emb_num = student_n
        self.stu_dim = self.knowledge_dim
        self.affect_dim = self.knowledge_dim
        self.prednet_input_len = self.knowledge_dim
        self.prednet_len1, self.prednet_len2 = 512,256 

        super(Net, self).__init__()

        self.student_emb = nn.Embedding(self.emb_num, self.stu_dim)
        self.student_affect = nn.Embedding(self.emb_num, self.affect_dim)
        self.k_difficulty = nn.Embedding(self.exer_n, self.knowledge_dim)
        self.e_discrimination = nn.Embedding(self.exer_n, 1)
        self.prednet_affect = nn.Linear(
            self.knowledge_dim + self.affect_dim, 4)
        self.guess = nn.Linear(4, 1)
        self.slip = nn.Linear(4, 1)

        self.prednet_full1 = nn.Linear(self.prednet_input_len, self.prednet_len1)
        self.prednet_full2 = nn.Linear(self.prednet_len1, self.prednet_len2)
        self.prednet_full3 = nn.Linear(self.prednet_len2, 1)

        # initialization    
        for name, param in self.named_parameters():
            if 'weight' in name:
                nn.init.xavier_normal_(param)


    def forward(self, stu_id, exer_id, kn_emb, labels=None):
        # 确保ID在有效范围内
        if torch.max(stu_id).item() >= self.emb_num or torch.min(stu_id).item() < 0:
            raise ValueError(f"学生ID越界: 最大值 {torch.max(stu_id).item()}, 最小值 {torch.min(stu_id).item()}, 学生数量 {self.emb_num}")
        if torch.max(exer_id).item() >= self.exer_n or torch.min(exer_id).item() < 0:
            raise ValueError(f"习题ID越界: 最大值 {torch.max(exer_id).item()}, 最小值 {torch.min(exer_id).item()}, 习题数量 {self.exer_n}")
        
        stu_emb = torch.sigmoid(self.student_emb(stu_id))
        stu_affect = torch.sigmoid(self.student_affect(stu_id))
        k_difficulty = torch.sigmoid(self.k_difficulty(exer_id))
        affect = torch.sigmoid(self.prednet_affect(torch.cat((stu_affect, k_difficulty), dim=1)))
        e_discrimination = torch.sigmoid(
            self.e_discrimination(exer_id)) * 10
        input_x = e_discrimination * (stu_emb - k_difficulty) * kn_emb 
        input_x = torch.sigmoid(self.prednet_full1(input_x))
        input_x = torch.sigmoid(self.prednet_full2(input_x))
        o = torch.sigmoid(self.prednet_full3(input_x))
        g = torch.sigmoid(self.guess(affect))
        s = torch.sigmoid(self.slip(affect))
        output = ((1-s)*o) + (g*(1-o))
        if labels is not None:
            try:
                closs = self.contrastive_loss(affect, labels)
                return output, affect, closs
            except Exception as e:
                print(f"对比损失计算错误: {e}")
                # 返回一个默认的对比损失
                return output, affect, torch.tensor(0.1, device=output.device)
        return output, affect

    def contrastive_loss(self, affect, label):
        t = 0.1
        batch_size = affect.shape[0]
        
        # 如果批次大小为1，无法计算对比损失
        if batch_size <= 1:
            return torch.tensor(0.1, device=affect.device)
            
        try:
            similarity_matrix = F.cosine_similarity(affect.unsqueeze(1), affect.unsqueeze(0), dim=2)
            mask_positive = torch.ones_like(similarity_matrix) * (label.expand(batch_size, batch_size).eq(label.expand(batch_size, batch_size).t()))
            mask_negative = torch.ones_like(mask_positive) - mask_positive
            mask_0 = torch.ones(batch_size, batch_size, device=affect.device) - torch.eye(batch_size, batch_size, device=affect.device)
            mask_positive = mask_positive.to(affect.device)
            mask_negative = mask_negative.to(affect.device)
            
            similarity_matrix = torch.exp(similarity_matrix/t)
            similarity_matrix = similarity_matrix * mask_0
            positives = mask_positive*similarity_matrix
            
            # 检查正例是否存在
            if torch.sum(positives) == 0:
                return torch.tensor(0.1, device=affect.device)
                
            negatives = similarity_matrix - positives
            negatives_sum = torch.sum(negatives, dim=1)
            negatives_sum_expend = negatives_sum.repeat(batch_size, 1).T
            positives_sum = positives + negatives_sum_expend
            
            # 避免除以零
            epsilon = 1e-8
            loss = torch.div(positives, positives_sum + epsilon)
            loss = loss + mask_negative + torch.eye(batch_size, batch_size, device=loss.device)
            loss = -torch.log(loss + epsilon)
            
            # 计算非零元素数量，避免除以零
            non_zero_count = torch.nonzero(loss).size(0)
            if non_zero_count > 0:
                loss = torch.sum(torch.sum(loss, dim=1)) / non_zero_count
            else:
                loss = torch.tensor(0.1, device=affect.device)
                
            return loss
        except Exception as e:
            print(f"对比损失计算中出现异常: {e}")
            return torch.tensor(0.1, device=affect.device)

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
