# 双层电路板网格布线服务

基于 **Python + FastAPI + OR-Tools (CP-SAT)** 的双层电路板网格布线服务。
对所有网络**联合求解**，先最小化总过孔数，再最小化同层移动总步数，
并只在证明完成后才报告 `optimal` / `infeasible`。

## 快速开始

### Docker Compose（一键启动）

```bash
docker compose up --build
```

服务监听 `http://localhost:8000`：

- `POST /route` — 布线接口（CP-SAT 联合求解）
- `POST /inspect` — 走线审查接口（只校验给定候选路径，不重新求解）
- `GET  /health` — 健康检查
- `GET  /docs` — Swagger UI 交互文档

### 本地开发

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

运行测试：

```bash
pip install pytest httpx
python -m pytest tests/ -q
```

## 布线规则

- 网格宽、高均为 2～20 的整数；层编号为 `0` / `1`。
- 请求含两层各自的禁布格（`blocked`）以及 1～6 条双焊盘网络（`nets`）。
- 走线只能沿**同层正交相邻格**移动；**过孔**在原坐标打通两层（占两层各一格）。
- 每条网络的路径不得重复占格。
- 不同网络在**同层**的占格不得重合，也不得正交相邻（对角相邻允许）。
- 每条网络有非负过孔上限 `via_limit`。
- 目标（字典序）：先最小化**总过孔数**，再最小化**同层移动总步数**。

## POST /route

### 请求体

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `width` | int | 网格宽，2～20 |
| `height` | int | 网格高，2～20 |
| `blocked` | array | 禁布格列表，元素为 `{"x", "y", "layer"}`，可省略 |
| `nets` | array | 1～6 条网络 |
| `nets[].name` | string | 可选名称，缺省自动命名 `N1`、`N2`… |
| `nets[].pads` | array | 恰好 2 个焊盘，各为 `{"x", "y", "layer"}` |
| `nets[].via_limit` | int | 非负整数，该网过孔数上限 |

坐标从 `0` 开始，`0 <= x < width`，`0 <= y < height`，`layer ∈ {0, 1}`。

### 响应体

| 字段 | 说明 |
| --- | --- |
| `status` | `optimal`：已证明最优；`feasible`：10 秒限时到、已有可行方案（未证明最优）；`infeasible`：已证明无解；`unknown`：10 秒限时到、尚未找到任何可行方案 |
| `solve_time_seconds` | 求解耗时（秒） |
| `total_vias` | 总过孔数（`infeasible`/`unknown` 时为 `null`） |
| `total_moves` | 同层移动总步数（`infeasible`/`unknown` 时为 `null`） |
| `nets[].path` | 该网从 `pads[0]` 到 `pads[1]` 的有序占格序列（含过孔两端的层切换） |
| `nets[].vias` | 该网过孔坐标列表（该坐标两层均被占用） |
| `nets[].via_count` / `nets[].move_count` | 该网过孔数 / 同层移动步数 |

求解时限为每次请求 **10 秒**（可用环境变量 `ROUTER_TIME_LIMIT` 覆盖，
见 `docker-compose.yml`）。只有完成证明时才返回 `optimal` 或 `infeasible`；
限时触发时按是否已找到可行方案区分 `feasible` 与 `unknown`。

### 实际请求与响应示例

下面是一个真实可复现的例子（8×8 板，第 0 层 `x=3` 整列禁布形成一堵墙，
N1 必须借道第 1 层；N2 在第 1 层直行，注意 N1 在第 1 层的走线段与 N2
保持了至少一格间距）：

```bash
curl -s -X POST http://localhost:8000/route \
  -H 'Content-Type: application/json' \
  -d '{
  "width": 8,
  "height": 8,
  "blocked": [
    {"x": 3, "y": 0, "layer": 0}, {"x": 3, "y": 1, "layer": 0},
    {"x": 3, "y": 2, "layer": 0}, {"x": 3, "y": 3, "layer": 0},
    {"x": 3, "y": 4, "layer": 0}, {"x": 3, "y": 5, "layer": 0},
    {"x": 3, "y": 6, "layer": 0}, {"x": 3, "y": 7, "layer": 0}
  ],
  "nets": [
    {"name": "N1", "pads": [{"x": 0, "y": 3, "layer": 0}, {"x": 7, "y": 3, "layer": 0}], "via_limit": 2},
    {"name": "N2", "pads": [{"x": 0, "y": 5, "layer": 1}, {"x": 7, "y": 5, "layer": 1}], "via_limit": 0}
  ]
}'
```

实际响应（`solve_time_seconds` 随机器略有浮动）：

```json
{
  "status": "optimal",
  "solve_time_seconds": 0.234,
  "total_vias": 2,
  "total_moves": 14,
  "nets": [
    {
      "name": "N1",
      "path": [
        {"x": 0, "y": 3, "layer": 0},
        {"x": 1, "y": 3, "layer": 0},
        {"x": 2, "y": 3, "layer": 0},
        {"x": 2, "y": 3, "layer": 1},
        {"x": 3, "y": 3, "layer": 1},
        {"x": 4, "y": 3, "layer": 1},
        {"x": 5, "y": 3, "layer": 1},
        {"x": 6, "y": 3, "layer": 1},
        {"x": 7, "y": 3, "layer": 1},
        {"x": 7, "y": 3, "layer": 0}
      ],
      "vias": [
        {"x": 2, "y": 3},
        {"x": 7, "y": 3}
      ],
      "via_count": 2,
      "move_count": 7
    },
    {
      "name": "N2",
      "path": [
        {"x": 0, "y": 5, "layer": 1},
        {"x": 1, "y": 5, "layer": 1},
        {"x": 2, "y": 5, "layer": 1},
        {"x": 3, "y": 5, "layer": 1},
        {"x": 4, "y": 5, "layer": 1},
        {"x": 5, "y": 5, "layer": 1},
        {"x": 6, "y": 5, "layer": 1},
        {"x": 7, "y": 5, "layer": 1}
      ],
      "vias": [],
      "via_count": 0,
      "move_count": 7
    }
  ]
}
```

路径中相邻两格 `layer` 相同表示一次同层移动，`layer` 不同（坐标不变）
表示一次过孔。

### 无解示例

两焊盘分处不同层但 `via_limit` 为 0，可证明无解：

```bash
curl -s -X POST http://localhost:8000/route \
  -H 'Content-Type: application/json' \
  -d '{
  "width": 4,
  "height": 4,
  "nets": [
    {"name": "N1", "pads": [{"x": 0, "y": 0, "layer": 0}, {"x": 3, "y": 3, "layer": 1}], "via_limit": 0}
  ]
}'
```

```json
{
  "status": "infeasible",
  "solve_time_seconds": 0.005,
  "total_vias": null,
  "total_moves": null,
  "nets": null
}
```

### 输入校验（HTTP 422）

以下非法请求返回 `422 Unprocessable Entity`（FastAPI/Pydantic 校验）：

- 网格宽高超出 2～20，或网络条数不在 1～6；
- 焊盘越界（`x`/`y` 超出网格或 `layer` 非 0/1）；
- 焊盘落在禁布格上；
- 重复焊盘（任意两焊盘的 `(x, y, layer)` 完全相同，含同一网内）；
- 过孔上限为负数或非整数；
- 禁布格越界。

示例（焊盘落在禁布格上）：

```bash
curl -s -X POST http://localhost:8000/route \
  -H 'Content-Type: application/json' \
  -d '{
  "width": 4, "height": 4,
  "blocked": [{"x": 1, "y": 1, "layer": 0}],
  "nets": [{"pads": [{"x": 1, "y": 1, "layer": 0}, {"x": 3, "y": 3, "layer": 0}], "via_limit": 1}]
}'
# HTTP 422
# {"detail":[{"type":"value_error","loc":["body"],
#   "msg":"Value error, net 0 pad (1, 1, layer 0) is on a blocked cell", ...}]}
```

## POST /inspect

走线审查接口。请求体与 `/route` 的板定义完全相同（`width`、`height`、
`blocked`、`nets`，并经过同样的板面校验），另外要求一个 **`paths`** 字段：
按 `nets` 的网序排列，每条网络给出一条**有序候选路径**（从首焊盘到末焊盘
的占格序列，编号规则与 `/route` 返回的 `path` 一致）。

接口**不会重新求解**，只静态检查给定路径，并报告**全部**走线违规：一条网
出错不会中断对其他规则和其他网络的检查。越界坐标和非法层号属于**走线违规**
（仍返回 `200`），而不是请求格式错误；只有请求本身畸形时才返回 `422`。

### 审查的规则

| 规则码 | 含义 |
| --- | --- |
| `ENDPOINT_MISMATCH` | 路径首格不是 `pads[0]`，或末格不是 `pads[1]`（空路径两个端点都报） |
| `CELL_OUT_OF_BOUNDS` | 步格坐标超出板面（`x`/`y`） |
| `ILLEGAL_LAYER` | 步格 `layer` 不是 `0`/`1` |
| `BLOCKED_CELL` | 步格落在禁布格上 |
| `DUPLICATE_CELL` | 同一网重复占据同一个 `(x, y, layer)` |
| `NON_ORTHOGONAL_STEP` | 同层相邻两步不是正交单位步（对角、跳跃、原地） |
| `LAYER_CHANGE_OFFSET` | 相邻两步换了层但坐标不同（非原位换层） |
| `VIA_LIMIT` | 过孔数（同坐标两层均被占用即计一个过孔）超过 `via_limit` |
| `CROSS_NET_COINCIDE` | 两条不同网络在同层占据同一格 |
| `CROSS_NET_ADJACENT` | 两条不同网络在同层占据正交相邻格 |

细则：

- **过孔计数**：某坐标的第 0、1 两层都被同一网占用即计 1 个过孔（无论两层
  在路径中是否相邻）；过孔按同坐标占两层计数。
- **跨网比较范围**：只比较**板内合法层**的占格；越界格、非法层格不参与跨网
  比较；**禁布格仍然参与**（禁布格上的异网重合/相邻照报）。
- **三网同格**：同一格被三条网占据时报 `0-1`、`0-2`、`1-2` **三对**冲突。
- **镜像去重（方向无关）**：每条无向正交格边只枚举一次；异网同层正交相邻的
  无向格对按**网对**只报一条（`nets` 恒为 `[i, j]`、`i < j`），不依赖走线
  方向——低网号走线位于高网号右侧或下侧同样报出。同一边两侧有多对网时每对
  分别报告；两个网只在边的同一端点重合不算相邻（由 `CROSS_NET_COINCIDE`
  负责）。同一网重复访问该端点的**全部步号**都保留。
- 步号（`steps`）从 **0** 开始，即路径数组下标。

### 响应体

| 字段 | 说明 |
| --- | --- |
| `legal` | 仅当没有任何违规时为 `true` |
| `violations` | 违规列表，按「网序 → 步号 → 规则码」排序 |
| `violations[].rule` | 上表中的规则码 |
| `violations[].nets` | 涉及网络的下标（网序）：单网规则为 `[i]`，跨网规则为 `[i, j]`（`i < j`） |
| `violations[].steps` | 与 `nets` 平行：每个网参与该违规的步号列表（已排序；空路径的端点违规为 `[]`） |
| `violations[].cells` | 涉及格：跨网规则按网序给出，其余按规范序；格为 `{"x", "y", "layer"}`（可以是越界/非法层值） |
| `violations[].via_count` / `via_limit` | 仅 `VIA_LIMIT` 违规出现：实际过孔数 / 上限 |

### 实际请求与响应示例

合法候选路径（与 `/route` 可能返回的路径格式完全相同）：

```bash
curl -s -X POST http://localhost:8000/inspect \
  -H 'Content-Type: application/json' \
  -d '{
  "width": 3,
  "height": 3,
  "nets": [
    {"name": "N1", "pads": [{"x": 0, "y": 0, "layer": 0}, {"x": 2, "y": 2, "layer": 0}], "via_limit": 2}
  ],
  "paths": [
    [
      {"x": 0, "y": 0, "layer": 0},
      {"x": 1, "y": 0, "layer": 0},
      {"x": 1, "y": 0, "layer": 1},
      {"x": 1, "y": 1, "layer": 1},
      {"x": 1, "y": 2, "layer": 1},
      {"x": 1, "y": 2, "layer": 0},
      {"x": 2, "y": 2, "layer": 0}
    ]
  ]
}'
```

```json
{"legal": true, "violations": []}
```

含多种违规的例子（4×3 板，第 0 层 `(2,1)` 禁布；N1 直行合法，N2 斜跳、
踩禁布格并与 N1 正交相邻）：

```bash
curl -s -X POST http://localhost:8000/inspect \
  -H 'Content-Type: application/json' \
  -d '{
  "width": 4,
  "height": 3,
  "blocked": [{"x": 2, "y": 1, "layer": 0}],
  "nets": [
    {"name": "N1", "pads": [{"x": 0, "y": 0, "layer": 0}, {"x": 3, "y": 0, "layer": 0}], "via_limit": 0},
    {"name": "N2", "pads": [{"x": 0, "y": 2, "layer": 0}, {"x": 3, "y": 2, "layer": 0}], "via_limit": 0}
  ],
  "paths": [
    [
      {"x": 0, "y": 0, "layer": 0},
      {"x": 1, "y": 0, "layer": 0},
      {"x": 2, "y": 0, "layer": 0},
      {"x": 3, "y": 0, "layer": 0}
    ],
    [
      {"x": 0, "y": 2, "layer": 0},
      {"x": 1, "y": 1, "layer": 0},
      {"x": 2, "y": 1, "layer": 0},
      {"x": 3, "y": 2, "layer": 0}
    ]
  ]
}'
```

实际响应（已按网序、步号、规则码排序；跨网违规排在 N2 自身违规之前）：

```json
{
  "legal": false,
  "violations": [
    {
      "rule": "CROSS_NET_ADJACENT",
      "nets": [0, 1],
      "steps": [[1], [1]],
      "cells": [
        {"x": 1, "y": 0, "layer": 0},
        {"x": 1, "y": 1, "layer": 0}
      ],
      "via_count": null,
      "via_limit": null
    },
    {
      "rule": "CROSS_NET_ADJACENT",
      "nets": [0, 1],
      "steps": [[2], [2]],
      "cells": [
        {"x": 2, "y": 0, "layer": 0},
        {"x": 2, "y": 1, "layer": 0}
      ],
      "via_count": null,
      "via_limit": null
    },
    {
      "rule": "NON_ORTHOGONAL_STEP",
      "nets": [1],
      "steps": [[0, 1]],
      "cells": [
        {"x": 0, "y": 2, "layer": 0},
        {"x": 1, "y": 1, "layer": 0}
      ],
      "via_count": null,
      "via_limit": null
    },
    {
      "rule": "BLOCKED_CELL",
      "nets": [1],
      "steps": [[2]],
      "cells": [{"x": 2, "y": 1, "layer": 0}],
      "via_count": null,
      "via_limit": null
    },
    {
      "rule": "NON_ORTHOGONAL_STEP",
      "nets": [1],
      "steps": [[2, 3]],
      "cells": [
        {"x": 2, "y": 1, "layer": 0},
        {"x": 3, "y": 2, "layer": 0}
      ],
      "via_count": null,
      "via_limit": null
    }
  ]
}
```

### 反向网序示例（方向无关的相邻归并）

`CROSS_NET_ADJACENT` 对每条**无向正交格边**只枚举一次，并按**网序** `[i, j]`
（`i < j`）报告跨在该边两侧的每一对网，与两条网谁的编号更小、谁在左/上无关。
下面的 3×3 板上 N1（网序 0）走在右侧 `x=2` 一列、N2（网序 1）走在左侧
`x=1` 一列——即**低网号走线位于高网号右侧**。修复前右/下扫描按网号过滤，
会漏掉全部三条相邻边并错误返回 `legal=true`；现在三条边分别报出，
`steps` 与 `nets` 平行且按网序给出（N1 在前），`cells` 按规范序（左格在前）：

```bash
curl -s -X POST http://localhost:8000/inspect \
  -H 'Content-Type: application/json' \
  -d '{
  "width": 3,
  "height": 3,
  "nets": [
    {"name": "N1", "pads": [{"x": 2, "y": 0, "layer": 0}, {"x": 2, "y": 2, "layer": 0}], "via_limit": 0},
    {"name": "N2", "pads": [{"x": 1, "y": 0, "layer": 0}, {"x": 1, "y": 2, "layer": 0}], "via_limit": 0}
  ],
  "paths": [
    [
      {"x": 2, "y": 0, "layer": 0},
      {"x": 2, "y": 1, "layer": 0},
      {"x": 2, "y": 2, "layer": 0}
    ],
    [
      {"x": 1, "y": 0, "layer": 0},
      {"x": 1, "y": 1, "layer": 0},
      {"x": 1, "y": 2, "layer": 0}
    ]
  ]
}'
```

实际响应：

```json
{
  "legal": false,
  "violations": [
    {
      "rule": "CROSS_NET_ADJACENT",
      "nets": [0, 1],
      "steps": [[0], [0]],
      "cells": [
        {"x": 1, "y": 0, "layer": 0},
        {"x": 2, "y": 0, "layer": 0}
      ],
      "via_count": null,
      "via_limit": null
    },
    {
      "rule": "CROSS_NET_ADJACENT",
      "nets": [0, 1],
      "steps": [[1], [1]],
      "cells": [
        {"x": 1, "y": 1, "layer": 0},
        {"x": 2, "y": 1, "layer": 0}
      ],
      "via_count": null,
      "via_limit": null
    },
    {
      "rule": "CROSS_NET_ADJACENT",
      "nets": [0, 1],
      "steps": [[2], [2]],
      "cells": [
        {"x": 1, "y": 2, "layer": 0},
        {"x": 2, "y": 2, "layer": 0}
      ],
      "via_count": null,
      "via_limit": null
    }
  ]
}
```

把 N1 放在下侧、N2 放在上侧（低网号位于高网号**下侧**）同理，逐边报出，
不会再返回 `legal=true`。同一条边上的多个网对分别各报一条；某网重复访问
端点时，该网参与冲突的**全部步号**都会保留。

### 输入校验（HTTP 422）

除继承 `/route` 的全部板面校验（尺寸、网络数、焊盘越界/落禁布格/重复等）
外，`/inspect` 另有以下 422 情形：

- 缺少 `paths` 字段；
- `paths` 条数与 `nets` 不一致；
- 路径坐标不是整数（`0.5`、`1.0`、`"1"`、`true`、`null` 均拒绝）；
- 单条路径步数超过两层板格总数 `2 × width × height`
  （空路径合法，报端点违规；长度恰好等于上限的路径可以提交审查）。

示例（坐标使用了小数）：

```bash
curl -s -X POST http://localhost:8000/inspect \
  -H 'Content-Type: application/json' \
  -d '{
  "width": 3, "height": 3,
  "nets": [{"pads": [{"x": 0, "y": 0, "layer": 0}, {"x": 2, "y": 2, "layer": 0}], "via_limit": 0}],
  "paths": [[{"x": 0, "y": 0, "layer": 0.5}, {"x": 2, "y": 2, "layer": 0}]]
}'
# HTTP 422
# {"detail":[{"type":"int_type","loc":["body","paths",0,0,"layer"],
#   "msg":"Input should be a valid integer","input":0.5}]}
```

## 实现要点

- **模型**（`app/solver.py`）：每条网络建模为从 `pads[0]` 到 `pads[1]` 的
  单位流。节点为两层上的自由格；弧为同层正交移动弧与过孔弧。除源/汇外
  每个节点入度=出度≤1，保证路径不重复占格；某网在同坐标两层均占格时
  过孔变量强制为 1（过孔占两层）。异网之间对同层每格及其正交邻格加
  互斥约束。
- **目标**：`min 4795 * 总过孔数 + 总移动步数`。权重大于最大可能步数
  （6 网 × 799 步 = 4794），因此严格等价于字典序（先过孔后步数）。
- **证明速度**：每网移动步数变量定义域下界直接取两焊盘曼哈顿距离、
  过孔变量下界按焊盘是否异层取 0/1，使根节点下界立即有效；另用一个
  快速顺序 Dijkstra 启发式把可行布线作为 hint 注入加速搜索。
- **限时语义**：CP-SAT `max_time_in_seconds = 10`。返回 `OPTIMAL` /
  `INFEASIBLE` 才分别报告 `optimal` / `infeasible`；限时到时有解报
  `feasible`、无解报 `unknown`。若求解器超时但启发式已找到经独立
  校验的完整合法布线，也按 `feasible` 返回该方案。
- **解校验**：`tests/test_router.py` 内含独立校验器，对返回的每条路径
  检查端点、占格不重复、同层正交移动、过孔占两层、禁布格、过孔上限、
  异网隔离及目标值一致性。
- **走线审查**（`app/inspector.py`）：`POST /inspect` 不求解，只逐条规则
  审计候选路径。单网规则（端点、越界、非法层、禁布、重复、非正交跳步、
  非原位换层、过孔上限）逐网检查；跨网规则只对板内合法层占格建占格表，
  同格报 `CROSS_NET_COINCIDE`（每对网一条，三网同格报三对）。相邻检查
  **方向无关**：对每个占格只看其 `+x`/`+y` 邻格，从而每条无向正交边恰好
  枚举一次；汇总边两端各自的占网集合，凡跨边相对（一侧有此网、另一侧有
  彼网，正反两种朝向都算）的异网对按 `i < j` 各报一条，因此低网号走线在
  高网号右侧/下侧也不会漏报；同边多网对分别报告，`steps` 与 `nets` 平行
  且保留重复访问的全部步号，`cells` 为该冲突两格。越界与非法层以 `200`
  返回违规；请求畸形（缺字段、路径数不符、非整数坐标、单路径超过 `2wh`
  格）由 Pydantic 返回 `422`。`tests/test_inspect.py` 覆盖全部规则、
  反向网序、排序语义与 422。

## 项目结构

```
app/
  main.py       # FastAPI 入口，POST /route、POST /inspect、GET /health
  schemas.py    # Pydantic 请求/响应模型与 422 校验
  solver.py     # CP-SAT 联合建模、启发式 hint、结果提取
  inspector.py  # /inspect 走线规则静态审查（不求解）
tests/
  test_router.py
  test_inspect.py
Dockerfile
docker-compose.yml
requirements.txt
```
