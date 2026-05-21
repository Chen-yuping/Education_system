# DNCDM integration

This folder contains the platform integration for two interaction-record decoupling cognitive diagnosis models:

- `DNCDM`: Decoupling NCDM. The `D` denotes interaction-record decoupling. This model decouples heterogeneous interaction logs into student-exercise-concept triples and propagates prerequisite relations to construct a relation-enhanced Q-matrix for NCDM.
- `GDNCDM`: Gated Decoupling NCDM. It extends `DNCDM` with soft gates that adaptively fuse original Q-matrix signals and propagated relation residuals to reduce noisy propagation.

The runtime interface follows the original platform dataset format:

- `config.txt`
- `train.json`
- `val.json`
- `homologous.csv`
- `prerequisite_edges.csv` (optional, for researcher datasets with explicit prerequisite edges)

The adapter does not create per-run `.npz`, `.pt`, `.pth`, or history CSV files. Teacher-side training uses the JSON files exported by the existing `export_training_data()` flow and keeps the trained model in memory for the immediate diagnosis response.
