import abc
import numpy as np

class BaseCDModel(metaclass=abc.ABCMeta):
    """认知诊断模型基础抽象类"""
    def __init__(self):
        self.model = None
        self.train_losses = []  # 训练损失记录
        self.val_accuracies = [] # 验证准确率记录

    @abc.abstractmethod
    def init_model(self, **kwargs):
        """初始化模型参数"""
        pass

    @abc.abstractmethod
    def train_step(self, train_data, **kwargs):
        """单轮训练步骤"""
        pass

    @abc.abstractmethod
    def predict(self, test_data):
        """模型预测"""
        pass

    def evaluate(self, val_data):
        """验证集评估（计算准确率）"""
        predictions = self.predict(val_data)
        ground_truth = np.array(val_data["responses"])
        accuracy = np.mean(predictions == ground_truth)
        return accuracy

    def save_model(self, save_path):
        """保存模型（按需实现）"""
        import os
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        # 示例：保存参数到npz文件
        np.savez(save_path, **self.model)

    def load_model(self, load_path):
        """加载模型（按需实现）"""
        params = np.load(load_path)
        self.model = {k: params[k] for k in params.files}