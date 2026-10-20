# API 说明

基础路径：`/api`。所有响应均为 JSON（页面路由除外）。交互式文档也可在运行后访问 `/docs`。

## 认证

登录成功后服务端设置 HttpOnly Cookie：

```text
survey_access_token=<JWT>; HttpOnly; SameSite=Lax; Path=/
```

同时响应体中返回 `access_token`，API 客户端也可以使用：

```http
Authorization: Bearer <access_token>
```

密码使用 Argon2id 哈希保存。受保护接口需要有效登录状态；公开填写接口根据问卷设置决定是否允许匿名。

### 错误格式

域校验错误：

```json
{
  "detail": {
    "code": "selection_count",
    "message": "q_multi_0002 requires 2..3 selected options, got 1",
    "question_id": "q_multi_0002"
  }
}
```

普通业务错误：

```json
{ "detail": "survey not found" }
```

常见状态码：

| 状态码 | 含义 |
|---:|---|
| 200 / 201 / 204 | 成功 / 已创建 / 无内容 |
| 401 | 未登录、令牌无效或过期 |
| 403 | 已登录但不允许该操作（如禁止匿名时匿名提交） |
| 404 | 问卷/题目不存在，或不是当前用户所有 |
| 409 | 状态冲突、重复提交、重复用户名等 |
| 422 | 请求字段或答卷校验失败 |

---

## 1. 账号接口

### POST `/api/auth/register`

注册并自动登录。

```json
{
  "username": "alice_01",
  "email": "alice@example.com",
  "password": "StrongPass123!",
  "display_name": "Alice"
}
```

约束：

- 用户名：3–32 位小写字母、数字或下划线，唯一；
- 邮箱唯一；
- 密码 8–128 位。

响应 201：

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "user": {
    "id": "651f...",
    "username": "alice_01",
    "email": "alice@example.com",
    "display_name": "Alice",
    "status": "active",
    "created_at": "2026-10-20T03:10:00Z"
  }
}
```

### POST `/api/auth/login`

```json
{ "username": "alice_01", "password": "StrongPass123!" }
```

响应 200，结构与注册相同；错误密码返回 401。

### POST `/api/auth/logout`

清除认证 Cookie，返回 204。

### GET `/api/auth/me`

返回当前用户信息，需要登录。

---

## 2. 问卷管理接口

以下接口均要求登录，并且只能操作自己创建的问卷。访问他人问卷返回 404。

### POST `/api/surveys`

创建草稿问卷和 v1 草稿版本。

```json
{
  "title": "数据库课程体验调查",
  "description": "匿名调查",
  "allow_anonymous": true,
  "allow_multiple_responses": true,
  "closes_at": "2026-12-31T23:59:59Z"
}
```

`opens_at`、`slug` 可选；不填时服务端生成时间窗口和唯一 Slug。响应 201 包含
`id`、`slug`、`status=draft` 和 `current_draft_version_id`。

### GET `/api/surveys`

返回当前用户的问卷列表（按更新时间倒序，最多 200 条）。每项包含：

```text
id, slug, title, description, status
allow_anonymous, allow_multiple_responses
opens_at, closes_at, published_at, created_at, updated_at
```

### GET `/api/surveys/{survey_id}`

返回问卷详情，并附带：

- `current_draft`：`{id, version_no, state, revision, questions}`
- `published_version`：同样的版本结构，或 `null`

### PATCH `/api/surveys/{survey_id}`

更新可变元数据。所有字段可选：

```json
{
  "title": "新标题",
  "description": "新说明",
  "allow_anonymous": false,
  "allow_multiple_responses": false,
  "closes_at": "2027-01-31T23:59:59Z"
}
```

`closes_at: null` 可清除截止时间。`opens_at < closes_at`。

### POST `/api/surveys/{survey_id}/close`

关闭问卷。关闭后公开填写和提交均返回 409。关闭操作幂等。

### POST `/api/surveys/{survey_id}/questions`

向草稿逐题添加题目。请求体就是完整题目对象（见“题目结构”）。返回：

```json
{
  "survey_id": "...",
  "survey_version_id": "...",
  "revision": 2,
  "question": { "...": "完整题目" }
}
```

### PUT `/api/surveys/{survey_id}/draft`

编辑器使用的整份草稿保存接口：

```json
{
  "revision": 2,
  "questions": [ { "question_id": "q_...", "type": "single_choice", "...": "..." } ]
}
```

`revision` 用于乐观锁；版本已变化时返回 409。保存阶段校验题目字段和题目 ID 唯一性，
发布阶段再执行跨题目的跳转目标和规则合法性校验。

### POST `/api/surveys/{survey_id}/new-draft`

从当前已发布版本克隆出下一版草稿（`version_no + 1`），不改变线上版本；
如果已经有未完成的新草稿，则幂等返回该草稿。发布新草稿后，旧版本和旧答卷仍保留。

### POST `/api/surveys/{survey_id}/publish`

发布当前草稿。服务端会：

1. 校验题目和跳转图；
2. 生成 `content_hash`；
3. 将版本状态置为 `published`；
4. 更新问卷的 `published_version_id` 和 `published_at`。

对已发布问卷再次发布时，会发布当前新版本草稿，版本号递增；这是幂等接口。

发布是幂等的，重复调用返回同一发布结果。已关闭问卷不能发布。

### POST `/api/surveys/{survey_id}/responses`

管理端的提交入口（公开填写请使用 Slug 接口）。请求体与公开提交相同，见下文。

---

## 3. 公开填写接口

### GET `/api/public/surveys/{slug}`

无需登录即可读取问卷公开信息：

```json
{
  "id": "6ad6...",
  "slug": "s-42e6341c1fad",
  "title": "浏览器验收问卷",
  "description": "...",
  "status": "published",
  "allow_anonymous": true,
  "allow_multiple_responses": true,
  "requires_login": false,
  "is_open": true,
  "opens_at": "...",
  "closes_at": "...",
  "version_no": 1
}
```

草稿问卷返回 404；已关闭或不在开放窗口内时 `is_open=false`。

### POST `/api/public/surveys/{slug}/next`

服务端逐步计算下一道可见题目。浏览器不自行决定跳转。

```json
{
  "answers": [
    {
      "question_id": "q_gate_0001",
      "type": "single_choice",
      "option_ids": ["o_no_00000001"]
    }
  ],
  "skipped_question_ids": []
}
```

响应：

```json
{
  "survey_id": "6ad6...",
  "survey_version_id": "6ad6...",
  "next_question": {
    "question_id": "q_text_0004",
    "type": "text",
    "title": "补充建议",
    "description": null,
    "required": false,
    "options": null,
    "validation": {
      "min_length": 0,
      "max_length": 500,
      "trim": true
    }
  },
  "completed": false,
  "path": ["q_gate_0001"],
  "version_no": 1
}
```

- 未作答的必答题会作为 `next_question` 返回；
- 选答题可加入 `skipped_question_ids` 后跳过；
- 全部路径结束后 `completed=true`、`next_question=null`；
- 某个答案不合法时返回 422 和稳定错误码。

`next_question` 不包含服务端跳转规则，浏览器无法修改路径。

### POST `/api/public/surveys/{slug}/responses`

提交完整答案：

```json
{
  "answers": [
    {
      "question_id": "q_gate_0001",
      "type": "single_choice",
      "option_ids": ["o_yes_0000001"]
    },
    {
      "question_id": "q_multi_0002",
      "type": "multi_choice",
      "option_ids": ["o_opt_a_0001", "o_opt_b_0001"]
    },
    {
      "question_id": "q_number_0003",
      "type": "number",
      "number": 20
    }
  ],
  "is_anonymous": true,
  "submission_token": "8d3e5f0c-4e3b-4f2b-a8e9-bf1a2c3d4e5f"
}
```

提交时服务端重新遍历路径，校验必答、选项、数量和数字范围，
并拒绝为未展示题目提交的答案。`submission_token` 用于幂等。

- 允许匿名且 `is_anonymous=true`：不需要登录，`respondent_id=null`；
- `allow_anonymous=false`：必须登录；
- `allow_multiple_responses=false`：同一登录用户再次提交返回 409；
- 已关闭/过期：409；
- 返回 201，包含 `response_id`、`is_anonymous`、`submitted_at` 和 `question_path`。

---

## 4. 统计接口

统计针对当前已发布版本，必须登录且为问卷所有者。

### GET `/api/surveys/{survey_id}/stats`

返回整卷概览：

```json
{
  "survey": { "id": "...", "title": "问卷", "status": "published" },
  "version": { "id": "...", "version_no": 1, "published_at": "..." },
  "response_count": 30,
  "questions": [
    {
      "question_id": "q_multi_0002",
      "type": "multi_choice",
      "title": "你使用过哪些资源？",
      "required": true,
      "answered_count": 20,
      "response_rate": 0.6667,
      "option_counts": [
        {
          "option_id": "o_opt_a_0001",
          "label": "课件",
          "count": 18,
          "percentage": 90.0
        }
      ]
    },
    {
      "question_id": "q_number_0003",
      "type": "number",
      "title": "每周学习时长",
      "required": true,
      "answered_count": 19,
      "response_rate": 0.6333,
      "average": 22.5,
      "min": 18,
      "max": 30
    }
  ],
  "generated_at": "2026-10-20T03:15:00Z"
}
```

- 单选题、多选题的 `percentage` 分母是本题作答人数；
- 多选题各选项比例之和可以超过 100%；
- 文本题总览只返回作答数量，内容通过单题接口分页读取；
- 无答案的数字题返回 `average/min/max=null`；小数答案的统计分析同样适用。

### GET `/api/surveys/{survey_id}/questions/{qid}/stats`

文本题：`/questions/q_text_0004/stats?page=1&page_size=20`

```json
{
  "survey_id": "...",
  "survey_version_id": "...",
  "question_id": "q_text_0004",
  "type": "text",
  "title": "补充建议",
  "required": false,
  "answered_count": 3,
  "answers": [
    { "text": "希望增加案例", "submitted_at": "2026-10-20T03:10:00Z" }
  ],
  "pagination": {
    "page": 1,
    "page_size": 20,
    "total": 3,
    "total_pages": 1
  },
  "generated_at": "..."
}
```

选择题返回 `option_counts`，数字题返回 `average/min/max`；`page/page_size` 仅对文本题生效，
`page_size` 最大 100。

---

## 5. 题目结构

题目使用 `type` 作为判别字段。

```json
{
  "question_id": "q_single_0001",
  "type": "single_choice",
  "title": "你的身份是？",
  "description": "可选说明",
  "required": true,
  "options": [
    { "option_id": "o_student_0001", "label": "学生" },
    { "option_id": "o_teacher_0001", "label": "教师" }
  ],
  "logic": {
    "fallback": { "action": "next" },
    "rules": [
      {
        "rule_id": "r_teacher_0001",
        "when": {
          "mode": "all",
          "conditions": [
            {
              "question_id": "q_single_0001",
              "operator": "eq",
              "value": "o_teacher_0001"
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
}
```

规则语义：

- `rules` 按数组顺序求值，第一条命中即生效；
- 条件可以引用当前或更早题目；未展示/未作答的来源条件为 false；
- `goto` 只能指向后面的题目；
- 未命中时使用 `fallback` 的 `next` 或 `end`；
- 所有跳转由服务端解释，客户端只能展示。

各题型 `validation`：

| 题型 | 字段 |
|---|---|
| `multi_choice` | `min_selected`、`max_selected` 或 `exact_selected`（互斥） |
| `text` | `min_length`、`max_length`、`trim` |
| `number` | `integer`（true 时只接受整数，false 时接受有限小数）、可选 `min`/`max` |

---

## 6. 数据与一致性约定

- 一份答卷只引用提交时固定的 `survey_version_id`；
- 发布版本不可变，旧答卷始终按旧版本解释；
- 提交是单文档插入，返回前完成全部校验；
- `(survey_id, submission_token)` 唯一索引防止重试重复落库；
- 发布版本推进为幂等操作，不依赖副本集事务；
- 全部索引由 `python -m backend.init_db` 或启动时的 `AUTO_CREATE_INDEXES=true` 创建。
