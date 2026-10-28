# ActForge Harness — 第一阶段开发文档

> **产品名**：ActForge / ActForge_Harness  
> **文档用途**：在本仓库之外的独立工作空间，从零实现一个「具身拿取易拉罐」仿真 Harness（接入 LLM）。  
> **文档版本**：v1.1  
> **阶段目标**：Mock 仿真 + LLM 决策 + **Skillbook（按需 Skills）** + **Recall（分层 Memory）** + 机械臂完成「拿起桌上易拉罐」+ 自动验收。  
> **独立性要求**：按本文自行设计实现，**不要** fork / 复制 / 对照改写 Thea 或 OpenHarness 源码与模块命名。能力可类似，包名/协议/控制流必须是 ActForge 自己的。

---

## 0. 使用说明

1. 新建独立 Git 仓库（建议名：`ActForge_Harness`；Python 包名示例：`actforge`，下文部分路径仍可用 `embody_pick` 作过渡，最终统一为 `actforge`）。
2. 将本文全文放入新仓库根目录，例如 `docs/DEV_PHASE1.md`，作为唯一开发依据。
3. 严格按 **第 16 章开发顺序** 推进；每完成一个 Step，勾选验收清单。
4. 第一阶段结束时，应能用一句话指令在终端演示：仿真臂拿起易拉罐，且日志中可见 Skill 加载与 Memory 读写。

---

## 1. 背景与边界

### 1.1 要解决什么问题

构建一个**具身任务编排层（ActForge Harness）**：

- 接收自然语言指令（如「把桌上的易拉罐拿起来」）；
- 维护仿真世界状态；
- 由 LLM 选择下一步动作；
- **按需加载 Skill（流程说明书）**，避免把长流程塞进系统提示；
- **分层记忆**：任务便签 / 长期记忆 / 动作经验，按生命周期注入决策上下文；
- 经确定性门禁后执行；
- 用确定性规则判定任务是否成功。

模型负责「选下一步做什么」；Harness 负责「世界、Skillbook、Recall、安全门禁、执行、验收、日志」。

### 1.2 第一阶段明确不做

| 不做 | 原因 |
|------|------|
| 真机 SDK / 力控 / 急停认证 | 超出 Demo 范围 |
| LIBERO / RoboTwin / 复杂仿真套件 | 第一阶段用 Mock 即可 |
| 飞书 / Slack 等 IM | 第二阶段再加 |
| 多 Agent / Swarm | 非本阶段 |
| 完整视觉检测管线 | 物体位姿由仿真直接给出 |
| 整屋导航、双臂、多房间 | 场景固定为单桌面 |
| 复制 Thea / OpenHarness 架构与命名 | 避免版权与产品同质化风险 |

> **v1.1 已纳入 Phase 1**：Skillbook（Skills 目录 + `load_skill`）、Recall（分层 Memory）。二者用 ActForge 自己的模块名与存储布局实现，不要照搬其它项目的包结构。

### 1.3 知识产权与实现纪律（必读）

- **允许**：自行实现「指令→决策→动作→校验」「技能按需加载」「分层记忆」类通用能力（思想不受版权保护）。
- **禁止**：复制 Thea / OpenHarness 的源代码、目录结构照搬、论文式对外模块品牌用语作为你的产品模块名。
- **推荐**：本文给出的包名、状态机、事件协议、配置格式即为你的独立设计；实现时只对照本文，不要开着 Thea 源码改。
- **对外叙事**用自己的术语：任务流水线、能力插件、**Skillbook**、**Recall**、世界快照、动作门禁、后验验收。
- 本文不构成法律意见；商业交付前建议公司法务做 IP 审查。

---

## 2. 第一阶段验收标准（Definition of Done）

同时满足以下条件即视为 Phase 1 完成：

1. **自然语言入口**：CLI 支持 `--instruction "把桌上的易拉罐拿起来"`。
2. **LLM 参与决策**：至少一轮动作由 LLM 输出（非纯硬编码脚本路径）；另提供 `--policy script` 便于无 Key 联调。
3. **仿真执行闭环**：机械臂完成接近 → 闭合夹爪 → 抬起。
4. **自动验收通过**：`holding == can_cola` 且罐体相对桌面抬起高度 ≥ 阈值。
5. **Skillbook**：存在 `skills/` 目录；snapshot 默认只带 **技能目录（name+description）**；LLM 可通过 `load_skill` **按需**加载正文；加载后进入「活动流程」并出现在后续 snapshot。
6. **Recall 分层记忆**：
   - **Task Notes（任务便签）**：仅本任务有效，可读写；
   - **Durable Memory（长期记忆）**：跨任务持久化到磁盘，任务开始可检索注入；
   - **Tool Experience（动作经验）**：记录动作成败摘要，供后续决策参考；任务结束可沉淀精华到长期记忆（规则或可选 LLM 摘要）。
7. **可审计日志**：JSONL 记录每步 snapshot 摘要、LLM 意图、gate 结果、act 结果、verify 结果，以及 `skill.loaded` / `memory.*` 事件。
8. **失败可解释**：抓空、门禁拒绝、超时、步数耗尽均有明确 `fail_reason`。
9. **单测通过**：抓取成功、抓空、门禁拒绝、验收器、`load_skill`、三层 memory 读写至少各 1 个自动化测试。

### 2.1 Demo 脚本（验收演示用）

```bash
# 无 LLM：脚本策略（开发自测）
python -m actforge run --scene configs/scene_desk_v1.yaml --policy script \
  --instruction "把桌上的易拉罐拿起来"

# 有 LLM
python -m actforge run --scene configs/scene_desk_v1.yaml --policy llm \
  --instruction "把桌上的易拉罐拿起来"
```

期望终端末尾类似：

```text
TASK_RESULT status=success steps=6 holding=can_cola lift_z=0.15
log=runs/xxxx/events.jsonl
```

---

## 3. 推荐技术栈

| 项 | 选型 | 说明 |
|----|------|------|
| 语言 | Python ≥ 3.10 | |
| 包管理 | `uv` 或 `pip` + `pyproject.toml` | 任选其一 |
| LLM | OpenAI 兼容 Chat Completions | 国内兼容网关亦可 |
| 配置 | YAML（场景/任务）+ `.env`（密钥） | |
| 数据校验 | Pydantic v2 | ActionIntent、Snapshot |
| 测试 | pytest | |
| 日志 | JSON Lines | 每事件一行 |

可选依赖（第一阶段）：

```text
pydantic>=2
pyyaml>=6
httpx>=0.27
python-dotenv>=1.0
pytest>=8
typer>=0.12          # 或 argparse
rich>=13             # 可选，美化终端
```

---

## 4. 仓库与目录结构（独立设计）

在新工作空间创建：

```text
ActForge_Harness/                 # 仓库根目录（推荐名）
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── docs/
│   └── DEV_PHASE1.md             # 本文
├── configs/
│   ├── scene_desk_v1.yaml
│   ├── task_pick_can.yaml
│   └── recall.yaml               # 记忆相关配置
├── prompts/
│   └── pick_can_system.md
├── skills/                       # Skillbook 目录（按需加载正文）
│   ├── pick-can/
│   │   └── SKILL.md
│   └── grasp-retry/
│       └── SKILL.md
├── data/                         # 持久化数据（gitignore 可忽略内容、保留 .gitkeep）
│   └── recall/
│       ├── durable/              # 长期记忆条目（md/json）
│       └── lessons.jsonl         # 动作经验追加日志（可选）
├── src/
│   └── actforge/                 # 或过渡名 embody_pick
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── kernel/
│       │   ├── __init__.py
│       │   ├── events.py
│       │   ├── task.py
│       │   └── state_machine.py
│       ├── worldview/
│       │   ├── __init__.py
│       │   ├── models.py
│       │   └── snapshot.py
│       ├── skillbook/            # Skills：目录扫描 + load_skill
│       │   ├── __init__.py
│       │   ├── loader.py
│       │   ├── catalog.py
│       │   └── types.py
│       ├── recall/               # 分层 Memory
│       │   ├── __init__.py
│       │   ├── task_notes.py     # 任务便签（仅本任务）
│       │   ├── durable.py        # 长期记忆（跨任务）
│       │   ├── tool_experience.py# 动作经验
│       │   └── service.py        # 统一门面：注入 snapshot / 写入 API
│       ├── capabilities/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── registry.py
│       │   ├── sense.py
│       │   ├── act.py
│       │   ├── skill_caps.py     # load_skill
│       │   └── memory_caps.py    # note_write / memory_search / ...
│       ├── policy_gate/
│       │   ├── __init__.py
│       │   └── rules.py
│       ├── verify/
│       │   ├── __init__.py
│       │   └── pick_can.py
│       ├── adapters/
│       │   ├── __init__.py
│       │   ├── llm_openai.py
│       │   ├── policy_script.py
│       │   └── sim_mock.py
│       └── util/
│           ├── __init__.py
│           ├── config.py
│           └── logging_jsonl.py
├── tests/
│   ├── test_sim_grasp.py
│   ├── test_gate.py
│   ├── test_verify.py
│   ├── test_skillbook.py
│   ├── test_recall.py
│   └── test_state_machine_script.py
└── runs/                         # gitignore；运行输出
```

`pyproject.toml` 示例要点：

```toml
[project]
name = "actforge"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
  "pydantic>=2",
  "pyyaml>=6",
  "httpx>=0.27",
  "python-dotenv>=1.0",
  "typer>=0.12",
]

[project.optional-dependencies]
dev = ["pytest>=8", "ruff>=0.5"]

[project.scripts]
actforge = "actforge.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/actforge"]
```

---

## 5. 场景与任务配置

### 5.1 `configs/scene_desk_v1.yaml`

```yaml
scene_id: desk_v1
description: "单桌面，一罐一干扰杯，简化臂"

table:
  z: 0.0
  x_min: -0.5
  x_max: 0.5
  y_min: -0.5
  y_max: 0.5

robot:
  ee_pose: { x: 0.0, y: -0.35, z: 0.25, yaw: 0.0 }
  gripper: open          # open | closed
  holding: null          # null | object_id

objects:
  - id: can_cola
    label: cola_can
    display_name: 易拉罐
    xyz: { x: 0.10, y: 0.05, z: 0.06 }
    yaw: 0.0
    radius: 0.033         # 水平抓取判定半径辅助
    height: 0.12
    graspable: true

  - id: cup_white
    label: cup
    display_name: 白杯子
    xyz: { x: -0.15, y: 0.08, z: 0.05 }
    yaw: 0.0
    radius: 0.04
    height: 0.09
    graspable: true

# 抓取几何阈值（Mock 物理）
grasp:
  xy_tolerance: 0.03      # 末端与物体水平距离上限（米）
  z_tolerance: 0.04       # 高度差上限
  lift_after_grasp: 0.10  # 验收：相对桌面至少抬起

motion:
  default_z_offset: 0.12  # move_above 默认离物体顶的高度余量
  step_sleep_sec: 0.0     # Demo 可改为 0.05 慢放
```

### 5.2 `configs/task_pick_can.yaml`

```yaml
task_id: pick_can
goal:
  type: pick_object
  object_id: can_cola
  min_lift_z: 0.10        # 相对 table.z

limits:
  max_steps: 24           # 含 load_skill / note 等步骤，略增
  timeout_sec: 120

skills:
  dir: skills
  require_load_for_demo: true   # Demo/集成测试期望至少一次 load_skill

aliases:
  # 用于从自然语言粗解析目标（LLM 为主，规则为辅）
  can_cola: ["易拉罐", "可乐罐", "罐子", "can", "cola"]
```

### 5.3 `configs/recall.yaml`

见第 13.2 节完整示例；CLI 通过 `--recall-config` 加载。
### 5.4 `.env.example`

```bash
EMBODY_LLM_API_KEY=sk-xxx
EMBODY_LLM_BASE_URL=https://api.openai.com/v1
EMBODY_LLM_MODEL=gpt-4o-mini
# 若走国内兼容网关，改 BASE_URL 与 MODEL 即可
```

---

## 6. 核心数据模型

文件：`src/embody_pick/worldview/models.py`

### 6.1 几何与物体

```python
from typing import Literal, Optional
from pydantic import BaseModel, Field


class Pose(BaseModel):
    x: float
    y: float
    z: float
    yaw: float = 0.0


class SceneObject(BaseModel):
    id: str
    label: str
    display_name: str
    xyz: Pose
    radius: float = 0.03
    height: float = 0.1
    graspable: bool = True


class RobotState(BaseModel):
    ee_pose: Pose
    gripper: Literal["open", "closed"] = "open"
    holding: Optional[str] = None


class WorldState(BaseModel):
    scene_id: str
    table_z: float
    robot: RobotState
    objects: dict[str, SceneObject]  # id -> object
    grasp_xy_tolerance: float = 0.03
    grasp_z_tolerance: float = 0.04
```

### 6.2 动作意图（LLM / 脚本统一输出）

```python
class ActionIntent(BaseModel):
    thought: str = ""
    action: str
    args: dict = Field(default_factory=dict)
```

允许的 `action` 枚举（第一阶段冻结；含 Skill / Memory）：

| action | args | 说明 |
|--------|------|------|
| `list_objects` | `{}` | 返回物体列表（也可仅用于调试；每轮 snapshot 已含列表） |
| `get_object_pose` | `{object_id}` | 查询位姿 |
| `move_above` | `{object_id, z_offset?}` | 移到物体上方 |
| `move_down` | `{delta_z?}` 默认 0.08 | 末端下降 |
| `close_gripper` | `{}` | 闭合；内部判定是否抓住 |
| `open_gripper` | `{}` | 张开；若持有则释放到当前位置 |
| `lift` | `{delta_z?}` 默认 0.12 | 末端上抬；持有物跟随 |
| `load_skill` | `{skill_name}` | **按需**加载 Skill 正文到「活动流程」 |
| `note_write` | `{text}` | 写入 Task Notes（本任务便签） |
| `memory_search` | `{query, limit?}` | 检索 Durable Memory |
| `memory_write` | `{text, tags?}` | 写入 Durable Memory（长期） |
| `done` | `{reason?}` | 模型声称完成；仍以 Verify 为准 |

> 说明：Tool Experience（动作经验）主要由 Harness **在每次 ACT 后自动追加**，一般不需要 LLM 手动写；可选提供 `lesson_write` 但不作为 Phase 1 必做。

### 6.3 执行结果

```python
class ActResult(BaseModel):
    ok: bool
    action: str
    message: str = ""
    observation: dict = Field(default_factory=dict)


class GateResult(BaseModel):
    allowed: bool
    reason: str = ""


class VerifyResult(BaseModel):
    success: bool
    reason: str = ""
    metrics: dict = Field(default_factory=dict)
```

---

## 7. 世界快照（给 LLM 看的视图）

文件：`src/embody_pick/worldview/snapshot.py`

原则：**每轮决策前**生成紧凑文本或 JSON，避免把整个调试结构塞进 prompt。

建议结构化 snapshot（再 `model_dump_json`）：

```json
{
  "instruction": "把桌上的易拉罐拿起来",
  "goal_object_id": "can_cola",
  "step": 3,
  "max_steps": 20,
  "robot": {
    "ee": {"x": 0.1, "y": 0.05, "z": 0.18, "yaw": 0.0},
    "gripper": "open",
    "holding": null
  },
  "objects": [
    {
      "id": "can_cola",
      "name": "易拉罐",
      "x": 0.1, "y": 0.05, "z": 0.06,
      "graspable": true
    },
    {
      "id": "cup_white",
      "name": "白杯子",
      "x": -0.15, "y": 0.08, "z": 0.05,
      "graspable": true
    }
  ],
  "last_result": {
    "action": "move_above",
    "ok": true,
    "message": "ee moved above can_cola"
  },
  "skill_catalog": [
    {"name": "pick-can", "description": "桌面圆柱易拉罐抓取与抬起的标准流程"},
    {"name": "grasp-retry", "description": "抓空后重新对准并重试闭合夹爪"}
  ],
  "active_skill": {
    "name": "pick-can",
    "body_excerpt": "1. move_above 目标..."
  },
  "recall": {
    "task_notes": ["目标是 can_cola，不要抓 cup_white"],
    "durable_hits": [
      {"id": "d001", "text": "易拉罐抓取时 xy 容差约 3cm，需先到正上方再下降", "score": 0.82}
    ],
    "recent_lessons": [
      {"action": "close_gripper", "ok": false, "message": "grasp_miss"}
    ]
  },
  "allowed_actions": [
    "list_objects", "get_object_pose", "move_above", "move_down",
    "close_gripper", "open_gripper", "lift",
    "load_skill", "note_write", "memory_search", "memory_write",
    "done"
  ]
}
```

实现要求：

- `holding` 非空时，被持有物体的 `xyz` 应与末端绑定（或标注 `attached_to: ee`）。
- `last_result` 必须包含失败原因，供 LLM 纠正。
- **默认只放 `skill_catalog`（短）**；`active_skill.body` 仅在 `load_skill` 之后注入，且可截断到 N 字符（如 2000）。
- `recall.durable_hits` 每轮可自动用 instruction / goal 做一次轻量检索（limit=3），也可等 LLM 调 `memory_search`。
- `recent_lessons` 只保留最近 K 条（如 5），避免上下文膨胀。

---

## 8. Mock 仿真语义（`adapters/sim_mock.py`）

第一阶段**不**接真实物理引擎。用确定性规则模拟「假物理」。

### 8.1 `move_above(object_id, z_offset)`

1. 查物体；不存在则失败。
2. 目标位姿：

   - `x, y = object.x, object.y`
   - `z = object.z + object.height/2 + z_offset`（或 `object.z + z_offset`，团队内统一一种并写进注释）
3. 直接或插值更新 `robot.ee_pose`（Demo 可瞬时到达）。
4. 若 `holding` 非空，同步更新被持有物体 xyz。

### 8.2 `move_down(delta_z)`

- `ee.z = max(table_z + 0.02, ee.z - delta_z)`
- 持有物跟随。

### 8.3 `close_gripper`

1. 若已 `closed`：返回 ok + message 已关闭。
2. 设 `gripper = closed`。
3. **抓取判定**（全部满足才抓住）：
   - 存在候选物体 `o`，`o.graspable == True`
   - `hypot(ee.x - o.x, ee.y - o.y) <= grasp_xy_tolerance`
   - `abs(ee.z - o.z) <= grasp_z_tolerance`（或相对物体顶部的容差，选定一种）
   - 当前 `holding is None`
4. 成功：`holding = o.id`；物体标记附着。
5. 失败：`holding` 仍为 `None`，`ok=False`，`message="grasp_miss"`。

若多个物体同时满足，选**水平距离最近**者。

### 8.4 `open_gripper`

- `gripper = open`
- 若曾 holding：物体放到当前 ee 投影位置（z 落到桌面物体高度），`holding = None`

### 8.5 `lift(delta_z)`

- `ee.z += delta_z`
- 持有物跟随抬高

### 8.6 只读

- `list_objects` / `get_object_pose`：不改世界，只返回 observation。

---

## 9. 能力注册与执行（`capabilities/`）

### 9.1 接口

```python
class Capability(Protocol):
    name: str
    def execute(self, world: WorldState, args: dict) -> ActResult: ...
```

`CapabilityRegistry`：

- `register(cap)`
- `execute(name, world, args) -> ActResult`
- 未知 name → `ActResult(ok=False, message="unknown_action")`

### 9.2 注册表内容（启动时）

将下列动作全部注册完毕：

- `sense` + `act`：仿真读写与运动
- `skill_caps`：`load_skill`
- `memory_caps`：`note_write` / `memory_search` / `memory_write`

`sim_mock` 作为运动底层；Skill / Memory 类 capability **不调用仿真**，只改 Skillbook / Recall 状态。  
Registry 的 `execute` 需能传入 `ctx={"skillbook", "recall"}`（见第 14.2 节伪代码）。

---

## 10. 动作门禁（`policy_gate/rules.py`）

在 **ACT 之前**调用。Gate 失败则**不执行**动作，把 `reason` 写入 `last_result`，进入下一轮让策略重选。

建议规则（可配置开关）：

| ID | 规则 | 行为 |
|----|------|------|
| G1 | `action` 不在允许列表 | 拒绝 |
| G2 | 需要 `object_id` 但缺失/不存在 | 拒绝 |
| G3 | `close_gripper` 时已 holding | 拒绝或警告（建议拒绝） |
| G4 | `lift` 时无 holding | 允许但 Verify 不会成功；可警告 |
| G5 | 步数将超限时仍非 `done` | 由 kernel 结束任务，不必 gate |
| G6 | 坐标越出桌面包围盒过大 | 拒绝 `move_*` |
| G7 | `load_skill` 缺 `skill_name` | 拒绝 |
| G8 | `note_write` / `memory_write` 的 text 为空或超长 | 拒绝 |

第一阶段至少实现 G1–G3、G7–G8；G4–G6 可迭代加。

```python
def check(intent: ActionIntent, world: WorldState) -> GateResult:
    ...
```

---

## 11. 验收器（`verify/pick_can.py`）

每轮 ACT 之后调用（以及模型输出 `done` 时强制调用）。

成功条件（全部满足）：

```text
world.robot.holding == goal.object_id
AND world.robot.gripper == "closed"
AND world.objects[goal.object_id].xyz.z >= table_z + min_lift_z
```

返回：

```python
VerifyResult(
  success=True/False,
  reason="picked_and_lifted" | "not_holding" | "not_lifted_enough" | ...,
  metrics={"holding": ..., "can_z": ..., "need_z": ...}
)
```

注意：LLM 输出 `done` **不能**单独结束成功任务；必须 `VerifyResult.success`。

---

## 12. Skillbook：Skills 目录与按需 `load_skill`

> ActForge 模块名：**Skillbook**。对外可称「技能 / 流程说明书」。  
> 设计要点：**目录常驻短描述，正文按需加载**——不要把所有 SKILL.md 全文塞进 system prompt。

### 12.1 目录约定

```text
skills/
├── pick-can/
│   └── SKILL.md
└── grasp-retry/
    └── SKILL.md
```

每个 `SKILL.md` 使用 YAML frontmatter + Markdown 正文：

```markdown
---
name: pick-can
description: 桌面圆柱易拉罐（cola can）的接近、抓取与抬起标准流程。
---

## 适用场景

用户要求拿起易拉罐 / 可乐罐，且场景中存在 `can_cola`。

## 推荐步骤

1. 确认目标 id（一般为 can_cola，勿与 cup 混淆）。
2. `move_above` 到目标正上方。
3. `move_down` 接近。
4. `close_gripper`；若 grasp_miss，转技能 grasp-retry。
5. `lift` 抬起后 `done`。

## 注意

- 先对准再闭合；不要隔空抓。
- 干扰物 cup_white 不要抓。
```

### 12.2 数据模型（`skillbook/types.py`）

```python
class SkillMeta(BaseModel):
    name: str
    description: str
    path: str  # 文件路径，不进 LLM 亦可


class SkillBody(BaseModel):
    name: str
    description: str
    body: str  # frontmatter 之后的 Markdown


class SkillbookState(BaseModel):
    catalog: list[SkillMeta]
    active: SkillBody | None = None  # 当前已 load 的技能（Phase 1 只保留 1 个）
```

### 12.3 加载器行为（`skillbook/loader.py` / `catalog.py`）

1. 启动或任务开始时扫描 `skills/**/SKILL.md`。
2. 解析 frontmatter → `SkillMeta` 列表（失败的文件记日志并跳过）。
3. `load_skill(name)`：
   - 名称不存在 → `ActResult(ok=False, message="unknown_skill")`
   - 成功 → 设置 `SkillbookState.active`，事件 `skill.loaded`
   - Phase 1：**后加载覆盖前一个** active（简单）；可选记录 `loaded_history`
4. snapshot 规则：
   - 始终包含 `skill_catalog`（仅 name + description）
   - 仅当 active 非空时包含 `active_skill`（可 `body_excerpt` 截断）

### 12.4 Capability：`load_skill`

注册在 `capabilities/skill_caps.py`，不调用仿真，只改 SkillbookState。

Gate：`skill_name` 必填；未知名拒绝或交由 capability 返回失败（二选一，推荐 capability 返回 ok=False，便于 LLM 看到 message）。

### 12.5 与脚本/LLM 策略的配合

- **script 模式**：序列开头可先 `load_skill(pick-can)`（可选，证明链路），再执行抓取动作。
- **llm 模式**：system prompt 写明「先根据 catalog 选择并 `load_skill`，再按活动流程执行」；若模型不 load 也能靠通用提示完成，但 **Demo 验收要求至少出现一次 `load_skill`**（可用集成测试或日志断言）。

### 12.6 必交付的两个技能文件

| 技能 | 作用 |
|------|------|
| `pick-can` | 主流程 |
| `grasp-retry` | 抓空后的恢复流程 |

---

## 13. Recall：分层 Memory

> ActForge 模块名：**Recall**。三层生命周期与 Thea 的「任务笔记 / 长期记忆 / 工具经验」**能力对齐**，但存储格式、API、注入方式按本文实现，不要抄其它仓库代码。

### 13.1 三层定义

| 层级 | ActForge 名 | 生命周期 | 存储 | 谁写入 | 如何进入上下文 |
|------|-------------|----------|------|--------|----------------|
| Task Notes | `task_notes` | **仅当前任务**；任务结束丢弃（可把摘要写入 durable） | 内存 list | LLM：`note_write`；也可由 Harness 自动记关键里程碑 | 每轮全量或最近 N 条进入 snapshot |
| Durable Memory | `durable` | **跨任务** | `data/recall/durable/*.md` 或 json | LLM：`memory_write`；任务成功后规则沉淀 | 任务开始 / 每轮自动检索 top-k；或 `memory_search` |
| Tool Experience | `tool_experience` | 本任务详细 + 可选追加到 `lessons.jsonl` | 内存环 + 可选 jsonl | **每次 ACT 后 Harness 自动写** | snapshot 中 `recent_lessons` 最近 K 条 |

### 13.2 配置 `configs/recall.yaml`

```yaml
task_notes:
  max_items: 20

durable:
  dir: data/recall/durable
  auto_retrieve_each_step: true
  top_k: 3
  max_write_chars: 500

tool_experience:
  recent_k: 5
  persist_jsonl: data/recall/lessons.jsonl
  persist_on_act: true

on_task_success:
  # 成功后把一条短总结写入 durable（规则模板即可，Phase 1 不必再用 LLM 总结）
  write_durable_summary: true
  summary_template: "任务成功：{instruction}；目标={goal_object_id}；步数={steps}"
```

### 13.3 数据模型

```python
class TaskNote(BaseModel):
    ts: str
    text: str


class DurableItem(BaseModel):
    id: str
    text: str
    tags: list[str] = []
    created_at: str


class Lesson(BaseModel):
    ts: str
    step: int
    action: str
    ok: bool
    message: str = ""
    args_digest: str = ""  # 可选：参数摘要，避免存过大结构
```

### 13.4 `recall/service.py` 门面 API

```python
class RecallService:
    def on_task_start(self, instruction: str, goal_object_id: str) -> None:
        """清空 task_notes；可选预检索 durable → 缓存到 self._durable_hits"""

    def build_recall_snapshot(self) -> dict:
        """返回 snapshot['recall'] 字段"""

    def note_write(self, text: str) -> ActResult: ...
    def memory_search(self, query: str, limit: int = 3) -> ActResult: ...
    def memory_write(self, text: str, tags: list[str] | None = None) -> ActResult: ...

    def record_lesson(self, step: int, act_result: ActResult, args: dict) -> None:
        """ACT 后调用"""

    def on_task_end(self, outcome: TaskOutcome, instruction: str, goal_object_id: str) -> None:
        """成功则可写 durable summary；flush lessons jsonl"""
```

### 13.5 Durable 检索（Phase 1 保持简单）

**不要**第一阶段就上向量库。用朴素打分即可：

1. 将 query 与条目 text 分词（中英文：按空白 + 对中文可双字符 shingle 或简单子串）。
2. `score = 子串命中数 / 或 Jaccard(token_set)`。
3. 取 top_k。

单测：写入含「易拉罐」「xy 容差」的条目，用 query=`拿易拉罐` 能检索到。

### 13.6 Durable 文件格式（示例）

`data/recall/durable/d001_grasp_tolerance.md`：

```markdown
---
id: d001
tags: [grasp, can]
created_at: 2026-10-26T00:00:00Z
---

易拉罐抓取时需先到正上方再下降；xy 容差约 3cm，抓空后应重试对准。
```

### 13.7 Memory 相关 Capability

| action | 行为 |
|--------|------|
| `note_write` | 追加 TaskNote；超 `max_items` 丢弃最旧 |
| `memory_search` | 检索 durable，结果放在 `ActResult.observation.hits`，并更新下一轮 snapshot 缓存 |
| `memory_write` | 校验长度后落盘一条 durable |

Gate：`text` 为空拒绝；`memory_write` 超长拒绝。

### 13.8 自动写入 Tool Experience

在状态机 `ACT` 成功返回后（无论 ok True/False）：

```python
recall.record_lesson(step, act_result, intent.args)
```

`grasp_miss` 这类失败必须出现在 `recent_lessons`，方便 LLM 下一轮改选 `load_skill(grasp-retry)` 或重新 `move_above`。

---

## 14. 状态机与任务生命周期

### 14.1 状态

```text
IDLE → RUNNING → (SUCCESS | FAILED | TIMEOUT)
```

RUNNING 内循环相位：

```text
SENSE → DECIDE → GATE → ACT → (自动记 Lesson) → VERIFY → (继续 | 结束)
```

任务边界：

```text
on_task_start(Recall + Skillbook.catalog)
  → loop ...
  → on_task_end(Recall 沉淀)
```

### 14.2 伪代码（必须按此实现）

```python
def run_task(
    instruction, world, policy, gate, registry, verifier, limits,
    skillbook, recall, event_log, goal_object_id,
):
    event_log.emit("task.started", {"instruction": instruction})
    skillbook.reset_active()
    recall.on_task_start(instruction, goal_object_id)
    last_result = None

    for step in range(1, limits.max_steps + 1):
        snap = build_snapshot(
            instruction, world, step, limits.max_steps, last_result,
            skillbook=skillbook,
            recall=recall.build_recall_snapshot(),
            goal_object_id=goal_object_id,
        )
        event_log.emit("sense.done", {"step": step, "snapshot": snap.to_compact_dict()})

        intent = policy.decide(snap)   # script 或 llm
        event_log.emit("decide.done", {"step": step, "intent": intent.model_dump()})

        gate_result = gate.check(intent, world, skillbook=skillbook)
        event_log.emit("gate.checked", gate_result.model_dump())
        if not gate_result.allowed:
            last_result = ActResult(ok=False, action=intent.action, message=gate_result.reason)
            recall.record_lesson(step, last_result, intent.args)
            continue

        # load_skill / note_write / memory_* 走 registry，内部写 skillbook/recall
        act_result = registry.execute(intent.action, world, intent.args, ctx={
            "skillbook": skillbook,
            "recall": recall,
        })
        event_log.emit("act.done", act_result.model_dump())
        if intent.action == "load_skill" and act_result.ok:
            event_log.emit("skill.loaded", {"name": intent.args.get("skill_name")})
        last_result = act_result
        recall.record_lesson(step, act_result, intent.args)

        verify = verifier.check(world)
        event_log.emit("verify.done", verify.model_dump())
        if verify.success:
            outcome = TaskOutcome(status="success", steps=step, verify=verify)
            recall.on_task_end(outcome, instruction, goal_object_id)
            event_log.emit("task.finished", {"status": "success", "steps": step})
            return outcome

        if intent.action == "done" and not verify.success:
            last_result = ActResult(ok=False, action="done", message=verify.reason)
            continue

    outcome = TaskOutcome(status="failed", reason="max_steps")
    recall.on_task_end(outcome, instruction, goal_object_id)
    event_log.emit("task.finished", {"status": "failed", "reason": "max_steps"})
    return outcome
```

另：可用墙钟 `timeout_sec` 在循环头检查。

### 14.3 事件类型（`kernel/events.py`）

统一字段：

```json
{
  "ts": "2026-10-26T12:00:00Z",
  "run_id": "uuid",
  "type": "act.done",
  "payload": {}
}
```

最少事件：

- `task.started` / `sense.done` / `decide.done` / `gate.checked` / `act.done` / `verify.done` / `task.finished`
- `skill.loaded`
- `memory.note_written` / `memory.durable_written` / `memory.searched`（可由 capability 或 service 发）

输出路径：`runs/<run_id>/events.jsonl`。
---

## 15. 策略：脚本 vs LLM

### 15.1 脚本策略（`adapters/policy_script.py`）

用于无 API Key 时把闭环跑通。固定序列（可按当前 world 小幅分支）：

```text
1. load_skill(pick-can)
2. note_write("目标 can_cola")
3. move_above(can_cola, z_offset=0.12)
4. move_down(delta_z=0.10)
5. close_gripper
6. lift(delta_z=0.12)
7. done
```

若 `close_gripper` 失败：`load_skill(grasp-retry)` → 再 `move_above` → `close_gripper` 一次，仍失败则结束。

### 15.2 LLM 策略（`adapters/llm_openai.py`）

职责：

1. 读取 `prompts/pick_can_system.md` + 当前 snapshot JSON。
2. 调用 Chat Completions，`temperature=0.2`（或 0）。
3. 要求模型**只输出一个 JSON 对象**（不要 Markdown 围栏；若有围栏则剥离）。
4. 用 Pydantic 校验为 `ActionIntent`；失败则重试最多 2 次，并附加解析错误信息。
5. HTTP：`POST {BASE_URL}/chat/completions`，Header `Authorization: Bearer {API_KEY}`。

请求消息示例：

```text
system: <pick_can_system.md 内容>
user: <snapshot JSON>
```

### 15.3 `prompts/pick_can_system.md` 建议全文

```markdown
你是 ActForge 桌面机械臂任务的动作决策器。根据用户指令，通过选择动作拿起目标物体。

规则：
1. 每轮只能输出一个 JSON 对象，不要输出其它文字。
2. JSON 格式：
   {"thought":"简短推理","action":"动作名","args":{}}
3. action 只能是 snapshot.allowed_actions 中的值，包括：
   list_objects | get_object_pose | move_above | move_down |
   close_gripper | open_gripper | lift |
   load_skill | note_write | memory_search | memory_write | done
4. 不要编造 objects 列表中不存在的 object_id。
5. 任务开始时：若 skill_catalog 中有相关技能，先 load_skill，再按 active_skill 执行。
6. 可使用 note_write 记录本任务要点；可用 memory_search 查阅长期经验。
7. 典型成功顺序：load_skill(pick-can) → move_above(目标) → move_down → close_gripper → lift → done。
8. 若 last_result.ok=false 或 recent_lessons 出现 grasp_miss：先纠错（可 load_skill(grasp-retry)），再行动。
9. 只有当你认为已经抓住目标并抬起后，才输出 action=done。
10. 用户说「易拉罐/可乐罐」时，目标一般为 can_cola；以 snapshot.goal_object_id 为准。
```

---

## 16. CLI 设计

文件：`src/actforge/cli.py`

```text
actforge run \
  --instruction "把桌上的易拉罐拿起来" \
  --scene configs/scene_desk_v1.yaml \
  --task configs/task_pick_can.yaml \
  --skills-dir skills \
  --recall-config configs/recall.yaml \
  --policy script|llm \
  --max-steps 20 \
  --runs-dir runs
```

行为：

1. 加载 scene → `WorldState`
2. 加载 task limits / goal
3. 扫描 Skillbook；初始化 RecallService
4. 创建 `run_id`，初始化 JSONL
5. 选择 policy
6. `run_task(...)`
7. 打印 `TASK_RESULT` 与日志路径；成功 exit 0，失败 exit 1

也可用 Typer 子命令 `run`；或 `python -m actforge ...`。

---

## 17. 开发顺序（严格按 Step 执行）

### Step 0 — 建仓与工程（0.5 天）

- [ ] 初始化 git、`pyproject.toml`、包结构、`.gitignore`（忽略 `.env`、`runs/`、`data/recall/**` 内容可忽略、`__pycache__`）
- [ ] 可执行 `python -c "import actforge"`
- [ ] 复制本文到 `docs/DEV_PHASE1.md`
- [ ] 创建空目录 `skills/`、`data/recall/durable/`

**完成标准**：空包可安装（`pip install -e .`）。

---

### Step 1 — 模型与场景加载（0.5 天）

- [ ] 实现 `models.py`、`config.py` 加载 YAML → `WorldState`
- [ ] 单元测试：加载 `scene_desk_v1.yaml` 后存在 `can_cola` 与 `cup_white`

**完成标准**：`tests/test_load_scene.py` 通过。

---

### Step 2 — Mock 仿真 + 脚本直调（1 天）**【禁止接 LLM】**

- [ ] 实现 `sim_mock.py` 全部动作语义
- [ ] 手写 Python：依次调用 move_above → move_down → close → lift
- [ ] 断言 holding 与抬起高度

**完成标准**：`tests/test_sim_grasp.py` 通过；另有 `test_grasp_miss`（故意偏移末端再 close → 抓空）。

---

### Step 3 — Capability / Gate / Verify（1 天）

- [ ] Registry 包装 sim
- [ ] Gate G1–G3
- [ ] `pick_can` Verify
- [ ] 测试：未知 action 拒绝；错 object_id 拒绝；成功路径 verify 通过

**完成标准**：`tests/test_gate.py`、`tests/test_verify.py` 通过。

---

### Step 4 — Skillbook（0.5～1 天）

- [ ] 编写 `skills/pick-can/SKILL.md`、`skills/grasp-retry/SKILL.md`
- [ ] `catalog` 扫描 + frontmatter 解析
- [ ] `load_skill` capability + snapshot 字段
- [ ] 单测：未知技能失败；加载后 active 有正文

**完成标准**：`tests/test_skillbook.py` 通过。

---

### Step 5 — Recall 分层 Memory（1 天）

- [ ] `task_notes` / `durable` / `tool_experience` 三层实现
- [ ] `note_write` / `memory_search` / `memory_write` capabilities
- [ ] ACT 后自动 `record_lesson`
- [ ] 任务成功写 durable summary
- [ ] 单测：便签隔离（新任务清空）；durable 检索命中；lesson 环缓冲

**完成标准**：`tests/test_recall.py` 通过。

---

### Step 6 — 状态机 + 脚本策略 + CLI + JSONL（1 天）

- [ ] `state_machine.run_task`（含 skillbook + recall）
- [ ] `policy_script`（含 load_skill / note_write）
- [ ] CLI `--policy script`
- [ ] 事件写入 `runs/<id>/events.jsonl`（含 `skill.loaded`）

**完成标准**：一条命令脚本模式跑通拿罐；JSONL 可见 skill 与 memory 相关事件。

---

### Step 7 — 接入 LLM（1～2 天）

- [ ] `.env` 加载
- [ ] `llm_openai.py` + 更新后的 `pick_can_system.md`
- [ ] JSON 解析与重试
- [ ] CLI `--policy llm`

**完成标准**：真实 Key 下成功拿起 `can_cola`；日志中至少一次 `load_skill`；出现 `grasp_miss` 时能利用 lessons/技能重试。

---

### Step 8 — Demo 打磨与回归（0.5～1 天）

- [ ] Rich/纯文本逐步打印相位（含 active_skill 名、notes 条数）
- [ ] 回归用例表（见第 18 章）全部手跑或自动化
- [ ] README：安装、配置 Key、Demo 命令、Skillbook/Recall 说明、架构示意

**完成标准**：陌生人按 README 10 分钟内跑通 script；有 Key 时跑通 llm。

---

## 18. 测试与回归矩阵

| 编号 | 场景 | 策略 | 期望 |
|------|------|------|------|
| T1 | 标准桌面 | script | success，且曾 load_skill |
| T2 | 标准桌面 | llm | success，且曾 load_skill |
| T3 | close 前 ee 远离罐子（单测 sim） | n/a | grasp_miss |
| T4 | intent.object_id=not_exist | gate | 拒绝，任务不崩 |
| T5 | max_steps=3 且脚本过短 | script | failed/max_steps |
| T6 | 指令拿罐，检查未误抓 cup（llm） | llm | holding=can_cola |
| T7 | 模型过早 done | 可单测 verifier | 不 success，继续或最终失败 |
| T8 | load_skill 未知名 | n/a | ok=false |
| T9 | note_write 后新任务 | n/a | task_notes 已清空 |
| T10 | durable 写入后 memory_search | n/a | 能命中 |
| T11 | ACT 失败后 recent_lessons | n/a | 含对应 action/message |
---

## 19. 日志与可观测性

每步在终端打印一行摘要（便于 Demo）：

```text
[step 1] DECIDE load_skill pick-can
[step 1] ACT ok skill=pick-can
[step 3] DECIDE move_above can_cola
[step 3] GATE allow
[step 3] ACT ok ee=(0.10,0.05,0.18)
[step 3] VERIFY pending holding=None lessons=1
```

JSONL 保留全量，勿在终端 dump 整段 prompt 与完整 skill body（除非 `--verbose`）。

---

## 20. 失败码与结束原因（建议枚举）

```text
success
max_steps
timeout
llm_parse_exhausted
user_abort
```

Gate/Act 失败**不是**任务立即结束条件（除非连续 N 次同样错误，可作为可选优化）。

---

## 21. 安全与免责（写进 README）

- 本阶段仅为**仿真编排 Demo**，不提供机器人功能安全、急停、碰撞认证。
- 若未来接真机：动作门禁、限速、工作空间限制、急停必须独立于 LLM，且由机器人控制器执行。
- 日志与 durable memory 可能含指令与状态，注意部署侧隐私与留存策略。

---

## 22. 第二阶段预留（本阶段只预留接口，不实现）

| 方向 | 预留方式 |
|------|----------|
| PyBullet / MuJoCo | `adapters/sim_mock.py` 与 `SimBackend` Protocol 对齐，可替换实现 |
| 真机 | 同一 Capability 名，换 backend |
| 飞书 Channel | 另建 `adapters/channel_*`，复用 `run_task` |
| 向量检索 Memory | Recall.durable 换后端，API 保持 `memory_search` |
| 多 active skills 栈 | Skillbook 从「单 active」升级为栈 |
| 视觉 | 未来用检测结果写回 `WorldState.objects`，决策侧无感 |

> Skills / 分层 Memory 已在 **Phase 1（v1.1）实现**，不再列入预留。

`SimBackend` Protocol 建议：

```python
class SimBackend(Protocol):
    def reset(self, scene_cfg) -> WorldState: ...
    def apply(self, action: str, args: dict, world: WorldState) -> ActResult: ...
```

---

## 23. 与竞品/参考项目的差异（对内说明）

| 维度 | ActForge Phase 1 | 刻意差异 |
|------|------------------|----------|
| 控制流 | 显式 SENSE→DECIDE→GATE→ACT→VERIFY 状态机 | 非论文组件一一映射式公共 API |
| 世界模型 | 物体表 + 位姿快照 | 非 Scene Graph Brief / ref 寻址体系 |
| Skills | **Skillbook**：catalog 常驻 + `load_skill` 按需正文 | 独立目录/类型/事件名 |
| Memory | **Recall**：task_notes / durable / tool_experience | 独立存储布局与朴素检索；非照搬其它项目模块 |
| 验收 | `verify/pick_can` 目标谓词 | 独立模块命名与协议 |
| 工具面 | 抓取动作 + skill/memory 动作的 JSON 意图 | 仍保持窄接口 |
| 产品入口 | 单一 CLI 任务 | 非多 mode 安装矩阵 |

开发时**不要**为了「看起来像」而去对齐其它开源 Harness 的目录名与事件名。

---

## 24. 里程碑时间盒（参考）

| 天数 | 产出 |
|------|------|
| D1 | Step 0–1 |
| D2 | Step 2 |
| D3 | Step 3 |
| D4 | Step 4 Skillbook |
| D5 | Step 5 Recall |
| D6 | Step 6 状态机 + script CLI |
| D7–D8 | Step 7 LLM |
| D9 | Step 8 Demo |

单人全职大约 **7～9 天**可完成 Phase 1（含 Skills + Memory）；无 LLM Key 时以 script 模式先验收。

---

## 25. 快速自检清单（发布 Demo 前）

- [ ] `pip install -e ".[dev]"` 成功
- [ ] `pytest -q` 全绿（含 skillbook / recall）
- [ ] script 模式拿罐成功，且日志有 `skill.loaded`
- [ ] llm 模式拿罐成功（有 Key），且至少一次 `load_skill`
- [ ] `data/recall/durable/` 在成功任务后可出现 summary 条目
- [ ] `runs/*/events.jsonl` 可读
- [ ] README 含安装、两条 Demo 命令、Skill/Memory 说明
- [ ] `.env` 未进 git
- [ ] 无复制自其它 Harness 的源码文件

---

## 26. 附录 A — 最小 `ActionIntent` JSON 样例

```json
{"thought": "先加载抓罐流程", "action": "load_skill", "args": {"skill_name": "pick-can"}}
```

```json
{"thought": "记下目标", "action": "note_write", "args": {"text": "目标是 can_cola，不要抓杯子"}}
```

```json
{"thought": "先到易拉罐上方", "action": "move_above", "args": {"object_id": "can_cola", "z_offset": 0.12}}
```

```json
{"thought": "下降接近", "action": "move_down", "args": {"delta_z": 0.10}}
```

```json
{"thought": "闭合夹爪抓取", "action": "close_gripper", "args": {}}
```

```json
{"thought": "抓空了，加载重试流程", "action": "load_skill", "args": {"skill_name": "grasp-retry"}}
```

```json
{"thought": "抬起", "action": "lift", "args": {"delta_z": 0.12}}
```

```json
{"thought": "已抬起，任务完成", "action": "done", "args": {"reason": "can lifted"}}
```

---

## 27. 附录 B — 抓取判定参考实现要点

```python
import math

def can_grasp(ee: Pose, obj: SceneObject, xy_tol: float, z_tol: float) -> bool:
    if not obj.graspable:
        return False
    dist_xy = math.hypot(ee.x - obj.xyz.x, ee.y - obj.xyz.y)
    if dist_xy > xy_tol:
        return False
    if abs(ee.z - obj.xyz.z) > z_tol:
        return False
    return True
```

容差以 `scene_desk_v1.yaml` 为准；若 script 路径不稳定，优先**放宽容差**而不是改状态机。

---

## 28. 附录 C — 新工作空间启动命令模板

```bash
mkdir ActForge_Harness && cd ActForge_Harness
git init
# 放入本文 docs/DEV_PHASE1.md
# 创建第 4 章目录结构（含 skills/、data/recall/）

python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
# source .venv/bin/activate

pip install -e ".[dev]"
copy .env.example .env   # 填写 KEY

pytest -q
python -m actforge --help
python -m actforge run --policy script --instruction "把桌上的易拉罐拿起来"
```

---

## 29. 附录 D — Skill / Memory 最小单测提纲

```python
# test_skillbook.py
def test_catalog_loads_pick_can(skills_dir):
    catalog = scan_skills(skills_dir)
    assert any(s.name == "pick-can" for s in catalog)

def test_load_skill_sets_active(skillbook):
    result = skillbook.load("pick-can")
    assert result.ok
    assert skillbook.active is not None
    assert "move_above" in skillbook.active.body

def test_load_unknown_skill(skillbook):
    result = skillbook.load("no-such")
    assert not result.ok

# test_recall.py
def test_task_notes_reset_between_tasks(recall):
    recall.on_task_start("a", "can_cola")
    recall.note_write("hello")
    recall.on_task_start("b", "can_cola")
    assert recall.build_recall_snapshot()["task_notes"] == []

def test_durable_search(recall, tmp_path):
    recall.memory_write("易拉罐抓取需要 3cm xy 容差", tags=["grasp"])
    hits = recall.memory_search("易拉罐", limit=3)
    assert hits.ok and len(hits.observation["hits"]) >= 1

def test_lesson_recorded_on_act(recall):
    recall.record_lesson(1, ActResult(ok=False, action="close_gripper", message="grasp_miss"), {})
    lessons = recall.build_recall_snapshot()["recent_lessons"]
    assert lessons[0]["message"] == "grasp_miss"
```

---

## 30. 文档维护

| 变更类型 | 动作 |
|----------|------|
| 增减 action | 同步改：动作表、prompt、registry、测试 |
| 增减 Skill 文件 | 只加 `skills/*/SKILL.md`，保持 frontmatter 规范 |
| 改 Memory 层级语义 | 同步改第 13 章、snapshot、`recall.yaml`、测试 |
| 改抓取容差 | 只改 scene yaml + 测试期望 |
| 换 LLM 供应商 | 只改 `.env` 与 `llm_openai.py` 的 URL 拼接 |

**Phase 1 冻结后**，不要随意加动作；新能力放入 Phase 2 提案。

---

**— 文档结束（v1.1）—**

按本文从 Step 0 做到 Step 8，即可在独立工作空间交付：**LLM + Skillbook + Recall + 仿真臂拿起易拉罐** 的 ActForge Harness 雏形。
