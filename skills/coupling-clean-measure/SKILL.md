---
name: coupling-clean-measure
description: 对接箍内壁擦拭并用测量尺测内径的标准流程。
---

## 适用场景

用户要求清洁/擦拭接箍，或测量接箍内径；场景中有 `coupling`、`rag`、`ruler`。

## 推荐步骤

1. `load_skill(coupling-clean-measure)`。
2. 接近并抓取 `rag`：`move_above(rag, z_offset=0.10)` → **`move_down(delta_z=0.12)`**（默认 0.08 太高会 grasp_miss）→ `close_gripper` → `lift`。
3. `move_above(coupling)`，然后 `wipe_inner`（必须手持抹布；画面上会下降并绕圈擦拭）。
4. **擦完立刻离开接箍**：用 snapshot.recall.object_homes.rag 的坐标 `move_to` → `place_home`，不要停在接箍上方。
5. 抓取 `ruler`：同样用 `move_down(delta_z=0.12)`，勿用默认 0.08。
6. `move_above(coupling)`，然后 `measure_inner`（必须手持量尺）。
7. **把量尺放回原位**：`move_to` 到量尺初始位上方 → `place_home`。
8. `return_home` 让机械臂回到初始位姿，再 `done`。

## 注意

- 接箍 `coupling` 不可抓取。
- 先擦拭再测量；擦拭前必须持有抹布，测量前必须持有量尺。
- 擦完 / 测完后必须用 `place_home` 放回工具，不要随手放在别处。
- 两个子任务都结束后必须 `return_home`，再 `done`。
