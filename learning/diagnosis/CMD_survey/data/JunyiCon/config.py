import torch
import os

# 获取当前文件所在目录的上级目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, 'ConData')

#mixed:

hparams = {
    'n_user': 10000,#学生数.大：247606，小：10000
    'n_item': 882,#题目数(原：836)
    'max_exercise_id': 836,#for hier
    'n_know': 711,#属性数
    'hidden_dim': 1,#隐藏维度
    'lr':5e-3,
    'mixed_lr':1e-3,
    'weight_decay': 1e-5,
    'epoch': 8,
    'batch_size': 4096,
    'logger_mode': 'both', # 'file'/'both'/'console'
    'loss_factor': 0.001,
    'device': torch.device("cuda:0" if torch.cuda.is_available() else "cpu"),#torch.device('cpu'), #torch.device("cuda:0" if torch.cuda.is_available() else "cpu"),
    'batch_show': 10,
    'train_ratio': 0.8,
    'itf_type':'irt', # 'irt'/'mirt'/'mf'/'sigmoid-mf'/'ncd'
    'base_log_path': os.path.join(BASE_DIR, 'logs', 'baselog'),
    'Con_log_path': os.path.join(BASE_DIR, 'logs', 'Conlog'),
    'Hier_log_path': os.path.join(BASE_DIR, 'logs', 'Hierlog'),
    'Mixed_log_path': os.path.join(BASE_DIR, 'logs', 'mixedlog'),
    'model_name': os.path.join(BASE_DIR, 'model', 'HierIRT.pkl')
}
