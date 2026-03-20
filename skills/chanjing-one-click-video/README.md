# chanjing-one-click-video

> 用户输入选题 → 自动生成「数字人口播 + AI 生成画面」混合短视频

基于 [chan-skills](https://github.com/chanjing-ai/chan-skills) 的 OpenClaw skill。**触发条件、约束、参数与完整环境变量表以 `SKILL.md` 为准**；本文侧重安装与本地运行。

---

## 在 OpenClaw 中使用（推荐）

这是最简单的使用方式——安装完成后，直接用自然语言告诉 AI 你要什么视频，它会自动跑完整个流程。

### 第一步：安装 skill

```bash
openclaw skill install github:chandashi/chanjing-one-click-video
```

### 第二步：配置蝉镜凭证

联系蝉镜获取 `app_id` 和 `secret_key`，写入凭证文件：

```bash
mkdir -p ~/.chanjing
cat > ~/.chanjing/credentials.json <<EOF
{
  "app_id": "你的app_id",
  "secret_key": "你的secret_key"
}
EOF
```

### 第三步：配置 chan-skills 路径

该 skill 调用蝉镜 chan-skills 工具集来渲染视频，需要告诉 OpenClaw 它在哪里。

在 OpenClaw workspace 的 `TOOLS.md` 中添加：

```markdown
## chanjing-one-click-video 环境配置

运行此 skill 时，exec 命令需要以下环境变量：

- `CHAN_SKILLS_DIR=/path/to/chan-skills`（chan-skills 仓库绝对路径）
```

### 第四步：直接对话触发

安装后，在 OpenClaw 对话框里用自然语言说：

```
帮我做一个关于"为什么年轻人开始重视睡眠管理"的60秒抖音视频
```

```
根据这个选题生成一个短视频：家装公司怎么用短视频获客，平台微信视频号
```

```
帮我一键做成片，话题是呼吁减少使用一次性筷子，30秒
```

AI 会自动完成：规划 → 文案 → 分镜 → 渲染 → 输出视频文件路径。

### 验证安装

```bash
python $(openclaw skill path chanjing-one-click-video)/scripts/check_deps.py
```

---

## 快速开始（命令行直接运行）

### 1. 配置凭证

```bash
# 蝉镜 AK/SK（写入 ~/.chanjing/credentials.json）
# 联系蝉镜获取 AK/SK，或运行 chanjing-credentials-guard

# chan-skills 仓库路径（渲染必填）
export CHAN_SKILLS_DIR="/path/to/chan-skills"
```

### 2. 运行（Stub 模式，不调用真实 API）

```bash
cd chanjing-one-click-video
STUB_MODE=1 python scripts/run_workflow.py --topic "为什么现在很多老板开始重视 AI agent"
```

### 3. 运行（真实模式）

```bash
python scripts/run_workflow.py \
  --topic "家装公司怎么用短视频获客" \
  --industry "家装" \
  --platform douyin \
  --duration 60 \
  --output result.json
```

---

## 目录结构

```
chanjing-one-click-video/
├── SKILL.md                    # OpenClaw skill 定义（触发条件、参数、说明）
├── README.md                   # 本文件
├── examples/
│   ├── example_input_1.json    # AI/企业服务选题示例
│   ├── example_input_2.json    # 家装行业选题示例
│   ├── example_input_3.json    # 家庭教育选题示例
│   └── example_output_1.json   # 完整输出示例
├── scripts/
│   ├── run_workflow.py         # 主入口：完整流程编排
│   ├── schemas.py              # 数据结构定义
│   ├── planners.py             # video_plan
│   ├── copywriter.py           # 口播全文
│   ├── storyboard.py           # 分镜（DH/AI 分配）
│   ├── render.py               # 渲染编排
│   ├── _auth.py                # 蝉镜鉴权
│   └── utils.py                # 日志、计时工具
├── templates/
│   ├── plan_prompt.md          # 规划模板（历史保留）
│   ├── script_prompt.md        # 文案模板（历史保留）
│   ├── storyboard_prompt.md    # 分镜模板（历史保留）
│   └── rewrite_hook_prompt.md  # 开场白模板（历史保留）
└── tests/
    ├── test_plan_generation.py
    ├── test_script_generation.py
    ├── test_storyboard_generation.py
    └── test_end_to_end_stub.py
```

---

## 流程与环境

`run_workflow.py`：输入规范化 → `planners` / `copywriter` / `storyboard` → `render.py`（**整篇一次 TTS**，按分镜切 WAV；数字人镜头音频驱动合成，AI 镜头文生视频后与切段合成，最后 ffmpeg concat）。

详尽的镜头分配规则、业务约束、环境变量清单与依赖 skills 见 **SKILL.md**。本地规划+文案+分镜通常在 1 秒内完成；真实成片多为数分钟级（CDN 串行下载为主因）。`render_result.render_path` 取值如 `mixed_dh_ai`、`all_dh`、`stub`。

---

## 示例

### 示例 1：AI 企业服务类

```bash
python scripts/run_workflow.py --topic "为什么现在很多老板开始重视 AI agent" \
  --industry "AI/企业服务" --duration 60
```

输出关键字段：
```json
{
  "status": "success",
  "script_result": {
    "title": "老板为啥突然迷上AI agent",
    "hook": "你有没有发现，身边越来越多的老板，开始不动声色地研究AI agent了？"
  },
  "render_result": {
    "video_file": "/tmp/output.mp4",
    "render_path": "mixed_dh_ai"
  }
}
```

### 示例 2：家装行业

```bash
python scripts/run_workflow.py --input examples/example_input_2.json
```

---

## 运行测试

```bash
# 全部测试（stub 模式，无需真实 API）
python -m unittest discover -s tests -v

# 单独运行 E2E 测试
STUB_MODE=1 python -m unittest tests/test_end_to_end_stub.py -v
```

---

## 错误排查

| 错误信息 | 原因 | 解决方法 |
|----------|------|----------|
| `输入过于模糊` | 选题太短或太笼统 | 提供更明确的选题（≥5字）|
| `CHAN_SKILLS_DIR 未设置` | 未设置环境变量 | `export CHAN_SKILLS_DIR=/path/to/chan-skills` |
| `蝉镜凭证未配置` | 未设置 AK/SK | 检查 `~/.chanjing/credentials.json` |
| `没有可用的公共数字人形象` | 账户无公共数字人权限 | 联系蝉镜开通 |
| `视频时长只能在[5,10]秒范围内` | AI 视频模型限制 | 已内置处理（duration 自动夹到 5-10s）|

---

## 已知限制

见 SKILL.md「限制」；概要：本地 mp4、AI 单段时长受模型约束、CDN 串行下载。

## 与 Chanjing Claw 的集成

`run_workflow.py` 支持 JSON 输入/输出；`--input` 可接流水线。
