"""Prepare NCDM and HierCDF inputs from Math1's own source files."""

import csv
import importlib.util
import json
import threading
from pathlib import Path

import networkx as nx


MATH1 = Path(__file__).resolve().parent / 'diagnosis' / 'CMD_survey' / 'data' / 'Math1'
_PREPARE_LOCK = threading.Lock()


def _validate_model_config():
    student_count, exercise_count, knowledge_count = map(
        int, (MATH1 / 'config.txt').read_text(encoding='utf-8').splitlines()[-1].split(',')
    )
    spec = importlib.util.spec_from_file_location('math1_hiercdf_config', MATH1 / 'config.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    params = module.hparams
    if (params['n_user'], params['n_item'], params['n_know']) != (
        student_count, exercise_count, knowledge_count
    ):
        raise ValueError('Math1/config.py 的学生、习题或知识点数量与 config.txt 不一致。')


def _read_responses(path, student_count, exercise_count):
    with path.open(encoding='utf-8-sig', newline='') as source:
        reader = csv.DictReader(source)
        if not {'user_id', 'exer_id', 'score'}.issubset(reader.fieldnames or []):
            raise ValueError(f'{path.name} 必须包含 user_id,exer_id,score 三列。')
        rows = []
        for row in reader:
            user, exercise, score = int(row['user_id']), int(row['exer_id']), int(row['score'])
            if not (1 <= user <= student_count and 1 <= exercise <= exercise_count and score in (0, 1)):
                raise ValueError(f'{path.name} 存在超出配置范围的 ID 或非二值分数。')
            rows.append((user, exercise, score))
    if not rows:
        raise ValueError(f'{path.name} 为空。')
    return rows


def _prepare_math1_inputs():
    """Validate Math1 sources and write the two models' expected file formats."""
    config_lines = (MATH1 / 'config.txt').read_text(encoding='utf-8').splitlines()
    student_count, exercise_count, knowledge_count = map(int, config_lines[-1].split(','))

    q_rows = []
    with (MATH1 / 'Q_matrix.txt').open(encoding='utf-8') as source:
        for line in source:
            if line.strip():
                row = [int(float(value)) for value in line.split()]
                if len(row) != knowledge_count or any(value not in (0, 1) for value in row):
                    raise ValueError('Math1 Q_matrix.txt 必须是二值的习题×知识点矩阵。')
                q_rows.append(row)
    if len(q_rows) != exercise_count:
        raise ValueError('Math1 Q_matrix.txt 行数与 config.txt 的习题数不一致。')

    graph = nx.DiGraph()
    graph.add_nodes_from(range(knowledge_count))
    with (MATH1 / 'prerequisite.csv').open(encoding='utf-8-sig', newline='') as source:
        reader = csv.DictReader(source)
        if not {'from', 'to'}.issubset(reader.fieldnames or []):
            raise ValueError('Math1 prerequisite.csv 必须包含 from,to 两列。')
        for row in reader:
            start, end = int(row['from']) - 1, int(row['to']) - 1
            if not (0 <= start < knowledge_count and 0 <= end < knowledge_count):
                raise ValueError('Math1 先修关系的知识点 ID 超出配置范围。')
            graph.add_edge(start, end)
    if not graph.number_of_edges() or not nx.is_directed_acyclic_graph(graph):
        raise ValueError('Math1 先修关系必须是非空的有向无环图。')

    train = _read_responses(MATH1 / 'train.csv', student_count, exercise_count)
    valid = _read_responses(MATH1 / 'test.csv', student_count, exercise_count)

    def ncdm_records(rows):
        return [
            {'user_id': user, 'exer_id': exercise, 'score': score,
             'knowledge_code': [index + 1 for index, value in enumerate(q_rows[exercise - 1]) if value]}
            for user, exercise, score in rows
        ]

    for name, rows in (('train.json', train), ('val.json', valid)):
        (MATH1 / name).write_text(json.dumps(ncdm_records(rows), ensure_ascii=False), encoding='utf-8')

    (MATH1 / 'q_matrix.txt').write_text(
        ''.join(' '.join(map(str, row)) + '\n' for row in q_rows), encoding='utf-8'
    )
    with (MATH1 / 'knowledge_graphs_prereq.csv').open('w', encoding='utf-8', newline='') as target:
        writer = csv.writer(target)
        writer.writerow(('from', 'to'))
        writer.writerows(sorted(graph.edges()))

    for name, rows in (('log_split__train_mini.csv', train), ('log_split__valid_mini.csv', valid)):
        with (MATH1 / name).open('w', encoding='utf-8', newline='') as target:
            writer = csv.writer(target)
            writer.writerow(('user_id', 'exercise_id', 'score'))
            writer.writerows((user - 1, exercise - 1, score) for user, exercise, score in rows)

    config_path = MATH1 / 'config.py'
    if not config_path.exists():
        config_path.write_text(
            'import torch\n\n'
            '# HierCDF.train() defaults; hidden_dim=1 matches the adapter\'s irt interaction.\n'
            'hparams = {\n'
            f"    'n_user': {student_count}, 'n_item': {exercise_count}, 'n_know': {knowledge_count},\n"
            f"    'max_exercise_id': {exercise_count}, 'hidden_dim': 1,\n"
            "    'lr': 0.01, 'epoch': 5, 'batch_size': 64,\n"
            "    'logger_mode': 'both', 'loss_factor': 1.0, 'batch_show': 200,\n"
            "    'device': torch.device('cpu'),\n"
            '}\n', encoding='utf-8'
        )


def prepare_math1_hiercdf():
    """Serialize preparation when both models start together on the same data."""
    with _PREPARE_LOCK:
        sources = [MATH1 / name for name in
                   ('config.txt', 'train.csv', 'test.csv', 'Q_matrix.txt', 'prerequisite.csv')]
        outputs = [MATH1 / name for name in
                   ('train.json', 'val.json', 'q_matrix.txt', 'knowledge_graphs_prereq.csv',
                    'log_split__train_mini.csv', 'log_split__valid_mini.csv', 'config.py')]
        if all(path.exists() for path in outputs):
            if min(path.stat().st_mtime for path in outputs) >= max(path.stat().st_mtime for path in sources):
                _validate_model_config()
                return
        _prepare_math1_inputs()
        _validate_model_config()


if __name__ == '__main__':
    prepare_math1_hiercdf()
