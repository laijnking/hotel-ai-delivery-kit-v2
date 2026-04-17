# 前端管理层体验整改记录

更新时间：2026-04-16

## 1. 本轮目标

本轮前端整改的目标，不是继续堆技术功能，而是把移动端首页往“管理层经营简报界面”收口：

- 先看经营观察，再看关键指标。
- 把分层分析直接放在主结果卡里，而不是藏在技术折叠区。
- 保留连续追问和高级设置，但不打断阅读节奏。

## 2. 本轮已完成

### 2.1 结果卡阅读顺序重构

在 [frontend/src/App.tsx](C:/Project/HotelAgent/hotel-ai-delivery-kit-v2/frontend/src/App.tsx:828) 中，结果卡已调整为更贴近管理层阅读习惯的结构：

- `经营观察`
- `关键指标`
- `范围/时间/指标/模式`
- `分层分析`
- `内部对标 / 外部对标`
- `重点酒店 / 异常拆解`
- `继续追问`

其中新增了：

- `management-observation`
- `management-sections`
- `getManagementSections()`

系统会优先挑选“经营总览、收入质量、客房效率、利润质量、成本效率、重点酒店与梯队、横向对标”等报告式 section，在主结果区直接呈现。

### 2.2 移动端结果样式增强

在 [frontend/src/styles.css](C:/Project\HotelAgent\hotel-ai-delivery-kit-v2/frontend/src/styles.css:372) 中，补充了管理层结果卡样式：

- `management-section-grid`
- `management-section-card`
- `management-section-title`
- `management-section-content`

目的不是增加花哨效果，而是把原本偏“调试面板”的结构，拉回成“简报卡片”式阅读体验。

### 2.3 会话历史抽屉能力已预埋，暂未启用

当前代码中已经预埋了 `conversation-history-drawer` 结构和样式，但开关仍保持关闭：

- 原因：这一轮优先保证现有主流程稳定，不在同一轮里同时重构首页布局和会话历史入口。
- 当前状态：代码已具备抽屉化基础，但仍沿用现有会话历史显示方式。

这属于“已准备、未切换”的能力，不影响当前交付稳定性。

## 3. 本轮验证

本轮已完成前端构建和交互回归：

### 3.1 构建验证

在 `frontend` 目录执行：

```bash
npm run build
```

结果：通过。

### 3.2 Playwright 交互验证

在 `frontend` 目录执行：

```bash
npx playwright test tests/management-chat.spec.ts
```

结果：14 个移动端交互测试全部通过。

补充说明：

- 本轮继续回归时再次执行了同一套构建与 Playwright 验证。
- 当前前端仍保持稳定通过状态，可继续在此基线上推进首屏收口和会话历史抽屉化。

覆盖的主要链路包括：

- 发送问题
- 快捷提问
- 连续追问
- 报告模式
- 角色视角
- 结构化详情展开
- 组合总览问题
- 区域/单店追问链路

## 4. 当前结论

到这一轮为止，前端首页虽然还没有完全切成“只有一个输入框”的极简态，但结果呈现已经明显从“技术调试页”向“管理层经营简报页”移动：

- 用户先看到经营观察，而不是技术标签。
- 用户先读经营分层，再决定要不要看技术细节。
- 报告式 section 已进入主结果卡，而不是只能在折叠层里查看。

## 5. 下一轮建议

下一轮前端建议继续做两件事：

1. 启用会话历史抽屉化  
   集团管理层默认不把会话历史放在首页主视觉中，而是放入抽屉入口。

2. 继续压缩首屏  
   把首页进一步收敛成：
   - 标题
   - 一组快捷问法
   - 输入框
   - 当前结果卡

这样会更接近最终用户真正使用时的心理模型：  
“我问一个经营问题，系统直接给我一张能读的经营简报。”

## 6. 2026-04-17 补充修订

本轮根据管理层真实使用反馈，补了两项体验修正：

- 结果卡不再重复展示同一段长摘要。顶部 `result-summary` 继续保留完整摘要；“经营观察”优先展示首个经营分析 section 的内容；“管理层速览”改为只解释当前对比口径，不再重复摘要正文。
- 默认对比口径切换为 `去年同期`。后端在摘要、经营总览、口径说明里都会明确写出“对去年同期差额/差异率”；前端“管理层速览”也同步说明差额的含义。

本轮对应改动：

- [backend/configs/semantic_mapping.yaml](C:/Project/HotelAgent/hotel-ai-delivery-kit-v2/backend/configs/semantic_mapping.yaml:38)：默认 `compare_mode` 调整为 `yoy`。
- [backend/apps/semantic-service/app/main.py](C:/Project/HotelAgent/hotel-ai-delivery-kit-v2/backend/apps/semantic-service/app/main.py:520)：把“经营情况/收入情况/利润情况/怎么样”这类宽泛问法的默认口径从预算改为去年同期，并同步修正 skill 默认值。
- [backend/apps/explanation-service/app/main.py](C:/Project/HotelAgent/hotel-ai-delivery-kit-v2/backend/apps/explanation-service/app/main.py:462)：新增对比口径标签函数，并把组合摘要、经营总览、口径说明统一改成显式口径表达。
- [frontend/src/App.tsx](C:/Project/HotelAgent/hotel-ai-delivery-kit-v2/frontend/src/App.tsx:400)：前端增加 `budget / yoy / actual` 的中文标签，并把“管理层速览”改成口径说明块，避免与主摘要重复。

## 7. 2026-04-17 第二轮补充

这一轮继续根据真实页面反馈，补了四个直接影响管理层阅读的问题：

- “公司的所有酒店”现在会稳定识别成 `公司全部酒店` 的组合问题，而不是退回成“当前管理范围”的 50 条单点快照。
- 样本数展示按组合成员数优先显示。组合问题显示 `83 家`，不再把组合返回的 1 条汇总行或 50 条比较样本误当成样本数。
- 指标名称增加业务口径说明。`OPERATING_PROFIT` 在前端显示为“经营利润（GOP）”，与“业主利润（经营净利润）”区分开。
- 结果卡继续去重，经营观察优先取“经营总览”等 section，不再直接复用“分析范围”里的整段摘要。
- 根据最新产品判断，已取消独立的“经营观察”结果块显示，避免与“分层分析”重复。页面现在保留顶部摘要、关键指标、管理层速览和分层分析四层结构。

本轮验证：

- 后端 `49` 个测试通过。
- `npm run build` 通过。
- `npx playwright test tests/management-chat.spec.ts` 14 项移动端交互测试通过。
