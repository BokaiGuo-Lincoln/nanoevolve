<div align="center">

# NanoEvolve

**能够成立的最小程序进化闭环。**

保留 AlphaEvolve 的“生成—验证—选择”反馈循环，删除 OpenEvolve 的研究基础设施，用 Pi 的原语化、文件化和完全可观察原则重新实现。

[English](README.md) · [设计规范](docs/superpowers/specs/2026-08-02-nanoevolve-design.md) · [变更日志](CHANGELOG.md) · [贡献指南](CONTRIBUTING.md)

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![Runtime dependencies](https://img.shields.io/badge/runtime_dependencies-0-2E8B57)
![Tests](https://img.shields.io/badge/tests-stdlib_unittest-4C1)
![Status](https://img.shields.io/badge/status-v0.5_target_stopping-2E8B57)
![State](https://img.shields.io/badge/state-append--only_JSONL-6E56CF)

</div>

```text
Archive --select--> Prompt --> Model --> Candidate
   ^                                      |
   |                                      v
   +------------- Evaluation <-- Evaluator
```

NanoEvolve 保留 AlphaEvolve 类系统真正有用的计算内核——`select → mutate → evaluate → archive`——但不把它扩张成 agent 框架。核心没有工具循环、规划器、sub-agent、隐藏记忆、插件注册中心或数据库。

## 为什么是 NanoEvolve？

- **极小控制面：** 一个 `evolve()` 函数和四个 CLI 命令。
- **状态完全可见：** prompt、原始响应、候选、评分和错误全部落盘。
- **运行可恢复：** append-only JSONL 可以在中断后重建 archive。
- **选择可复现：** 每一代都派生独立、稳定的随机种子。
- **Evaluator 决定真值：** 领域逻辑保留在普通 `evaluate.py` 函数中。
- **零运行时依赖：** 核心只使用 Python 标准库。

## 三分钟快速体验

确定性示例不需要 API key，也不会发起网络请求。

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python examples/hello_evolve/demo.py
```

结尾输出类似：

```text
NanoEvolve deterministic demo completed.
Best score: 8.0
Inspect: nanoevolve inspect /tmp/nanoevolve-hello-... <record-id>
```

脚本打印出的临时项目会继续保留，可以直接用 CLI 查看：

```bash
nanoevolve best /tmp/nanoevolve-hello-...
nanoevolve inspect /tmp/nanoevolve-hello-... <record-id>
```

## 可复现基准

无需 API key 或网络即可运行确定性的八点装箱演化轨迹：

```bash
python examples/circle_packing/demo.py
```

该运行通过三个可检查 generation，将最小点间距从 `0.4000000000` 提升到 `0.5176380902`。它验证的是真实 generate–evaluate–select–archive 循环，而不是合成分数计数器。

## 接入真实模型

一个实验只需要三个显式文件：

```text
my-experiment/
├── TASK.md
├── seed.py
└── evaluate.py
```

配置任意兼容 OpenAI Chat Completions、非 streaming 的端点：

```bash
export NANOEVOLVE_MODEL="your-model"
export NANOEVOLVE_BASE_URL="https://your-endpoint.example/v1"
export NANOEVOLVE_API_KEY="..."

nanoevolve run my-experiment \
  --iterations 100 \
  --random-seed 42 \
  --target-score 0.95
```

恢复到指定总代数：

```bash
nanoevolve resume my-experiment --iterations 200
```

`resume --iterations 200` 表示“推进到 generation 200”，不是“额外执行 200 次”。达到 200 代后重复执行不会再次调用模型。

`--target-score` 会在任意成功候选达到目标分数后，于下一个 generation batch 开始前停止。目标值会写入 `run.json` 并由 `resume` 自动复用。使用 `workers > 1` 时，当前 batch 中已经启动的候选仍会完成评估和提交。

## 最小 Python API

```python
from nanoevolve import OpenAICompatibleModel, evolve
from evaluate import evaluate

model = OpenAICompatibleModel(
    model="your-model",
    base_url="https://your-endpoint.example/v1",
    api_key="...",
)

best = evolve(
    seed="seed.py",
    evaluate=evaluate,
    model=model,
    task="TASK.md",
    iterations=100,
    target_score=0.95,
)

print(best.evaluation.score)
print(best.source_path)
```

Evaluator 必须是一个可导入的顶层函数：

```python
from nanoevolve import Evaluation


def evaluate(source_path: str) -> Evaluation:
    score = run_benchmark(source_path)
    return Evaluation(
        score=score,
        feedback="Benchmark completed.",
        metrics={"runtime_ms": 12.4},
    )
```

默认仍只优化 `score`。命名 metrics 也可以用于字典序多目标选择和 MAP-Elites feature coordinates。

## CLI

| 命令 | 作用 |
| --- | --- |
| `nanoevolve run <project>` | 创建新运行；存在旧状态时拒绝覆盖。 |
| `nanoevolve resume <project>` | 恢复并推进到指定总代数。 |
| `nanoevolve best <project>` | 显示当前最高分成功记录。 |
| `nanoevolve inspect <project> <record-id>` | 检查 lineage、评估、错误和 artifacts。 |

`best` 和 `inspect` 支持 `--json`，便于脚本集成。

`run` 与 `resume` 支持把逐行事件流写到 stderr，同时让最终 best-record 摘要继续保留在 stdout：

```bash
nanoevolve run my-experiment --iterations 100 --json-events 2>events.jsonl
```

`events.jsonl` 的每一行都是一个包含 `type`、`generation`、`record_id` 和 `data` 的 JSON 对象。事件覆盖 parent selection、模型完成、候选提取、archive commit、失败和 new-best。

`inspect` 还可以不添加标签或格式，原样输出一个已经持久化的 artifact：

```bash
nanoevolve inspect my-experiment <record-id> --artifact prompt > prompt.txt
```

Artifact 名称来自普通 `inspect` 输出中的列表。`--artifact` 与 `--json` 互斥。

## 路线图能力

所有高级能力均为显式可选项，并且仍然只通过 `evolve()` 或既有的 `run`/`resume` 命令进入：

```bash
nanoevolve run my-experiment \
  --mutation-mode search_replace \
  --inspiration-count 2 \
  --artifact-feedback stdout \
  --workers 4 \
  --archive-backend sqlite \
  --objective score:max \
  --objective runtime_ms:min \
  --feature size \
  --feature-bin size=100 \
  --islands 4 \
  --migration-interval 20 \
  --target-score 0.95
```

- 用 `seed/` 目录替代 `seed.py` 即可启用多文件 workspace；evaluator 会收到 workspace 目录路径。
- `full`、`search_replace`、`evolve_blocks` 分别支持完整快照、精确 patch 和命名可编辑区域。
- `--sandbox-command "..."` 使用外部隔离命令包装 evaluator worker；凭据必须通过环境提供，不能写入命令参数。
- `workers > 1` 会顺序生成确定性 batch、并行评估、再按 generation 顺序提交记录。
- SQLite 只替换 record index；prompt、响应、workspace、输出和评估仍是普通的哈希文件。
- Feature metrics 与 bins 启用简化 MAP-Elites；islands 默认本地选择，并在 migration generation 扩大候选池。
- `target_score` / `--target-score` 会在下一个 batch 边界停止模型调用，并发出可观察的 `target_reached` 事件。

无需 API key 或网络即可运行确定性组合示例：

```bash
python examples/roadmap_showcase/demo.py
```

该示例会在同一次可检查运行中覆盖多文件、SEARCH/REPLACE、inspiration、artifact feedback、并行 evaluator、SQLite、多目标、MAP-Elites、islands 和 migration 路径。

## 版本与发布验证

安装后的 console script 与模块入口共享同一套 parser 和版本来源：

```bash
nanoevolve --version
python -m nanoevolve --version
```

发布或交付源码快照之前运行：

```bash
python scripts/release_check.py
```

发布检查会运行测试和编译，验证中英文 README 结构，约束核心代码行数，检查 package metadata，并拒绝发布文档中的占位符。

发布基础设施与运行时依赖严格分离。Wheel 和 source distribution 使用仅供开发的 `build` 包；安装后的 NanoEvolve 仍声明零运行时依赖。

开发约定见 [`CONTRIBUTING.md`](CONTRIBUTING.md)，生成代码的信任边界见 [`SECURITY.md`](SECURITY.md)，已验证里程碑见 [`CHANGELOG.md`](CHANGELOG.md)。

公开仓库为 `BokaiGuo-Lincoln/nanoevolve`。Package author 与许可证字段仍保持空缺，直到项目所有者提供权威信息。

## 透明状态

每个项目只有一个可直接检查的状态目录：

```text
.nanoevolve/
├── run.json
├── records.jsonl 或 records.sqlite3
└── candidates/
    └── <record-id>/
        ├── source.py 或 workspace/...
        ├── prompt.txt
        ├── response.txt
        ├── evaluation.json
        ├── stdout.txt
        └── stderr.txt
```

`run.json` 是不可变的初始元数据；`records.jsonl` 是默认动态状态真相，`records.sqlite3` 是可选的等价索引。候选 artifacts 会先写入磁盘，再让对应 record 对后续选择可见；archive 重新打开时会验证文件哈希。

每一次 mutation attempt 都消耗一个 generation，包括非法模型响应、evaluator 异常和超时。失败尝试永久可检查，但不会进入 parent pool。

## 架构

```mermaid
flowchart LR
    Task["TASK.md"] --> Mutation["mutation.py<br/>prompt + model + parser"]
    Archive["archive.py<br/>JSONL / SQLite + selection"] --> Engine["engine.py<br/>deterministic batches"]
    Engine --> Mutation
    Mutation --> Runner["runner.py<br/>fresh evaluator process"]
    Runner --> Engine
    Engine --> Archive
    CLI["cli.py<br/>run / resume / best / inspect"] --> Engine
```

六个语义模块保持具体而透明。NanoEvolve 不提供 policy 类层级、provider registry、隐藏记忆或 observer framework。

## 选择策略

默认 parent 策略刻意保持简单：

- 概率 `0.8`：从最高分的五个成功记录中按排名权重采样。
- 概率 `0.2`：在全部成功记录中均匀探索。
- 随机性来自 `SHA-256(run_seed, generation)`。
- 同分记录通过 record ID 稳定排序。

可选选择层均显式启用：字典序 score/metric objectives、按 metric 分箱的 MAP-Elites，以及带周期迁移的确定性 islands。不设置这些参数时仍保持原始 top-k 行为。

## 安全边界

> **重要：** `SubprocessRunner` 提供的是故障隔离，不是真正的安全沙箱。

生成代码和 evaluator 仍可能访问网络、用户可读文件、系统程序和同一用户的其他进程。对于不可信代码，请在 Docker、Podman、虚拟机或其他外部 sandbox 中运行整个实验。

默认 evaluator 子进程会移除名称中包含 `API_KEY`、`ACCESS_TOKEN`、`AUTH_TOKEN`、`SECRET` 或 `PASSWORD` 的环境变量。

## 路线图

### v0.1 — Nano core

- [x] 完整源码 mutation 格式
- [x] 顺序进化循环
- [x] Append-only JSONL archive
- [x] 确定性 top-k + exploration
- [x] 具有显式失败状态的 subprocess evaluator
- [x] `run`、`resume`、`best`、`inspect`
- [x] 无网络确定性示例

### v0.1.1 — 发布硬化

- [x] `python -m nanoevolve` 与共享 `--version`
- [x] Typed wheel 与显式 source distribution 内容
- [x] 跨平台 CI matrix 和 package-build job
- [x] 纯标准库 release checker
- [x] 贡献指南、安全政策和变更日志
- [x] Clean-wheel 安装与 installed CLI/demo 验证

### v0.2 — 更强 mutation context

- [x] SEARCH/REPLACE diff
- [x] EVOLVE-BLOCK 区域
- [x] Inspiration candidates
- [x] Artifact feedback

### v0.3 — Mini workspace

- [x] 多文件 workspace
- [x] 外部 sandbox command
- [x] 并行 evaluator workers
- [x] 可选 SQLite archive
- [x] 多指标选择

### v0.4 — Quality diversity

- [x] 简化 MAP-Elites
- [x] 用户提供 feature coordinates
- [x] 可选 islands 与 migration

### v0.5 — 目标感知停止

- [x] Python 与 CLI 运行共享持久化 target score
- [x] Seed 与 resume 预检查，避免多余模型调用
- [x] 显式 `target_reached` 事件
- [x] 确定性的并行 batch 边界语义

已发布的 v0.2-v0.5 路线图现已全部实现。未来能力仍需由真实运行中的明确需求驱动；“功能对齐更大的框架”不是目标。

## 开发与验证

```bash
python -m unittest discover -s tests -v
python -m compileall nanoevolve examples
python scripts/release_check.py
python -m nanoevolve --version
```

完整设计与实施清单：

- [`docs/superpowers/specs/2026-08-02-nanoevolve-design.md`](docs/superpowers/specs/2026-08-02-nanoevolve-design.md)
- [`tasks/plan.md`](tasks/plan.md)
- [`tasks/todo.md`](tasks/todo.md)
- [`docs/superpowers/specs/2026-08-02-v0.1.1-release-hardening-design.md`](docs/superpowers/specs/2026-08-02-v0.1.1-release-hardening-design.md)

## 项目边界

NanoEvolve 不是完整 AlphaEvolve 复现，也不是自主 coding agent。它是一个可以被阅读、嵌入、检查并通过普通 Python 扩展的透明程序进化内核。
