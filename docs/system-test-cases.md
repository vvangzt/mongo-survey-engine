# 在线问卷系统 API 系统测试用例

## 1. 测试范围与环境

### 1.1 测试范围

| 需求 | 覆盖用例 |
|---|---|
| 创建问卷 | TC-SUR-001 |
| 添加题目（单选、多选限制、数字限制、文本、小数） | TC-QUE-001 ~ TC-QUE-006 |
| 跳转逻辑（分支跳转） | TC-JMP-001、TC-JMP-002 |
| 表单校验（多选数量、数字范围） | TC-VAL-001 ~ TC-VAL-004 |
| 正常提交、匿名提交 | TC-SUB-001、TC-SUB-002 |
| 统计分析准确性 | TC-STA-001 ~ TC-STA-003 |
| 新版本与发布后运营 | TC-VER-001、TC-SET-001 |

### 1.2 测试环境

| 项目 | 值 |
|---|---|
| 后端框架 | FastAPI + Pydantic v2 |
| 数据库 | MongoDB 8.3（测试时自动启动隔离实例） |
| 测试框架 | pytest 9.1.1 |
| HTTP 客户端 | requests |
| 服务启动方式 | pytest fixture 中启动真实 Uvicorn HTTP 服务 |
| 认证方式 | 真实注册/登录：测试用户通过 `/api/auth/register` 建立，使用 HttpOnly Cookie；匿名用例使用无 Cookie 的独立客户端 |
| 测试日期 | 2026-10-20 |

测试服务器使用独立数据库 `survey_api_it_<random>`，测试结束后自动删除。若本机没有 `mongod`，可通过环境变量 `MONGODB_TEST_URI` 指向一个可丢弃的 MongoDB。

### 1.3 执行方式

```bash
python -m pytest tests/test_system_integration.py -v
```

运行全部测试：

```bash
python -m pytest -v
```

本次执行结果：

```text
tests/test_system_integration.py .......... 24 passed
全部测试 ................................... 64 passed
```

---

## 2. 基线测试数据

所有发布、提交和统计用例使用同一份基线问卷。题目按以下顺序添加：

| 顺序 | question_id | 类型 | 关键配置 |
|---:|---|---|---|
| 1 | `q_gate_0001` | 单选 | 必答；选项 `o_yes_0000001`（是）、`o_no_00000001`（否）；选择“否”时跳转至 `q_text_0004` |
| 2 | `q_multi_0002` | 多选 | 必答；4 个选项；`min_selected=2`、`max_selected=3` |
| 3 | `q_number_0003` | 数字 | 必答；合法整数；闭区间 `[18, 60]` |
| 4 | `q_text_0004` | 文本 | 非必答；`max_length=500` |

单选题上的跳转规则（随问卷版本冻结）：

```json
{
  "fallback": { "action": "next" },
  "rules": [
    {
      "rule_id": "r_skip_0001",
      "when": {
        "mode": "all",
        "conditions": [
          {
            "question_id": "q_gate_0001",
            "operator": "eq",
            "value": "o_no_00000001"
          }
        ]
      },
      "then": {
        "action": "goto",
        "target_question_id": "q_text_0004"
      }
    }
  ]
}
```

因此：

- 选择“是”：展示 `q_gate → q_multi → q_number → q_text`；
- 选择“否”：展示 `q_gate → q_text`，跳过第 2、3 题；
- 被跳过的必答题不参与必答校验。

---

## 3. 测试用例表

> 实际结果来自本次自动化测试执行，而非人工填写。

| 用例编号 | 测试模块 | 前置条件 | 测试步骤 | 输入数据 | 预期输出 | 实际结果 |
|---|---|---|---|---|---|---|
| TC-SUR-001 | 创建问卷 | 用户已认证；问卷 Slug 未被占用 | 1. `POST /api/surveys`<br>2. 检查响应与数据库状态 | `title=数据库课程体验调查`<br>`description=系统测试问卷`<br>`allow_anonymous=true` | HTTP 201；`status=draft`；返回唯一 `slug` 和 `current_draft_version_id`；可继续加题 | 通过。HTTP 201，草稿创建成功，返回 slug 和草稿版本 ID |
| TC-QUE-001 | 添加题目-单选 | 存在草稿问卷；用户为所有者 | 1. `POST /api/surveys/{id}/questions`<br>2. 提交单选题定义<br>3. 检查返回题目 | `question_id=q_gate_0001`<br>`type=single_choice`<br>2 个选项；必答 | HTTP 201；返回 `type=single_choice`、2 个选项，revision 递增 | 通过。HTTP 201；题型、选项数量和 revision 均正确 |
| TC-QUE-002 | 添加题目-多选限制 | 已添加 TC-QUE-001 题目 | 1. 提交多选题定义<br>2. 检查 validation 字段 | `type=multi_choice`<br>`min_selected=2`<br>`max_selected=3`<br>4 个选项 | HTTP 201；`validation.min_selected=2`、`max_selected=3`；revision 继续递增 | 通过。HTTP 201；最少/最多选择数保存正确 |
| TC-QUE-003 | 添加题目-数字限制 | 已添加前两题 | 1. 提交数字题定义<br>2. 检查 validation 字段 | `type=number`<br>`integer=true`<br>`min=18`<br>`max=60` | HTTP 201；返回整数校验和闭区间上下界；revision 继续递增 | 通过。HTTP 201；`integer=true`、`min=18`、`max=60` |
| TC-QUE-005 | 添加题目-小数允许 | 存在草稿问卷 | 提交整数关闭、允许小数的数字题并保存 | `integer=false`、`min=0`、`max=100.5` | HTTP 201；发布后小数答案可提交 | 通过。小数题在 API、跳转和统计链路中验证 |
| TC-QUE-006 | 多选指定数量 | 专用问卷已发布 | 提交 1 项和恰好 2 项两种答卷 | `exact_selected=2` | 1 项返回 422 `selection_count`；2 项返回 201 | 通过 |
| TC-QUE-004 | 添加题目-文本 | 已添加前三题 | 1. 提交文本题定义<br>2. 检查长度限制 | `type=text`<br>`min_length=0`<br>`max_length=500`<br>`trim=true` | HTTP 201；文本长度限制保存正确 | 通过。HTTP 201；`max_length=500` |
| TC-JMP-001 | 跳转逻辑-分支跳转 | 基线问卷已发布；无答卷 | 1. 提交选择“否”的答案<br>2. 检查返回的实际题目路径 | `q_gate_0001=o_no_00000001`<br>`q_text_0004=未使用实验环境，走跳过分支`<br>其余题不提交 | HTTP 201；路径仅包含 `q_gate_0001 → q_text_0004`；跳过两题仍提交成功 | 通过。HTTP 201；`question_path=["q_gate_0001","q_text_0004"]`；被跳过必答题未报错 |
| TC-VAL-001 | 校验-多选少于下限 | 基线问卷已发布 | 1. 选择“是”进入多选<br>2. 多选只选 1 项<br>3. 提交答卷<br>4. 查询总览确认未落库 | `q_multi_0002` 选中 1 项（最少要求 2 项）<br>`q_number_0003=20` | HTTP 422；错误码 `selection_count`；`response_count` 仍为 0 | 通过。HTTP 422，`code=selection_count`，总览 `response_count=0` |
| TC-VAL-002 | 校验-多选超过上限 | 基线问卷已发布 | 1. 进入多选<br>2. 选中 4 项<br>3. 提交答卷<br>4. 查询总览确认未落库 | `q_multi_0002` 选中 4 项（最多要求 3 项）<br>`q_number_0003=20` | HTTP 422；错误码 `selection_count`；`response_count` 仍为 0 | 通过。HTTP 422，`code=selection_count`，总览 `response_count=0` |
| TC-VAL-003 | 校验-数字低于下限 | 基线问卷已发布 | 1. 多选选 2 项<br>2. 数字输入 17<br>3. 提交答卷<br>4. 查询总览确认未落库 | `q_number_0003=17`<br>合法范围 `[18,60]` | HTTP 422；错误码 `number_out_of_range`；`response_count` 仍为 0 | 通过。HTTP 422，`code=number_out_of_range`，总览 `response_count=0` |
| TC-VAL-004 | 校验-数字超过上限 | 基线问卷已发布 | 1. 多选选 2 项<br>2. 数字输入 61<br>3. 提交答卷<br>4. 查询总览确认未落库 | `q_number_0003=61`<br>合法范围 `[18,60]` | HTTP 422；错误码 `number_out_of_range`；`response_count` 仍为 0 | 通过。HTTP 422，`code=number_out_of_range`，总览 `response_count=0` |
| TC-SUB-001 | 提交-正常提交 | 问卷已发布；请求带认证身份 | 1. 完整回答 4 题<br>2. 设置 `is_anonymous=false`<br>3. 提交 | 单选“是”；多选 B、C；数字 20；文本“正常提交” | HTTP 201；`is_anonymous=false`；返回 response_id；路径包含全部 4 题 | 通过。HTTP 201；路径长度 4，返回匿名标记和 response_id |
| TC-SUB-002 | 提交-匿名提交 | 问卷允许匿名；请求不携带认证身份 | 1. 完整回答 4 题<br>2. 设置 `is_anonymous=true`<br>3. 匿名提交 | 单选“是”；多选 B、C；数字 25；文本“匿名提交” | HTTP 201；`is_anonymous=true`；返回 response_id；不要求登录 | 通过。HTTP 201，匿名提交成功并记录匿名标记 |
| TC-STA-001 | 统计-整卷总览准确性 | 基线问卷已发布；已提交 3 份有效答卷：1 份分支“否”、2 份完整“是” | 1. `GET /api/surveys/{id}/stats`<br>2. 核对总提交数、分题统计 | 分支卷：否 + 文本<br>普通卷：是，B/C，20<br>匿名卷：是，B/C，25 | `response_count=3`；单选“是”2、“否”1；多选 B=2、C=2；数字 count=2、avg=22.5、min=20、max=25；文本 count=3 | 通过。总提交、选项人数、数字均值/最值、文本数量全部准确 |
| TC-STA-002 | 统计-选择题与数字题详情 | 同 TC-STA-001 数据 | 1. 请求多选题详情<br>2. 请求数字题详情<br>3. 核对 answered_count 和数值 | API 数据：3 份答卷；2 份回答多选和数字题 | 多选题 `answered_count=2`；选项 B、C 各 2 次；数字题 `average=22.5` | 通过。详情接口作答人数与聚合值正确 |
| TC-STA-003 | 统计-文本分页 | 同 TC-STA-001 数据；共 3 条文本答案 | 1. 请求文本题详情<br>2. 参数 `page=1&page_size=2` | 3 条文本；每页 2 条 | HTTP 200；`total=3`、`total_pages=2`；当前页返回 2 条 | 通过。分页元数据和当前页条数正确 |

---

### 3.1 附加质量用例

| 用例编号 | 测试模块 | 前置条件 | 测试步骤 | 输入数据 | 预期输出 | 实际结果 |
|---|---|---|---|---|---|---|
| TC-AUTH-001 | 注册/登录/退出 | 服务启动，用户名未注册 | 注册 → `/me` → 退出 → 错误密码登录 → 正确登录 | 用户名、邮箱、8 位以上密码 | 注册 201、退出 204、错误密码 401、重新登录 200 | 通过 |
| TC-ACL-001 | 权限隔离 | 用户 A 创建问卷 | 用户 B 查看 A 的列表、详情，并尝试加题/发布 | 两个独立登录账号 | 列表不含 A 的问卷；详情/加题/发布均为 404 | 通过 |
| TC-LIFE-001 | 发布/关闭/多次填写 | 草稿问卷含题目 | 重复发布；关闭后提交；一次性问卷二次提交 | 两次发布、关闭后提交、重复登录提交 | 发布幂等；关闭后 409；一次性问卷第二次 409 | 通过 |
| TC-DRAFT-001 | 草稿整份保存 | 草稿 revision=1 | 使用 `PUT /draft` 保存两道题；再用旧 revision 保存 | revision=1/2 与题目数组 | 首次 200、revision=2；旧 revision 返回 409 | 通过 |
| TC-PUB-001 | Slug 公开填写 | 问卷已发布且允许匿名 | 按 Slug 获取信息、请求下一题、跳过选答题、提交 | 分支答案和匿名提交 | 服务端返回路径；提交 201 | 通过 |
| TC-CON-001 | 并发匿名提交 | 问卷已发布，允许匿名 | 10 并发线程提交 30 份不同 token 的答卷 | 30 个匿名客户端请求 | 全部 201；统计 `response_count=30`，选项计数 30 | 通过 |
| TC-VER-001 | 新版本发布与旧答卷保留 | 问卷 v1 已发布且有答卷 | 创建新草稿、修改题目、发布 v2；检查旧答卷和统计版本 | 新草稿 revision=1、旧版本 id | v2 发布成功；旧答卷仍引用 v1；当前统计只计 v2 | 通过 |
| TC-SET-001 | 发布后运营设置 | 问卷已发布 | 修改截止时间、匿名和多次策略 | PATCH 运营字段 | 题目版本不变；公开信息立即采用新策略 | 通过 |
| TC-UI-001 | 页面与静态资源 | 服务已启动 | 访问登录/注册/工作台/编辑器/公开填写/统计页和 CSS | 浏览器会话与 Cookie | 未登录访问工作台重定向；用户可访问自己的页面；他人编辑页 404 | 通过 |

## 4. 自动化测试与用例映射

测试代码：

- [`tests/test_system_integration.py`](../tests/test_system_integration.py)
- [`tests/conftest.py`](../tests/conftest.py)

| 用例编号 | pytest 测试函数 |
|---|---|
| TC-SUR-001 | `test_create_survey` |
| TC-QUE-001 ~ 004 | `test_add_questions_with_type_specific_constraints` |
| TC-JMP-001 | `test_jump_logic_skips_branch` |
| TC-VAL-001、TC-VAL-002 | `test_multi_choice_count_validation[1]`、`[4]` |
| TC-VAL-003、TC-VAL-004 | `test_number_range_validation[17]`、`[61]` |
| TC-SUB-001、TC-SUB-002 | `test_normal_and_anonymous_submissions` |
| TC-STA-001 ~ 003 | `test_statistics_accuracy` |
| TC-QUE-005、TC-JMP-002 | `test_multi_and_decimal_number_jumps` |
| TC-QUE-006 | `test_exact_multi_choice_constraint` |
| TC-AUTH-001 | `test_auth_api.py::test_register_me_logout_and_login` |
| TC-ACL-001 | `test_owner_cannot_see_or_publish_another_users_survey` |
| TC-LIFE-001 | `test_publish_is_idempotent`、`test_close_survey_blocks_submissions`、`test_allow_multiple_responses_false_rejects_second_submission` |
| TC-DRAFT-001 | `test_bulk_draft_save_and_revision_conflict` |
| TC-PUB-001 | `test_public_slug_flow_branching_and_submission` |
| TC-VER-001 | `test_new_version_clone_publish_and_response_preservation` |
| TC-SET-001 | `test_published_operational_settings_can_change` |
| TC-CON-001 | `test_concurrent_anonymous_submissions` |
| TC-UI-001 | `test_web_pages_and_static_assets` |

测试隔离策略：

1. 每个测试通过 API 注册独立用户并创建自己的问卷，避免用例相互污染；
2. pytest session 只启动一次 MongoDB 和 Uvicorn，测试库使用随机名称；
3. 认证使用真实注册/登录流程和 Cookie，不安装测试专用认证覆盖；
4. 匿名提交使用独立、未登录的 HTTP 客户端，验证无需登录也能提交；
5. 跳转路径由服务端根据冻结版本重新计算，并由测试直接断言 `question_path`。

## 5. 实际执行记录

```text
$ python -m pytest tests/test_system_integration.py -v

tests/test_system_integration.py::test_create_survey PASSED
tests/test_system_integration.py::test_add_questions_with_type_specific_constraints PASSED
tests/test_system_integration.py::test_jump_logic_skips_branch PASSED
tests/test_system_integration.py::test_multi_choice_count_validation[1] PASSED
tests/test_system_integration.py::test_multi_choice_count_validation[4] PASSED
tests/test_system_integration.py::test_number_range_validation[17] PASSED
tests/test_system_integration.py::test_number_range_validation[61] PASSED
tests/test_system_integration.py::test_normal_and_anonymous_submissions PASSED
tests/test_system_integration.py::test_statistics_accuracy PASSED
tests/test_system_integration.py::test_owner_cannot_see_or_publish_another_users_survey PASSED
tests/test_system_integration.py::test_owner_list_contains_only_own_surveys PASSED
tests/test_system_integration.py::test_publish_is_idempotent PASSED
tests/test_system_integration.py::test_close_survey_blocks_submissions PASSED
tests/test_system_integration.py::test_allow_multiple_responses_false_rejects_second_submission PASSED
tests/test_system_integration.py::test_bulk_draft_save_and_revision_conflict PASSED
tests/test_system_integration.py::test_public_slug_flow_branching_and_submission PASSED
tests/test_system_integration.py::test_public_survey_requires_login_when_anonymous_disabled PASSED
tests/test_system_integration.py::test_closed_public_survey_is_not_accepting PASSED
tests/test_system_integration.py::test_concurrent_anonymous_submissions PASSED
tests/test_system_integration.py::test_web_pages_and_static_assets PASSED
tests/test_system_integration.py::test_exact_multi_choice_constraint PASSED
tests/test_system_integration.py::test_multi_and_decimal_number_jumps PASSED
tests/test_system_integration.py::test_published_operational_settings_can_change PASSED
tests/test_system_integration.py::test_new_version_clone_publish_and_response_preservation PASSED

24 passed
```

全量测试（含校验引擎、聚合映射和已有 API 测试）：

```text
64 passed, 1 warning
```

> 说明：分页测试只验证分页元数据和当前页数量，不断言文本顺序；文本页按
> `submitted_at DESC, _id DESC` 稳定排序。
