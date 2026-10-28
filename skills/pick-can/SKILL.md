---
name: pick-can
description: 桌面圆柱易拉罐（cola can）的接近、抓取与抬起标准流程。
---

## 适用场景

用户要求拿起易拉罐 / 可乐罐，且场景中存在 `can_cola`。

## 推荐步骤

1. 确认目标 id（一般为 can_cola，勿与 cup 混淆）。
2. `move_above` 到目标正上方（可用 z_offset=0.12）。
3. `move_down` 接近，**建议 args 使用 `{"delta_z": 0.16}`**（默认 0.08 往往偏高会 grasp_miss）。
4. `close_gripper`；若 grasp_miss，转技能 grasp-retry。
5. `lift` 抬起后，`return_home` 回到机械臂初始位姿（罐可继续持握），再 `done`。

## 注意

- 先对准再闭合；不要隔空抓。
- 干扰物 cup_white 不要抓。
- 任务结束前必须 `return_home`。
