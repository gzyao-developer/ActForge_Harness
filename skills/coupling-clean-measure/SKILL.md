---
name: coupling-clean-measure
description: 接箍A/B 中径擦测：各件准入→擦拭返回→清理复核→测量→判定→归档→回初始位。
---

## 适用场景

桌面有 **coupling_A、coupling_B**、rag、ruler。对每件接箍独立完成擦测；先 A 后 B。

## 单件流程

1. `task_admit(workpiece=A|B, object_id=coupling_A|coupling_B)`
2. 抓 rag → `move_above(当前接箍)` → `wipe_inner` → `place_home` → `wipe_return`
3. `cleaning_review(result=clean)`（确认洁净，允许测量）
4. 抓 ruler → `move_above(当前接箍)` → `measure_inner` → `place_home`
5. `report_measurement` → `rule_judge` → `archive_record`
6. `return_home`，再处理下一件；两件都完成后 `done`

## 判定参考

| 接箍 | 典型 Δd | 判定 |
|------|---------|------|
| A | +0.020 | 合格 |
| B | +0.080 | 不合格（仍须归档） |

## 注意

- 跟随 snapshot.`recall.inspection` 的推荐动作。
- 擦拭返回后必须清理复核，才能测量。
- 任务成功看是否归档完成，不是看是否全部合格。
