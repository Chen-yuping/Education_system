import numpy as np
from sklearn.decomposition import NMF
import torch
import json
from tqdm import tqdm
import sys
import os

# 将项目根目录添加到路径中，以便导入 params
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import params

class NMF_Q_Matrix:
    """
    使用非负矩阵分解 (NMF) 来预测 Q 矩阵的类。
    逻辑：
    1. 构建学生-题目得分矩阵 V (Users x Items)。
    2. 使用 NMF 将 V 分解为 W (Users x Skills) 和 H (Skills x Items)。
       V (R) ≈ S (Students x Skills) * Q^T (Skills x Items)
       Q 矩阵 = H.T (Items x Skills)
    """
    def __init__(self, user_num, item_num, skill_num, max_iter=500, verbose=1):
        self.user_num = user_num
        self.item_num = item_num
        self.skill_num = skill_num
        
        # 检查 n_components 是否超过矩阵维度限制
        max_components = min(item_num, user_num)
        if skill_num > max_components:
            print(f"Warning: skill_num ({skill_num}) > min(items, users) ({max_components})")
            print(f"Using 'random' init instead of 'nndsvda'")
            init_method = 'random'
        else:
            init_method = 'nndsvda'
        
        # solver='mu': 乘法更新规则，对稀疏数据更稳定
        self.model = NMF(
            n_components=skill_num, 
            init=init_method,
            solver='mu',
            beta_loss='frobenius',
            random_state=42, 
            max_iter=max_iter, 
            verbose=verbose, 
            tol=1e-4,
            alpha_W=0.1,
            alpha_H=0.1,
            l1_ratio=0.5
        )
        self.Q_matrix = None
        self.S_matrix = None

    def fit(self, data_loader):
        """
        从数据加载器中构建评分矩阵并拟合 NMF 模型。
        
        按照 Desmarais (2012) 论文的逻辑：
        V (items × users) ≈ W (items × skills) × H (skills × users)
        其中 W 就是我们要的 Q 矩阵
        """
        # 构建 V 矩阵，形状为 (items × users)，与论文一致
        V = np.zeros((self.item_num, self.user_num))

        print("Building Score Matrix V (items × users) from Data Loader...")
        print("Following Desmarais (2012): V ≈ W(Q) × H(S)")
        
        if isinstance(data_loader, torch.utils.data.DataLoader):
            for batch in tqdm(data_loader, desc="Processing Batches"):
                user_ids, item_ids, _, scores = batch
                user_ids = user_ids.numpy()
                item_ids = item_ids.numpy()
                scores = scores.numpy()
                
                for u, i, s in zip(user_ids, item_ids, scores):
                    if u < self.user_num and i < self.item_num:
                         V[i, u] = s  # 注意：V[item, user]
        else:
            for log in tqdm(data_loader, desc="Processing Logs"):
                u = log['user_id']
                i = log['exer_id']
                s = log['score']
                if u < self.user_num and i < self.item_num:
                    V[i, u] = s  # 注意：V[item, user]
        
        print(f"Score Matrix V shape: {V.shape} (items × users)")
        print(f"Sparsity: {1.0 - np.count_nonzero(V) / V.size:.4f}")

        print("Running NMF: V ≈ W × H ...")
        # NMF 分解：V ≈ W × H
        # W: (items × skills) - 这就是 Q 矩阵
        # H: (skills × users) - 这是学生能力矩阵 S 的转置
        self.Q_matrix = self.model.fit_transform(V)  # W: items × skills
        H = self.model.components_                    # H: skills × users
        self.S_matrix = H.T                           # S: users × skills
        
        print(f"Q matrix (W) shape: {self.Q_matrix.shape} (items × skills)")
        print(f"S matrix (H.T) shape: {self.S_matrix.shape} (users × skills)")
        print("NMF finished.")
        return self.Q_matrix

    def get_binary_q_matrix(self, method='argmax'):
        """
        将连续值的 Q 矩阵转换为 0/1 二值矩阵。
        
        按照 Desmarais (2012) 论文的方法：
        每个题目只分配到 1 个技能，使用 argmax 选择权重最大的技能。
        
        Args:
            method: 二值化方法
                - 'argmax': 论文原始方法，每题只选1个技能（默认）
        """
        if self.Q_matrix is None:
            raise ValueError("Model not fitted yet.")
        
        binary_Q = np.zeros_like(self.Q_matrix)
        
        # 论文方法：每个 item 只分配到权重最大的那个 skill
        # "assigns each item to one of the K clusters based on the maximum column value in W"
        for i in range(self.item_num):
            row = self.Q_matrix[i]
            max_skill_idx = np.argmax(row)
            binary_Q[i, max_skill_idx] = 1
        
        skills_per_item = binary_Q.sum(axis=1)
        print(f"Binary Q-matrix stats (method={method}):")
        print(f"  Skills per item: {skills_per_item.mean():.2f} (should be 1.0)")
        print(f"  Total items: {self.item_num}")
        
        # 统计每个技能被分配了多少题目
        items_per_skill = binary_Q.sum(axis=0)
        print(f"  Items per skill distribution:")
        print(f"    Min: {items_per_skill.min()}, Max: {items_per_skill.max()}, Mean: {items_per_skill.mean():.2f}")
        
        return binary_Q

    def save_q_matrix(self, filepath):
        """保存预测的 Q 矩阵到文件"""
        if self.Q_matrix is None:
            raise ValueError("Model not fitted yet.")
        np.savetxt(filepath, self.Q_matrix, fmt='%.4f')
        print(f"Q-matrix saved to {filepath}")
    
    def save_binary_q_matrix(self, filepath, method='argmax'):
        """保存二值化 Q 矩阵"""
        bin_q = self.get_binary_q_matrix(method=method)
        np.savetxt(filepath, bin_q, fmt='%d')
        print(f"Binary Q-matrix saved to {filepath}")


if __name__ == "__main__":
    u_num = 100
    i_num = 50
    k_num = 5
    
    true_Q = np.random.randint(0, 2, (i_num, k_num))
    for i in range(i_num):
        if true_Q[i].sum() == 0:
            true_Q[i, np.random.randint(0, k_num)] = 1
            
    true_S = np.random.rand(u_num, k_num)
    true_V = np.dot(true_S, true_Q.T)
    V_obs = (true_V > 0.5).astype(float)
    
    data = []
    for u in range(u_num):
        for i in range(i_num):
            if np.random.rand() > 0.5:
                data.append({'user_id': u, 'exer_id': i, 'score': V_obs[u, i]})
            
    nmf_solver = NMF_Q_Matrix(u_num, i_num, k_num)
    predicted_Q = nmf_solver.fit(data)
    
    print("Predicted Q (First 5 items):")
    print(predicted_Q[:5])
    
    bin_Q = nmf_solver.get_binary_q_matrix(method='argmax')
    print("Binary Q (First 5 items):")
    print(bin_Q[:5])
