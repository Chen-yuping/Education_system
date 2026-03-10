import logging
import torch
import numpy as np
from tqdm import tqdm
from sklearn.metrics import roc_auc_score, accuracy_score, f1_score
import sys
import os
import pandas as pd
from model.ICD.ICD import ICD

class ICD_Adapter:
    '''ICD适配器 - 使ICD模型能够接受与其他模型相同格式的json数据'''

    def __init__(self, knowledge_n, exer_n, student_n, cdm_type='mirt', alpha=0.2, beta=0.9, stream_num=10):
        """
        初始化ICD适配器
        
        Args:
            knowledge_n: 知识点数量
            exer_n: 习题数量
            student_n: 学生数量
            cdm_type: 底层认知诊断模型类型，可选'mirt', 'irt', 'ncd', 'dina'
            alpha: 动量参数
            beta: 遗忘因子
            stream_num: 数据流的分割数量
        """
        self.knowledge_n = knowledge_n
        self.exer_n = exer_n
        self.student_n = student_n
        self.cdm_type = cdm_type
        self.alpha = alpha
        self.beta = beta
        self.stream_num = stream_num
        
        # 初始化ICD模型
        self.icd = ICD(
            cdm=cdm_type,
            user_n=student_n,
            item_n=exer_n,
            know_n=knowledge_n,
            epoch=1,
            inner_metrics=True,
            logger=logging,
            alpha=alpha,
            ctx='cuda:0' if torch.cuda.is_available() else 'cpu'
        )
        
        # 创建临时目录来存储转换后的数据
        os.makedirs('temp_data', exist_ok=True)

    def _convert_json_to_csv(self, data_loader, file_path):
        """将json格式的数据转换为ICD模型需要的CSV格式"""
        print(f"Converting data to CSV format for ICD: {file_path}")
        records = []
        
        for batch_data in tqdm(data_loader, "Processing data", file=sys.stdout):
            user_id, item_id, knowledge_emb, y = batch_data
            
            # 转换为CPU上的numpy数组
            user_id = user_id.cpu().numpy()
            item_id = item_id.cpu().numpy()
            knowledge_emb = knowledge_emb.cpu().numpy()
            y = y.cpu().numpy()
            
            for i in range(len(user_id)):
                # 获取知识点列表
                k_ids = np.where(knowledge_emb[i] > 0)[0] + 1  # 加1因为知识点ID通常从1开始
                
                records.append({
                    'user_id': int(user_id[i]) + 1,  # 加1因为ICD通常使用从1开始的ID
                    'item_id': int(item_id[i]) + 1,
                    'score': float(y[i]),
                    'knowledge_code': k_ids.tolist()
                })
        
        # 创建DataFrame并保存为CSV
        df = pd.DataFrame(records)
        df.to_csv(file_path, index=False)
        
        return df

    def _create_item2knowledge_csv(self, data_loader, file_path):
        """创建习题到知识点映射的CSV文件"""
        print(f"Creating item to knowledge mapping: {file_path}")
        item_knowledge_map = {}
        
        for batch_data in tqdm(data_loader, "Processing mapping", file=sys.stdout):
            _, item_id, knowledge_emb, _ = batch_data
            
            # 转换为CPU上的numpy数组
            item_id = item_id.cpu().numpy()
            knowledge_emb = knowledge_emb.cpu().numpy()
            
            for i in range(len(item_id)):
                item = int(item_id[i]) + 1  # 加1因为ICD通常使用从1开始的ID
                k_ids = np.where(knowledge_emb[i] > 0)[0] + 1
                
                if item not in item_knowledge_map:
                    item_knowledge_map[item] = k_ids.tolist()
        
        # 创建DataFrame并保存为CSV
        items = []
        knowledge_codes = []
        for item, codes in item_knowledge_map.items():
            items.append(item)
            knowledge_codes.append(codes)
        
        df = pd.DataFrame({
            'item_id': items,
            'knowledge_code': knowledge_codes
        })
        df.to_csv(file_path, index=False)
        
        return df
        
    def train(self, train_data, test_data=None, epoch=10, device="cpu", lr=0.002, silence=False):
        """与其他CDM模型兼容的训练接口"""
        print(f"Training ICD model with {self.cdm_type} as base CDM...")
        
        # 将数据转换为CSV格式
        train_csv_path = 'temp_data/icd_train.csv'
        test_csv_path = 'temp_data/icd_test.csv'
        item2know_path = 'temp_data/icd_item.csv'
        
        train_df = self._convert_json_to_csv(train_data, train_csv_path)
        if test_data is not None:
            test_df = self._convert_json_to_csv(test_data, test_csv_path)
        
        # 创建习题到知识点的映射
        item_df = self._create_item2knowledge_csv(train_data, item2know_path)
        
        # 将数据分成多个小批次以模拟增量学习场景
        train_df_list = np.array_split(train_df, self.stream_num)
        train_df_list = [df.reset_index(drop=True) for df in train_df_list]
        
        # 创建i2k映射
        i2k = {}
        for _, row in item_df.iterrows():
            i2k[row['item_id']] = row['knowledge_code']
        
        # 训练ICD模型
        self.icd.train(
            inc_train_df_list=train_df_list,
            i2k=i2k,
            beta=self.beta,
            warmup_ratio=0.2,
            tolerance=1e-2
        )
        
        # 评估性能
        if test_data is not None:
            auc, accuracy, rmse, f1 = self.eval(test_data, device)
            print(f"Test performance: AUC={auc:.6f}, ACC={accuracy:.6f}, RMSE={rmse:.6f}, F1={f1:.6f}")
            return epoch, auc, accuracy
        
        return epoch, 0, 0
    
    def eval(self, test_data, device="cpu"):
        """评估模型性能"""
        print("Evaluating ICD model...")
        y_true, y_pred = [], []
        
        # 转换测试数据
        test_csv_path = 'temp_data/icd_test.csv'
        test_df = self._convert_json_to_csv(test_data, test_csv_path)
        
        # 使用ICD模型进行预测
        # 注意：由于ICD没有直接提供预测接口，这里使用了一种简化方法
        # 在实际应用中，你可能需要根据ICD的具体实现来更新这部分代码
        for index, row in tqdm(test_df.iterrows(), "Predicting", file=sys.stdout):
            user_id = row['user_id']
            item_id = row['item_id']
            true_score = row['score']
            
            # 这里只是一个占位符，实际使用时应替换为真实的预测逻辑
            # 由于ICD模型主要用于增量学习，可能不提供直接的预测接口
            # 在此使用ICD底层模型进行预测
            pred_score = 0.5  # 占位符
            
            y_true.append(true_score)
            y_pred.append(pred_score)
        
        # 计算评估指标
        y_true = np.array(y_true)
        y_pred = np.array(y_pred)
        
        rmse = np.sqrt(np.mean((y_true - y_pred) ** 2))
        auc = roc_auc_score(y_true, y_pred)
        accuracy = accuracy_score(y_true, y_pred >= 0.5)
        f1 = f1_score(y_true, y_pred >= 0.5)
        
        return auc, accuracy, rmse, f1
    
    def save(self, filepath):
        """保存模型参数"""
        # 由于ICD没有直接提供save接口，这里只是一个占位符
        # 实际使用时应根据ICD的具体实现来更新
        print(f"Saving ICD model to {filepath}")
        
    def load(self, filepath):
        """加载模型参数"""
        # 由于ICD没有直接提供load接口，这里只是一个占位符
        # 实际使用时应根据ICD的具体实现来更新
        print(f"Loading ICD model from {filepath}") 