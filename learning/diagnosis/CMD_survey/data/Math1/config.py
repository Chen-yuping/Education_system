import torch

# HierCDF.train() defaults; hidden_dim=1 matches the adapter's irt interaction.
hparams = {
    'n_user': 4209, 'n_item': 15, 'n_know': 11,
    'max_exercise_id': 15, 'hidden_dim': 1,
    'lr': 0.01, 'epoch': 5, 'batch_size': 64,
    'logger_mode': 'both', 'loss_factor': 1.0, 'batch_show': 200,
    'device': torch.device('cpu'),
}
