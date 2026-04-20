# 业务口径规则

## 默认口径

- “经营情况 / 经营表现 / 经营状况”：
  - 默认 `intent=query`
  - 默认 `metric_code=OWNER_PROFIT`
  - 默认 `compare_mode=yoy`

- “收入情况 / 营收情况 / 表现怎么样”：
  - 若未明确预算或同比，默认 `compare_mode=yoy`

## 追问动作

- “继续展开原因 / 为什么 / 归因”：
  - `intent=explain`
  - `conversation_action=follow_up_continue`
  - `analysis_mode=driver_analysis`

- “只看华南区 / 只看单店 / 聚焦某品牌”：
  - `conversation_action=refine_scope`

- “换成同比 / 改成预算”：
  - `conversation_action=shift_compare_mode`

## 需要澄清的典型情况

- 没有范围：例如“帮我分析一下经营利润”
- 上下文不足：例如“继续”“换成同比”
- 范围冲突：例如区域和酒店明显不一致
