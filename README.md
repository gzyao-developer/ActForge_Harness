# ActForge Harness

面向具身任务的 **编排层（Harness）**：用自然语言下指令，由脚本或大模型逐步决策，完成抓取、擦拭、测量等桌面操作，并带技能按需加载、分层记忆、逐步评估与自动验收。

本仓库提供完整的仿真演示 Demo（Mock / PyBullet），与 Harness 控制流、技能与验收逻辑打通。

当前内置两类任务（**根据指令自动选择**）：

| 任务 | 触发示例 | 场景与目标 |
|------|----------|------------|
| **抓取** `pick_can` | 「把桌上的易拉罐拿起来」 | 易拉罐 + 干扰杯；抓住并抬起后回到初始位 |
| **接箍中径擦测** `coupling_clean` | 「擦拭接箍并测量内径」 | 接箍 A/B + 抹布 + 量尺；准入→擦拭→复核→测量→判定→归档 |

---

## 它解决什么问题

| 角色 | 职责 |
|------|------|
| **大模型 / 脚本** | 每步只决定「下一步做什么」（DECIDE） |
| **Harness** | 维护世界状态、加载技能与记忆、门禁、执行、评估、验收、写流程日志 |
| **执行后端** | Mock 或 PyBullet 执行动作，便于本地完整演示 |

核心控制流（逐步循环，不是一次规划完再播放）：

```text
SENSE → DECIDE → GATE → ACT → EVALUATE → VERIFY
              ↑_________________________________|
```

- **EVALUATE**：对本步动作打分；低于阈值可回退并重做当前步  
- **VERIFY**：整任务是否成功（按任务验收条件）

接箍 LLM 路径额外有 **Flow Assist**（`inspection/assist.py`）：纠正漏掉的 `wipe_return`、打断连续空转的 `move_above` 等，尽量对齐 script 的 A/B 业务事件序。

---

## 环境要求

- Python ≥ 3.10  
- Windows / Linux / macOS  
- （可选）OpenAI 兼容 LLM；国内可用 **Kimi（Moonshot）**  
- （可选）PyBullet，用于带窗口的可视化演示  

---

## 安装

```bash
cd ActForge_Harness
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux / macOS
# source .venv/bin/activate

pip install -e ".[dev]"

# 需要可视化窗口时再装
pip install -e ".[pybullet]"
```

配置大模型（仅 `--policy llm` 需要）：

```bash
# Windows
copy .env.example .env
# Linux / macOS
# cp .env.example .env
```

编辑 `.env` 示例（Kimi）：

```bash
EMBODY_LLM_API_KEY=你的密钥
EMBODY_LLM_BASE_URL=https://api.moonshot.cn/v1
EMBODY_LLM_MODEL=kimi-k2.7-code-highspeed
EMBODY_LLM_TEMPERATURE=1
```

> 更快优先用 `kimi-k2.7-code-highspeed` 或 `kimi-k3.1-pro-highspeed`；部分模型仅允许 `temperature=1`。

---

## 功能一：抓取（pick_can）

**做什么**：根据指令识别目标（默认易拉罐 `can_cola`），接近 → 抓取 → 抬起 → **机械臂回到初始位姿**（可继续持握目标）。

**验收**：抓住目标、夹爪闭合、抬起高度达标，且已 `return_home`。

### 怎么用

```bash
# 无 Key：脚本决策 + Mock（最快自测）
python -m actforge run --policy script --sim mock --instruction "把桌上的易拉罐拿起来"

# 可视化演示（PyBullet 窗口）
python -m actforge run --policy script --sim pybullet --gui --real-time --instruction "把桌上的易拉罐拿起来"

# 大模型逐步决策
python -m actforge run --policy llm --sim pybullet --gui --real-time --instruction "把桌上的易拉罐拿起来"

# 强制指定任务（忽略指令路由）
python -m actforge run --task-id pick_can --policy script --sim mock
```

成功时终端类似：`task_id=pick_can`，并打印 `holding` / `lift_z`。

---

## 功能二：接箍中径擦测（coupling_clean）

**做什么**：场景中有 **接箍 A、接箍 B**。对每件分别走完整擦测链路，演示 **执行 / 人工确认 / 测量 / 判定** 分离。

- **script**：固定可复现，事件与 Δd 对齐下表  
- **llm**：prompt + `recall.inspection` 阶段提示 + Flow Assist，尽量走同一业务事件序，并写入同一份 `process.log`

**单件流程（A、B 各走一遍）**：

| 事件 | 含义 |
|------|------|
| 任务准入 | 该接箍到位，开始清理 |
| 擦拭返回 | 擦拭完成，待人工确认 |
| 清理复核 | 人工确认洁净 → 允许测量 |
| 仪器测量 | 输出 Δd |
| 规则判定 | 偏差在限内 → 合格；超限 → 不合格 |
| 记录归档 | 证据齐备；**不合格也归档** |
| 回初始位 | `return_home` 后再处理下一件 |

| 接箍 | Δd | 判定 |
|------|-----|------|
| A | +0.020 | 合格 |
| B | +0.080 | 不合格（仍归档） |

**验收**：A/B 均已归档、空手、最终已回初始位（不以「全部合格」为任务成功条件）。

### 怎么用

```bash
# 推荐基线：脚本 + Mock（无 Key、最快）
python -m actforge run --policy script --sim mock --instruction "擦拭接箍并测量内径"

# 可视化（观察擦拭/测量动作；--real-time 按墙钟放慢）
python -m actforge run --policy script --sim pybullet --gui --real-time --instruction "请擦拭接箍内壁并测量内径"

# 大模型：对齐 A/B 流程；日志格式同 script
# 追求速度可去掉 --real-time；墙钟主要花在每次 DECIDE 的 API 调用上
python -m actforge run --policy llm --sim pybullet --gui --no-evaluate --instruction "擦拭接箍并测量内径"

python -m actforge run --task-id coupling_clean --policy script --sim mock
```

### 流程日志 `process.log`

每次运行写入 `runs/<run_id>/process.log`（终端同步），面向业务阅读：

- 业务事件行：`[接箍A] 任务准入 | … | …`
- 少量物理里程碑：抓取 / 擦拭 / 测量 Δd / 回初始位
- 文末「关键事件」时间表与 A/B 合格结论

默认**不**打印逐步 DECIDE/GATE/ACT（避免暴露脚本/仿真/复核实现细节）；调试加 `--verbose`。明细事件另见同目录 `events.jsonl`。

> **Windows PowerShell** 换行请用反引号 `` ` ``，或写成一行；不要用 bash 的 `\`。

---

## 常用参数

| 参数 | 说明 | 常用值 |
|------|------|--------|
| `--policy` | 谁来 DECIDE | `script`（无 Key）/ `llm`（大模型） |
| `--sim` | 演示后端 | `mock` / `pybullet` |
| `--gui` | 打开可视化窗口 | 仅 `pybullet` |
| `--real-time` | 按墙钟放慢动作，方便观察 | 与 `--gui` 一起用；会拉长墙钟 |
| `--instruction` | 自然语言指令（自动选任务） | 见上文两功能示例 |
| `--task-id` | 强制任务 | `pick_can` / `coupling_clean` |
| `--verbose` | 打印逐步 DECIDE/GATE/ACT 与 LLM 细节 | 调试用 |
| `--no-evaluate` | 关闭逐步评估 | LLM 演示时可加快、少重试 |
| `--max-steps` | 最大步数 | 覆盖任务配置 |

```bash
python -m actforge run --help
```

---

## script 和 llm 怎么选

| | `--policy script` | `--policy llm` |
|--|-------------------|----------------|
| 是否调用大模型 | 否 | 是（读 `.env`） |
| 动作序列 | 代码写死的标准流程 | **每步**根据 snapshot 由模型选一个动作 |
| 接箍对齐 | 固定事件与 Δd | 阶段提示 + Flow Assist 纠偏 |
| 适用 | 安装自测、无 Key、对照基线 | 决策演示、扩展新指令/新动作 |

扩展新任务时：注册动作能力 + 更新 skill / prompt，优先走 **llm**；需要稳定复现对照时保留 script。

---

## 项目结构

```text
configs/               场景、任务、记忆、评估阈值
skills/                Skillbook（pick-can、coupling-clean-measure、grasp-retry 等）
prompts/               LLM 系统提示（抓取 / 接箍）
src/actforge/          Harness 核心
  kernel/              状态机（含 Flow Assist 挂载）
  inspection/          接箍业务动作、阶段提示、流程纠偏
  adapters/            script / llm / mock / pybullet
  evaluate/ verify/    逐步评估与任务验收
runs/                  每次运行的 process.log + events.jsonl
data/recall/           长期记忆落盘
tests/                 pytest
docs/DEV_PHASE1.md     开发文档
```

| 模块 | 作用 |
|------|------|
| **Skillbook** | 技能只暴露短描述；`load_skill` 按需加载正文 |
| **Recall** | 任务便签 / 跨任务长期记忆 / 动作经验；接箍另注入 `inspection` 阶段提示 |
| **Inspection** | 准入/复核/判定/归档等业务动作；`guide` 推荐下一步；`assist` 防空转与补 `wipe_return` |
| **Evaluate** | 逐步打分；失败可 rewind 后重做（`configs/evaluate.yaml`） |
| **MockSim / PyBulletSim** | 本地完整演示后端；与同一套 Harness 对接 |
| **ProcessLog** | 业务可读流程日志（事件 + 关键表），不暴露实现细节 |
| **Verify** | 抓取：抓住+抬起+回初始位；接箍：A/B 归档完成+回初始位（合格与否单独记录） |

---

## 评估相关

默认开启逐步评估。可在 `configs/evaluate.yaml` 调整：

- `threshold`：低于该分重做当前步  
- `max_retries`：单步最多额外重试次数  
- `rewind_on_retry`：重试前是否回退到该步开始前  

```bash
python -m actforge run --policy script --sim mock --no-evaluate --instruction "把桌上的易拉罐拿起来"
```

---

## 测试

```bash
pytest -q
# 接箍与 Flow Assist
pytest -q tests/test_coupling_task.py tests/test_flow_assist.py
```

未安装 PyBullet 时，相关用例会自动 skip。

---

## 说明

- `.env`、运行日志与 `data/recall/` 可能含密钥或指令内容，请勿提交密钥，并注意留存策略。  
- 开发依据见：`开发文档.md` / `docs/DEV_PHASE1.md`。
