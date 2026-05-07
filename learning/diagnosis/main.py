import torch
from CMD_survey.model import IRT, NCDM, DINA, myMIRT, KSCD, AGCDM, myRcd, AGCDM_no_gate, CDFKC_with_gate
from CMD_survey.model import NCDM_GS, myRcd_GS, KSCD_GS  # 引入新的带gs因素模型
from CMD_survey.model import KaNCD  # 引入KaNCD模型
from CMD_survey.model.KaNCD_adapter import KaNCD_Adapter  # 引入KaNCD适配器
from CMD_survey.model.CACD_adapter import CACD_Adapter  # 引入CACD适配器
from CMD_survey.model.QCCDM_adapter import QCCDM_Adapter  # 引入QCCDM适配器
#from model.ICD_adapter import ICD_Adapter  # 引入ICD适配器
from CMD_survey.model.CDMFKC import CDMFKC
from CMD_survey.model.IRT_Affect import IRT_Affect
from CMD_survey.model.MIRT_Affect import MIRT_Affect
from CMD_survey.model.DINA_Affect import DINA_Affect
from CMD_survey.model.RCD_Affect import RCD_Affect
from CMD_survey.model.MF import MF  # 引入MF模型
from CMD_survey.model.MF_Affect import MF_Affect  # 引入带情感因素的MF模型
from CMD_survey.model.NCDM_NoQ import NCDM_NoQ  # 引入不使用Q矩阵的NCDM变体
import params
import dataloader
import time
import os

# 确保result目录存在
os.makedirs('result', exist_ok=True)


src, tgt = dataloader.CD_DL()
device = 'cuda:0'


def IRT_main():
    """
    IRT 模型训练
    
    💡 模型选择方法：
    在 model/IRT.py 的 irf 函数（第12行）中注释/取消注释对应的 return 语句：
    - 3-PL: return c + (1 - c) / (1 + F.exp(-D * a * (theta - b)))
    - 2-PL: return 1 / (1 + F.exp(-D * a * (theta - b)))  ← 当前使用
    - 1-PL: return 1 / (1 + F.exp(-D * (theta - b)))
    """
    cdm = IRT.IRT(params.un, params.en, value_range=4.0, a_range=2.0)
    e, auc, acc, rmse = cdm.train(train_data=src, test_data=tgt, epoch=params.epoch, device=device, lr=params.lr)

    # 保存模型参数
    model_path = os.path.join(params.dataset, 'models', 'IRT.pth')
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    cdm.save(model_path)
    print(f"模型已保存到: {model_path}")

    # 打印最终结果到标准输出
    print("\n" + "="*50)
    print("IRT 训练完成 - 最终结果:")
    print("="*50)
    print(f"Best Epoch: {e}")
    print(f"Accuracy: {acc:.6f}")
    print(f"AUC: {auc:.6f}")
    print("="*50 + "\n")
    
    with open('result/IRT.txt', 'a', encoding='utf8') as f:
        f.write('epoch= %d, accuracy= %f, auc= %f\n' % (e, acc, auc))

def myMIRT_main():
    cdm = myMIRT.MIRT(params.un, params.en, params.kn)
    e, auc, acc = cdm.train(train_data=src, test_data=tgt, epoch=params.epoch, device=device, lr=params.lr)
    with open('result/myMIRT.txt', 'a', encoding='utf8') as f:
        f.write('epoch= %d, accuracy= %f, auc= %f\n' % (e, acc, auc))

def DINA_main():
    cdm = DINA.DINA(params.un, params.en, params.kn)
    e, auc, acc = cdm.train(train_data=src, test_data=tgt, epoch=params.epoch, device=device, lr=params.lr)
    
    # 打印最终结果到标准输出
    print("\n" + "="*50)
    print("DINA 训练完成 - 最终结果:")
    print("="*50)
    print(f"Best Epoch: {e}")
    print(f"Accuracy: {acc:.6f}")
    print(f"AUC: {auc:.6f}")
    print("="*50 + "\n")
    
    with open('result/DINA.txt', 'a', encoding='utf8') as f:
        f.write('epoch= %d, accuracy= %f, auc= %f\n' % (e, acc, auc))

def NCD_main():
    cdm = NCDM.NCDM(params.kn, params.en, params.un)  # reverse
    e, auc, acc, rmse = cdm.train(train_data=src, test_data=tgt, epoch=params.epoch, device=device, lr=params.lr)

    # 保存模型参数
    model_path = os.path.join(params.dataset, 'models', 'NCDM.pth')
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    cdm.save(model_path)
    print(f"模型已保存到: {model_path}")

    # 打印最终结果到标准输出（供evaluate_knowledge_code_impact.py捕获）
    print("\n" + "="*50)
    print("NCDM 训练完成 - 最终结果:")
    print("="*50)
    print(f"Best Epoch: {e}")
    print(f"Accuracy: {acc:.6f}")
    print(f"AUC: {auc:.6f}")
    print("="*50 + "\n")


def NCDM_NoQ_main():
    """
    不使用 Q 矩阵的 NCDM 变体
    用于验证 Q 矩阵对 NCDM 性能的影响
    
    如果 NCDM_NoQ >= NCDM，说明 Q 矩阵没有帮助（甚至有害）
    """
    cdm = NCDM_NoQ(params.kn, params.en, params.un)
    e, auc, acc = cdm.train(train_data=src, test_data=tgt, epoch=params.epoch, device=device, lr=params.lr)
    
    print("\n" + "="*50)
    print("NCDM_NoQ 训练完成 - 最终结果:")
    print("="*50)
    print(f"Best Epoch: {e}")
    print(f"Accuracy: {acc:.6f}")
    print(f"AUC: {auc:.6f}")
    print("="*50 + "\n")
    
    with open('result/NCDM_NoQ.txt', 'a', encoding='utf8') as f:
        f.write('epoch= %d, accuracy= %f, auc= %f\n' % (e, acc, auc))

def myRCD_main():
    cdm = myRcd.ACD(params.un, params.en, params.kn, params.latent_dim)
    e, auc, acc, rmse = cdm.train(train_data=src, test_data=tgt, epoch=200, device=device, lr=params.lr)
    
    # 打印最终结果到标准输出
    print("\n" + "="*50)
    print("RCD 训练完成 - 最终结果:")
    print("="*50)
    print(f"Best Epoch: {e}")
    print(f"Accuracy: {acc:.6f}")
    print(f"AUC: {auc:.6f}")
    print(f"RMSE: {rmse:.6f}")
    print("="*50 + "\n")
    
    with open('result/myRCD.txt', 'a', encoding='utf8') as f:
        f.write('epoch= %d, accuracy= %f, auc= %f\n' % (e, acc, auc))

def KSCD_main():
    cdm = KSCD.kscd(params.un, params.en, params.kn, params.latent_dim)
    e, auc, acc, rmse = cdm.train(train_data=src, test_data=tgt, epoch=params.epoch, device=device, lr=params.lr)
    with open('result/KSCD.txt', 'a', encoding='utf8') as f:
        f.write('epoch= %d, accuracy= %f, auc= %f\n' % (e, acc, auc))

def AGCDM_main():
    learner = AGCDM.Learner(src, tgt, tgt,
                      params.un, params.en, params.kn,
                      knowledge_embed_size=params.latent_dim, epoch_size=params.epoch,
                      batch_size=params.batch_size, lr=params.lr, device=device)
    learner.reset_model()
    learner.train()

def AGCDM_no_gate_main():
    learner = AGCDM_no_gate.Learner(src, tgt, tgt,
                      params.un, params.en, params.kn,
                      knowledge_embed_size=params.latent_dim, epoch_size=params.epoch,
                      batch_size=params.batch_size, lr=params.lr, device=device)
    learner.reset_model()
    learner.train()
def CDFKC_with_gate_main():
    learner = CDFKC_with_gate.Learner(src, tgt, tgt,
                      params.un, params.en, params.kn,
                      knowledge_embed_size=params.latent_dim, epoch_size=params.epoch,
                      batch_size=params.batch_size, lr=params.lr, device=device)
    learner.reset_model()
    learner.train()
def CDMFKC_main():
    start_time = time.time()
    cdm = CDMFKC(params.kn, params.en, params.un)
    e, auc, acc = cdm.train(train_data=src, test_data=tgt, epoch=params.epoch, device=device, lr=params.lr)

def NCDM_GS_main():
    """带有猜测和滑动因素的NCDM模型测试函数"""
    cdm = NCDM_GS.NCDM_GS(params.kn, params.en, params.un)
    e, auc, acc = cdm.train(train_data=src, test_data=tgt, epoch=params.epoch, device=device, lr=params.lr)

def myRcd_GS_main():
    """带有猜测和滑动因素的myRcd模型测试函数"""
    cdm = myRcd_GS.ACD_GS(params.un, params.en, params.kn, params.latent_dim)
    e, auc, acc, rmse = cdm.train(train_data=src, test_data=tgt, epoch=params.epoch, device=device, lr=params.lr)

def KSCD_GS_main():
    """带有猜测和滑动因素的KSCD模型测试函数"""
    cdm = KSCD_GS.kscd_gs(params.un, params.en, params.kn, params.latent_dim)
    e, auc, acc, rmse = cdm.train(train_data=src, test_data=tgt, epoch=params.epoch, device=device, lr=params.lr)

def KaNCD_main():
    """Knowledge-aware Neural Cognitive Diagnosis模型测试函数"""
    # 初始化KaNCD适配器, 可选mf_type: 'mf', 'gmf', 'ncf1', 'ncf2'
    cdm = KaNCD_Adapter(knowledge_n=params.kn, exer_n=params.en, student_n=params.un, 
                        dim=params.latent_dim, mf_type='gmf')
    # 训练模型 - 使用与其他模型相同的数据格式和接口
    start_time = time.time()
    e, auc, acc = cdm.train(train_data=src, test_data=tgt, epoch=params.epoch, device=device, lr=params.lr)
    end_time = time.time()
    train_time = end_time - start_time
    
    # 保存结果，与其他模型保持一致的格式
    with open('result/KaNCD.txt', 'a', encoding='utf8') as f:
        f.write('epoch= %d, accuracy= %f, auc= %f\n' % (e, acc, auc))
        f.write('Training time: %f seconds\n' % train_time)
    
    return e, auc, acc

def CACD_main():
    """Contrastive Affect-aware Cognitive Diagnosis模型测试函数"""
    try:
        print("开始训练CACD模型...")
        print(f"数据集: {params.dataset}, 学生数: {params.un}, 习题数: {params.en}, 知识点数: {params.kn}")
        
        # 初始化CACD适配器
        cdm = CACD_Adapter(knowledge_n=params.kn, exer_n=params.en, student_n=params.un)
        
        # 训练模型
        start_time = time.time()
        e, auc, acc, rmse = cdm.train(train_data=src, test_data=tgt, epoch=params.epoch, device=device, lr=params.lr)
        end_time = time.time()
        train_time = end_time - start_time
        
        # 保存结果
        with open('result/CACD.txt', 'a', encoding='utf8') as f:
            f.write('数据集: %s\n' % params.dataset)
            f.write('epoch= %d, accuracy= %f, auc= %f, rmse= %f\n' % (e, acc, auc, rmse))
            f.write('Training time: %f seconds\n' % train_time)
            f.write('-' * 50 + '\n')
        
        print("CACD模型训练完成!")
        print(f"最终结果 - Epoch: {e}, AUC: {auc:.4f}, ACC: {acc:.4f}, RMSE: {rmse:.4f}")
        return e, auc, acc, rmse
    except Exception as e:
        print(f"CACD模型训练出错: {e}")
        # 记录错误
        with open('result/CACD_error.txt', 'a', encoding='utf8') as f:
            f.write(f"数据集: {params.dataset}, 错误: {e}\n")
            f.write('-' * 50 + '\n')
        return 0, 0.5, 0.5, 1.0

def IRT_Affect_main():
    """带情感因素的IRT模型测试函数"""
    print("开始训练IRT_Affect模型...")
    print(f"数据集: {params.dataset}, 学生数: {params.un}, 习题数: {params.en}, 知识点数: {params.kn}")
    
    # 初始化IRT_Affect模型
    cdm = IRT_Affect(user_num=params.un, item_num=params.en, value_range=4.0, a_range=2.0)
    
    # 训练模型
    start_time = time.time()
    e, auc, acc, rmse = cdm.train(train_data=src, test_data=tgt, epoch=params.epoch, device=device, lr=params.lr)
    end_time = time.time()
    train_time = end_time - start_time
    
    # 保存结果
    with open('result/IRT_Affect.txt', 'a', encoding='utf8') as f:
        f.write('数据集: %s\n' % params.dataset)
        f.write('epoch= %d, accuracy= %f, auc= %f, rmse= %f\n' % (e, acc, auc, rmse))
        f.write('Training time: %f seconds\n' % train_time)
        f.write('-' * 50 + '\n')
    
    print("IRT_Affect模型训练完成!")
    print(f"最终结果 - Epoch: {e}, AUC: {auc:.4f}, ACC: {acc:.4f}, RMSE: {rmse:.4f}")
    return e, auc, acc, rmse

def MIRT_Affect_main():
    """带情感因素的MIRT模型测试函数"""
    print("开始训练MIRT_Affect模型...")
    print(f"数据集: {params.dataset}, 学生数: {params.un}, 习题数: {params.en}, 知识点数: {params.kn}")
    
    # 初始化MIRT_Affect模型
    cdm = MIRT_Affect(user_num=params.un, item_num=params.en, latent_dim=params.kn)
    
    # 训练模型
    start_time = time.time()
    e, auc, acc, rmse = cdm.train(train_data=src, test_data=tgt, epoch=params.epoch, device=device, lr=params.lr)
    end_time = time.time()
    train_time = end_time - start_time
    
    # 保存结果
    with open('result/MIRT_Affect.txt', 'a', encoding='utf8') as f:
        f.write('数据集: %s\n' % params.dataset)
        f.write('epoch= %d, accuracy= %f, auc= %f, rmse= %f\n' % (e, acc, auc, rmse))
        f.write('Training time: %f seconds\n' % train_time)
        f.write('-' * 50 + '\n')
    
    print("MIRT_Affect模型训练完成!")
    print(f"最终结果 - Epoch: {e}, AUC: {auc:.4f}, ACC: {acc:.4f}, RMSE: {rmse:.4f}")
    return e, auc, acc, rmse

def DINA_Affect_main():
    """带情感因素的DINA模型测试函数"""
    print("开始训练DINA_Affect模型...")
    print(f"数据集: {params.dataset}, 学生数: {params.un}, 习题数: {params.en}, 知识点数: {params.kn}")
    
    # 初始化DINA_Affect模型
    cdm = DINA_Affect(user_num=params.un, item_num=params.en, hidden_dim=params.kn)
    
    # 训练模型
    start_time = time.time()
    e, auc, acc, rmse = cdm.train(train_data=src, test_data=tgt, epoch=params.epoch, device=device, lr=params.lr)
    end_time = time.time()
    train_time = end_time - start_time
    
    # 保存结果
    with open('result/DINA_Affect.txt', 'a', encoding='utf8') as f:
        f.write('数据集: %s\n' % params.dataset)
        f.write('epoch= %d, accuracy= %f, auc= %f, rmse= %f\n' % (e, acc, auc, rmse))
        f.write('Training time: %f seconds\n' % train_time)
        f.write('-' * 50 + '\n')
    
    print("DINA_Affect模型训练完成!")
    print(f"最终结果 - Epoch: {e}, AUC: {auc:.4f}, ACC: {acc:.4f}, RMSE: {rmse:.4f}")
    return e, auc, acc, rmse

def RCD_Affect_main():
    """带情感因素的RCD模型测试函数"""
    print("开始训练RCD_Affect模型...")
    print(f"数据集: {params.dataset}, 学生数: {params.un}, 习题数: {params.en}, 知识点数: {params.kn}")
    
    # 初始化RCD_Affect模型
    cdm = RCD_Affect(student_n=params.un, exer_n=params.en, k_n=params.kn, emb_dim=params.latent_dim)
    
    # 训练模型
    start_time = time.time()
    e, auc, acc, rmse = cdm.train(train_data=src, test_data=tgt, epoch=200, device=device, lr=params.lr)
    end_time = time.time()
    train_time = end_time - start_time
    
    # 保存结果
    with open('result/RCD_Affect.txt', 'a', encoding='utf8') as f:
        f.write('数据集: %s\n' % params.dataset)
        f.write('epoch= %d, accuracy= %f, auc= %f, rmse= %f\n' % (e, acc, auc, rmse))
        f.write('Training time: %f seconds\n' % train_time)
        f.write('-' * 50 + '\n')
    
    print("RCD_Affect模型训练完成!")
    print(f"最终结果 - Epoch: {e}, AUC: {auc:.4f}, ACC: {acc:.4f}, RMSE: {rmse:.4f}")
    return e, auc, acc, rmse

def MF_main():
    """Multiple-Strategy Fusion模型测试函数"""
    print("开始训练MF模型...")
    print(f"数据集: {params.dataset}, 学生数: {params.un}, 习题数: {params.en}, 知识点数: {params.kn}")
    
    # 初始化MF模型，strategy_num表示每道题目可能的解题策略数量
    cdm = MF(user_num=params.un, item_num=params.en, hidden_dim=params.kn, strategy_num=2, ste=False)
    
    # 训练模型
    start_time = time.time()
    e, auc, acc = cdm.train(train_data=src, test_data=tgt, epoch=params.epoch, device=device, lr=params.lr)
    end_time = time.time()
    train_time = end_time - start_time
    
    # 保存结果
    with open('result/MF.txt', 'a', encoding='utf8') as f:
        f.write('数据集: %s\n' % params.dataset)
        f.write('epoch= %d, accuracy= %f, auc= %f\n' % (e, acc, auc))
        f.write('Training time: %f seconds\n' % train_time)
        f.write('-' * 50 + '\n')
    
    print("MF模型训练完成!")
    print(f"最终结果 - Epoch: {e}, AUC: {auc:.4f}, ACC: {acc:.4f}")
    return e, auc, acc

def MF_Affect_main():
    """带情感因素的Multiple-Strategy Fusion模型测试函数"""
    print("开始训练MF_Affect模型...")
    print(f"数据集: {params.dataset}, 学生数: {params.un}, 习题数: {params.en}, 知识点数: {params.kn}")
    
    # 初始化MF_Affect模型，strategy_num表示每道题目可能的解题策略数量
    cdm = MF_Affect(user_num=params.un, item_num=params.en, hidden_dim=params.kn, strategy_num=2, ste=False)
    
    # 训练模型
    start_time = time.time()
    e, auc, acc, rmse = cdm.train(train_data=src, test_data=tgt, epoch=params.epoch, device=device, lr=params.lr)
    end_time = time.time()
    train_time = end_time - start_time
    
    # 保存结果
    with open('result/MF_Affect.txt', 'a', encoding='utf8') as f:
        f.write('数据集: %s\n' % params.dataset)
        f.write('epoch= %d, accuracy= %f, auc= %f, rmse= %f\n' % (e, acc, auc, rmse))
        f.write('Training time: %f seconds\n' % train_time)
        f.write('-' * 50 + '\n')
    
    print("MF_Affect模型训练完成!")
    print(f"最终结果 - Epoch: {e}, AUC: {auc:.4f}, ACC: {acc:.4f}, RMSE: {rmse:.4f}")
    return e, auc, acc, rmse

def QCCDM_main(mode='1', q_aug='single'):
    """Q-matrix Causal Cognitive Diagnosis Model测试函数
    
    Args:
        mode: 模式选择
            '1' - 仅使用结构因果模型(SCM) (默认)
            '2' - 仅使用Q矩阵增强
            '12' - 同时使用SCM和Q矩阵增强
        q_aug: Q矩阵增强方式
            'single' - 单一Q矩阵增强 (默认)
            'mf' - 矩阵分解Q矩阵增强
    """
    print("开始训练QCCDM模型...")
    print(f"数据集: {params.dataset}, 学生数: {params.un}, 习题数: {params.en}, 知识点数: {params.kn}")
    print(f"模式: {mode}, Q矩阵增强: {q_aug}")
    
    # 强制使用float32数据类型
    torch.set_default_dtype(torch.float32)
    
    # 初始化QCCDM适配器
    # mode参数: '1'-仅使用SCM, '2'-仅使用Q矩阵增强, '12'-两者都使用
    # q_aug参数: 'single'-单一Q矩阵增强, 'mf'-矩阵分解Q矩阵增强
    cdm = QCCDM_Adapter(
        knowledge_n=params.kn, 
        exer_n=params.en, 
        student_n=params.un,
        mode=mode,  # 使用传入的模式
        lambda_reg=0.01,  # 正则化参数
        dtype=torch.float32,  # 强制使用float32
        num_layers=2,  # 网络层数
        nonlinear='sigmoid',  # 非线性函数
        q_aug=q_aug  # Q矩阵增强方式
    )
    
    # 训练模型
    start_time = time.time()
    e, auc, acc, rmse = cdm.train(train_data=src, test_data=tgt, epoch=params.epoch, device=device, lr=params.lr)
    end_time = time.time()
    train_time = end_time - start_time
    
    # 保存结果
    result_file = f'result/QCCDM_mode{mode}_{q_aug}.txt'
    with open(result_file, 'a', encoding='utf8') as f:
        f.write('数据集: %s\n' % params.dataset)
        f.write(f'模式: {mode}, Q矩阵增强: {q_aug}\n')
        f.write('epoch= %d, accuracy= %f, auc= %f, rmse= %f\n' % (e, acc, auc, rmse))
        f.write('Training time: %f seconds\n' % train_time)
        f.write('-' * 50 + '\n')
    
    print("QCCDM模型训练完成!")
    print(f"最终结果 - Epoch: {e}, AUC: {auc:.4f}, ACC: {acc:.4f}, RMSE: {rmse:.4f}")
    print(f"结果已保存到: {result_file}")
    return e, auc, acc, rmse

# def ICD_main():
#     """Incremental Cognitive Diagnosis模型测试函数"""
#     # 初始化ICD适配器，可选底层CDM类型: 'mirt', 'irt', 'ncd', 'dina'
#     cdm = ICD_Adapter(
#         knowledge_n=params.kn, 
#         exer_n=params.en, 
#         student_n=params.un, 
#         cdm_type='mirt',  # 使用MIRT作为底层认知诊断模型
#         alpha=0.2,        # 动量参数
#         beta=0.9,         # 遗忘因子
#         stream_num=10     # 数据流分割数量
#     )
    
    # 训练模型
    start_time = time.time()
    e, auc, acc = cdm.train(train_data=src, test_data=tgt, epoch=50, device=device, lr=0.002)
    end_time = time.time()
    train_time = end_time - start_time
    
    # 保存结果
    with open('result/ICD.txt', 'a', encoding='utf8') as f:
        f.write('epoch= %d, accuracy= %f, auc= %f\n' % (e, acc, auc))
        f.write('Training time: %f seconds\n' % train_time)
    
    return e, auc, acc

# 根据选择的模型运行对应的函数
model_functions = {
    'IRT': IRT_main,
    'MIRT': myMIRT_main,
    'DINA': DINA_main,
    'NCDM': NCD_main,
    'NCDM_NoQ': NCDM_NoQ_main,
    'RCD': myRCD_main,
    'KSCD': KSCD_main,
    'AGCDM': AGCDM_main,
    'AGCDM_no_gate': AGCDM_no_gate_main,
    'CDFKC_with_gate': CDFKC_with_gate_main,
    'CDMFKC': CDMFKC_main,
    'NCDM_GS': NCDM_GS_main,
    'RCD_GS': myRcd_GS_main,
    'KSCD_GS': KSCD_GS_main,
    'KaNCD': KaNCD_main,
    'CACD': CACD_main,
    'QCCDM': lambda: QCCDM_main(mode=args.qccdm_mode, q_aug=args.q_aug),
    'IRT_Affect': IRT_Affect_main,
    'MIRT_Affect': MIRT_Affect_main,
    'DINA_Affect': DINA_Affect_main,
    'RCD_Affect': RCD_Affect_main,
    'MF': MF_main,
    'MF_Affect': MF_Affect_main
}

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Cognitive Diagnosis Model Training - 所有参数从 params.py 读取')
    parser.add_argument('--model', choices=[
        'IRT', 'MIRT', 'DINA', 'NCDM', 'NCDM_NoQ', 'RCD', 'KSCD', 'AGCDM', 'AGCDM_no_gate', 
        'CDFKC_with_gate', 'CDMFKC', 'NCDM_GS', 'RCD_GS', 'KSCD_GS', 'KaNCD', 
        'CACD', 'QCCDM', 'IRT_Affect', 'MIRT_Affect', 'DINA_Affect', 'RCD_Affect', 
        'MF', 'MF_Affect'
    ], default='NCDM', help='选择要运行的模型')
    
    # QCCDM 专用参数
    parser.add_argument('--qccdm_mode', choices=['1', '2', '12'], default='1',
                        help="QCCDM模式: '1'-仅SCM(默认), '2'-仅Q矩阵增强, '12'-两者都用")
    parser.add_argument('--q_aug', choices=['single', 'mf'], default='single',
                        help="Q矩阵增强方式: 'single'-单一增强(默认), 'mf'-矩阵分解增强")
    
    # 注意：以下参数仅用于兼容性，实际使用的参数来自 params.py
    parser.add_argument('--dataset_dir', default='data/mooper', help='[未使用] 数据集在 params.py 中配置')
    parser.add_argument('--epoch', type=int, default=100, help='[未使用] 在 params.py 中配置')
    parser.add_argument('--lr', type=float, default=0.002, help='[未使用] 在 params.py 中配置')
    parser.add_argument('--batch_size', type=int, default=1024, help='[未使用] 在 params.py 中配置')
    
    args = parser.parse_args()
    

    
    if args.model in model_functions:
        print("="*60)
        print("📋 训练配置（来自 params.py）")
        print("="*60)
        print(f"运行模型: {args.model}")
        print(f"数据集目录: {params.dataset}")
        print(f"训练数据: {params.src}")
        print(f"验证数据: {params.tgt}")
        print(f"训练轮数: {params.epoch}")
        print(f"学习率: {params.lr}")
        print(f"批次大小: {params.batch_size}")
        print(f"学生数: {params.un}, 题目数: {params.en}, 知识点数: {params.kn}")
        print("="*60)
        print("💡 提示: 修改参数请编辑 params.py 文件")
        print("="*60 + "\n")
        
        model_functions[args.model]()
    else:
        print(f"未知模型: {args.model}")
        print(f"可用模型: {list(model_functions.keys())}")
        
    # 原始的直接调用方式（如果不使用命令行参数）
    # NCD_main() 
