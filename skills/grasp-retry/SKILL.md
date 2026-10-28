---
name: grasp-retry
description: 抓空后重新对准并重试闭合夹爪。
---

## 适用场景

`close_gripper` 返回 `grasp_miss`，或 `recent_lessons` 中出现抓取失败。

## 推荐步骤

1. `open_gripper`（若已关闭）。
2. 再次 `move_above` 目标物体，确认 xy 对准。
3. `move_down`，使用 `{"delta_z": 0.16}` 充分下降。
4. 再次 `close_gripper`。
5. 成功则 `lift`，否则记录 note 后继续纠错。

## 注意

- 抓空多因 xy 偏移过大或高度不对，先重对准再闭合。
